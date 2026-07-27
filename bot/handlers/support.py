from aiogram import Router, F, types

router = Router()


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
        "Contact Admin / Support Team for payment verification issues or session setup assistance."
    )
    await message.answer(support_text)
