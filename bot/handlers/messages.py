import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select

from core.database import async_session_factory
from models.user import User
from models.account import TelegramAccount
from bot.keyboards.inline import (
    get_messages_accounts_keyboard,
    get_account_msg_config_keyboard,
    get_timer_preset_keyboard
)
from bot.keyboards.main_menu import get_main_menu_keyboard, get_cancel_keyboard

logger = logging.getLogger(__name__)

router = Router()


class ConfigAccountMsgStates(StatesGroup):
    waiting_for_message = State()
    waiting_for_timer = State()


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
        "<b>💬 Config Messages & Timers per Account</b>\n\n"
        "Select an account below to set its auto-broadcasting message, adjust timer interval, or enable/disable auto-messaging:"
    )
    kb = get_messages_accounts_keyboard(accounts)
    if edit and isinstance(event_obj, types.Message):
        await event_obj.edit_text(text, reply_markup=kb)
    else:
        await event_obj.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("acc_msg_cfg_"))
async def open_account_msg_config(callback: types.CallbackQuery):
    acc_id = int(callback.data.split("_")[3])
    async with async_session_factory() as db:
        acc = await db.get(TelegramAccount, acc_id)
        if not acc:
            await callback.answer("Account not found.", show_alert=True)
            return

        msg_status = f"<code>{acc.custom_message}</code>" if acc.custom_message else "<i>Not Set</i>"
        enabled_status = "🟢 ENABLED" if acc.auto_group_enabled else "🔴 DISABLED"
        
        info = (
            f"<b>⚙️ Settings for Account:</b> <code>{acc.phone_number}</code>\n\n"
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
        "💡 <b>Tip for Message Variants:</b> Separate multiple message versions using <code>---</code> on a new line to automatically rotate variants and avoid Telegram spam flags!\n\n"
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
        acc = await db.get(TelegramAccount, acc_id)
        if acc:
            acc.interval_minutes = minutes
            await db.commit()
            phone = acc.phone_number

    await state.clear()

    if minutes >= 60:
        time_display = f"{minutes // 60} hour(s)"
    else:
        time_display = f"{minutes} minute(s)"

    await callback.message.answer(
        f"⏱ Timer interval updated to <b>every {time_display}</b> for account <code>{phone}</code>!",
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
        acc = await db.get(TelegramAccount, acc_id)
        if acc:
            acc.interval_minutes = minutes
            await db.commit()
            phone = acc.phone_number

    await state.clear()

    if minutes >= 60:
        time_display = f"{minutes // 60} hour(s)"
    else:
        time_display = f"{minutes} minute(s)"

    await message.answer(
        f"⏱ Timer interval updated to <b>every {time_display}</b> for account <code>{phone}</code>!",
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
            
            # Refresh inline keyboard menu
            msg_preview = acc.custom_message if acc.custom_message else "<i>None set</i>"
            text = (
                f"<b>⚙️ Configuration for Account:</b> <code>{acc.phone_number}</code>\n\n"
                f"<b>Status:</b> {status_text}\n"
                f"<b>Timer Interval:</b> Every {acc.interval_minutes} minute(s)\n"
                f"<b>Configured Message:</b>\n{msg_preview}\n\n"
                f"Select an option below to update settings:"
            )
            await callback.message.edit_text(text, reply_markup=get_account_msg_config_keyboard(acc.id, acc.auto_group_enabled))
