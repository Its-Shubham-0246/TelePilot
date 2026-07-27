import json
from datetime import datetime
from typing import List, Optional
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base


class MessageTemplate(Base):
    __tablename__ = "message_templates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    _content_variants: Mapped[str] = mapped_column("content_variants", Text, nullable=False, default="[]")
    media_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    delay_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="templates")

    @property
    def content_variants(self) -> List[str]:
        try:
            return json.loads(self._content_variants)
        except Exception:
            return []

    @content_variants.setter
    def content_variants(self, variants: List[str]):
        self._content_variants = json.dumps(variants)
