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
        Claims or updates the active leader lock in the database for this container instance.
        Returns True if this container is the active LEADER.
        """
        from models.system_lock import SystemLock, INSTANCE_ID
        try:
            async with async_session_factory() as db:
                lock = await db.get(SystemLock, "scheduler_leader")
                now = datetime.utcnow()
                if not lock:
                    lock = SystemLock(key="scheduler_leader", instance_id=INSTANCE_ID, updated_at=now)
                    db.add(lock)
                else:
                    lock.instance_id = INSTANCE_ID
                    lock.updated_at = now
                await db.commit()
                return True
        except Exception as e:
            logger.warning(f"[SchedulerLock] claim_leadership warning: {e}")
            return True

    async def is_leader(self) -> bool:
        """
        Checks if this container instance is currently the registered leader.
        """
        from models.system_lock import SystemLock, INSTANCE_ID
        try:
            async with async_session_factory() as db:
                lock = await db.get(SystemLock, "scheduler_leader")
                if not lock:
                    return True
                return lock.instance_id == INSTANCE_ID
        except Exception as e:
            return True

    async def process_active_schedules(self):
        """Iterates over active schedules and runs group broadcasts for enabled accounts in parallel."""
        # Leader Lock Check — prevent dual-container execution during Railway rolling deploys
        if not await self.is_leader():
            logger.info("[SchedulerLock] Skipping schedule processing — another container instance is active leader.")
            return

        try:
            # Step 1: Collect active schedule IDs using a short-lived session
            async with async_session_factory() as db:
                stmt = select(Schedule).where(Schedule.is_active == True)
                result = await db.execute(stmt)
                schedule_ids = [s.id for s in result.scalars().all()]

            if not schedule_ids:
                return

            # Step 2: Run all active schedule checks concurrently in parallel
            tasks = [self._process_single_schedule(sched_id) for sched_id in schedule_ids]
            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            logger.error(f"[Scheduler] process_active_schedules failed: {type(e).__name__}: {e}", exc_info=True)

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
            TelegramAccount.auto_group_enabled == True,
        )
        accounts_res = await db.execute(stmt_acc)
        accounts: List[TelegramAccount] = accounts_res.scalars().all()

        if not accounts:
            logger.info(f"[Scheduler] No enabled accounts for schedule #{schedule.id}")
            return

        account_ids = [acc.id for acc in accounts]

        # 3. Process each ready account in PARALLEL using individual tasks & sessions
        account_tasks = [
            self._process_single_account(acc_id, schedule.id, user_telegram_id)
            for acc_id in account_ids
        ]
        await asyncio.gather(*account_tasks, return_exceptions=True)

    async def _process_single_account(self, account_id: int, schedule_id: int, user_telegram_id: Optional[int]):
        """Processes a single account broadcast with concurrency semaphore, isolated session and staggered startup safety."""
        async with self.account_semaphore:
            async with async_session_factory() as db:
                account = await db.get(TelegramAccount, account_id)
                if not account or not account.is_active or not account.auto_group_enabled:
                    return

            now = datetime.utcnow()

            # Auto-reset FLOOD_WAIT if the wait period has passed
            if account.status == "FLOOD_WAIT" and account.rate_limit_until:
                if now >= account.rate_limit_until:
                    logger.info(f"[Scheduler] FloodWait cleared for {account.phone_number}")
                    account.status = "ACTIVE"
                    account.rate_limit_until = None
                    await db.commit()
                else:
                    wait_left = int((account.rate_limit_until - now).total_seconds() / 60)
                    logger.info(f"[Scheduler] {account.phone_number} FloodWait {wait_left}m left — skipping")
                    return

            # Skip banned/broken accounts
            if account.status in ("BANNED", "RE_LOGIN_REQUIRED"):
                logger.info(f"[Scheduler] {account.phone_number} status={account.status} — skipping")
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
                logger.error(f"[Scheduler] {account.phone_number} — session invalid (needs re-login)")
                account.status = "RE_LOGIN_REQUIRED"
                await db.commit()
                if user_telegram_id:
                    await _notify_user(
                        user_telegram_id,
                        f"🔴 <b>Account Needs Re-Login!</b>\n\n"
                        f"The session for <code>{account.phone_number}</code> has expired or is invalid.\n\n"
                        f"Please:\n"
                        f"1️⃣ Tap <b>👤 My Accounts</b>\n"
                        f"2️⃣ Find this account → <b>🗑 Remove Account</b>\n"
                        f"3️⃣ Tap <b>➕ Add Account</b> to reconnect"
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
            try:
                broadcast_results = await mtproto_service.broadcast_to_account_groups(
                    session_str=session_str,
                    message_variants=variants,
                    phone_number=account.phone_number
                )
            except Exception as broadcast_err:
                logger.error(f"[Scheduler] broadcast failed for {account.phone_number}: {broadcast_err}")
                return

            if not broadcast_results:
                logger.info(f"[Scheduler] {account.phone_number} — no groups found or session unauthorized")
                return

            # Log results and handle flood wait / session revocation
            sent_count = 0
            failed_count = 0
            session_revoked = False
            for group_title, success, log_msg, flood_seconds in broadcast_results:
                if log_msg == "SESSION_REVOKED":
                    account.status = "RE_LOGIN_REQUIRED"
                    await db.commit()
                    session_revoked = True
                    if user_telegram_id:
                        await _notify_user(
                            user_telegram_id,
                            f"🔴 <b>Account Session Terminated!</b>\n\n"
                            f"<code>{account.phone_number}</code> was connected from two locations simultaneously "
                            f"(happens during Railway deploys) and Telegram permanently terminated the session.\n\n"
                            f"Please:\n"
                            f"1️⃣ Tap <b>👤 My Accounts</b>\n"
                            f"2️⃣ Find this account → <b>🗑 Remove Account</b>\n"
                            f"3️⃣ Tap <b>➕ Add Account</b> to reconnect"
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
                    logger.warning(f"[Scheduler] {account.phone_number} FloodWait {flood_seconds}s")
                    if user_telegram_id:
                        wait_mins = round(flood_seconds / 60, 1)
                        await _notify_user(
                            user_telegram_id,
                            f"⏳ <b>Rate Limited by Telegram!</b>\n\n"
                            f"Account <code>{account.phone_number}</code> hit Telegram's rate limit.\n"
                            f"Auto-messaging paused for <b>{wait_mins} minute(s)</b> and will resume automatically."
                        )
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

