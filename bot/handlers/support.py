from aiogram import Router, F, types

router = Router()

UPDATES_CHANNEL_URL = "https://t.me/TelePilotUpdates"


@router.message(F.text == "⚙️ Settings")
async def show_settings(message: types.Message):
    settings_text = (
        "<b>⚙️ User Settings</b>\n\n"
        "<b>Timezone:</b> UTC (Default)\n"
        "<b>Anti-Spam Delay Jitter:</b> Enabled (1-5s random offset)\n"
        "<b>Session Data Encryption:</b> AES-256 Enabled\n\n"
        "<i>To modify your time-zone or schedule interval, use the ⏰ Scheduler menu.</i>"
    )
    await message.answer(settings_text)


@router.message(F.text == "🆘 Support")
async def show_support(message: types.Message):
    support_text = (
        "<b>🆘 Help & Support</b>\n\n"
        "<b>Telegram Terms of Service Disclaimer:</b>\n"
        "This software acts only on Telegram accounts whose owners have explicitly connected and authorized access.\n"
        "Avoid aggressive bulk messaging or spam to prevent Telegram account restrictions.\n\n"
        "<b>Technical Assistance:</b>\n"
        "Contact Admin / Support Team for payment verification issues or session setup assistance.\n\n"
        f"📢 <b>Updates & Announcements:</b>\n"
        f"Join our channel for latest features, fixes & sale alerts:\n"
        f"👉 <a href='{UPDATES_CHANNEL_URL}'>t.me/TelePilotUpdates</a>"
    )
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📢 Join Updates Channel", url=UPDATES_CHANNEL_URL)]
    ])
    await message.answer(support_text, reply_markup=kb, disable_web_page_preview=True)


@router.message(F.text == "📢 Updates Channel")
async def show_updates_channel(message: types.Message):
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📢 Open TelePilot Updates", url=UPDATES_CHANNEL_URL)]
    ])
    await message.answer(
        f"📢 <b>TelePilot Official Updates Channel</b>\n\n"
        f"Get the latest:\n"
        f"✅ New features & improvements\n"
        f"🔥 Exclusive discounts & sales\n"
        f"🐛 Bug fix notices\n"
        f"⚙️ Maintenance alerts\n\n"
        f"👇 Tap below to join:",
        reply_markup=kb,
        disable_web_page_preview=True
    )

