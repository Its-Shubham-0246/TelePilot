from aiogram import Router, types
from aiogram.filters import CommandStart
from sqlalchemy import select
from core.database import async_session_factory
from models.user import User
from config import settings
from bot.keyboards.main_menu import get_main_menu_keyboard
from services.subscription_service import is_sale_active, get_sale_days_left

router = Router()


@router.message(CommandStart())
async def cmd_start(message: types.Message):
    if message.chat.type != "private":
        await message.answer("👉 Please click @TelePilotSaaSBot to message me in private chat!")
        return

    # Check for referral deep-link parameter (e.g. /start ref_12345 or /start 12345)
    referrer_telegram_id = None
    args = message.text.split()
    if len(args) > 1:
        param = args[1].strip()
        if param.startswith("ref_"):
            param = param.replace("ref_", "")
        if param.isdigit():
            referrer_telegram_id = int(param)

    async with async_session_factory() as db:
        stmt = select(User).where(User.telegram_id == message.from_user.id)
        result = await db.execute(stmt)
        user = result.scalars().first()

        if not user:
            is_admin = message.from_user.id in settings.admin_ids_list
            
            # Find referrer if valid and not self-referral
            referrer_user = None
            if referrer_telegram_id and referrer_telegram_id != message.from_user.id:
                stmt_ref = select(User).where(User.telegram_id == referrer_telegram_id)
                referrer_user = (await db.execute(stmt_ref)).scalars().first()

            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
                is_admin=is_admin,
                referrer_id=referrer_user.id if referrer_user else None,
                ref_commission_rate=0.30  # 30% commission
            )
            db.add(user)
            await db.commit()

            # Notify referrer of new sign-up
            if referrer_user:
                try:
                    from bot.bot_instance import bot
                    username_str = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name or "New user"
                    await bot.send_message(
                        referrer_user.telegram_id,
                        f"🎉 <b>New Referral Joined!</b>\n\n"
                        f"User {username_str} just joined TelePilot using your referral link!\n\n"
                        f"💰 You will earn <b>30% commission</b> on all their subscription purchases! 🚀",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass


    if is_sale_active():
        sale_left = get_sale_days_left()
        welcome_text = (
            f"<b>Welcome to TelePilot — Telegram Group Automation!</b> 🚀\n"
            f"👥 <b>Trusted by 10,000+ Users & Marketers Worldwide</b>\n\n"
            f"🔥 <b>LIMITED SALE — {sale_left} DAYS LEFT!</b>\n"
            f"⚡ 1 Day    — <s>₹49</s>  ➜  <b>₹39</b>\n"
            f"📅 7 Days  — <s>₹199</s> ➜  <b>₹179</b>\n"
            f"🏆 30 Days — <s>₹399</s> ➜  <b>₹299</b>\n\n"
            f"Automate group messaging securely using your authorized Telegram accounts.\n\n"
            f"<b>Key Features:</b>\n"
            f"• Multi-account management (Up to 15 accounts)\n"
            f"• AES-256 session encryption\n"
            f"• Message variants & rotation\n"
            f"• Exact-interval scheduling (1 min → 5 hrs)\n\n"
            f"📢 Stay updated: <a href='https://t.me/TelePilotUpdates'>t.me/TelePilotUpdates</a>\n\n"
            f"Use the menu below to get started."
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


