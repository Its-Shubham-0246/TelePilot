import asyncio
import random
import logging
from datetime import datetime, timedelta
from typing import Tuple, Optional, List

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError,
    SlowModeWaitError,
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    UserDeactivatedError,
    AuthKeyInvalidError,
    AuthKeyDuplicatedError,
    UserBannedInChannelError,
    ChatWriteForbiddenError,
    ChatAdminRequiredError,
    UserNotParticipantError,
    ChannelPrivateError,
    PeerIdInvalidError,
)

# Permanent error keywords — these should never be retried (no amount of waiting will fix them)
_PERMANENT_ERROR_KEYWORDS = (
    'PAYMENT_REQUIRED',   # Group requires Telegram Premium/paid subscription
    'TOPIC_CLOSED',        # Forum topic is closed by admin
    'INVITE_REQUEST_SENT', # Needs admin approval to join
    'PEER_FLOOD',          # Account is flagged for spamming (account-level)
)

from config import settings

logger = logging.getLogger(__name__)


class MTProtoService:
    def __init__(self, api_id: int = None, api_hash: str = None):
        self.api_id = api_id or settings.TELEGRAM_API_ID
        self.api_hash = api_hash or settings.TELEGRAM_API_HASH

    async def send_login_code(self, phone_number: str) -> Tuple[str, str]:
        """
        Initiates Telegram sign-in for phone_number.
        Returns (phone_code_hash, temp_session_string).
        """
        logger.info(f"[OTP] Sending login code to {phone_number}")
        session = StringSession()
        client = TelegramClient(session, self.api_id, self.api_hash)
        try:
            await client.connect()
            logger.info(f"[OTP] Connected to DC{client.session.dc_id} for {phone_number}")
            sent_code = await client.send_code_request(phone_number)
            session_str = client.session.save()
            logger.info(f"[OTP] Code sent to {phone_number} | hash={sent_code.phone_code_hash[:8]}... | DC={client.session.dc_id}")
            return sent_code.phone_code_hash, session_str
        except Exception as e:
            logger.error(f"[OTP] send_login_code failed for {phone_number}: {type(e).__name__}: {e}")
            raise
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def sign_in_code(
        self, phone_number: str, code: str, phone_code_hash: str, temp_session_str: str
    ) -> Tuple[str, bool]:
        """
        Submits OTP code using the saved session string.
        Returns (final_session_string, requires_2fa).
        """
        logger.info(f"[OTP] sign_in_code for {phone_number} | code='{code}' | hash={phone_code_hash[:8]}...")
        session = StringSession(temp_session_str)
        client = TelegramClient(session, self.api_id, self.api_hash)
        try:
            await client.connect()
            logger.info(f"[OTP] Reconnected to DC{client.session.dc_id} for {phone_number}")
            try:
                await client.sign_in(phone=phone_number, code=code, phone_code_hash=phone_code_hash)
                final_session = client.session.save()
                logger.info(f"[OTP] sign_in SUCCESS for {phone_number}")
                return final_session, False
            except SessionPasswordNeededError:
                temp_session = client.session.save()
                logger.info(f"[OTP] 2FA required for {phone_number}")
                return temp_session, True
        except Exception as e:
            logger.error(f"[OTP] sign_in_code FAILED for {phone_number}: {type(e).__name__}: {e}")
            raise
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def sign_in_2fa(self, phone_number: str, password: str, temp_session_str: str) -> str:
        """
        Submits 2FA password. Returns final_session_string.
        """
        logger.info(f"[OTP] sign_in_2fa for {phone_number}")
        session = StringSession(temp_session_str)
        client = TelegramClient(session, self.api_id, self.api_hash)
        try:
            await client.connect()
            await client.sign_in(password=password)
            final_session = client.session.save()
            logger.info(f"[OTP] 2FA SUCCESS for {phone_number}")
            return final_session
        except Exception as e:
            logger.error(f"[OTP] sign_in_2fa FAILED for {phone_number}: {type(e).__name__}: {e}")
            raise
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def cancel_pending_login(self, phone_number: str):
        """No-op kept for compatibility."""
        pass




    async def broadcast_to_account_groups(
        self,
        session_str: str,
        message_variants: List[str],
        media_url: Optional[str] = None,
        delay_between_groups: float = 1.5
    ) -> List[Tuple[str, bool, str, Optional[int]]]:
        """
        Connects once via MTProto session, fetches joined groups, and broadcasts messages with inter-group delay.
        Returns list of (group_title, success, log_msg, flood_wait_seconds).
        """
        if not message_variants:
            return []

        session = StringSession(session_str)
        client = TelegramClient(session, self.api_id, self.api_hash)
        results = []

        try:
            await client.connect()
            if not await client.is_user_authorized():
                logger.error("Session unauthorized during broadcast.")
                return [("All Groups", False, "Session expired or user unauthorized.", None)]

            groups = []
            async for dialog in client.iter_dialogs():
                if dialog.is_group:
                    groups.append((dialog.entity, dialog.name or str(dialog.id)))

            if not groups:
                logger.info("No joined groups found for session.")
                return []

            logger.info(f"Found {len(groups)} joined groups. Starting single-connection broadcast...")

            for index, (group_entity, group_title) in enumerate(groups):
                if index > 0:
                    jitter = random.uniform(0.5, 1.5)
                    await asyncio.sleep(delay_between_groups + jitter)

                message_text = random.choice(message_variants)
                sent = False

                for attempt in range(2):  # 1 initial attempt + 1 retry on transient errors
                    try:
                        if media_url:
                            await client.send_file(group_entity, media_url, caption=message_text)
                        else:
                            await client.send_message(group_entity, message_text)

                        results.append((group_title, True, f"Sent to {group_title}", None))
                        sent = True
                        break

                    except FloodWaitError as e:
                        # Account-wide flood wait — stop ALL sends for this account
                        logger.warning(f"[Broadcast] FloodWait on '{group_title}': {e.seconds}s — stopping account")
                        results.append((group_title, False, f"FloodWait: retry in {e.seconds}s", e.seconds))
                        return results  # Return immediately with flood_seconds set

                    except SlowModeWaitError as e:
                        # Group slow mode — skip this group, try again next interval
                        logger.info(f"[Broadcast] SlowMode on '{group_title}': {e.seconds}s wait — skipping this cycle")
                        results.append((group_title, False, f"SlowMode: {e.seconds}s — will retry next interval", None))
                        sent = True  # Don't retry, move to next group
                        break

                    except (UserBannedInChannelError, UserNotParticipantError) as e:
                        # Kicked or banned from this group — permanent skip
                        logger.warning(f"[Broadcast] Banned/not member of '{group_title}': {e}")
                        results.append((group_title, False, f"Banned or not a member: {e}", None))
                        sent = True  # No point retrying
                        break

                    except (ChatWriteForbiddenError, ChatAdminRequiredError) as e:
                        # No write permission (broadcast channel, muted, admin-only) — permanent skip
                        logger.warning(f"[Broadcast] No write permission in '{group_title}': {e}")
                        results.append((group_title, False, f"Write not allowed: {e}", None))
                        sent = True  # No point retrying
                        break

                    except ChannelPrivateError as e:
                        # Channel became private — permanent skip
                        logger.warning(f"[Broadcast] Channel private '{group_title}': {e}")
                        results.append((group_title, False, f"Channel is now private: {e}", None))
                        sent = True
                        break

                    except Exception as e:
                        err_str = str(e)
                        # Check for known permanent errors — retry is pointless
                        if any(kw in err_str for kw in _PERMANENT_ERROR_KEYWORDS):
                            logger.warning(f"[Broadcast] Permanent skip '{group_title}': {err_str}")
                            results.append((group_title, False, f"Permanent: {err_str}", None))
                            sent = True
                            break
                        elif attempt == 0:
                            # Transient error — wait 2s and retry once
                            logger.warning(f"[Broadcast] Transient error on '{group_title}' (attempt 1): {e} — retrying in 2s")
                            await asyncio.sleep(2)
                        else:
                            # Second failure — log and move on
                            logger.error(f"[Broadcast] Failed '{group_title}' after retry: {e}")
                            results.append((group_title, False, f"Failed after retry: {err_str}", None))
                            sent = True

                if not sent:
                    results.append((group_title, False, "Unknown failure", None))

            return results

        except AuthKeyDuplicatedError as e:
            # Session used from two IPs simultaneously (Railway rolling deploy) — session is permanently terminated by Telegram
            logger.error(f"[Broadcast] Auth key duplicated (dual-IP conflict): {e}")
            return [("All Groups", False, "SESSION_REVOKED", None)]
        except (UserDeactivatedError, AuthKeyInvalidError) as e:
            logger.error(f"[Broadcast] Session revoked/invalidated: {e}")
            return [("All Groups", False, "SESSION_REVOKED", None)]
        except Exception as e:
            logger.error(f"[Broadcast] Unexpected broadcast exception: {type(e).__name__}: {e}")
            return [("All Groups", False, f"Error: {str(e)}", None)]
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

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
            try:
                await client.disconnect()
            except Exception:
                pass

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
