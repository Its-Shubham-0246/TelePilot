from datetime import datetime, timedelta
from aiogram import Router, F, types
from sqlalchemy import select, func
from core.database import async_session_factory
from models.user import User
from models.account import TelegramAccount
from models.schedule import Schedule
from models.job_log import JobLog
from services.subscription_service import subscription_service

router = Router()


@router.message(F.text == "🏠 Dashboard")
async def show_dashboard(message: types.Message):
    async with async_session_factory() as db:
        # Get user
        stmt_user = select(User).where(User.telegram_id == message.from_user.id)
        user_res = await db.execute(stmt_user)
        user = user_res.scalars().first()

        if not user:
            await message.answer("Please type /start to initialize your profile.")
            return

        # 1. Subscription Info
        sub = await subscription_service.get_active_subscription(db, user.id)
        if sub:
            sub_status = f"🟢 Active ({sub.plan_name})"
            days_left = (sub.expires_at - datetime.utcnow()).days
            days_str = f"{days_left} Days"
        else:
            sub_status = "🔴 Inactive / Expired"
            days_str = "0 Days"

        # 2. Connected Accounts
        stmt_acc = select(func.count(TelegramAccount.id)).where(TelegramAccount.user_id == user.id)
        acc_count = (await db.execute(stmt_acc)).scalar() or 0

        # 3. Schedule Running Status
        stmt_sched = select(Schedule).where(Schedule.user_id == user.id)
        sched_res = await db.execute(stmt_sched)
        schedules = sched_res.scalars().all()
        is_running = any(s.is_active for s in schedules)
        status_str = "▶️ Running" if is_running else "⏸ Stopped / Paused"

        # 4. Messages Sent Today
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        stmt_sent = select(func.count(JobLog.id)).join(Schedule).where(
            Schedule.user_id == user.id,
            JobLog.status == "SUCCESS",
            JobLog.sent_at >= today_start
        )
        sent_today = (await db.execute(stmt_sent)).scalar() or 0

        # 5. Errors & Warnings
        stmt_err = select(func.count(JobLog.id)).join(Schedule).where(
            Schedule.user_id == user.id,
            JobLog.status.in_(["FAILED", "FLOOD_WAIT"]),
            JobLog.sent_at >= today_start
        )
        errors_today = (await db.execute(stmt_err)).scalar() or 0

    dashboard_text = (
        f"<b>📊 SaaS User Dashboard</b>\n\n"
        f"<b>👤 User:</b> {user.full_name or user.username or message.from_user.id}\n"
        f"<b>💳 Subscription:</b> {sub_status}\n"
        f"<b>⏳ Days Remaining:</b> {days_str}\n"
        f"<b>📱 Connected Accounts:</b> {acc_count} / 15\n"
        f"<b>⚡ Schedule Status:</b> {status_str}\n"
        f"<b>📤 Messages Sent Today:</b> {sent_today}\n"
        f"<b>⚠️ Errors/Warnings Today:</b> {errors_today}\n"
    )

    await message.answer(dashboard_text)
