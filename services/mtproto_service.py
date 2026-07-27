import asyncio
import random
import logging
from datetime import datetime, timedelta
from typing import Tuple, Optional, List

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError,
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    UserDeactivatedError,
    AuthKeyInvalidError,
    UserBannedInChannelError,
    ChatWriteForbiddenError,
    PeerIdInvalidError,
)

from config import settings

logger = logging.getLogger(__name__)


class MTProtoService:
    def __init__(self, api_id: int = None, api_hash: str = None):
        self.api_id = api_id or settings.TELEGRAM_API_ID
        self.api_hash = api_hash or settings.TELEGRAM_API_HASH
        self.pending_clients: Dict[str, TelegramClient] = {}

    async def cancel_pending_login(self, phone_number: str):
        """Disconnects and cleans up any active pending login client for phone_number."""
        client = self.pending_clients.pop(phone_number, None)
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def send_login_code(self, phone_number: str) -> Tuple[str, str]:
        """
        Initiates Telegram sign-in for phone_number.
        Keeps the client connected while waiting for OTP.
        Returns (phone_code_hash, temp_session_string).
        """
        # Cleanup any previous attempt for this phone
        await self.cancel_pending_login(phone_number)

        session = StringSession()
        client = TelegramClient(session, self.api_id, self.api_hash)
        await client.connect()
        try:
            sent_code = await client.send_code_request(phone_number)
            session_str = client.session.save()
            # Keep client active in memory so MTProto connection stays open for sign_in
            self.pending_clients[phone_number] = client
            return sent_code.phone_code_hash, session_str
        except Exception as e:
            await client.disconnect()
            raise e

    async def sign_in_code(
        self, phone_number: str, code: str, phone_code_hash: str, temp_session_str: str
    ) -> Tuple[str, bool]:
        """
        Submits OTP code over the active MTProto connection.
        Returns (final_session_string, requires_2fa).
        """
        client = self.pending_clients.get(phone_number)
        created_fresh = False

        if not client or not client.is_connected():
            session = StringSession(temp_session_str)
            client = TelegramClient(session, self.api_id, self.api_hash)
            await client.connect()
            created_fresh = True

        try:
            try:
                await client.sign_in(phone=phone_number, code=code, phone_code_hash=phone_code_hash)
                final_session = client.session.save()
                await self.cancel_pending_login(phone_number)
                return final_session, False
            except SessionPasswordNeededError:
                temp_session = client.session.save()
                # Keep client active in pending_clients for 2FA step
                self.pending_clients[phone_number] = client
                return temp_session, True
        except Exception as e:
            if created_fresh:
                await client.disconnect()
            else:
                # Keep active client connected in case user re-types code
                pass
            raise e

    async def sign_in_2fa(self, phone_number: str, password: str, temp_session_str: str) -> str:
        """
        Submits 2FA password over the active MTProto connection.
        Returns final_session_string.
        """
        client = self.pending_clients.get(phone_number)
        created_fresh = False

        if not client or not client.is_connected():
            session = StringSession(temp_session_str)
            client = TelegramClient(session, self.api_id, self.api_hash)
            await client.connect()
            created_fresh = True

        try:
            await client.sign_in(password=password)
            final_session = client.session.save()
            await self.cancel_pending_login(phone_number)
            return final_session
        except Exception as e:
            if created_fresh:
                await client.disconnect()
            raise e


    async def fetch_joined_groups(self, session_str: str) -> List[Tuple[any, str]]:
        """
        Fetches all joined groups and supergroups for an account.
        Returns list of (dialog_entity, dialog_title).
        """
        session = StringSession(session_str)
        client = TelegramClient(session, self.api_id, self.api_hash)
        groups = []
        try:
            await client.connect()
            if not await client.is_user_authorized():
                return []
            async for dialog in client.iter_dialogs():
                if dialog.is_group:
                    groups.append((dialog.entity, dialog.name or str(dialog.id)))
            return groups
        except Exception as e:
            logger.error(f"Error fetching dialogs: {e}")
            return []
        finally:
            await client.disconnect()

    async def send_message_to_target(
        self,
        session_str: str,
        target_chat: any,
        message_variants: List[str],
        media_url: Optional[str] = None,
        delay_seconds: int = 5
    ) -> Tuple[bool, str, Optional[int]]:
        """
        Connects via MTProto session and sends a randomly selected variant to target_chat.
        Returns (success, log_or_error_message, flood_wait_seconds).
        """
        if not message_variants:
            return False, "No message content variants provided.", None

        message_text = random.choice(message_variants)
        session = StringSession(session_str)
        client = TelegramClient(session, self.api_id, self.api_hash)

        try:
            await client.connect()
            if not await client.is_user_authorized():
                return False, "Session expired or user unauthorized.", None

            jitter = random.uniform(1.0, 3.0)
            actual_delay = delay_seconds + jitter
            await asyncio.sleep(actual_delay)

            if media_url:
                await client.send_file(target_chat, media_url, caption=message_text)
            else:
                await client.send_message(target_chat, message_text)

            return True, f"Message sent successfully to {target_chat}", None

        except FloodWaitError as e:
            logger.warning(f"FloodWait encountered for session on target {target_chat}: wait {e.seconds} seconds")
            return False, f"FloodWait limit hit: retry in {e.seconds}s", e.seconds

        except (UserDeactivatedError, AuthKeyInvalidError) as e:
            logger.error(f"Account session invalidated: {e}")
            return False, f"Account session revoked/invalidated: {e}", None

        except (UserBannedInChannelError, ChatWriteForbiddenError) as e:
            return False, f"Permission denied writing to channel/group {target_chat}: {e}", None

        except Exception as e:
            logger.error(f"Failed to send message to {target_chat}: {e}")
            return False, f"Error sending message: {str(e)}", None

        finally:
            await client.disconnect()


mtproto_service = MTProtoService()
