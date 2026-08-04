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


engine = create_async_engine(
    database_url,
    echo=False,
    future=True
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
        # Safe schema migration for new referral columns on existing database
        from sqlalchemy import text
        migrations = [
            "ALTER TABLE users ADD COLUMN referrer_id INTEGER REFERENCES users(id) ON DELETE SET NULL",
            "ALTER TABLE users ADD COLUMN ref_commission_rate FLOAT DEFAULT 0.30",
            "ALTER TABLE users ADD COLUMN referral_balance FLOAT DEFAULT 0.0",
            "ALTER TABLE users ADD COLUMN total_withdrawn FLOAT DEFAULT 0.0",
        ]
        for m in migrations:
            try:
                await conn.execute(text(m))
            except Exception:
                pass

