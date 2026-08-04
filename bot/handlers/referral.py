import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func
from datetime import datetime

from core.database import async_session_factory
from models.user import User
from models.referral import ReferralTransaction, WithdrawalRequest
from bot.keyboards.main_menu import get_main_menu_keyboard, get_cancel_keyboard

logger = logging.getLogger(__name__)
router = Router()


class WithdrawalState(StatesGroup):
    waiting_for_payout_details = State()


@router.message(F.text == "🤝 Referral Program")
@router.message(F.text == "/referral")
async def show_referral_program(message: types.Message):
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.telegram_id == message.from_user.id))).scalars().first()
        if not user:
            await message.answer("Please type /start first.")
            return

        # Count total referrals
        stmt_ref_count = select(func.count(User.id)).where(User.referrer_id == user.id)
        ref_count = (await db.execute(stmt_ref_count)).scalar() or 0

        # Calculate total earned commission
        stmt_total_earned = select(func.sum(ReferralTransaction.commission)).where(
            ReferralTransaction.referrer_id == user.id,
            ReferralTransaction.status == "EARNED"
        )
        total_earned = (await db.execute(stmt_total_earned)).scalar() or 0.0

    bot_info = await message.bot.get_me()
    bot_username = bot_info.username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user.telegram_id}"

    commission_perc = int((user.ref_commission_rate or 0.30) * 100)
    avail_balance = round(user.referral_balance or 0.0, 2)
    withdrawn = round(user.total_withdrawn or 0.0, 2)

    ref_text = (
        f"<b>🤝 TelePilot Affiliate & Referral Program</b>\n\n"
        f"Earn <b>{commission_perc}% recurring commission</b> on every subscription your referrals purchase!\n\n"
        f"🔗 <b>Your Unique Referral Link:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        f"📊 <b>Your Affiliate Stats:</b>\n"
        f"• <b>Total Referrals Joined:</b> {ref_count}\n"
        f"• <b>Commission Rate:</b> {commission_perc}%\n"
        f"• <b>Total Lifetime Earnings:</b> ₹{total_earned:,.2f} INR\n"
        f"• <b>Total Withdrawn:</b> ₹{withdrawn:,.2f} INR\n"
        f"• <b>Available Balance:</b> <b>₹{avail_balance:,.2f} INR</b>\n\n"
        f"💡 <i>Share your referral link on Telegram, YouTube, Twitter, or WhatsApp. You earn {commission_perc}% instant cash every time they buy!</i>"
    )

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📲 Share Referral Link", url=f"https://t.me/share/url?url={ref_link}&text=Automate%20your%20Telegram%20Marketing%2024/7%20with%20TelePilot!%20Get%20full%20multi-account%20automation%20with%20anti-ban%20protection.")],
        [types.InlineKeyboardButton(text="💸 Withdraw Earnings (UPI / Bank)", callback_data="request_withdrawal")],
        [types.InlineKeyboardButton(text="📜 Earnings History", callback_data="ref_history")],
    ])

    await message.answer(ref_text, reply_markup=kb, disable_web_page_preview=True)


