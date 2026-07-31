import asyncio
from aiogram import Router, F, types
from sqlalchemy import select

from core.database import async_session_factory
from models.user import User
from models.schedule import Schedule
from models.account import TelegramAccount
from services.scheduler_service import scheduler_service
from bot.keyboards.main_menu import get_main_menu_keyboard

router = Router()




@router.message(F.text == "⏰ Scheduler")
async def show_scheduler_menu(message: types.Message):
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.telegram_id == message.from_user.id))).scalars().first()
        if not user:
            await message.answer("Please type /start first.")
            return

        sched = (await db.execute(select(Schedule).where(Schedule.user_id == user.id))).scalars().first()
        stmt_acc = select(TelegramAccount).where(TelegramAccount.user_id == user.id, TelegramAccount.auto_group_enabled == True)
        enabled_accs = (await db.execute(stmt_acc)).scalars().all()

    status_text = "▶️ Running" if (sched and sched.is_active) else "⏸ Stopped / Paused"
    enabled_count = len(enabled_accs)

    info = (
        f"<b>⏰ Automation Scheduler</b>\n\n"
        f"<b>System Status:</b> {status_text}\n"
        f"<b>Active Enabled Accounts:</b> {enabled_count} account(s)\n"
        f"<b>Group Strategy:</b> Automatic discovery of all joined groups/supergroups for each account.\n\n"
        f"<i>To configure message content, timer, or toggle auto-messaging per account, use <b>💬 Messages</b> or <b>👤 My Accounts</b>.</i>\n\n"
        f"Press <b>▶️ Start</b> to launch auto group messaging across all enabled accounts!"
    )

    await message.answer(info, reply_markup=get_main_menu_keyboard())


@router.message(F.text == "▶️ Start")
async def start_automation(message: types.Message):
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.telegram_id == message.from_user.id))).scalars().first()
        if not user:
            return

        # Check user accounts
        stmt_all = select(TelegramAccount).where(
            TelegramAccount.user_id == user.id,
            TelegramAccount.is_active == True
        )
        all_accounts = (await db.execute(stmt_all)).scalars().all()

        if not all_accounts:
            await message.answer(
                "⚠️ No Telegram accounts connected yet. Please tap <b>➕ Add Account</b> to connect your account first.",
                reply_markup=get_main_menu_keyboard()
            )
            return

        # Filter enabled accounts, auto-enable if none are enabled
        enabled_accounts = [acc for acc in all_accounts if acc.auto_group_enabled]
        if not enabled_accounts:
            for acc in all_accounts:
                acc.auto_group_enabled = True
            enabled_accounts = all_accounts

        # Only reset last_used_at if account has never been run before
        for acc in enabled_accounts:
            if not acc.last_used_at:
                acc.last_used_at = None

        # Get or create schedule
        sched = (await db.execute(select(Schedule).where(Schedule.user_id == user.id))).scalars().first()
        if not sched:
            sched = Schedule(
                user_id=user.id,
                mode="AUTO_GROUP",
                interval_minutes=30,
                is_active=True
            )
            db.add(sched)
        else:
            sched.is_active = True

        await db.commit()

    await message.answer(
        f"🚀 <b>Auto Group Automation Started!</b>\n\n"
        f"<b>Enabled Accounts:</b> {len(enabled_accounts)} account(s)\n\n"
        f"⚡ <b>Automation Active:</b> Messages will repeat automatically according to each account's configured timer interval.",
        reply_markup=get_main_menu_keyboard()
    )

    # Trigger immediate execution in background task
    asyncio.create_task(scheduler_service.process_active_schedules())


@router.message(F.text.in_(["⏸ Pause", "⏹ Stop"]))
async def stop_automation(message: types.Message):
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.telegram_id == message.from_user.id))).scalars().first()
        if not user:
            return
        sched = (await db.execute(select(Schedule).where(Schedule.user_id == user.id))).scalars().first()
        if sched:
            sched.is_active = False
            await db.commit()

    await message.answer("⏸ <b>Auto Group Automation Stopped / Paused.</b>", reply_markup=get_main_menu_keyboard())
