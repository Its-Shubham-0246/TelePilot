from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from config import settings


class Base(DeclarativeBase):
    pass


# Normalize DATABASE_URL scheme for SQLAlchemy async drivers
# Railway Postgres emits 'postgres://' or 'postgresql://' — asyncpg requires 'postgresql+asyncpg://'
database_url = settings.DATABASE_URL
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

IS_POSTGRES = "postgresql" in database_url

engine_kwargs = {
    "echo": False,
    "future": True,
}

if IS_POSTGRES:
    # Railway Postgres free/hobby plan allows 25 max connections.
    # pool_size=10 + max_overflow=15 = 25 max total — stays within limit.
    # pool_timeout: fail fast (30s) if all connections are busy instead of hanging forever.
    # pool_recycle: recycle connections every 30 min to avoid stale connection errors.
    # pool_pre_ping: issue a SELECT 1 before each checkout to detect dead connections.
    engine_kwargs.update({
        "pool_size": 10,
        "max_overflow": 15,
        "pool_timeout": 30,
        "pool_recycle": 1800,
        "pool_pre_ping": True,
        "connect_args": {
            "command_timeout": 60,  # asyncpg: cancel queries taking longer than 60s
            "server_settings": {
                "application_name": "telepilot",
            },
        },
    })
else:
    # SQLite: use NullPool so each async context gets its own connection (avoids thread-safety issues)
    from sqlalchemy.pool import NullPool
    engine_kwargs["poolclass"] = NullPool

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

    # Safe schema migrations — each statement is run independently so a failure
    # on one (e.g. column already exists) does not block the rest.
    from sqlalchemy import text
    import logging
    logger = logging.getLogger(__name__)

    # Postgres uses BOOLEAN literals; SQLite uses 0/1 integers.
    bool_false = "FALSE" if IS_POSTGRES else "0"
    bool_true = "TRUE" if IS_POSTGRES else "1"

    migrations = [
        "ALTER TABLE users ADD COLUMN referrer_id INTEGER REFERENCES users(id) ON DELETE SET NULL",
        "ALTER TABLE users ADD COLUMN ref_commission_rate FLOAT DEFAULT 0.30",
        "ALTER TABLE users ADD COLUMN referral_balance FLOAT DEFAULT 0.0",
        "ALTER TABLE users ADD COLUMN total_withdrawn FLOAT DEFAULT 0.0",
        f"ALTER TABLE telegram_accounts ADD COLUMN current_msg_index INTEGER DEFAULT 0",
        f"ALTER TABLE telegram_accounts ADD COLUMN auto_join_enabled BOOLEAN DEFAULT {bool_false}",
        "ALTER TABLE discovered_groups ADD COLUMN username VARCHAR(255)",
        "ALTER TABLE discovered_groups ADD COLUMN invite_link VARCHAR(500)",
        f"ALTER TABLE discovered_groups ADD COLUMN can_send_msgs BOOLEAN DEFAULT {bool_true}",
        "CREATE INDEX IF NOT EXISTS ix_job_logs_sent_at ON job_logs (sent_at)",
        "CREATE INDEX IF NOT EXISTS ix_job_logs_status ON job_logs (status)",
        "CREATE INDEX IF NOT EXISTS ix_job_logs_account_id ON job_logs (account_id)",
        "CREATE INDEX IF NOT EXISTS ix_schedules_user_id ON schedules (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_telegram_accounts_user_id ON telegram_accounts (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_telegram_accounts_user_active_auto ON telegram_accounts (user_id, is_active, auto_group_enabled)",
        "CREATE INDEX IF NOT EXISTS ix_schedules_is_active ON schedules (is_active)",
        "CREATE INDEX IF NOT EXISTS ix_subscriptions_user_status_exp ON subscriptions (user_id, status, expires_at)",
    ]

    for m in migrations:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(m))
        except Exception as e:
            # Expected on re-deploy: column already exists, index already exists — safe to ignore.
            logger.debug(f"[Migration] Skipped (already applied or not applicable): {e}")