@router.callback_query(F.data == "request_withdrawal")
async def start_withdrawal_flow(callback: types.CallbackQuery, state: FSMContext):
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalars().first()
        if not user:
            return

        avail_balance = round(user.referral_balance or 0.0, 2)
        MIN_WITHDRAWAL = 100.0

        if avail_balance < MIN_WITHDRAWAL:
            await callback.answer(
                f"⚠️ Minimum withdrawal amount is ₹{MIN_WITHDRAWAL} INR.\n"
                f"Your current balance is ₹{avail_balance} INR.",
                show_alert=True
            )
            return

    await state.set_state(WithdrawalState.waiting_for_payout_details)
    await state.update_data(amount=avail_balance)

    await callback.message.answer(
        f"<b>💸 Request Affiliate Payout</b>\n\n"
        f"<b>Available Balance to Withdraw:</b> ₹{avail_balance:,.2f} INR\n\n"
        f"Please enter your payment details below:\n"
        f"👉 <b>UPI ID</b> (e.g. <code>username@upi</code> or PhonePe/GooglePay number)\n"
        f"👉 OR <b>Bank Account details</b> (Account No + IFSC Code)\n\n"
        f"Tap <b>🔙 Back to Main Menu</b> to cancel.",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()


@router.message(WithdrawalState.waiting_for_payout_details)
async def process_payout_details(message: types.Message, state: FSMContext):
    if message.text.strip() == "🔙 Back to Main Menu":
        await state.clear()
        await message.answer("🏠 Returned to main menu.", reply_markup=get_main_menu_keyboard())
        return

    payout_info = message.text.strip()
    data = await state.get_data()
    amount = data.get("amount", 0.0)

    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.telegram_id == message.from_user.id))).scalars().first()
        if not user or user.referral_balance < amount:
            await message.answer("❌ Insufficient balance for withdrawal.", reply_markup=get_main_menu_keyboard())
            await state.clear()
            return

        # Deduct balance & move to pending withdrawal
        user.referral_balance = round(user.referral_balance - amount, 2)

        w = WithdrawalRequest(
            user_id=user.id,
            amount=amount,
            payout_info=payout_info,
            status="PENDING"
        )
        db.add(w)
        await db.commit()
        await db.refresh(w)

        # Notify Admin immediately
        try:
            from config import settings
            from bot.bot_instance import bot
            admin_msg = (
                f"💸 <b>NEW AFFILIATE WITHDRAWAL REQUEST!</b>\n\n"
                f"<b>User:</b> @{user.username if user.username else user.full_name} (<code>{user.telegram_id}</code>)\n"
                f"<b>Amount:</b> ₹{amount:,.2f} INR\n"
                f"<b>Payout Info:</b> <code>{payout_info}</code>\n"
                f"<b>Request ID:</b> <code>#WITH-{w.id}</code>\n\n"
                f"👉 Admin Approve: <code>/approvepayout {w.id}</code>\n"
                f"👉 Admin Reject: <code>/rejectpayout {w.id}</code>"
            )
            for admin_id in settings.admin_ids_list:
                try:
                    await bot.send_message(admin_id, admin_msg, parse_mode="HTML")
                except Exception:
                    pass
        except Exception as err:
            logger.warning(f"Failed to alert admin on withdrawal request: {err}")

    await state.clear()
    await message.answer(
        f"✅ <b>Withdrawal Request Submitted!</b>\n\n"
        f"• <b>Amount:</b> ₹{amount:,.2f} INR\n"
        f"• <b>Payout Details:</b> <code>{payout_info}</code>\n\n"
        f"Your payout request has been sent to our team and will be processed via UPI within 24 hours. 🚀",
        reply_markup=get_main_menu_keyboard()
    )


@router.callback_query(F.data == "ref_history")
async def show_referral_history(callback: types.CallbackQuery):
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalars().first()
        if not user:
            return

        txs = (await db.execute(
            select(ReferralTransaction)
            .where(ReferralTransaction.referrer_id == user.id)
            .order_by(ReferralTransaction.created_at.desc())
            .limit(10)
        )).scalars().all()

        withdrawals = (await db.execute(
            select(WithdrawalRequest)
            .where(WithdrawalRequest.user_id == user.id)
            .order_by(WithdrawalRequest.created_at.desc())
            .limit(10)
        )).scalars().all()

    lines = ["<b>📜 Affiliate Earnings & Payout History</b>\n"]
    if txs:
        lines.append("<b>💰 Recent Commissions:</b>")
        for tx in txs:
            dt_str = tx.created_at.strftime('%Y-%m-%d %H:%M')
            lines.append(f"  • {dt_str}: <b>+₹{tx.commission:.2f} INR</b> ({int(tx.rate*100)}% on ₹{tx.amount})")
    else:
        lines.append("<i>No commissions earned yet. Share your referral link to start earning!</i>")

    lines.append("")
    if withdrawals:
        lines.append("<b>💸 Recent Withdrawal Requests:</b>")
        for w in withdrawals:
            dt_str = w.created_at.strftime('%Y-%m-%d %H:%M')
            status_icon = "🟢" if w.status == "APPROVED" else ("🔴" if w.status == "REJECTED" else "⏳")
            lines.append(f"  • {status_icon} #{w.id} ({dt_str}): ₹{w.amount:.2f} INR — <b>{w.status}</b>")

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🔙 Back to Referral Program", callback_data="back_to_ref")]
    ])
    await callback.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "back_to_ref")
async def callback_back_to_ref(callback: types.CallbackQuery):
    await show_referral_program(callback.message)
    await callback.answer()
