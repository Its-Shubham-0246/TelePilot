import random
import pytest
from datetime import datetime, timedelta
from core.database import init_db, async_session_factory
from models.user import User
from services.subscription_service import subscription_service, PRICING_PLANS


@pytest.mark.asyncio
async def test_subscription_creation_and_extension():
    await init_db()
    random_id = random.randint(1000000, 9999999)

    async with async_session_factory() as db:
        user = User(telegram_id=random_id, username=f"subuser_{random_id}")
        db.add(user)
        await db.commit()
        await db.refresh(user)

        # Purchase 30 days
        sub = await subscription_service.add_or_renew_subscription(db, user.id, 30)
        assert sub.status == "ACTIVE"
        assert sub.plan_name == "30 Days Plan"
        assert sub.is_valid is True

        # Extend by 90 days
        updated_sub = await subscription_service.add_or_renew_subscription(db, user.id, 90)
        days_diff = (updated_sub.expires_at - datetime.utcnow()).days
        assert days_diff >= 119  # ~120 days total


@pytest.mark.asyncio
async def test_referral_commission_30_percent():
    await init_db()
    ref_id = random.randint(1000000, 9999999)
    buyer_id = random.randint(1000000, 9999999)

    from models.payment import Payment
    from bot.handlers.subscription import process_referral_commission
    from models.referral import ReferralTransaction

    async with async_session_factory() as db:
        referrer = User(telegram_id=ref_id, username=f"ref_{ref_id}", ref_commission_rate=0.30)
        db.add(referrer)
        await db.commit()
        await db.refresh(referrer)

        # Active subscription required for referrer to earn commission
        await subscription_service.add_or_renew_subscription(db, referrer.id, 30)

        buyer = User(telegram_id=buyer_id, username=f"buyer_{buyer_id}", referrer_id=referrer.id)
        db.add(buyer)
        await db.commit()
        await db.refresh(buyer)


        pay = Payment(user_id=buyer.id, amount=299.0, currency="INR", plan_duration_days=30, status="VERIFIED")
        db.add(pay)
        await db.commit()
        await db.refresh(pay)

        await process_referral_commission(db, buyer, pay)

        await db.refresh(referrer)
        assert referrer.referral_balance == 89.70  # 30% of ₹299 = ₹89.70

