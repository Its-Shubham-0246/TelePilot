import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func

from core.database import async_session_factory
from models.user import User
from models.account import TelegramAccount
from services.mtproto_service import mtproto_service
from bot.keyboards.inline import get_account_manage_keyboard
from bot.keyboards.main_menu import get_main_menu_keyboard, get_cancel_keyboard

logger = logging.getLogger(__name__)

router = Router()


class AddAccountStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_otp = State()
    waiting_for_2fa = State()


# ── Back / Cancel handler (works in any FSM state) ──────────────────────────
@router.message(F.text == "🔙 Back to Main Menu")
async def cancel_to_main(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🏠 Returned to main menu.", reply_markup=get_main_menu_keyboard())


# ── Add Account ──────────────────────────────────────────────────────────────
@router.message(F.text == "➕ Add Account")
async def start_add_account(message: types.Message, state: FSMContext):
    async with async_session_factory() as db:
        stmt_user = select(User).where(User.telegram_id == message.from_user.id)
        user = (await db.execute(stmt_user)).scalars().first()
        if not user:
            await message.answer("Please type /start first.")
            return

        stmt_count = select(func.count(TelegramAccount.id)).where(TelegramAccount.user_id == user.id)
        count = (await db.execute(stmt_count)).scalar() or 0

        if count >= 15:
            await message.answer(
                "⚠️ You have reached the maximum limit of 15 connected accounts.",
                reply_markup=get_main_menu_keyboard()
            )
            return

    await state.set_state(AddAccountStates.waiting_for_phone)
    await message.answer(
        "<b>📱 Add Telegram Account</b>\n\n"
        "Enter the phone number with country code (e.g. <code>+919876543210</code>):\n\n"
        "Tap <b>🔙 Back to Main Menu</b> to cancel.",
        reply_markup=get_cancel_keyboard()
    )


@router.message(AddAccountStates.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    if phone == "🔙 Back to Main Menu":
        await state.clear()
        await message.answer("🏠 Returned to main menu.", reply_markup=get_main_menu_keyboard())
        return

    if not phone.startswith("+") or not phone[1:].isdigit():
        await message.answer(
            "❌ Invalid format. Enter with country code (e.g. <code>+919876543210</code>):",
            reply_markup=get_cancel_keyboard()
        )
        return

    await message.answer("⏳ Sending verification code to your Telegram account...")
    try:
        phone_code_hash, temp_session_str = await mtproto_service.send_login_code(phone)
        await state.update_data(
            phone=phone,
            phone_code_hash=phone_code_hash,
            temp_session_str=temp_session_str
        )
        await state.set_state(AddAccountStates.waiting_for_otp)
        await message.answer(
            "<b>📩 Enter Verification Code</b>\n\n"
            f"A code was sent to <code>{phone}</code>.\n"
            "Please enter the code:\n\n"
            "Tap <b>🔙 Back to Main Menu</b> to cancel.",
            reply_markup=get_cancel_keyboard()
        )
    except Exception as e:
        logger.error(f"Error sending OTP: {e}")
        await message.answer(
            f"❌ Failed to send OTP: {str(e)}\nPlease try again.",
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()


@router.message(AddAccountStates.waiting_for_otp)
async def process_otp(message: types.Message, state: FSMContext):
    if message.text.strip() == "🔙 Back to Main Menu":
        await state.clear()
        await message.answer("🏠 Returned to main menu.", reply_markup=get_main_menu_keyboard())
        return

    code = message.text.strip()
    data = await state.get_data()
    phone = data.get("phone")
    phone_code_hash = data.get("phone_code_hash")
    temp_session_str = data.get("temp_session_str")

    await message.answer("⏳ Verifying code...")
    try:
        final_session_str, requires_2fa = await mtproto_service.sign_in_code(
            phone_number=phone,
            code=code,
            phone_code_hash=phone_code_hash,
            temp_session_str=temp_session_str
        )

        if requires_2fa:
            await state.update_data(temp_session_str=final_session_str)
            await state.set_state(AddAccountStates.waiting_for_2fa)
            await message.answer(
                "<b>🔐 Two-Factor Authentication (2FA) Required</b>\n\n"
                "Enter your 2FA password:\n\n"
                "Tap <b>🔙 Back to Main Menu</b> to cancel.",
                reply_markup=get_cancel_keyboard()
            )
            return

        await save_account_session(message.from_user.id, phone, final_session_str)
        await state.clear()
        await message.answer(
            f"✅ Account <code>{phone}</code> connected successfully!",
            reply_markup=get_main_menu_keyboard()
        )

    except Exception as e:
        logger.error(f"Error verifying OTP: {e}")
        await message.answer(
            f"❌ Invalid OTP code: {str(e)}",
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()


@router.message(AddAccountStates.waiting_for_2fa)
async def process_2fa(message: types.Message, state: FSMContext):
    if message.text.strip() == "🔙 Back to Main Menu":
        await state.clear()
        await message.answer("🏠 Returned to main menu.", reply_markup=get_main_menu_keyboard())
        return

    password = message.text.strip()
    data = await state.get_data()
    phone = data.get("phone")
    temp_session_str = data.get("temp_session_str")

    await message.answer("⏳ Verifying 2FA password...")
    try:
        final_session_str = await mtproto_service.sign_in_2fa(password, temp_session_str)
        await save_account_session(message.from_user.id, phone, final_session_str)
        await state.clear()
        await message.answer(
            f"✅ Account <code>{phone}</code> connected successfully!",
            reply_markup=get_main_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"Error verifying 2FA: {e}")
        await message.answer(
            f"❌ Invalid 2FA password: {str(e)}",
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()


async def save_account_session(telegram_id: int, phone: str, session_str: str):
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.telegram_id == telegram_id))).scalars().first()
        if not user:
            return
        acc = TelegramAccount(
            user_id=user.id,
            phone_number=phone,
            is_active=True,
            status="ACTIVE"
        )
        acc.set_session_string(session_str)
        db.add(acc)
        await db.commit()


# ── My Accounts ───────────────────────────────────────────────────────────────
@router.message(F.text == "👤 My Accounts")
async def list_user_accounts(message: types.Message):
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.telegram_id == message.from_user.id))).scalars().first()
        if not user:
            await message.answer("Please type /start first.")
            return
        accounts = (await db.execute(select(TelegramAccount).where(TelegramAccount.user_id == user.id))).scalars().all()

    if not accounts:
        await message.answer(
            "No Telegram accounts connected yet. Tap ➕ Add Account to get started.",
            reply_markup=get_main_menu_keyboard()
        )
        return

    await message.answer(f"<b>📱 Connected Accounts ({len(accounts)}/15):</b>")
    for acc in accounts:
        status_icon = "🟢" if acc.is_active and acc.status == "ACTIVE" else "🔴"
        await message.answer(
            f"{status_icon} <b>Phone:</b> <code>{acc.phone_number}</code>\n"
            f"<b>Status:</b> {acc.status}\n"
            f"<b>Active:</b> {'Yes' if acc.is_active else 'No'}",
            reply_markup=get_account_manage_keyboard(acc.id, acc.is_active)
        )


