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
