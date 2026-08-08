import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from datetime import datetime

from core.database import async_session_factory
from models.user import User
from models.account import TelegramAccount
from bot.keyboards.inline import (
    get_messages_accounts_keyboard,
    get_account_msg_config_keyboard,
    get_timer_preset_keyboard
)
from bot.keyboards.main_menu import get_main_menu_keyboard, get_cancel_keyboard

from services.mtproto_service import mtproto_service

logger = logging.getLogger(__name__)

router = Router()


class ConfigAccountMsgStates(StatesGroup):
    waiting_for_message = State()
    waiting_for_timer = State()
    waiting_for_common_message = State()
    waiting_for_common_timer = State()


@router.message(F.text == "💬 Messages")
async def manage_messages_entry(message: types.Message):
    await show_accounts_message_list(message)


@router.callback_query(F.data == "msg_list_accounts")
async def callback_list_accounts(callback: types.CallbackQuery):
    await show_accounts_message_list(callback.message, edit=True)


async def show_accounts_message_list(event_obj, edit: bool = False):
    async with async_session_factory() as db:
        user_stmt = select(User).where(User.telegram_id == event_obj.from_user.id)
        user = (await db.execute(user_stmt)).scalars().first()
        if not user:
            return

        stmt = select(TelegramAccount).where(
            TelegramAccount.user_id == user.id,
            TelegramAccount.is_active == True
        )
        accounts = (await db.execute(stmt)).scalars().all()

    if not accounts:
        text = "⚠️ No Telegram accounts connected yet. Please tap <b>➕ Add Account</b> to connect your account first."
        if edit and isinstance(event_obj, types.Message):
            await event_obj.edit_text(text, reply_markup=get_main_menu_keyboard())
        else:
            await event_obj.answer(text, reply_markup=get_main_menu_keyboard())
        return

    text = (
        "<b>💬 Config Messages & Timers for Accounts</b>\n\n"
        "🌐 <b>Common Message & Timer (All Accounts):</b> Set a shared message and timer to synchronize auto-messaging across all accounts simultaneously.\n\n"
        "📱 <b>Individual Account Config:</b> Select an account below to configure individual messages and timers."
    )
    kb = get_messages_accounts_keyboard(accounts)
    if edit and isinstance(event_obj, types.Message):
        await event_obj.edit_text(text, reply_markup=kb)
    else:
        await event_obj.answer(text, reply_markup=kb)


@router.callback_query(F.data == "cfg_common_msg")
async def start_set_common_message(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ConfigAccountMsgStates.waiting_for_common_message)

    await callback.message.answer(
        "<b>🌐 Set Common Auto-Messaging Text for ALL Accounts</b>\n\n"
        "Send your message text below. It will be applied to <b>ALL your connected accounts simultaneously</b>!\n\n"
        "💡 <b>Sequential Switching:</b> Separate multiple message versions using <code>---</code> on a new line. Messages will switch sequentially (Msg 1 ➔ Msg 2 ➔ Msg 3 ➔ Msg 1...) on every interval cycle for all accounts at the exact same scheduled time!\n\n"
        "💡 <b>Spintax Randomization:</b> Use <code>{Click Here|Watch Now|Download Free}</code> for word variations per send.\n\n"
        "Tap <b>🔙 Back to Main Menu</b> to cancel.",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()


@router.message(ConfigAccountMsgStates.waiting_for_common_message)
async def process_common_message(message: types.Message, state: FSMContext):
    if message.text.strip() == "🔙 Back to Main Menu":
        await state.clear()
        await message.answer("🏠 Returned to main menu.", reply_markup=get_main_menu_keyboard())
        return

    msg_text = message.text.strip()

    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.telegram_id == message.from_user.id))).scalars().first()
        if user:
            accs = (await db.execute(
                select(TelegramAccount).where(
                    TelegramAccount.user_id == user.id,
                    TelegramAccount.is_active == True
                )
            )).scalars().all()
            for acc in accs:
                acc.custom_message = msg_text
                acc.current_msg_index = 0
            await db.commit()
            acc_count = len(accs)
        else:
            acc_count = 0

    await state.clear()
    await message.answer(
        f"✅ <b>Common Message set for ALL {acc_count} connected accounts!</b>\n\n"
        f"All accounts will now send this message sequentially at the exact same scheduled interval.",
        reply_markup=get_main_menu_keyboard()
    )


@router.callback_query(F.data == "cfg_common_timer")
async def start_set_common_timer(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ConfigAccountMsgStates.waiting_for_common_timer)

    kb = get_timer_preset_keyboard(0)
    await callback.message.answer(
        "<b>⏱ Select Common Timer Interval for ALL Accounts</b>\n\n"
        "Select how often ALL your connected accounts should send messages simultaneously:\n"
        "👉 <b>Choose a preset below</b> or type custom minutes (e.g. <code>15</code>):\n\n"
        "<i>All accounts will be synchronized to trigger at the exact same time!</i>",
        reply_markup=kb
    )
    await callback.answer()


