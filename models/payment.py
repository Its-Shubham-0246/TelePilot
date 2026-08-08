from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Float, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base

if TYPE_CHECKING:
    from models.user import User


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    plan_duration_days: Mapped[int] = mapped_column(Integer, nullable=False)  # 30, 90, 180, 365
    status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)  # PENDING, VERIFIED, FAILED
    gateway_payment_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)      # pay_xxxx (actual payment)
    gateway_transaction_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # plink_xxxx (payment link ID)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="payments")
