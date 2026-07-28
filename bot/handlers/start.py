from aiogram import Router, types
from aiogram.filters import CommandStart
from sqlalchemy import select
from core.database import async_session_factory
from models.user import User
from config import settings
from bot.keyboards.main_menu import get_main_menu_keyboard

router = Router()


@router.message(CommandStart())
async def cmd_start(message: types.Message):
    async with async_session_factory() as db:
        stmt = select(User).where(User.telegram_id == message.from_user.id)
        result = await db.execute(stmt)
        user = result.scalars().first()

        if not user:
            is_admin = message.from_user.id in settings.admin_ids_list
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
                is_admin=is_admin
            )
            db.add(user)
            await db.commit()

    welcome_text = (
        f"<b>Welcome to TelePilot — Telegram Group Automation!</b> 🚀\n\n"
        f"Automate group messaging securely using your authorized Telegram accounts.\n\n"
        f"<b>Key Features:</b>\n"
        f"• Multi-account management\n"
        f"• AES-256 session encryption\n"
        f"• Message variants & rotation\n"
        f"• Exact-interval scheduling (1 min → 5 hrs)\n\n"
        f"📢 Stay updated: <a href='https://t.me/TelePilotUpdates'>t.me/TelePilotUpdates</a>\n"
        f"Use the menu below to get started."
    )

    await message.answer(welcome_text, reply_markup=get_main_menu_keyboard(), disable_web_page_preview=True)