# ── Callback: Back to main ────────────────────────────────────────────────────
@router.callback_query(F.data == "back_to_main")
async def callback_back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("🏠 Returned to main menu.", reply_markup=get_main_menu_keyboard())
    await callback.answer()


# ── Callback: Toggle / Delete account ─────────────────────────────────────────
@router.callback_query(F.data.startswith("acc_toggle_"))
async def callback_toggle_account(callback: types.CallbackQuery):
    acc_id = int(callback.data.split("_")[2])
    async with async_session_factory() as db:
        acc = await db.get(TelegramAccount, acc_id)
        if acc:
            acc.is_active = not acc.is_active
            await db.commit()
            status_str = "activated ✅" if acc.is_active else "deactivated ⏸"
            await callback.answer(f"Account {acc.phone_number} {status_str}.")
            await callback.message.edit_reply_markup(
                reply_markup=get_account_manage_keyboard(acc.id, acc.is_active)
            )


@router.callback_query(F.data.startswith("acc_delete_"))
async def callback_delete_account(callback: types.CallbackQuery):
    acc_id = int(callback.data.split("_")[2])
    async with async_session_factory() as db:
        acc = await db.get(TelegramAccount, acc_id)
        if acc:
            await db.delete(acc)
            await db.commit()
            await callback.answer("Account removed. 🗑")
            await callback.message.delete()
