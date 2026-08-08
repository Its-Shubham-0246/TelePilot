import json
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import String, Integer, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base

if TYPE_CHECKING:
    from models.user import User


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(20), default="AUTO_GROUP", nullable=False)  # AUTO_GROUP, AUTO_DM, BOTH
    _target_chats: Mapped[str] = mapped_column("target_chats", Text, nullable=False, default="[]")
    _template_ids: Mapped[str] = mapped_column("template_ids", Text, nullable=False, default="[]")
    _account_ids: Mapped[str] = mapped_column("account_ids", Text, nullable=False, default="[]")
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    daily_start: Mapped[str] = mapped_column(String(10), default="00:00", nullable=False)  # HH:MM
    daily_end: Mapped[str] = mapped_column(String(10), default="23:59", nullable=False)    # HH:MM
    timezone: Mapped[str] = mapped_column(String(50), default="UTC", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="schedules")

    @property
    def target_chats(self) -> List[str]:
        try:
            return json.loads(self._target_chats)
        except Exception:
            return []

    @target_chats.setter
    def target_chats(self, chats: List[str]):
        self._target_chats = json.dumps(chats)

    @property
    def template_ids(self) -> List[int]:
        try:
            return json.loads(self._template_ids)
        except Exception:
            return []

    @template_ids.setter
    def template_ids(self, ids: List[int]):
        self._template_ids = json.dumps(ids)

    @property
    def account_ids(self) -> List[int]:
        try:
            return json.loads(self._account_ids)
        except Exception:
            return []

    @account_ids.setter
    def account_ids(self, ids: List[int]):
        self._account_ids = json.dumps(ids)
