from datetime import datetime
from typing import List, Optional
from sqlalchemy import BigInteger, String, Boolean, DateTime, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship, backref
from core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="ACTIVE", nullable=False)  # ACTIVE, BANNED
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Referral & Affiliate fields
    referrer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    ref_commission_rate: Mapped[float] = mapped_column(Float, default=0.30, nullable=False)  # 30% default commission
    referral_balance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_withdrawn: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


    # Relationships
    subscriptions: Mapped[List["Subscription"]] = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")
    accounts: Mapped[List["TelegramAccount"]] = relationship("TelegramAccount", back_populates="user", cascade="all, delete-orphan")
    templates: Mapped[List["MessageTemplate"]] = relationship("MessageTemplate", back_populates="user", cascade="all, delete-orphan")
    schedules: Mapped[List["Schedule"]] = relationship("Schedule", back_populates="user", cascade="all, delete-orphan")
    payments: Mapped[List["Payment"]] = relationship("Payment", back_populates="user", cascade="all, delete-orphan")
    referrer: Mapped[Optional["User"]] = relationship("User", remote_side=[id], backref=backref("referrals"))

