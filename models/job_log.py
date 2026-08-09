from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base


class JobLog(Base):
    __tablename__ = "job_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("telegram_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    target_chat: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # SUCCESS, FAILED, FLOOD_WAIT
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    error_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    schedule: Mapped["Schedule"] = relationship("Schedule")
    account: Mapped[Optional["TelegramAccount"]] = relationship("TelegramAccount")
