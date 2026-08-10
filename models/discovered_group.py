from datetime import datetime
from typing import Optional
from sqlalchemy import String, BigInteger, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class DiscoveredGroup(Base):
    """Tracks all groups discovered across all user accounts in the system.
    Used to alert the admin when a group is found that the reference account is NOT in.
    """
    __tablename__ = "discovered_groups"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Telegram group/channel ID (negative integer for groups)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True)
    group_title: Mapped[str] = mapped_column(String(255), nullable=False)
    # The phone number of the account that first discovered this group
    discovered_by_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    invite_link: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    can_send_msgs: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Whether admin has been notified about this group
    notified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
