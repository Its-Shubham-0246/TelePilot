import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from services.mtproto_service import MTProtoService, mtproto_service


@pytest.mark.asyncio
async def test_group_count_caching():
    service = MTProtoService(api_id=12345, api_hash="fakehash")
    phone = "+919876543210"

    # Initially cache is empty
    assert service.get_cached_group_count(phone) is None

    # Update cache
    service._update_group_count_cache(phone, 15)
    assert service.get_cached_group_count(phone) == 15
    assert service.get_cached_group_count("9876543210") == 15


@pytest.mark.asyncio
async def test_get_joined_group_count_returns_cached_when_locked():
    service = MTProtoService(api_id=12345, api_hash="fakehash")
    phone = "+919876543210"
    service._update_group_count_cache(phone, 8)

    lock = service.get_account_lock(phone)
    await lock.acquire()
    try:
        count = await service.get_joined_group_count("fakesession", phone_number=phone)
        assert count == 8
    finally:
        lock.release()


@pytest.mark.asyncio
async def test_get_joined_group_count_fallback_on_timeout_or_error():
    service = MTProtoService(api_id=12345, api_hash="fakehash")
    phone = "+919876543210"
    service._update_group_count_cache(phone, 12)

    with patch.object(service, 'fetch_joined_groups', side_effect=asyncio.TimeoutError("Timed out")):
        count = await service.get_joined_group_count("fakesession", phone_number=phone, timeout=0.1)
        assert count == 12


@pytest.mark.asyncio
async def test_get_joined_group_count_live_success():
    service = MTProtoService(api_id=12345, api_hash="fakehash")
    phone = "+919876543210"

    mock_groups = [(object(), "Group 1"), (object(), "Group 2"), (object(), "Group 3")]
    with patch.object(service, 'fetch_joined_groups', AsyncMock(return_value=mock_groups)):
        count = await service.get_joined_group_count("fakesession", phone_number=phone)
        assert count == 3
        assert service.get_cached_group_count(phone) == 3


def test_paid_and_unwritable_error_helpers():
    from services.mtproto_service import _is_paid_group_error, _is_general_read_only_error, _is_account_banned_or_muted_error
    from telethon.errors import ChatWriteForbiddenError, UserBannedInChannelError

    # Paid group errors (do NOT leave)
    assert _is_paid_group_error("PAYMENT_REQUIRED: This group requires Telegram Stars or subscription") is True
    assert _is_paid_group_error("STAR_PAY_REQUIRED") is True
    assert _is_paid_group_error("Random error") is False

    # General Read-Only errors (do NOT leave, only skip sending)
    assert _is_general_read_only_error(ChatWriteForbiddenError(request=None)) is True
    assert _is_general_read_only_error(Exception("CHAT_WRITE_FORBIDDEN")) is True
    assert _is_general_read_only_error(Exception("READ_ONLY group")) is True
    assert _is_general_read_only_error(UserBannedInChannelError(request=None)) is False

    # Individually Banned / Muted errors (AUTO-LEAVE)
    assert _is_account_banned_or_muted_error(UserBannedInChannelError(request=None)) is True
    assert _is_account_banned_or_muted_error(Exception("USER_BANNED_IN_CHANNEL")) is True
    assert _is_account_banned_or_muted_error(Exception("Account was MUTED by admin")) is True
    assert _is_account_banned_or_muted_error(ChatWriteForbiddenError(request=None)) is False


@pytest.mark.asyncio
async def test_auto_remove_banned_groups_admin_control():
    from config import settings
    from telethon.errors import UserBannedInChannelError

    service = MTProtoService(api_id=12345, api_hash="fakehash")
    phone = "+919876543210"

    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()
    mock_client.is_user_authorized = AsyncMock(return_value=True)

    mock_dialog = MagicMock()
    mock_dialog.is_group = True
    mock_dialog.is_channel = False
    mock_dialog.name = "Test Group"
    mock_dialog.entity = object()
    mock_dialog.id = 12345

    async def mock_iter_dialogs():
        yield mock_dialog

    mock_client.iter_dialogs = mock_iter_dialogs
    mock_client.send_message.side_effect = UserBannedInChannelError(request=None)
    mock_client.delete_dialog = AsyncMock()

    with patch('services.mtproto_service.StringSession'), \
         patch('services.mtproto_service.TelegramClient', return_value=mock_client):
        # Case 1: Admin AUTO_REMOVE_BANNED_GROUPS is False (default/disabled)
        settings.AUTO_REMOVE_BANNED_GROUPS = False
        res1 = await service.broadcast_to_account_groups("1fakesession", ["Hello"], phone_number=phone)
        assert mock_client.delete_dialog.called is False
        assert "Auto-Remove Disabled" in res1[0][2]

        # Case 2: Admin AUTO_REMOVE_BANNED_GROUPS is True (enabled)
        mock_client.delete_dialog.reset_mock()
        settings.AUTO_REMOVE_BANNED_GROUPS = True
        res2 = await service.broadcast_to_account_groups("1fakesession", ["Hello"], phone_number=phone)
        assert mock_client.delete_dialog.called is True
        assert "Auto-Left" in res2[0][2]

    # Reset back to False
    settings.AUTO_REMOVE_BANNED_GROUPS = False


