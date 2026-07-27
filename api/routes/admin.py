from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from models.user import User
from models.subscription import Subscription
from models.payment import Payment

router = APIRouter(prefix="/admin", tags=["Admin Panel"])


@router.get("/stats")
async def get_system_stats(db: AsyncSession = Depends(get_db)):
    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
    active_subs = (await db.execute(select(func.count(Subscription.id)).where(Subscription.status == "ACTIVE"))).scalar() or 0
    revenue = (await db.execute(select(func.sum(Payment.amount)).where(Payment.status == "VERIFIED"))).scalar() or 0.0

    return {
        "total_users": total_users,
        "active_subscriptions": active_subs,
        "total_revenue": revenue,
        "currency": "INR"
    }


@router.get("/users")
async def get_all_users(db: AsyncSession = Depends(get_db)):
    users = (await db.execute(select(User).order_by(User.id.desc()))).scalars().all()
    return [
        {
            "id": u.id,
            "telegram_id": u.telegram_id,
            "username": u.username,
            "full_name": u.full_name,
            "is_admin": u.is_admin,
            "status": u.status,
            "created_at": u.created_at
        }
        for u in users
    ]
