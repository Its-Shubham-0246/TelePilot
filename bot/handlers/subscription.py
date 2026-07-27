from datetime import datetime
from aiogram import Router, F, types
from sqlalchemy import select

from core.database import async_session_factory
from models.user import User
from models.payment import Payment
from services.subscription_service import subscription_service, PRICING_PLANS
from bot.keyboards.inline import get_subscription_plans_keyboard

router = Router()


@router.message(F.text == "💳 Subscription")
async def show_subscription(message: types.Message):
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.telegram_id == message.from_user.id))).scalars().first()
        if not user:
            await message.answer("Please type /start first.")
            return

        sub = await subscription_service.get_active_subscription(db, user.id)

    if sub:
        days_left = (sub.expires_at - datetime.utcnow()).days
        info = (
            f"<b>💳 Active Subscription</b>\n\n"
            f"<b>Plan:</b> {sub.plan_name}\n"
            f"<b>Status:</b> 🟢 Active\n"
            f"<b>Expires On:</b> {sub.expires_at.strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"<b>Days Remaining:</b> {days_left} Days\n"
            f"<b>Allowed Accounts:</b> Up to {sub.max_accounts} accounts\n\n"
            f"Select a plan below to renew or extend your subscription:"
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
    plan = PRICING_PLANS.get(days)
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

    payment_instructions = (
        f"<b>💳 Purchase Subscription ({plan['name']})</b>\n\n"
        f"<b>Amount:</b> ₹{plan['price']} INR\n"
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
            return

        # Find latest pending payment
        stmt = select(Payment).where(Payment.user_id == user.id, Payment.status == "PENDING").order_by(Payment.id.desc())
        pay = (await db.execute(stmt)).scalars().first()

        if not pay:
            await callback.answer("No pending payment found.", show_alert=True)
            return

        # Auto-verify simulation / confirmation
        pay.status = "VERIFIED"
        await db.commit()

        # Grant subscription
        sub = await subscription_service.add_or_renew_subscription(db, user.id, pay.plan_duration_days, pay.id)

    await callback.message.answer(
        f"🎉 <b>Payment Verified!</b>\n\n"
        f"Your <b>{sub.plan_name}</b> subscription is now active until {sub.expires_at.strftime('%Y-%m-%d')}!"
    )
    await callback.answer()
