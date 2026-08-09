import pytest
import asyncio
from unittest.mock import AsyncMock, patch
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
