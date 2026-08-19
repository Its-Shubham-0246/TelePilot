import random
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from core.database import init_db, async_session_factory
from models.user import User
from models.subscription import Subscription
from bot.handlers.admin import (
    find_user_by_input,
    admin_grant_lifetime,
    admin_revoke_lifetime,
    admin_list_users,
    admin_toggle_auto_remove,
    is_admin_user,
)
from config import settings


@pytest.mark.asyncio
async def test_find_user_by_input():
    await init_db()
    rand_id = random.randint(10000000, 99999999)
    username = f"admin_test_{rand_id}"
    full_name = f"Admin Test User {rand_id}"

    async with async_session_factory() as db:
        user = User(telegram_id=rand_id, username=username, full_name=full_name)
        db.add(user)
        await db.commit()

        # Find by ID
        found_by_id = await find_user_by_input(db, str(rand_id))
        assert found_by_id is not None
        assert found_by_id.id == user.id

        # Find by username with @
        found_by_uname = await find_user_by_input(db, f"@{username}")
        assert found_by_uname is not None
        assert found_by_uname.id == user.id

        # Find by full name substring
        found_by_name = await find_user_by_input(db, f"Admin Test User {rand_id}")
        assert found_by_name is not None
        assert found_by_name.id == user.id


@pytest.mark.asyncio
async def test_grant_lifetime_for_new_and_existing_user():
    await init_db()
    admin_id = settings.admin_ids_list[0] if settings.admin_ids_list else 6436648042

    # Test auto-creation when granting lifetime to unregistered Telegram ID
    unregistered_id = random.randint(10000000, 99999999)

    msg_mock = AsyncMock()
    msg_mock.from_user.id = admin_id
    msg_mock.text = f"/grantlifetime {unregistered_id}"
    msg_mock.answer = AsyncMock()

    await admin_grant_lifetime(msg_mock)

    # Check user was created and granted lifetime access
    async with async_session_factory() as db:
        from sqlalchemy import select
        created_user = (await db.execute(select(User).where(User.telegram_id == unregistered_id))).scalars().first()
        assert created_user is not None

        active_sub = (await db.execute(
            select(Subscription).where(
                Subscription.user_id == created_user.id,
                Subscription.status == "ACTIVE"
            )
        )).scalars().first()
        assert active_sub is not None
        assert active_sub.plan_name == "Lifetime Access (Admin Grant)"
        assert active_sub.max_accounts == 5
        assert active_sub.expires_at.year == 2099

    assert msg_mock.answer.called
    answer_text = msg_mock.answer.call_args[0][0]
    assert "Lifetime Access Granted!" in answer_text


@pytest.mark.asyncio
async def test_revoke_lifetime():
    await init_db()
    admin_id = settings.admin_ids_list[0] if settings.admin_ids_list else 6436648042
    rand_id = random.randint(10000000, 99999999)

    async with async_session_factory() as db:
        user = User(telegram_id=rand_id, username=f"revoke_{rand_id}")
        db.add(user)
        await db.commit()

        sub = Subscription(
            user_id=user.id,
            plan_name="Lifetime Access (Admin Grant)",
            status="ACTIVE",
            expires_at=datetime(2099, 12, 31, 23, 59, 59),
            max_accounts=5,
        )
        db.add(sub)
        await db.commit()

    msg_mock = AsyncMock()
    msg_mock.from_user.id = admin_id
    msg_mock.text = f"/revokelifetime {rand_id}"
    msg_mock.answer = AsyncMock()

    await admin_revoke_lifetime(msg_mock)

    async with async_session_factory() as db:
        from sqlalchemy import select
        revoked_sub = (await db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )).scalars().first()
        assert revoked_sub.status == "CANCELLED"

    answer_text = msg_mock.answer.call_args[0][0]
    assert "Revoked" in answer_text


@pytest.mark.asyncio
async def test_users_command_escapes_html():
    await init_db()
    admin_id = settings.admin_ids_list[0] if settings.admin_ids_list else 6436648042
    rand_id = random.randint(10000000, 99999999)

    # User with HTML characters in full name and username
    async with async_session_factory() as db:
        user = User(
            telegram_id=rand_id,
            username=f"user_<script>_{rand_id}",
            full_name="<Jane & John>"
        )
        db.add(user)
        await db.commit()

    msg_mock = AsyncMock()
    msg_mock.from_user.id = admin_id
    msg_mock.text = "/users"
    msg_mock.answer = AsyncMock()

    await admin_list_users(msg_mock)

    assert msg_mock.answer.called
    all_answers = "".join(call[0][0] for call in msg_mock.answer.call_args_list)
    assert "&lt;Jane &amp; John&gt;" in all_answers
    assert "&lt;script&gt;" in all_answers


@pytest.mark.asyncio
async def test_toggle_auto_remove():
    await init_db()
    admin_id = settings.admin_ids_list[0] if settings.admin_ids_list else 6436648042

    msg_mock = AsyncMock()
    msg_mock.from_user.id = admin_id

    # Test toggle ON
    msg_mock.text = "/autoremove on"
    msg_mock.answer = AsyncMock()
    await admin_toggle_auto_remove(msg_mock)
    assert settings.AUTO_REMOVE_BANNED_GROUPS is True
    assert "ENABLED" in msg_mock.answer.call_args[0][0]

    # Test toggle OFF
    msg_mock.text = "/autoremove off"
    msg_mock.answer = AsyncMock()
    await admin_toggle_auto_remove(msg_mock)
    assert settings.AUTO_REMOVE_BANNED_GROUPS is False
    assert "DISABLED" in msg_mock.answer.call_args[0][0]

