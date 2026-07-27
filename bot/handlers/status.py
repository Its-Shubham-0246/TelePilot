from aiogram import Router, F, types
from sqlalchemy import select, func

from core.database import async_session_factory
from models.user import User
from models.schedule import Schedule
from models.job_log import JobLog

router = Router()


@router.message(F.text == "📊 Status")
async def show_status_report(message: types.Message):
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.telegram_id == message.from_user.id))).scalars().first()
        if not user:
            await message.answer("Please type /start first.")
            return

        # Total Messages Sent
        stmt_success = select(func.count(JobLog.id)).join(Schedule).where(
            Schedule.user_id == user.id,
            JobLog.status == "SUCCESS"
        )
        total_sent = (await db.execute(stmt_success)).scalar() or 0

        # Total Failed Messages
        stmt_failed = select(func.count(JobLog.id)).join(Schedule).where(
            Schedule.user_id == user.id,
            JobLog.status == "FAILED"
        )
        total_failed = (await db.execute(stmt_failed)).scalar() or 0

        # Rate Limit Warnings
        stmt_flood = select(func.count(JobLog.id)).join(Schedule).where(
            Schedule.user_id == user.id,
            JobLog.status == "FLOOD_WAIT"
        )
        total_flood = (await db.execute(stmt_flood)).scalar() or 0

        # Connected Groups & Schedule Info
        stmt_sched = select(Schedule).where(Schedule.user_id == user.id)
        sched = (await db.execute(stmt_sched)).scalars().first()
        connected_groups = len(sched.target_chats) if (sched and sched.target_chats) else 0

        # Last Activity
        stmt_last = select(JobLog).join(Schedule).where(
            Schedule.user_id == user.id
        ).order_by(JobLog.sent_at.desc())
        last_log = (await db.execute(stmt_last)).scalars().first()
        last_activity = last_log.sent_at.strftime("%Y-%m-%d %H:%M UTC") if last_log else "No recent activity"

    report_text = (
        f"<b>📊 SaaS Detailed Status Report</b>\n\n"
        f"<b>✅ Total Messages Sent:</b> {total_sent}\n"
        f"<b>❌ Failed Messages:</b> {total_failed}\n"
        f"<b>⚠️ Rate-Limit Warnings:</b> {total_flood}\n"
        f"<b>📢 Connected Groups:</b> {connected_groups}\n"
        f"<b>🕒 Last Activity:</b> {last_activity}\n"
    )

    await message.answer(report_text)
