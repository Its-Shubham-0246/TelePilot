from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base
from core.security import encrypt_session_string, decrypt_session_string

if TYPE_CHECKING:
    from models.user import User


class TelegramAccount(Base):
    __tablename__ = "telegram_accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    phone_number: Mapped[str] = mapped_column(String(50), nullable=False)
    session_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_group_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_join_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Custom message & timer per account
    custom_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    current_msg_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    status: Mapped[str] = mapped_column(String(50), default="ACTIVE", nullable=False)  # ACTIVE, FLOOD_WAIT, BANNED, RE_LOGIN_REQUIRED
    rate_limit_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="accounts")

    def set_session_string(self, session_str: str):
        self.session_encrypted = encrypt_session_string(session_str)

    def get_session_string(self) -> str:
        return decrypt_session_string(self.session_encrypted)
