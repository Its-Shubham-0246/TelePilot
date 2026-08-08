import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from core.database import async_session_factory
from models.schedule import Schedule
from models.user import User
from models.account import TelegramAccount
from models.job_log import JobLog
from services.subscription_service import subscription_service
from services.mtproto_service import mtproto_service
from services.group_discovery_service import check_and_alert_new_groups

from config import settings

logger = logging.getLogger(__name__)


async def _notify_user(telegram_id: int, text: str):
    """Send a Telegram message notification to the user. Imported lazily to avoid circular imports."""
    try:
        from bot.bot_instance import bot
        await bot.send_message(telegram_id, text, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"[Scheduler] Failed to notify user {telegram_id}: {e}")


class SchedulerService:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self._semaphore: Optional[asyncio.Semaphore] = None

    @property
    def account_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_BROADCASTS)
        return self._semaphore

    def start(self):
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("APScheduler engine started.")
            self.scheduler.add_job(
                self.process_active_schedules,
                'interval',
                seconds=5,
                id='master_schedule_runner',
                replace_existing=True,
                max_instances=1,
                coalesce=True
            )

    def stop(self):
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("APScheduler engine stopped.")

    async def claim_leadership(self) -> bool:
        """
        Claims or renews the active leader lock in the database for this container instance.
        Returns True if this container is the active LEADER.
        """
        from models.system_lock import SystemLock, INSTANCE_ID
        try:
            async with async_session_factory() as db:
                lock = await db.get(SystemLock, "scheduler_leader")
                now = datetime.utcnow()
                LOCK_TTL_SECONDS = 30

                if not lock:
                    lock = SystemLock(key="scheduler_leader", instance_id=INSTANCE_ID, updated_at=now)
                    db.add(lock)
                    await db.commit()
                    return True

                # If lock belongs to us, renew timestamp
                if lock.instance_id == INSTANCE_ID:
                    lock.updated_at = now
                    await db.commit()
                    return True

                # If lock belongs to another instance, check if it has expired (> 30s old)
                time_since_update = (now - lock.updated_at).total_seconds()
                if time_since_update > LOCK_TTL_SECONDS:
                    logger.info(f"[SchedulerLock] Previous leader ({lock.instance_id[:8]}) expired after {time_since_update:.1f}s. Claiming leadership for {INSTANCE_ID[:8]}.")
                    lock.instance_id = INSTANCE_ID
                    lock.updated_at = now
                    await db.commit()
                    return True
                else:
                    # Active leader exists in another container
                    return False
        except Exception as e:
            logger.warning(f"[SchedulerLock] claim_leadership warning: {e}")
            return True

    async def is_leader(self) -> bool:
        """
        Checks if this container instance is currently the registered leader.
        """
        return await self.claim_leadership()

    async def process_active_schedules(self):
        """Iterates over active schedules and runs group broadcasts for enabled accounts in parallel."""
        # Leader Lock Check — prevent dual-container execution during Railway rolling deploys
        if not await self.is_leader():
            logger.info("[SchedulerLock] Skipping schedule processing — another container instance is active leader.")
            return

        try:
            # Step 1: Run database cleanup to prune old logs
            await self.cleanup_database()

            # Step 2: Collect active schedule IDs using a short-lived session
            async with async_session_factory() as db:
                stmt = select(Schedule).where(Schedule.is_active == True)
                result = await db.execute(stmt)
                schedule_ids = [s.id for s in result.scalars().all()]

            if not schedule_ids:
                return

            # Step 3: Run all active schedule checks concurrently in parallel
            tasks = [self._process_single_schedule(sched_id) for sched_id in schedule_ids]
            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            logger.error(f"[Scheduler] process_active_schedules failed: {type(e).__name__}: {e}", exc_info=True)

    async def cleanup_database(self):
        """Safely purges job logs older than 7 days and unsubscribed users (>2 days without active sub)."""
        try:
            from sqlalchemy import delete
            async with async_session_factory() as db:
                cutoff = datetime.utcnow() - timedelta(days=7)
                stmt_del_logs = delete(JobLog).where(JobLog.sent_at < cutoff)
                res_logs = await db.execute(stmt_del_logs)
                deleted_logs = res_logs.rowcount or 0
                await db.commit()

                purged_users = await subscription_service.purge_unsubscribed_users(db, grace_days=2)

                if deleted_logs > 0 or purged_users > 0:
                    logger.info(f"[DBCleanup] Purged {deleted_logs} old job log(s) (>7 days) and {purged_users} unsubscribed user(s) (>2 days without active sub).")
        except Exception as e:
            logger.warning(f"[DBCleanup] Safe cleanup warning: {e}")


    async def _process_single_schedule(self, sched_id: int):
        """Processes a single schedule with its own session."""
        try:
            async with async_session_factory() as job_db:
                sched = await job_db.get(Schedule, sched_id)
                if sched and sched.is_active:
                    await self._execute_schedule_job(job_db, sched)
        except Exception as e:
            logger.error(f"[Scheduler] Error on schedule #{sched_id}: {type(e).__name__}: {e}", exc_info=True)

    async def _execute_schedule_job(self, db, schedule: Schedule):
        # 0. Get user for notifications
        user_result = await db.execute(select(User).where(User.id == schedule.user_id))
        user = user_result.scalars().first()
        user_telegram_id = user.telegram_id if user else None

        # 1. Verify user active subscription
        has_sub = await subscription_service.check_user_has_active_sub(db, schedule.user_id)
        if not has_sub:
            logger.info(f"[Scheduler] User #{schedule.user_id} subscription expired. Pausing schedule.")
            schedule.is_active = False
            await db.commit()
            if user_telegram_id:
                await _notify_user(
                    user_telegram_id,
                    "⚠️ <b>Auto-Messaging Paused</b>\n\n"
                    "Your subscription has expired and auto-messaging has been stopped.\n\n"
                    "Tap <b>💳 Subscription</b> to renew."
                )
            return

        # 2. Fetch enabled user accounts (auto_group_enabled == True)
        stmt_acc = select(TelegramAccount).where(
            TelegramAccount.user_id == schedule.user_id,
            TelegramAccount.is_active == True,
            TelegramAccount.status.in_(["ACTIVE", "FLOOD_WAIT"]),
            TelegramAccount.auto_group_enabled == True,
        )
        accounts_res = await db.execute(stmt_acc)
        accounts: List[TelegramAccount] = accounts_res.scalars().all()

        if not accounts:
            logger.info(f"[Scheduler] No enabled accounts for schedule #{schedule.id}")
            return

        # 3. Process ready user accounts with stacked in-group delivery ("one below one") if multiple accounts
        ready_acc_data = []
        now = datetime.utcnow()

        for acc in accounts:
            if acc.status == "FLOOD_WAIT":
                if acc.rate_limit_until and now >= acc.rate_limit_until:
                    logger.info(f"[Scheduler] FloodWait cleared for {acc.phone_number}. Resuming active status.")
                    acc.status = "ACTIVE"
                    acc.rate_limit_until = None
                    await db.commit()
                else:
                    continue

            if acc.last_used_at:
                seconds_since_last = (now - acc.last_used_at).total_seconds()
                required_seconds = acc.interval_minutes * 60.0
                if seconds_since_last < required_seconds:
                    continue

            if not acc.custom_message:
                continue

            try:
                session_str = acc.get_session_string()
            except Exception:
                continue

            if not session_str:
                acc.is_active = False
                acc.status = "SESSION_EXPIRED"
                await db.commit()
                continue

            variants = [v.strip() for v in acc.custom_message.split("---") if v.strip()] or [acc.custom_message]

            ready_acc_data.append({
                "id": acc.id,
                "account": acc,
                "phone_number": acc.phone_number,
                "session_str": session_str,
                "seq_index": 0,
                "variants": variants,
            })

        if len(ready_acc_data) > 1:
            # Force a single unified sequence index across ALL accounts owned by the user
            shared_seq_idx = ready_acc_data[0]["account"].current_msg_index or 0
            for item in ready_acc_data:
                item["seq_index"] = shared_seq_idx
                item["account"].last_used_at = now
            await db.commit()

            logger.info(f"[Scheduler] Executing STACKED in-group broadcast for {len(ready_acc_data)} accounts of user #{schedule.user_id} (shared_seq_idx={shared_seq_idx})")

            results_by_account = await mtproto_service.broadcast_multi_account_stacked(
                accounts_data=ready_acc_data
            )

            for item in ready_acc_data:
                acc = item["account"]
                acc_id = acc.id
                variants = item["variants"]
                acc_results = results_by_account.get(acc_id, [])

                if len(variants) > 1:
                    acc.current_msg_index = (shared_seq_idx + 1) % len(variants)

                sent_count = 0
                failed_count = 0
                for group_title, success, log_msg, flood_seconds in acc_results:
                    if log_msg == "DUAL_IP_CONFLICT":
                        continue
                    if log_msg == "SESSION_REVOKED":
                        acc.status = "SESSION_REVOKED"
                        acc.is_active = False
                        if user_telegram_id:
                            await _notify_user(user_telegram_id, f"⚠️ <b>Session Logged Out:</b> Session for <code>{acc.phone_number}</code> was logged out on Telegram.")
                        break

                    job_log = JobLog(
                        schedule_id=schedule.id,
                        account_id=acc.id,
                        target_chat=group_title,
                        status="SUCCESS" if success else "FAILED",
                        sent_at=now,
                        error_details=None if success else log_msg
                    )
                    db.add(job_log)
                    if success:
                        sent_count += 1
                    else:
                        failed_count += 1

                    if flood_seconds:
                        acc.status = "FLOOD_WAIT"
                        acc.rate_limit_until = now + timedelta(seconds=flood_seconds)
                        break

                await db.commit()
                logger.info(f"[Scheduler] Stacked finish for {acc.phone_number} — sent={sent_count} failed={failed_count}")
            return

        # Single account fallback
        account_tasks = [
            self._process_single_account(acc.id, schedule.id, user_telegram_id)
            for acc in accounts
        ]
        await asyncio.gather(*account_tasks, return_exceptions=True)

    async def _process_single_account(self, account_id: int, schedule_id: int, user_telegram_id: Optional[int]):
        """Processes a single account broadcast with concurrency semaphore, isolated session and staggered startup safety."""
        async with self.account_semaphore:
            async with async_session_factory() as db:
                account = await db.get(TelegramAccount, account_id)
                if not account or not account.is_active or not account.auto_group_enabled or account.status not in ("ACTIVE", "FLOOD_WAIT"):
                    return

                now = datetime.utcnow()

                # Auto-reset FLOOD_WAIT if the wait period has passed
                if account.status == "FLOOD_WAIT":
                    if account.rate_limit_until and now >= account.rate_limit_until:
                        logger.info(f"[Scheduler] FloodWait cleared for {account.phone_number}. Resuming active status.")
                        account.status = "ACTIVE"
                        account.rate_limit_until = None
                        await db.commit()
                    else:
                        wait_left_secs = int((account.rate_limit_until - now).total_seconds()) if account.rate_limit_until else 60
                        wait_left_mins = round(max(wait_left_secs, 1) / 60.0, 1)
                        logger.info(f"[Scheduler] {account.phone_number} FloodWait active ({wait_left_mins}m remaining) — waiting automatically.")
                        return


                # Check interval timer (strict check: full interval_minutes * 60 seconds required)
                if account.last_used_at:
                    seconds_since_last = (now - account.last_used_at).total_seconds()
                    required_seconds = account.interval_minutes * 60.0
                    if seconds_since_last < required_seconds:
                        remaining_mins = round((required_seconds - seconds_since_last) / 60.0, 1)
                        logger.info(f"[Scheduler] {account.phone_number} — {remaining_mins}m until next send")
                        return

                # Check message is configured
                message_text = account.custom_message
                if not message_text:
                    logger.info(f"[Scheduler] {account.phone_number} — no message set, skipping silently")
                    return

                # Decrypt session
                try:
                    session_str = account.get_session_string()
                except Exception as decrypt_err:
                    logger.error(f"[Scheduler] {account.phone_number} — decrypt error: {decrypt_err}")
                    session_str = ""

                if not session_str:
                    logger.error(f"[Scheduler] {account.phone_number} — session invalid or expired.")
                    account.is_active = False
                    account.status = "SESSION_EXPIRED"
                    await db.commit()
                    if user_telegram_id:
                        await _notify_user(
                            user_telegram_id,
                            f"🔴 <b>Account Action Required:</b> Session for <code>{account.phone_number}</code> requires re-authentication. Tap <b>👤 My Accounts</b> to reconnect."
                        )
                    return

                # Mark last_used_at NOW so interval counts from trigger time
                account.last_used_at = now
                await db.commit()

                # Safety: Add a small random start delay (0 to 1.5s) to stagger concurrent account start times
                import random
                stagger = random.uniform(0.0, 1.5)
                await asyncio.sleep(stagger)

                logger.info(f"[Scheduler] Broadcasting in parallel for {account.phone_number} (interval={account.interval_minutes}m, stagger={stagger:.2f}s)")

                # Run single-connection broadcast to all joined groups
                variants = [v.strip() for v in message_text.split("---") if v.strip()] or [message_text]
                seq_idx = account.current_msg_index or 0

                try:
                    broadcast_results = await mtproto_service.broadcast_to_account_groups(
                        session_str=session_str,
                        message_variants=variants,
                        phone_number=account.phone_number,
                        seq_index=seq_idx
                    )
                except Exception as broadcast_err:
                    logger.error(f"[Scheduler] broadcast failed for {account.phone_number}: {broadcast_err}")
                    return

                if len(variants) > 1:
                    account.current_msg_index = (seq_idx + 1) % len(variants)
                    await db.commit()

                if not broadcast_results:
                    logger.info(f"[Scheduler] {account.phone_number} — no groups found or session unauthorized")
                    return

                # Log results and handle flood wait / session revocation
                sent_count = 0
                failed_count = 0
                session_revoked = False
                for group_title, success, log_msg, flood_seconds in broadcast_results:
                    if log_msg == "DUAL_IP_CONFLICT":
                        logger.warning(f"[Scheduler] Dual IP connection conflict for {account.phone_number} — skipping cycle without deleting account.")
                        break

                    if log_msg == "SESSION_REVOKED":
                        logger.info(f"[Scheduler] Session revoked on Telegram app for {account.phone_number} — setting status to SESSION_REVOKED.")
                        account.status = "SESSION_REVOKED"
                        account.is_active = False
                        await db.commit()
                        session_revoked = True
                        if user_telegram_id:
                            await _notify_user(
                                user_telegram_id,
                                f"⚠️ <b>Session Logged Out:</b> Session for <code>{account.phone_number}</code> was logged out on Telegram. Tap <b>➕ Add Account</b> to reconnect anytime."
                            )
                        break



                    job_log = JobLog(
                        schedule_id=schedule_id,
                        account_id=account.id,
                        target_chat=group_title,
                        status="SUCCESS" if success else "FAILED",
                        sent_at=datetime.utcnow(),
                        error_details=None if success else log_msg
                    )
                    db.add(job_log)
                    if success:
                        sent_count += 1
                    else:
                        failed_count += 1

                    if flood_seconds:
                        account.status = "FLOOD_WAIT"
                        account.rate_limit_until = datetime.utcnow() + timedelta(seconds=flood_seconds)
                        logger.warning(f"[Scheduler] {account.phone_number} FloodWait {flood_seconds}s (silent background pause)")
                        break


                await db.commit()
                if not session_revoked:
                    logger.info(f"[Scheduler] {account.phone_number} — sent={sent_count} failed={failed_count}")

                    try:
                        asyncio.create_task(
                            check_and_alert_new_groups(
                                discovering_phone=account.phone_number,
                                session_str=session_str,
                            )
                        )
                    except Exception as disc_err:
                        logger.debug(f"[GroupAlert] Could not schedule discovery task: {disc_err}")


scheduler_service = SchedulerService()

