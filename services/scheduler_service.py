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
                minutes=1,
                id='master_schedule_runner',
                replace_existing=True
            )

    def stop(self):
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("APScheduler engine stopped.")

    async def process_active_schedules(self):
        """Iterates over active schedules and runs group broadcasts for enabled accounts."""
        async with async_session_factory() as db:
            stmt = select(Schedule).where(Schedule.is_active == True)
            result = await db.execute(stmt)
            schedules = result.scalars().all()

            for sched in schedules:
                try:
                    await self._execute_schedule_job(db, sched)
                except Exception as e:
                    logger.error(f"Error processing schedule #{sched.id}: {e}")

    async def _execute_schedule_job(self, db, schedule: Schedule):
        # 1. Verify user active subscription
        has_sub = await subscription_service.check_user_has_active_sub(db, schedule.user_id)
        if not has_sub:
            logger.info(f"User #{schedule.user_id} subscription expired. Pausing schedule.")
            schedule.is_active = False
            await db.commit()
            return

        # 2. Fetch enabled user accounts (don't filter by status here — we handle it below)
        stmt_acc = select(TelegramAccount).where(
            TelegramAccount.user_id == schedule.user_id,
            TelegramAccount.is_active == True,
            TelegramAccount.auto_group_enabled == True,
        )
        accounts_res = await db.execute(stmt_acc)
        accounts: List[TelegramAccount] = accounts_res.scalars().all()

        if not accounts:
            logger.warning(f"No active & enabled accounts for schedule #{schedule.id}")
            return

        now = datetime.utcnow()

        for account in accounts:
            # Auto-reset FLOOD_WAIT if the wait period has passed
            if account.status == "FLOOD_WAIT" and account.rate_limit_until:
                if now >= account.rate_limit_until:
                    logger.info(f"[Scheduler] FloodWait cleared for {account.phone_number}")
                    account.status = "ACTIVE"
                    account.rate_limit_until = None
                else:
                    wait_left = int((account.rate_limit_until - now).total_seconds() / 60)
                    logger.info(f"[Scheduler] {account.phone_number} still in FloodWait ({wait_left}m left) — skipping")
                    continue

            # Skip banned accounts
            if account.status in ("BANNED", "RE_LOGIN_REQUIRED"):
                logger.info(f"[Scheduler] {account.phone_number} status={account.status} — skipping")
                continue

            # Check interval timer
            if account.last_used_at:
                minutes_since_last = (now - account.last_used_at).total_seconds() / 60.0
                if minutes_since_last < account.interval_minutes:
                    remaining = round(account.interval_minutes - minutes_since_last, 1)
                    logger.info(f"[Scheduler] {account.phone_number} — interval not reached ({remaining}m left)")
                    continue

            # Check message is configured
            message_text = account.custom_message
            if not message_text:
                logger.warning(f"[Scheduler] {account.phone_number} — no custom_message configured, skipping")
                continue

            # Get decrypted session
            session_str = account.get_session_string()
            if not session_str:
                logger.error(f"[Scheduler] {account.phone_number} — session decrypt failed (encryption key changed?), skipping")
                continue

            logger.info(f"[Scheduler] Running broadcast for {account.phone_number}")

            # 3. Fetch all joined groups
            try:
                joined_groups = await mtproto_service.fetch_joined_groups(session_str)
            except Exception as e:
                logger.error(f"[Scheduler] fetch_joined_groups failed for {account.phone_number}: {e}")
                account.last_used_at = now
                await db.commit()
                continue

            if not joined_groups:
                logger.info(f"[Scheduler] {account.phone_number} — not in any groups")
                account.last_used_at = now
                await db.commit()
                continue

            logger.info(f"[Scheduler] {account.phone_number} — broadcasting to {len(joined_groups)} group(s)")

            # 4. Broadcast message to all joined groups
            variants = [v.strip() for v in message_text.split("---") if v.strip()] or [message_text]
            for group_entity, group_title in joined_groups:
                success, log_msg, flood_seconds = await mtproto_service.send_message_to_target(
                    session_str=session_str,
                    target_chat=group_entity,
                    message_variants=variants,
                    delay_seconds=3
                )

                # Log result
                job_log = JobLog(
                    schedule_id=schedule.id,
                    account_id=account.id,
                    target_chat=group_title,
                    status="SUCCESS" if success else "FAILED",
                    sent_at=datetime.utcnow(),
                    error_details=None if success else log_msg
                )
                db.add(job_log)

                if flood_seconds:
                    account.status = "FLOOD_WAIT"
                    account.rate_limit_until = datetime.utcnow() + timedelta(seconds=flood_seconds)
                    logger.warning(f"[Scheduler] {account.phone_number} FloodWait {flood_seconds}s — pausing")
                    break

            account.last_used_at = datetime.utcnow()
            await db.commit()
            logger.info(f"[Scheduler] Broadcast complete for {account.phone_number}")


scheduler_service = SchedulerService()

