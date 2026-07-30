from aiogram import Router, types
from aiogram.filters import CommandStart
from sqlalchemy import select
from core.database import async_session_factory
from models.user import User
from config import settings
from bot.keyboards.main_menu import get_main_menu_keyboard
from services.subscription_service import subscription_service

router = Router()


@router.message(CommandStart())
async def cmd_start(message: types.Message):
    if message.chat.type != "private":
        await message.answer("👉 Please click @TelePilotSaaSBot to message me in private chat!")
        return

    trial_granted = False
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

        trial_granted = await subscription_service.grant_free_trial_if_new_user(db, user.id)

    if trial_granted:
        welcome_text = (
            f"<b>Welcome to TelePilot — Telegram Group Automation!</b> 🚀\n"
            f"🎁 <b>SPECIAL BONUS: 1-DAY FREE TRIAL ACTIVATED!</b>\n\n"
            f"Your 24-Hour Free Access is <b>ACTIVE</b> right now! Test all features with up to 5 accounts.\n\n"
            f"<b>Getting Started in 3 Simple Steps:</b>\n"
            f"1️⃣ Tap <b>➕ Add Account</b> to connect your Telegram account\n"
            f"2️⃣ Tap <b>💬 Messages</b> to set your text & interval timer\n"
            f"3️⃣ Tap <b>▶️ Start</b> to launch auto-broadcasting 24/7!\n\n"
            f"📢 Stay updated: <a href='https://t.me/TelePilotUpdates'>t.me/TelePilotUpdates</a>\n\n"
            f"Use the menu below to get started:"
        )
    else:
        welcome_text = (
            f"<b>Welcome to TelePilot — Telegram Group Automation!</b> 🚀\n"
            f"👥 <b>Trusted by 10,000+ Users & Marketers Worldwide</b>\n\n"
            f"Automate group messaging securely using your authorized Telegram accounts.\n\n"
            f"<b>Key Features:</b>\n"
            f"• Multi-account management (Up to 15 accounts)\n"
            f"• AES-256 session encryption\n"
            f"• Message variants & rotation\n"
            f"• Exact-interval scheduling (1 min → 5 hrs)\n\n"
            f"📢 Stay updated: <a href='https://t.me/TelePilotUpdates'>t.me/TelePilotUpdates</a>\n\n"
            f"Use the menu below to get started."
        )

    await message.answer(welcome_text, reply_markup=get_main_menu_keyboard(), disable_web_page_preview=True)