@router.message(ConfigAccountMsgStates.waiting_for_common_timer)
async def process_common_timer_input(message: types.Message, state: FSMContext):
    if message.text.strip() == "🔙 Back to Main Menu":
        await state.clear()
        await message.answer("🏠 Returned to main menu.", reply_markup=get_main_menu_keyboard())
        return

    try:
        minutes = int(message.text.strip())
        minutes = max(minutes, 1)
    except ValueError:
        minutes = 30

    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.telegram_id == message.from_user.id))).scalars().first()
        if user:
            accs = (await db.execute(
                select(TelegramAccount).where(
                    TelegramAccount.user_id == user.id,
                    TelegramAccount.is_active == True
                )
            )).scalars().all()
            now = datetime.utcnow()
            for acc in accs:
                acc.interval_minutes = minutes
                acc.last_used_at = now
            await db.commit()
            acc_count = len(accs)
        else:
            acc_count = 0

    await state.clear()

    if minutes >= 60:
        time_display = f"{minutes // 60} hour(s)"
    else:
        time_display = f"{minutes} minute(s)"

    await message.answer(
        f"⏱ <b>Common timer interval updated to every {time_display} across ALL {acc_count} accounts!</b>\n\n"
        f"All accounts are now synchronized to trigger at the exact same time.",
        reply_markup=get_main_menu_keyboard()
    )


@router.callback_query(F.data.startswith("acc_msg_cfg_"))
async def open_account_msg_config(callback: types.CallbackQuery):
    acc_id = int(callback.data.split("_")[3])
    async with async_session_factory() as db:
        acc = await db.get(TelegramAccount, acc_id)
        if not acc:
            await callback.answer("Account not found.", show_alert=True)
            return

        g_count = await mtproto_service.get_joined_group_count(acc.get_session_string(), phone_number=acc.phone_number)
        msg_status = f"<code>{acc.custom_message}</code>" if acc.custom_message else "<i>Not Set</i>"
        enabled_status = "🟢 ENABLED" if acc.auto_group_enabled else "🔴 DISABLED"
        
        info = (
            f"<b>⚙️ Settings for Account:</b> <code>{acc.phone_number}</code>\n\n"
            f"<b>📢 Groups Added:</b> <b>{g_count} group(s)</b>\n"
            f"<b>Auto-Messaging:</b> {enabled_status}\n"
            f"<b>Timer Interval:</b> Every <b>{acc.interval_minutes} minute(s)</b>\n"
            f"<b>Current Message:</b>\n{msg_status}\n\n"
            f"<i>Tap below to configure message, set timer interval, or toggle auto-messaging.</i>"
        )
        kb = get_account_msg_config_keyboard(acc.id, acc.auto_group_enabled)
        await callback.message.edit_text(info, reply_markup=kb)
        await callback.answer()


