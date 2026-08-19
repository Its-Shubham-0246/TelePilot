from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from config import settings


class Base(DeclarativeBase):
    pass


# SQLite / PostgreSQL async engine compatibility fallback
database_url = settings.DATABASE_URL
# Railway PostgreSQL can emit either 'postgres://' or 'postgresql://'
# SQLAlchemy async requires the 'postgresql+asyncpg://' scheme
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)


engine_kwargs = {
    "echo": False,
    "future": True,
}
if "postgresql" in database_url:
    engine_kwargs.update({
        "pool_size": 30,
        "max_overflow": 60,
        "pool_recycle": 1800,
        "pool_pre_ping": True,
    })

engine = create_async_engine(
    database_url,
    **engine_kwargs
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Safe schema migration for new columns and indexes on existing database
    from sqlalchemy import text
    migrations = [
        "ALTER TABLE users ADD COLUMN referrer_id INTEGER REFERENCES users(id) ON DELETE SET NULL",
        "ALTER TABLE users ADD COLUMN ref_commission_rate FLOAT DEFAULT 0.30",
        "ALTER TABLE users ADD COLUMN referral_balance FLOAT DEFAULT 0.0",
        "ALTER TABLE users ADD COLUMN total_withdrawn FLOAT DEFAULT 0.0",
        "ALTER TABLE telegram_accounts ADD COLUMN current_msg_index INTEGER DEFAULT 0",
        "ALTER TABLE telegram_accounts ADD COLUMN auto_join_enabled BOOLEAN DEFAULT FALSE",
        "ALTER TABLE discovered_groups ADD COLUMN username VARCHAR(255)",
        "ALTER TABLE discovered_groups ADD COLUMN invite_link VARCHAR(500)",
        "ALTER TABLE discovered_groups ADD COLUMN can_send_msgs BOOLEAN DEFAULT TRUE",
        "CREATE INDEX IF NOT EXISTS ix_job_logs_sent_at ON job_logs (sent_at)",
        "CREATE INDEX IF NOT EXISTS ix_job_logs_status ON job_logs (status)",
        "CREATE INDEX IF NOT EXISTS ix_job_logs_account_id ON job_logs (account_id)",
        "CREATE INDEX IF NOT EXISTS ix_schedules_user_id ON schedules (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_telegram_accounts_user_id ON telegram_accounts (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_telegram_accounts_user_active_auto ON telegram_accounts (user_id, is_active, auto_group_enabled)",
        "CREATE INDEX IF NOT EXISTS ix_schedules_is_active ON schedules (is_active)",
        "CREATE INDEX IF NOT EXISTS ix_subscriptions_user_status_exp ON subscriptions (user_id, status, expires_at)",
    ]
    import logging
    logger = logging.getLogger(__name__)

    for m in migrations:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(m))
        except Exception as e:
            # Try SQLite fallback if PostgreSQL syntax variant failed
            if "DEFAULT FALSE" in m or "DEFAULT TRUE" in m:
                try:
                    fallback_m = m.replace("DEFAULT FALSE", "DEFAULT 0").replace("DEFAULT TRUE", "DEFAULT 1")
                    async with engine.begin() as conn:
                        await conn.execute(text(fallback_m))
                except Exception:
                    pass
            logger.debug(f"[Migration] Statement '{m}' result: {e}")

