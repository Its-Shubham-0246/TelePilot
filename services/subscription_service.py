from datetime import datetime, timedelta
from typing import Optional, Dict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.subscription import Subscription
from models.user import User

PRICING_PLANS: Dict[int, Dict[str, any]] = {
    30: {"name": "30 Days Plan", "days": 30, "price": 299, "currency": "INR"},
    90: {"name": "90 Days Plan", "days": 90, "price": 699, "currency": "INR"},
    180: {"name": "180 Days Plan", "days": 180, "price": 1199, "currency": "INR"},
    365: {"name": "365 Days Plan", "days": 365, "price": 1999, "currency": "INR"},
}


class SubscriptionService:
    async def get_active_subscription(self, db: AsyncSession, user_id: int) -> Optional[Subscription]:
        """Returns active subscription for given database user_id if valid."""
        stmt = (
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.status == "ACTIVE",
                Subscription.expires_at > datetime.utcnow()
            )
            .order_by(Subscription.expires_at.desc())
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def check_user_has_active_sub(self, db: AsyncSession, user_id: int) -> bool:
        sub = await self.get_active_subscription(db, user_id)
        return sub is not None

    async def add_or_renew_subscription(
        self, db: AsyncSession, user_id: int, days: int, payment_id: Optional[int] = None
    ) -> Subscription:
        """Adds or extends user's subscription by days count."""
        plan_info = PRICING_PLANS.get(days, {"name": f"{days} Days Custom", "price": 0})
        active_sub = await self.get_active_subscription(db, user_id)

        now = datetime.utcnow()
        if active_sub:
            # Extend existing active subscription
            new_expires = active_sub.expires_at + timedelta(days=days)
            active_sub.expires_at = new_expires
            active_sub.plan_name = plan_info["name"]
            if payment_id:
                active_sub.payment_id = payment_id
            await db.commit()
            await db.refresh(active_sub)
            return active_sub
        else:
            # Create new subscription
            expires_at = now + timedelta(days=days)
            new_sub = Subscription(
                user_id=user_id,
                plan_name=plan_info["name"],
                max_accounts=15,
                status="ACTIVE",
                expires_at=expires_at,
                payment_id=payment_id
            )
            db.add(new_sub)
            await db.commit()
            await db.refresh(new_sub)
            return new_sub


subscription_service = SubscriptionService()
