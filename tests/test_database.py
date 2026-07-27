import random
import pytest
from sqlalchemy import select
from core.database import init_db, async_session_factory
from models.user import User
from models.account import TelegramAccount


@pytest.mark.asyncio
async def test_user_and_account_creation():
    await init_db()
    random_id = random.randint(1000000, 9999999)

    async with async_session_factory() as db:
        user = User(
            telegram_id=random_id,
            username=f"testuser_{random_id}",
            full_name="Test User",
            is_admin=False
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        assert user.id is not None
        assert user.telegram_id == random_id

        account = TelegramAccount(
            user_id=user.id,
            phone_number=f"+12345{random_id}",
            is_active=True,
            status="ACTIVE"
        )
        account.set_session_string("1StringSessionSecretData==")
        db.add(account)
        await db.commit()
        await db.refresh(account)

        assert account.get_session_string() == "1StringSessionSecretData=="