@router.callback_query(F.data.startswith("cfg_set_msg_"))
async def start_set_message(callback: types.CallbackQuery, state: FSMContext):
    acc_id = int(callback.data.split("_")[3])
    await state.update_data(account_id=acc_id)
    await state.set_state(ConfigAccountMsgStates.waiting_for_message)

    await callback.message.answer(
        "<b>📝 Set Auto-Messaging Text</b>\n\n"
        "Send your message text below.\n\n"
        "💡 <b>Tips for Higher Views & High RPM:</b>\n"
        "• <b>HTML Links & Formatting:</b> Use HTML tags like <code>&lt;a href=\"https://yourlink.com\"&gt;🔥 Click Here&lt;/a&gt;</code> for rich clickable links & preview cards!\n"
        "• <b>Spintax Randomization:</b> Use <code>{Click Here|Watch Now|Download Free}</code> to automatically randomize text for every group send!\n"
        "• <b>Multiple Variants:</b> Separate full variants using <code>---</code> on a new line.\n\n"
        "Tap <b>🔙 Back to Main Menu</b> to cancel.",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()


@router.message(ConfigAccountMsgStates.waiting_for_message)
async def process_account_message(message: types.Message, state: FSMContext):
    if message.text.strip() == "🔙 Back to Main Menu":
        await state.clear()
        await message.answer("🏠 Returned to main menu.", reply_markup=get_main_menu_keyboard())
        return

    data = await state.get_data()
    acc_id = data.get("account_id")
    msg_text = message.text.strip()

    async with async_session_factory() as db:
        acc = await db.get(TelegramAccount, acc_id)
        if acc:
            acc.custom_message = msg_text
            acc.current_msg_index = 0
            await db.commit()
            phone = acc.phone_number

    await state.clear()
    await message.answer(
        f"✅ Message configured successfully for account <code>{phone}</code>!",
        reply_markup=get_main_menu_keyboard()
    )


@router.callback_query(F.data.startswith("cfg_set_timer_"))
async def start_set_timer(callback: types.CallbackQuery, state: FSMContext):
    acc_id = int(callback.data.split("_")[3])
    await state.update_data(account_id=acc_id)
    await state.set_state(ConfigAccountMsgStates.waiting_for_timer)

    kb = get_timer_preset_keyboard(acc_id)
    await callback.message.answer(
        "<b>⏱ Select Timer Interval</b>\n\n"
        "Select how often this account should send messages to all its joined groups:\n"
        "👉 <b>Choose a preset below</b> or type custom minutes (e.g. <code>15</code>):",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_timer_val_"))
async def handle_timer_preset_click(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    acc_id = int(parts[3])
    minutes = int(parts[4])

    async with async_session_factory() as db:
        if acc_id == 0:
            user = (await db.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalars().first()
            if user:
                accs = (await db.execute(
                    select(TelegramAccount).where(
                        TelegramAccount.user_id == user.id,
                        TelegramAccount.is_active == True
                    )
                )).scalars().all()
                now = datetime.utcnow()
                for a in accs:
                    a.interval_minutes = minutes
                    a.last_used_at = now
                await db.commit()
                acc_count = len(accs)
                phone_info = f"across ALL {acc_count} accounts"
            else:
                phone_info = "all accounts"
        else:
            acc = await db.get(TelegramAccount, acc_id)
            if acc:
                acc.interval_minutes = minutes
                acc.last_used_at = datetime.utcnow()
                await db.commit()
                phone_info = f"for account <code>{acc.phone_number}</code>"
            else:
                phone_info = ""

    await state.clear()

    if minutes >= 60:
        time_display = f"{minutes // 60} hour(s)"
    else:
        time_display = f"{minutes} minute(s)"

    await callback.message.answer(
        f"⏱ Timer interval updated to <b>every {time_display}</b> {phone_info}!",
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()


@router.message(ConfigAccountMsgStates.waiting_for_timer)
async def process_account_timer(message: types.Message, state: FSMContext):
    if message.text.strip() == "🔙 Back to Main Menu":
        await state.clear()
        await message.answer("🏠 Returned to main menu.", reply_markup=get_main_menu_keyboard())
        return

    try:
        minutes = int(message.text.strip())
        minutes = max(minutes, 1)
    except ValueError:
        minutes = 30

    data = await state.get_data()
    acc_id = data.get("account_id")

    async with async_session_factory() as db:
        if acc_id == 0:
            user = (await db.execute(select(User).where(User.telegram_id == message.from_user.id))).scalars().first()
            if user:
                accs = (await db.execute(
                    select(TelegramAccount).where(
                        TelegramAccount.user_id == user.id,
                        TelegramAccount.is_active == True
                    )
                )).scalars().all()
                now = datetime.utcnow()
                for a in accs:
                    a.interval_minutes = minutes
                    a.last_used_at = now
                await db.commit()
                phone_info = f"across ALL {len(accs)} accounts"
            else:
                phone_info = "all accounts"
        else:
            acc = await db.get(TelegramAccount, acc_id)
            if acc:
                acc.interval_minutes = minutes
                acc.last_used_at = datetime.utcnow()
                await db.commit()
                phone_info = f"for account <code>{acc.phone_number}</code>"
            else:
                phone_info = ""

    await state.clear()

    if minutes >= 60:
        time_display = f"{minutes // 60} hour(s)"
    else:
        time_display = f"{minutes} minute(s)"

    await message.answer(
        f"⏱ Timer interval updated to <b>every {time_display}</b> {phone_info}!",
        reply_markup=get_main_menu_keyboard()
    )


@router.callback_query(F.data.startswith("cfg_toggle_group_"))
async def toggle_account_group_messaging(callback: types.CallbackQuery):
    acc_id = int(callback.data.split("_")[3])
    async with async_session_factory() as db:
        acc = await db.get(TelegramAccount, acc_id)
        if acc:
            acc.auto_group_enabled = not acc.auto_group_enabled
            await db.commit()
            status_text = "🟢 Enabled (will send messages)" if acc.auto_group_enabled else "🔴 Disabled (will NOT send messages)"
            await callback.answer(f"Account auto-messaging is now {status_text}.")
            
            msg_preview = acc.custom_message if acc.custom_message else "<i>None set</i>"
            text = (
                f"<b>⚙️ Configuration for Account:</b> <code>{acc.phone_number}</code>\n\n"
                f"<b>Status:</b> {status_text}\n"
                f"<b>Timer Interval:</b> Every {acc.interval_minutes} minute(s)\n"
                f"<b>Configured Message:</b>\n{msg_preview}\n\n"
                f"Select an option below to update settings:"
            )
            await callback.message.edit_text(text, reply_markup=get_account_msg_config_keyboard(acc.id, acc.auto_group_enabled))
