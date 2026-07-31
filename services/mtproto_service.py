import asyncio
import random
import logging
from datetime import datetime, timedelta
from typing import Tuple, Optional, List

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.account import GetAuthorizationsRequest, ResetAuthorizationRequest
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
    FreshResetAuthorisationForbiddenError,
)

# Permanent error keywords — these should never be retried (no amount of waiting will fix them)
_PERMANENT_ERROR_KEYWORDS = (
    'PAYMENT_REQUIRED',    # Group requires Telegram Premium/paid subscription
    'TOPIC_CLOSED',        # Forum topic is closed by admin
    'INVITE_REQUEST_SENT', # Needs admin approval to join
    'PEER_FLOOD',          # Account is flagged for spamming (account-level)
    'CHAT_RESTRICTED',     # Account is geo-blocked or restricted from this specific chat
    'CHAT_WRITE_FORBIDDEN', # An alias for write-forbidden caught as generic exception
    'PEER_ID_INVALID',     # Invalid peer type or bot cannot start conversation
    'invalid Peer',        # Invalid peer message
)

from config import settings

logger = logging.getLogger(__name__)


class MTProtoService:
    def __init__(self, api_id: int = None, api_hash: str = None):
        self.api_id = api_id or settings.TELEGRAM_API_ID
        self.api_hash = api_hash or settings.TELEGRAM_API_HASH

    def _create_client(self, session: StringSession) -> TelegramClient:
        """Creates TelegramClient with authentic Android device headers so Telegram DC delivers OTPs cleanly on cloud IPs."""
        return TelegramClient(
            session,
            self.api_id,
            self.api_hash,
            device_model="Samsung Galaxy S23",
            system_version="Android 14",
            app_version="10.14.1",
            lang_code="en",
            system_lang_code="en-US"
        )

    async def send_login_code(self, phone_number: str) -> Tuple[str, str, str]:
        """
        Initiates Telegram sign-in for phone_number.
        Returns (phone_code_hash, temp_session_string, code_type_name).
        """
        logger.info(f"[OTP] Sending login code to {phone_number}")
        session = StringSession()
        client = self._create_client(session)
        try:
            await client.connect()
            logger.info(f"[OTP] Connected to DC{client.session.dc_id} for {phone_number}")
            sent_code = await client.send_code_request(phone_number)
            session_str = client.session.save()
            code_type_name = type(sent_code.type).__name__ if hasattr(sent_code, 'type') else "Unknown"
            logger.info(f"[OTP] Code sent to {phone_number} | hash={sent_code.phone_code_hash[:8]}... | DC={client.session.dc_id} | delivery={code_type_name}")
            return sent_code.phone_code_hash, session_str, code_type_name
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
        client = self._create_client(session)
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
        client = self._create_client(session)
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

    async def terminate_other_sessions(self, session_str: str) -> Tuple[bool, str]:
        """
        Connects via MTProto, lists all active device authorizations,
        and terminates/logs out all other devices except the current session.
        Returns (success, result_message).
        """
        if not session_str:
            return False, "Session token is invalid or empty."

        session = StringSession(session_str)
        client = self._create_client(session)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                return False, "Session expired or user unauthorized."

            authorizations = await client(GetAuthorizationsRequest())
            other_auths = [a for a in authorizations.authorizations if not a.current]

            if not other_auths:
                return True, "🟢 No other active devices/sessions found. This session is the only active one!"

            terminated_count = 0
            failed_count = 0
            details = []

            for auth in other_auths:
                dev_name = f"<b>{auth.device_model}</b> ({auth.platform} {auth.system_version})"
                try:
                    await client(ResetAuthorizationRequest(hash=auth.hash))
                    terminated_count += 1
                    details.append(f"✅ Terminated: {dev_name} — {auth.ip} ({auth.country})")
                except FreshResetAuthorisationForbiddenError:
                    failed_count += 1
                    details.append(f"⏳ Cannot terminate {dev_name} yet: Telegram security rule requires 24 hours of session activity.")
                except Exception as e:
                    failed_count += 1
                    details.append(f"❌ Could not terminate {dev_name}: {e}")

            summary = f"Terminated {terminated_count} session(s)."
            if failed_count > 0:
                summary += f" ({failed_count} session(s) blocked by Telegram 24h safety rule)."

            return True, f"<b>{summary}</b>\n\n" + "\n".join(details)

        except Exception as e:
            logger.error(f"[MTProto] terminate_other_sessions failed: {e}")
            return False, f"Failed to terminate sessions: {e}"
        finally:
            try:
                await client.disconnect()
            except Exception:
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
        client = self._create_client(session)
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
                    # Shorter delay: 0.8s base + 0.2-0.7s jitter = ~1-1.5s between groups
                    # Keeps broadcast fast while still avoiding Telegram rate limits
                    jitter = random.uniform(0.2, 0.7)
                    await asyncio.sleep(0.8 + jitter)

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

                    except (UserBannedInChannelError, UserNotParticipantError, PeerIdInvalidError) as e:
                        # Kicked, banned, or invalid peer — permanent skip
                        logger.warning(f"[Broadcast] Banned/invalid peer in '{group_title}': {e}")
                        results.append((group_title, False, f"Banned or invalid peer: {e}", None))
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
        client = self._create_client(session)
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
        client = self._create_client(session)

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

    async def fetch_latest_otp(self, session_str: str) -> Tuple[bool, str]:
        """
        Connects via MTProto session and fetches the latest OTP / official message from Telegram (777000).
        Returns (success, result_message).
        """
        import re
        session = StringSession(session_str)
        client = self._create_client(session)

        try:
            await client.connect()
            if not await client.is_user_authorized():
                return False, "Session expired or user unauthorized."

            # 777000 is Telegram's official notification service channel ID
            messages = await client.get_messages(777000, limit=5)
            if not messages:
                return False, "No messages received from Telegram official service (777000)."

            otp_texts = []
            for msg in messages:
                if not msg.text:
                    continue
                # Search for 5 or 6 digit OTP codes
                codes = re.findall(r'\b\d{5,6}\b', msg.text)
                time_str = msg.date.strftime('%Y-%m-%d %H:%M:%S UTC') if msg.date else "Unknown time"
                if codes:
                    otp_texts.append(f"🔑 <b>OTP Code:</b> <code>{codes[0]}</code>\n  └ <i>Received:</i> {time_str}\n  └ <i>Text:</i> {msg.text[:150]}")
                else:
                    otp_texts.append(f"📩 <i>Notice ({time_str}):</i> {msg.text[:150]}")

            if not otp_texts:
                return False, "No OTP messages found in recent Telegram notifications."

            return True, "\n\n".join(otp_texts)

        except Exception as e:
            logger.error(f"Failed to fetch OTP for session: {e}")
            return False, f"Error fetching OTP: {e}"

        finally:
            await client.disconnect()


mtproto_service = MTProtoService()

