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

    async def process_active_schedules(self):
        """Iterates over active schedules and runs group broadcasts for enabled accounts."""
        try:
            async with async_session_factory() as db:
                stmt = select(Schedule).where(Schedule.is_active == True)
                result = await db.execute(stmt)
                schedules = result.scalars().all()

                for sched in schedules:
                    try:
                        await self._execute_schedule_job(db, sched)
                    except Exception as e:
                        logger.error(f"[Scheduler] Error processing schedule #{sched.id}: {e}")
        except Exception as e:
            logger.error(f"[Scheduler] process_active_schedules exception: {e}")

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

        now = datetime.utcnow()

        for account in accounts:
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
                    continue

            # Skip banned/broken accounts
            if account.status in ("BANNED", "RE_LOGIN_REQUIRED"):
                logger.info(f"[Scheduler] {account.phone_number} status={account.status} — skipping")
                continue

            # Check interval timer (with 2-second grace window for exact timing)
            if account.last_used_at:
                seconds_since_last = (now - account.last_used_at).total_seconds()
                required_seconds = account.interval_minutes * 60 - 2
                if seconds_since_last < required_seconds:
                    remaining_mins = round((account.interval_minutes * 60 - seconds_since_last) / 60.0, 1)
                    logger.info(f"[Scheduler] {account.phone_number} — {remaining_mins}m until next send")
                    continue

            # Check message is configured
            message_text = account.custom_message
            if not message_text:
                logger.warning(f"[Scheduler] {account.phone_number} — no message set, skipping")
                if user_telegram_id:
                    await _notify_user(
                        user_telegram_id,
                        f"⚠️ <b>No Message Configured!</b>\n\n"
                        f"Account <code>{account.phone_number}</code> has no message set.\n\n"
                        f"Tap <b>💬 Messages</b> → select the account → <b>📝 Set / Edit Message</b>"
                    )
                continue

            # Get decrypted session
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
                        f"The session for <code>{account.phone_number}</code> is invalid or expired.\n\n"
                        f"Please:\n"
                        f"1️⃣ Tap <b>👤 My Accounts</b>\n"
                        f"2️⃣ Find this account → <b>🗑 Remove Account</b>\n"
                        f"3️⃣ Tap <b>➕ Add Account</b> to reconnect"
                    )
                continue

            # Mark last_used_at NOW (before broadcast) so interval counts from trigger time
            account.last_used_at = now
            await db.commit()

            logger.info(f"[Scheduler] Broadcasting for {account.phone_number} (interval={account.interval_minutes}m)")

            # Run single-connection broadcast to all joined groups
            variants = [v.strip() for v in message_text.split("---") if v.strip()] or [message_text]
            try:
                broadcast_results = await mtproto_service.broadcast_to_account_groups(
                    session_str=session_str,
                    message_variants=variants
                )
            except Exception as broadcast_err:
                logger.error(f"[Scheduler] broadcast_to_account_groups failed for {account.phone_number}: {broadcast_err}")
                if user_telegram_id:
                    await _notify_user(
                        user_telegram_id,
                        f"❌ <b>Broadcast Error</b>\n\n"
                        f"Account <code>{account.phone_number}</code> failed to broadcast:\n"
                        f"<code>{str(broadcast_err)[:200]}</code>\n\n"
                        f"Auto-messaging will retry on next interval."
                    )
                continue

            if not broadcast_results:
                logger.info(f"[Scheduler] {account.phone_number} — no groups found or session unauthorized")
                if user_telegram_id:
                    await _notify_user(
                        user_telegram_id,
                        f"⚠️ <b>No Groups Found</b>\n\n"
                        f"Account <code>{account.phone_number}</code> is not a member of any Telegram groups, "
                        f"or the session has expired.\n\n"
                        f"If you recently joined groups, wait a moment and click <b>▶️ Start</b> again."
                    )
                continue

            # Log results and handle flood wait
            sent_count = 0
            failed_count = 0
            flood_hit = False
            for group_title, success, log_msg, flood_seconds in broadcast_results:
                job_log = JobLog(
                    schedule_id=schedule.id,
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
                    flood_hit = True
                    logger.warning(f"[Scheduler] {account.phone_number} FloodWait {flood_seconds}s")
                    if user_telegram_id:
                        wait_mins = round(flood_seconds / 60, 1)
                        await _notify_user(
                            user_telegram_id,
                            f"⏳ <b>Rate Limited!</b>\n\n"
                            f"Account <code>{account.phone_number}</code> hit Telegram's rate limit.\n"
                            f"Auto-messaging paused for <b>{wait_mins} minute(s)</b> and will resume automatically."
                        )
                    break

            await db.commit()
            logger.info(f"[Scheduler] {account.phone_number} — sent={sent_count} failed={failed_count} flood={flood_hit}")


scheduler_service = SchedulerService()
