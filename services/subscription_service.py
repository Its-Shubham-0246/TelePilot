from datetime import datetime, timedelta
from typing import Optional, Dict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.subscription import Subscription
from models.user import User

# ─── Regular (full) prices ────────────────────────────────────────────────────
PRICING_PLANS: Dict[int, Dict[str, any]] = {
    1:  {"name": "1 Day Plan",   "days": 1,  "price": 49,  "currency": "INR"},
    7:  {"name": "7 Days Plan",  "days": 7,  "price": 199, "currency": "INR"},
    30: {"name": "30 Days Plan", "days": 30, "price": 399, "currency": "INR"},
}

# ─── Limited-time sale ────────────────────────────────────────────────────────
# Sale runs until 23:59 IST on Aug 7, 2026 (10 days from Jul 28).
# After this date, prices auto-revert to PRICING_PLANS above.
SALE_ENDS = datetime(2026, 8, 7, 18, 29, 59)   # 23:59:59 IST = 18:29:59 UTC

SALE_PLANS: Dict[int, Dict[str, any]] = {
    1:  {"name": "1 Day Plan",   "days": 1,  "price": 39,  "currency": "INR", "original": 49},
    7:  {"name": "7 Days Plan",  "days": 7,  "price": 179, "currency": "INR", "original": 199},
    30: {"name": "30 Days Plan", "days": 30, "price": 299, "currency": "INR", "original": 399},
}


def is_sale_active() -> bool:
    """Returns True if the limited-time sale is currently running."""
    return datetime.utcnow() < SALE_ENDS


def get_active_pricing() -> Dict[int, Dict[str, any]]:
    """Returns the currently active pricing plans (sale or regular)."""
    return SALE_PLANS if is_sale_active() else PRICING_PLANS


def get_sale_days_left() -> int:
    """Returns whole days remaining in the sale (0 if sale has ended)."""
    delta = SALE_ENDS - datetime.utcnow()
    return max(0, delta.days)



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
            return new_sub

    async def grant_free_trial_if_new_user(self, db: AsyncSession, user_id: int) -> bool:

        """If user has never had any subscription, grant 1-Day Free Trial automatically."""
        stmt = select(Subscription).where(Subscription.user_id == user_id)
        existing_subs = (await db.execute(stmt)).scalars().all()

        if not existing_subs:
            trial_sub = Subscription(
                user_id=user_id,
                plan_name="1-Day Free Trial 🎁",
                status="ACTIVE",
                expires_at=datetime.utcnow() + timedelta(days=1),
                max_accounts=5
            )
            db.add(trial_sub)
            await db.commit()
            return True
        return False


subscription_service = SubscriptionService()

