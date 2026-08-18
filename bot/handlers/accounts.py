import logging
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func

from core.database import async_session_factory
from models.user import User
from models.account import TelegramAccount
from services.mtproto_service import mtproto_service
from bot.keyboards.inline import get_account_manage_keyboard
from bot.keyboards.main_menu import get_main_menu_keyboard, get_cancel_keyboard

from telethon.errors import PhoneCodeInvalidError, PhoneCodeExpiredError

logger = logging.getLogger(__name__)


router = Router()


class AddAccountStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_otp = State()
    waiting_for_2fa = State()


# ── Back / Cancel handler (works in any FSM state) ──────────────────────────
@router.message(F.text == "🔙 Back to Main Menu")
async def cancel_to_main(message: types.Message, state: FSMContext):
    data = await state.get_data()
    phone = data.get("phone")
    if phone:
        await mtproto_service.cancel_pending_login(phone)
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

        from services.subscription_service import subscription_service
        sub = await subscription_service.get_active_subscription(db, user.id)
        max_allowed = sub.max_accounts if sub else 5

        stmt_count = select(func.count(TelegramAccount.id)).where(TelegramAccount.user_id == user.id)
        count = (await db.execute(stmt_count)).scalar() or 0

        if count >= max_allowed:
            await message.answer(
                f"⚠️ You have reached the maximum limit of <b>{max_allowed}</b> connected accounts for your current plan.",
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
        phone_code_hash, temp_session_str, code_type = await mtproto_service.send_login_code(phone)
        await state.update_data(
            phone=phone,
            phone_code_hash=phone_code_hash,
            temp_session_str=temp_session_str
        )
        await state.set_state(AddAccountStates.waiting_for_otp)

        if "App" in code_type:
            delivery_hint = (
                "💬 <b>Sent to your TELEGRAM APP chat inbox!</b>\n"
                "👉 Open your Telegram app and look for a chat message from <b>Telegram</b> (NOT SMS)."
            )
        elif "Sms" in code_type:
            delivery_hint = "📱 <b>Sent via SMS!</b> Check your mobile phone SMS inbox."
        elif "Call" in code_type:
            delivery_hint = "📞 <b>Incoming Call!</b> Telegram is calling your phone to dictate the code."
        else:
            delivery_hint = "📩 Check your Telegram app chat inbox or SMS for the code."

        await message.answer(
            "<b>📩 Enter Verification Code</b>\n\n"
            f"Code sent for <code>{phone}</code>:\n\n"
            f"{delivery_hint}\n\n"
            "⚠️ <b>Important:</b> Type it with spaces so it doesn't expire:\n"
            "👉 Example: If code is <code>71556</code> → type: <b><code>7 1 5 5 6</code></b> (or <code>7-1-5-5-6</code>)\n\n"
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

    # Clean code string: remove spaces, dashes, invisible zero-width spaces
    code = message.text.strip().replace(" ", "").replace("-", "").replace("\u200b", "")
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
                "Your account has 2FA enabled. Please enter your 2FA password:\n\n"
                "Tap <b>🔙 Back to Main Menu</b> to cancel.",
                reply_markup=get_cancel_keyboard()
            )
            return

        await save_account_session(message.from_user.id, phone, final_session_str)
        await state.clear()
        await message.answer(
            f"🎉 <b>Account Connected!</b>\n\n"
            f"Telegram account <code>{phone}</code> connected successfully!",
            reply_markup=get_main_menu_keyboard()
        )

    except PhoneCodeInvalidError:
        logger.warning(f"[OTP] PhoneCodeInvalidError for {phone} — auto-resending fresh code")
        await _auto_resend_code(message, state, phone, reason="❌ <b>Code was invalid.</b>")

    except PhoneCodeExpiredError:
        logger.warning(f"[OTP] PhoneCodeExpiredError for {phone} — auto-resending fresh code")
        await _auto_resend_code(message, state, phone, reason="⏰ <b>Code expired.</b>")

    except Exception as e:
        logger.error(f"Error verifying OTP: {e}")
        await message.answer(
            f"❌ <b>Verification Error:</b> {str(e)}\n\n"
            f"Please tap <b>➕ Add Account</b> to try again.",
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()


async def _auto_resend_code(message: types.Message, state: FSMContext, phone: str, reason: str):
    """Automatically requests a fresh OTP and updates FSM with the new hash/session."""
    try:
        new_hash, new_session, code_type = await mtproto_service.send_login_code(phone)
        await state.update_data(phone_code_hash=new_hash, temp_session_str=new_session)
        await state.set_state(AddAccountStates.waiting_for_otp)

        if "App" in code_type:
            delivery_hint = "💬 Check your <b>Telegram App inbox</b> (chat named 'Telegram'), NOT SMS!"
        elif "Sms" in code_type:
            delivery_hint = "📱 Check your <b>mobile SMS inbox</b>."
        else:
            delivery_hint = "📩 Check your Telegram app or SMS inbox."

        await message.answer(
            f"{reason}\n\n"
            "🔄 <b>A fresh code has been sent!</b>\n\n"
            f"{delivery_hint}\n\n"
            "⚠️ <b>IMPORTANT — Type it with spaces:</b>\n"
            "If code is <code>71556</code> → type: <b><code>7 1 5 5 6</code></b>\n\n"
            "Tap <b>🔙 Back to Main Menu</b> to cancel.",
            reply_markup=get_cancel_keyboard()
        )
    except Exception as resend_err:
        logger.error(f"[OTP] Auto-resend failed for {phone}: {resend_err}")
        await message.answer(
            "❌ Could not resend code. Please tap <b>➕ Add Account</b> to try again.",
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
        final_session_str = await mtproto_service.sign_in_2fa(phone, password, temp_session_str)

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

        # If this phone number was previously added by another user (or this user), remove the old entry first
        existing_accounts = (
            await db.execute(select(TelegramAccount).where(TelegramAccount.phone_number == phone))
        ).scalars().all()

        for old_acc in existing_accounts:
            logger.info(f"[Account] Removing phone {phone} from previous user_id={old_acc.user_id} (now claimed by user_id={user.id})")
            await db.delete(old_acc)

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
@router.message(Command("account", "myaccounts"))
@router.message(F.text == "👤 My Accounts")
async def list_user_accounts(message: types.Message):
    import html
    try:
        async with async_session_factory() as db:
            user = (await db.execute(select(User).where(User.telegram_id == message.from_user.id))).scalars().first()
            if not user:
                await message.answer("Please type /start first.")
                return
            from services.subscription_service import subscription_service
            sub = await subscription_service.get_active_subscription(db, user.id)
            max_allowed = sub.max_accounts if sub else 5
            accounts = (await db.execute(select(TelegramAccount).where(TelegramAccount.user_id == user.id))).scalars().all()

        if not accounts:
            await message.answer(
                "No Telegram accounts connected yet. Tap ➕ Add Account to get started.",
                reply_markup=get_main_menu_keyboard()
            )
            return

        group_counts = []
        for acc in accounts:
            cached = mtproto_service.get_cached_group_count(acc.phone_number)
            if cached is not None:
                group_counts.append(cached)
            else:
                cnt = await mtproto_service.get_joined_group_count(acc.get_session_string(), phone_number=acc.phone_number)
                group_counts.append(cnt)
        total_groups = sum(group_counts)

        await message.answer(
            f"<b>📱 Connected Accounts ({len(accounts)}/{max_allowed}) | 📢 Total Groups: {total_groups}</b>"
        )
        for acc, g_count in zip(accounts, group_counts):
            status_icon = "🟢" if acc.is_active and acc.status == "ACTIVE" else "🔴"
            safe_phone = html.escape(acc.phone_number)
            safe_status = html.escape(acc.status)
            await message.answer(
                f"{status_icon} <b>Phone:</b> <code>{safe_phone}</code>\n"
                f"<b>📢 Groups Added:</b> <b>{g_count} group(s)</b>\n"
                f"<b>Status:</b> {safe_status}\n"
                f"<b>Active:</b> {'Yes' if acc.is_active else 'No'}",
                reply_markup=get_account_manage_keyboard(acc.id, acc.is_active)
            )
    except Exception as e:
        logger.error(f"Error in /myaccounts: {e}", exc_info=True)
        await message.answer(f"❌ Error displaying accounts list: {html.escape(str(e))}")



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
