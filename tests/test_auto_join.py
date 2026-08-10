import random
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.database import init_db, async_session_factory
from models.user import User
from models.account import TelegramAccount
from models.discovered_group import DiscoveredGroup
from services.mtproto_service import mtproto_service
from services.group_discovery_service import (
    scan_all_accounts_for_groups,
    auto_join_all_enabled_accounts_to_all_groups,
    auto_join_single_account_to_all_groups,
)
from bot.handlers.admin import admin_toggle_autojoin, admin_autojoin_status
from config import settings


@pytest.mark.asyncio
async def test_account_auto_join_enabled_default():
    await init_db()
    rand_id = random.randint(10000000, 99999999)
    phone = f"+9198{rand_id}"

    async with async_session_factory() as db:
        user = User(telegram_id=rand_id, username=f"user_{rand_id}")
        db.add(user)
        await db.commit()

        acc = TelegramAccount(
            user_id=user.id,
            phone_number=phone,
            session_encrypted="test_encrypted_session",
            auto_join_enabled=False
        )
        db.add(acc)
        await db.commit()

        assert acc.auto_join_enabled is False


@pytest.mark.asyncio
async def test_check_group_write_permission():
    # Broadcast channel entity -> False
    broadcast_entity = MagicMock()
    broadcast_entity.broadcast = True
    assert mtproto_service.check_group_write_permission(broadcast_entity) is False

    # Normal group entity -> True
    group_entity = MagicMock()
    group_entity.broadcast = False
    group_entity.default_banned_rights = None
    group_entity.restricted = False
    assert mtproto_service.check_group_write_permission(group_entity) is True


@pytest.mark.asyncio
async def test_admin_toggle_autojoin_command():
    await init_db()
    admin_id = settings.admin_ids_list[0] if settings.admin_ids_list else 6436648042

    rand_id = random.randint(10000000, 99999999)
    phone = f"+9177{rand_id}"

    async with async_session_factory() as db:
        user = User(telegram_id=rand_id, username=f"user_{rand_id}")
        db.add(user)
        await db.commit()

        acc = TelegramAccount(
            user_id=user.id,
            phone_number=phone,
            session_encrypted="test_session",
            auto_join_enabled=False
        )
        db.add(acc)
        await db.commit()

    msg_mock = AsyncMock()
    msg_mock.from_user.id = admin_id
    msg_mock.text = f"/autojoin {phone} on"
    msg_mock.answer = AsyncMock()

    await admin_toggle_autojoin(msg_mock)
    msg_mock.answer.assert_called_once()
    assert "ENABLED" in msg_mock.answer.call_args[0][0]

    async with async_session_factory() as db:
        updated_acc = await db.get(TelegramAccount, acc.id)
        assert updated_acc.auto_join_enabled is True
