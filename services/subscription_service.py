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

    async def enforce_user_account_limit(self, db: AsyncSession, user_id: int, max_limit: int = 5) -> List[str]:
        """
        Enforces max account limit for a user.
        If connected accounts exceed max_limit, keeps the first max_limit accounts
        and deletes/terminates excess accounts. Returns list of terminated phone numbers.
        """
        from models.account import TelegramAccount
        stmt = select(TelegramAccount).where(TelegramAccount.user_id == user_id).order_by(TelegramAccount.id.asc())
        accounts = (await db.execute(stmt)).scalars().all()

        if len(accounts) <= max_limit:
            return []

        excess_accounts = accounts[max_limit:]
        terminated_phones = [acc.phone_number for acc in excess_accounts]

        for acc in excess_accounts:
            await db.delete(acc)

        await db.commit()
        return terminated_phones

    async def sweep_and_enforce_lifetime_limits(self, db: AsyncSession):
        """Finds all active lifetime subscriptions, sets max_accounts=5, and terminates excess accounts."""
        stmt = select(Subscription).where(
            Subscription.status == "ACTIVE",
            Subscription.plan_name.ilike("%Lifetime%")
        )
        subs = (await db.execute(stmt)).scalars().all()
        for sub in subs:
            sub.max_accounts = 5
            await self.enforce_user_account_limit(db, sub.user_id, max_limit=5)
        await db.commit()


subscription_service = SubscriptionService()


