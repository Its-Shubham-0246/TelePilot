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


@pytest.mark.asyncio
async def test_purge_unsubscribed_users():
    await init_db()
    old_unsub_id = random.randint(10000000, 99999999)
    active_user_id = random.randint(10000000, 99999999)
    from models.subscription import Subscription

    async with async_session_factory() as db:
        # User 1: Created 3 days ago, no subscription -> SHOULD BE PURGED
        u1 = User(
            telegram_id=old_unsub_id,
            username=f"unsub_{old_unsub_id}",
            created_at=datetime.utcnow() - timedelta(days=3)
        )
        db.add(u1)

        # User 2: Active subscription -> MUST NOT BE PURGED
        u2 = User(telegram_id=active_user_id, username=f"active_{active_user_id}")
        db.add(u2)
        await db.commit()

        sub2 = Subscription(
            user_id=u2.id,
            plan_name="30 Days Plan",
            status="ACTIVE",
            expires_at=datetime.utcnow() + timedelta(days=20)
        )
        db.add(sub2)
        await db.commit()

    async with async_session_factory() as db:
        purged = await subscription_service.purge_unsubscribed_users(db, grace_days=2)
        assert purged >= 1

    async with async_session_factory() as db:
        from sqlalchemy import select
        res_u1 = (await db.execute(select(User).where(User.telegram_id == old_unsub_id))).scalars().first()
        res_u2 = (await db.execute(select(User).where(User.telegram_id == active_user_id))).scalars().first()

        assert res_u1 is None  # Purged
        assert res_u2 is not None  # Kept


@pytest.mark.asyncio
async def test_sequential_message_rotation():
    await init_db()
    rand_id = random.randint(10000000, 99999999)
    from models.account import TelegramAccount

    async with async_session_factory() as db:
        user = User(telegram_id=rand_id, username=f"seq_{rand_id}")
        db.add(user)
        await db.commit()

        acc = TelegramAccount(
            user_id=user.id,
            phone_number=f"+100{rand_id}",
            custom_message="Msg 1 --- Msg 2 --- Msg 3",
            interval_minutes=15,
            current_msg_index=0
        )
        acc.set_session_string("TestSession==")
        db.add(acc)
        await db.commit()

        # Step 1: initial index 0
        variants = [v.strip() for v in acc.custom_message.split("---") if v.strip()]
        idx1 = acc.current_msg_index
        assert variants[idx1 % len(variants)] == "Msg 1"

        # Advance index to 1
        acc.current_msg_index = (idx1 + 1) % len(variants)
        await db.commit()

        # Step 2: index 1
        idx2 = acc.current_msg_index
        assert variants[idx2 % len(variants)] == "Msg 2"

        # Advance index to 2
        acc.current_msg_index = (idx2 + 1) % len(variants)
        await db.commit()

        # Step 3: index 2
        idx3 = acc.current_msg_index
        assert variants[idx3 % len(variants)] == "Msg 3"

        # Advance index back to 0
        acc.current_msg_index = (idx3 + 1) % len(variants)
        await db.commit()
        assert acc.current_msg_index == 0



