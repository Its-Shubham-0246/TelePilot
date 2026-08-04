from datetime import datetime
from typing import Optional
from sqlalchemy import String, Float, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base


class ReferralTransaction(Base):
    __tablename__ = "referral_transactions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    referred_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    payment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("payments.id", ondelete="SET NULL"), nullable=True)
    
    amount: Mapped[float] = mapped_column(Float, nullable=False)  # Subscription price
    commission: Mapped[float] = mapped_column(Float, nullable=False)  # Earned commission
    rate: Mapped[float] = mapped_column(Float, default=0.30, nullable=False)  # e.g. 0.30 (30%)
    status: Mapped[str] = mapped_column(String(50), default="EARNED", nullable=False)  # EARNED, WITHDRAWN, CANCELLED

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    referrer: Mapped["User"] = relationship("User", foreign_keys=[referrer_id])
    referred_user: Mapped["User"] = relationship("User", foreign_keys=[referred_user_id])


class WithdrawalRequest(Base):
    __tablename__ = "withdrawal_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    payout_info: Mapped[str] = mapped_column(Text, nullable=False)  # UPI ID or Bank details
    status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)  # PENDING, APPROVED, REJECTED
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User")
