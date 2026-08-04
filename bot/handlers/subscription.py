import logging
from datetime import datetime
from aiogram import Router, F, types
from sqlalchemy import select

from core.database import async_session_factory
from models.user import User
from models.payment import Payment
from models.referral import ReferralTransaction
from services.subscription_service import (
    subscription_service, PRICING_PLANS,
    get_active_pricing, is_sale_active, get_sale_days_left
)
from bot.keyboards.inline import get_subscription_plans_keyboard

logger = logging.getLogger(__name__)
router = Router()



@router.message(F.text == "💳 Subscription")
async def show_subscription(message: types.Message):
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.telegram_id == message.from_user.id))).scalars().first()
        if not user:
            await message.answer("Please type /start first.")
            return

        # Check for active subscription first
        sub = await subscription_service.get_active_subscription(db, user.id)

        # If no active sub, check if they had a previous expired one
        expired_sub = None
        if not sub:
            from sqlalchemy import desc
            from models.subscription import Subscription as SubModel
            last_sub_result = await db.execute(
                select(SubModel)
                .where(SubModel.user_id == user.id)
                .order_by(desc(SubModel.expires_at))
                .limit(1)
            )
            expired_sub = last_sub_result.scalars().first()

    if sub:
        # Active subscription
        time_left = sub.expires_at - datetime.utcnow()
        days_left = time_left.days
        hours_left = int(time_left.total_seconds() // 3600)

        if days_left >= 1:
            remaining_str = f"{days_left} Day(s)"
        elif hours_left > 0:
            remaining_str = f"⚠️ {hours_left} Hour(s) — Expiring soon!"
        else:
            remaining_str = "⚠️ Less than 1 hour left!"

        info = (
            f"<b>💳 Active Subscription</b>\n\n"
            f"<b>Plan:</b> {sub.plan_name}\n"
            f"<b>Status:</b> 🟢 Active\n"
            f"<b>Expires On:</b> {sub.expires_at.strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"<b>Time Remaining:</b> {remaining_str}\n"
            f"<b>Allowed Accounts:</b> Up to {sub.max_accounts} accounts\n\n"
            f"Select a plan below to renew or extend your subscription:"
        )

    elif expired_sub:
        # Expired subscription — show clear EXPIRED / INACTIVE status
        expired_on = expired_sub.expires_at.strftime('%Y-%m-%d %H:%M UTC')
        info = (
            f"<b>💳 Subscription Status</b>\n\n"
            f"<b>Plan:</b> {expired_sub.plan_name}\n"
            f"<b>Status:</b> 🔴 Expired / Inactive\n"
            f"<b>Expired On:</b> {expired_on}\n\n"
            f"Your plan has ended. Please purchase a new plan to continue using the bot.\n\n"
        )
        # Append sale banner if active
        if is_sale_active():
            sale_left = get_sale_days_left()
            info += (
                f"🔥 <b>LIMITED SALE — {sale_left} DAYS LEFT!</b>\n"
                f"⚡ 1 Day – <s>₹49</s> ➜ <b>₹39</b>\n"
                f"📅 7 Days – <s>₹199</s> ➜ <b>₹179</b>\n"
                f"🏆 30 Days – <s>₹399</s> ➜ <b>₹299</b>\n\n"
                f"Select a plan below to reactivate:"
            )
        else:
            info += "Select a plan below to reactivate:"

    else:
        # Brand new user — no subscription at all
        if is_sale_active():
            sale_left = get_sale_days_left()
            info = (
                f"🔥 <b>LIMITED SALE — {sale_left} DAYS LEFT!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"<b>💳 Subscription Plans</b>\n\n"
                f"⚡ 1 Day    — <s>₹49</s>  ➜  <b>₹39</b>\n"
                f"📅 7 Days  — <s>₹199</s> ➜  <b>₹179</b>\n"
                f"🏆 30 Days — <s>₹399</s> ➜  <b>₹299</b>\n\n"
                f"⏳ Sale ends <b>Aug 7, 2026 at 11:59 PM IST</b>\n"
                f"Prices go back to normal after that!\n\n"
                f"Select a plan below to grab this deal:"
            )
        else:
            info = (
                f"<b>💳 SaaS Subscription Plans</b>\n\n"
                f"Get full access to Telegram Multi-Account Automation:\n"
                f"• 1 Day – <b>₹49</b>\n"
                f"• 7 Days – <b>₹199</b>\n"
                f"• 30 Days – <b>₹399</b>\n\n"
                f"Select a plan below to purchase:"
            )

    await message.answer(info, reply_markup=get_subscription_plans_keyboard())



@router.callback_query(F.data.startswith("buy_sub_"))
async def process_buy_sub(callback: types.CallbackQuery):
    days = int(callback.data.split("_")[2])
    # Always use the currently active pricing (sale or regular)
    plans = get_active_pricing()
    plan = plans.get(days)
    if not plan:
        await callback.answer("Invalid plan.")
        return

    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalars().first()
        if not user:
            return

        # Create payment entry
        pay = Payment(
            user_id=user.id,
            amount=plan["price"],
            currency=plan["currency"],
            plan_duration_days=days,
            status="PENDING"
        )
        db.add(pay)
        await db.commit()
        await db.refresh(pay)

    # Generate Razorpay payment link
    pay_url = None
    try:
        from services.razorpay_service import razorpay_service
        link_res = razorpay_service.create_payment_link(
            user_id=user.telegram_id,
            days=days,
            amount_inr=plan["price"],
            plan_name=plan["name"],
            user_name=callback.from_user.full_name,
            user_phone=None
        )
        pay_url = link_res.get("short_url")
        pay.gateway_transaction_id = link_res.get("id")
        async with async_session_factory() as db:
            db.add(pay)
            await db.commit()
    except Exception as err:
        pay_url = None

    pay_keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
    if pay_url:
        pay_keyboard.inline_keyboard.append([types.InlineKeyboardButton(text="💳 Pay Now (UPI / Cards / NetBanking)", url=pay_url)])
    pay_keyboard.inline_keyboard.append([types.InlineKeyboardButton(text="🔄 Check Payment Status", callback_data="verify_payment")])

    # Build amount line — show crossed-out original if it's a sale
    original = plan.get("original")
    if original and is_sale_active():
        amount_line = f"<b>Amount:</b> <s>₹{original}</s> ➜ <b>₹{plan['price']} INR</b> 🔥 Sale Price\n"
    else:
        amount_line = f"<b>Amount:</b> ₹{plan['price']} INR\n"

    payment_instructions = (
        f"<b>💳 Purchase Subscription ({plan['name']})</b>\n\n"
        f"{amount_line}"
        f"<b>Order ID:</b> <code>PAY-{pay.id}</code>\n\n"
        f"Click the button below to pay securely via UPI, Google Pay, PhonePe, Cards, or NetBanking."
    )
    await callback.message.answer(payment_instructions, reply_markup=pay_keyboard)
    await callback.answer()


@router.callback_query(F.data == "verify_payment")
async def verify_payment_callback(callback: types.CallbackQuery):
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalars().first()
        if not user:
            await callback.answer("User profile not found. Type /start first.", show_alert=True)
            return

        # Find latest pending payment
        stmt = select(Payment).where(Payment.user_id == user.id, Payment.status == "PENDING").order_by(Payment.id.desc())
        pay = (await db.execute(stmt)).scalars().first()

        if not pay:
            # Check if user already has active sub
            active_sub = await subscription_service.get_active_subscription(db, user.id)
            if active_sub:
                await callback.answer("✅ Your subscription is already ACTIVE!", show_alert=True)
            else:
                await callback.answer("❌ No pending payment order found. Please select a plan above to buy.", show_alert=True)
            return

        if not pay.gateway_transaction_id:
            await callback.answer(
                "❌ Payment link ID missing. Please tap on a subscription plan above to generate a new payment link.",
                show_alert=True
            )
            return

        # Query Razorpay API directly to verify actual payment status
        is_paid = False
        status_text = "unknown"
        try:
            from services.razorpay_service import razorpay_service
            link_info = razorpay_service.fetch_payment_link(pay.gateway_transaction_id)
            status_text = link_info.get("status", "unknown")
            amount_paid = link_info.get("amount_paid", 0)
            target_amount = link_info.get("amount", 0)

            # Check if status is paid OR if full amount in paise was received
            if status_text == "paid" or (target_amount > 0 and amount_paid >= target_amount):
                is_paid = True
        except Exception as err:
            logger.error(f"Error querying Razorpay API for link {pay.gateway_transaction_id}: {err}")

        if is_paid:
            pay.status = "VERIFIED"
            await db.commit()

            # Grant subscription
            sub = await subscription_service.add_or_renew_subscription(db, user.id, pay.plan_duration_days, pay.id)

            # Process referral commission (30% default)
            await process_referral_commission(db, user, pay)

            await callback.message.answer(
                f"🎉 <b>Payment Verified Successfully!</b>\n\n"
                f"Your <b>{sub.plan_name}</b> subscription is now active until {sub.expires_at.strftime('%d %b %Y, %I:%M %p UTC')}!\n\n"
                f"You now have full access to all TelePilot features 🚀"
            )
            await callback.answer("✅ Payment verified!")

        else:
            await callback.answer(
                f"❌ Payment Not Detected! (Razorpay Status: {status_text.upper()})\n\n"
                f"Please complete your payment via the link provided above before clicking verify.",
                show_alert=True
            )


async def process_referral_commission(db, buyer_user: User, payment: Payment):
    """Calculates and awards 30% affiliate commission to the referrer when a user buys a subscription."""
    if not buyer_user or not buyer_user.referrer_id:
        return

    referrer = await db.get(User, buyer_user.referrer_id)
    if not referrer:
        return

    # Verify referrer has an active subscription to be eligible for affiliate commissions
    referrer_sub = await subscription_service.get_active_subscription(db, referrer.id)
    if not referrer_sub:
        logger.info(f"Referrer #{referrer.id} has no active subscription — skipping referral commission.")
        try:
            from bot.bot_instance import bot
            await bot.send_message(
                referrer.telegram_id,
                f"⚠️ <b>Referral Commission Missed!</b>\n\n"
                f"Your referral just purchased a TelePilot subscription (₹{payment.amount:.2f} INR)!\n\n"
                f"🔒 However, referral commissions are exclusive to active subscribers. Please renew your subscription to earn <b>30% cash commission</b> on future purchases! 🚀",
                parse_mode="HTML"
            )
        except Exception:
            pass
        return

    rate = referrer.ref_commission_rate if hasattr(referrer, "ref_commission_rate") and referrer.ref_commission_rate else 0.30

    commission_earned = round(payment.amount * rate, 2)

    # Prevent duplicate commission for the same payment
    stmt_check = select(ReferralTransaction).where(ReferralTransaction.payment_id == payment.id)
    existing_tx = (await db.execute(stmt_check)).scalars().first()
    if existing_tx:
        return

    tx = ReferralTransaction(
        referrer_id=referrer.id,
        referred_user_id=buyer_user.id,
        payment_id=payment.id,
        amount=payment.amount,
        commission=commission_earned,
        rate=rate,
        status="EARNED"
    )
    db.add(tx)
    referrer.referral_balance = round((referrer.referral_balance or 0.0) + commission_earned, 2)
    await db.commit()

    # Send instant notification to the referrer on Telegram
    try:
        from bot.bot_instance import bot
        buyer_name = f"@{buyer_user.username}" if buyer_user.username else buyer_user.full_name or f"User #{buyer_user.telegram_id}"
        perc = int(rate * 100)
        await bot.send_message(
            referrer.telegram_id,
            f"💰 <b>Affiliate Commission Earned!</b>\n\n"
            f"Your referral <b>{buyer_name}</b> purchased a subscription (₹{payment.amount:.2f} INR)!\n\n"
            f"• <b>Commission Rate:</b> {perc}%\n"
            f"• <b>Earned:</b> <b>+₹{commission_earned:.2f} INR</b>\n"
            f"• <b>Current Available Balance:</b> <b>₹{referrer.referral_balance:.2f} INR</b>\n\n"
            f"Tap <b>🤝 Referral Program</b> in main menu to check earnings & request instant withdrawal! 🚀",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning(f"Failed to notify referrer {referrer.telegram_id}: {e}")



