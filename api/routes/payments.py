import logging
import json
from fastapi import APIRouter, Depends, HTTPException, Body, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from models.payment import Payment
from models.user import User
from services.subscription_service import subscription_service
from services.razorpay_service import razorpay_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["Payment Webhooks"])


@router.post("/webhook/razorpay")
async def razorpay_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Official Razorpay Webhook endpoint.
    Razorpay sends a POST request with event data when a payment_link is paid.
    - Verifies HMAC SHA-256 signature using RAZORPAY_WEBHOOK_SECRET
    - Finds the internal Payment record using Razorpay link_id stored in notes
    - Marks payment as VERIFIED and activates user subscription
    - Sends Telegram bot notification to the user
    """
    body_bytes = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    # ── 1. Verify Signature ──────────────────────────────────────────────────
    if not razorpay_service.verify_webhook_signature(body_bytes, signature):
        logger.warning("Razorpay webhook received with INVALID signature — rejected.")
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    payload = json.loads(body_bytes)
    event = payload.get("event", "")
    logger.info(f"Razorpay webhook received: event={event}")

    # ── 2. Handle payment_link.paid event ────────────────────────────────────
    if event == "payment_link.paid":
        payment_link_entity = payload.get("payload", {}).get("payment_link", {}).get("entity", {})
        payment_entity     = payload.get("payload", {}).get("payment", {}).get("entity", {})

        razorpay_link_id   = payment_link_entity.get("id", "")          # plink_xxxxx
        razorpay_payment_id = payment_entity.get("id", "")              # pay_xxxxx
        notes              = payment_link_entity.get("notes", {})
        telegram_user_id   = int(notes.get("telegram_user_id", 0))
        plan_days          = int(notes.get("plan_days", 30))
        plan_name          = notes.get("plan_name", "Subscription")

        if not telegram_user_id:
            logger.error("Razorpay webhook: telegram_user_id missing in notes.")
            return {"status": "ignored", "reason": "telegram_user_id not in notes"}

        # ── 3. Find User in DB ────────────────────────────────────────────────
        user_result = await db.execute(select(User).where(User.telegram_id == telegram_user_id))
        user = user_result.scalars().first()
        if not user:
            logger.error(f"Razorpay webhook: No user found with telegram_id={telegram_user_id}")
            return {"status": "ignored", "reason": "user not found"}

        # ── 4. Find or Create Payment Record ─────────────────────────────────
        pay_result = await db.execute(
            select(Payment).where(
                Payment.user_id == user.id,
                Payment.status == "PENDING"
            ).order_by(Payment.id.desc())
        )
        pay = pay_result.scalars().first()

        if not pay:
            # Create a new payment record if not already existing
            pay = Payment(
                user_id=user.id,
                amount=payment_entity.get("amount", 0) / 100,
                currency=payment_entity.get("currency", "INR"),
                plan_duration_days=plan_days,
                status="PENDING",
                gateway_payment_id=razorpay_payment_id
            )
            db.add(pay)
            await db.flush()

        # ── 5. Mark Payment as VERIFIED ───────────────────────────────────────
        pay.status = "VERIFIED"
        pay.gateway_payment_id = razorpay_payment_id
        await db.commit()
        await db.refresh(pay)

        # ── 6. Activate / Extend Subscription ────────────────────────────────
        sub = await subscription_service.add_or_renew_subscription(
            db, user_id=user.id, days=plan_days, payment_id=pay.id
        )
        logger.info(f"Subscription activated: user_id={user.id}, plan={plan_name}, expires={sub.expires_at}")

        # ── 7. Send Telegram Notification to User ────────────────────────────
        try:
            from bot.bot_instance import bot
            msg = (
                f"🎉 <b>Payment Successful!</b>\n\n"
                f"✅ <b>Plan:</b> {plan_name}\n"
                f"📅 <b>Active Until:</b> {sub.expires_at.strftime('%d %b %Y, %I:%M %p UTC')}\n"
                f"💳 <b>Payment ID:</b> <code>{razorpay_payment_id}</code>\n\n"
                f"Thank you! Your subscription is now active. Enjoy all features 🚀"
            )
            await bot.send_message(chat_id=telegram_user_id, text=msg)
            logger.info(f"Telegram notification sent to user {telegram_user_id}")
        except Exception as tg_err:
            logger.error(f"Failed to send Telegram notification: {tg_err}")

        return {"status": "ok", "message": "Subscription activated", "expires_at": str(sub.expires_at)}

    # ── Handle other events gracefully ───────────────────────────────────────
    logger.info(f"Razorpay webhook: unhandled event '{event}' — skipped.")
    return {"status": "ok", "event": event, "message": "Event acknowledged but not processed"}
