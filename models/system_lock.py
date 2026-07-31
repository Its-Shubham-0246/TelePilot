import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime
from core.database import Base

class SystemLock(Base):
    __tablename__ = "system_locks"

    key = Column(String(50), primary_key=True, default="scheduler_leader")
    instance_id = Column(String(100), nullable=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

# Unique UUID generated once when this Python container boots up
INSTANCE_ID = str(uuid.uuid4())
