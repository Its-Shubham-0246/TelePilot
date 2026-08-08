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
    'PAYMENT_REQUIRED',          # Group requires Telegram Premium/paid subscription
    'TOPIC_CLOSED',              # Forum topic is closed by admin
    'INVITE_REQUEST_SENT',       # Needs admin approval to join
    'PEER_FLOOD',                # Account is flagged for spamming (account-level)
    'CHAT_RESTRICTED',           # Account is geo-blocked or restricted from this specific chat
    'chat is restricted',        # Chat is restricted by Telegram/admin
    'restricted and cannot be used',
    'CHAT_WRITE_FORBIDDEN',      # An alias for write-forbidden caught as generic exception
    'CHAT_SEND_PLAIN_FORBIDDEN', # Group forbids sending plain text messages without media
    'PLAIN_FORBIDDEN',
    'PEER_ID_INVALID',           # Invalid peer type or bot cannot start conversation
    'invalid Peer',              # Invalid peer message
    'USER_IS_BLOCKED',
    'INPUT_USER_DEACTIVATED',
)


from config import settings

logger = logging.getLogger(__name__)


# Authentic Telegram Device Fingerprint Pool (Anti-Ban randomized hardware profiles)
_DEVICE_POOL = [
    {"device_model": "Samsung Galaxy S24 Ultra", "system_version": "Android 14", "app_version": "10.14.2"},
    {"device_model": "Samsung Galaxy S23", "system_version": "Android 14", "app_version": "10.14.1"},
    {"device_model": "Xiaomi 14 Pro", "system_version": "Android 14", "app_version": "10.14.0"},
    {"device_model": "OnePlus 12", "system_version": "Android 14", "app_version": "10.13.9"},
    {"device_model": "Google Pixel 8 Pro", "system_version": "Android 14", "app_version": "10.14.2"},
    {"device_model": "Nothing Phone (2)", "system_version": "Android 14", "app_version": "10.14.1"},
    {"device_model": "Vivo X100 Pro", "system_version": "Android 14", "app_version": "10.13.8"},
    {"device_model": "Realme GT 5 Pro", "system_version": "Android 14", "app_version": "10.14.0"},
    {"device_model": "Motorola Edge 50 Ultra", "system_version": "Android 14", "app_version": "10.14.1"},
    {"device_model": "iPhone 15 Pro Max", "system_version": "iOS 17.4", "app_version": "10.14.2"},
]


def process_spintax(text: str) -> str:
    """Processes Spintax patterns like {option1|option2|option3} to create unique message variations per group send."""
    if not text:
        return ""
    import re
    pattern = re.compile(r'\{([^{}]+)\}')
    while pattern.search(text):
        text = pattern.sub(lambda m: random.choice(m.group(1).split('|')), text)
    return text


def _get_device_fingerprint(phone_number: Optional[str] = None) -> dict:
    """Returns a deterministic device fingerprint based on phone number hash, or random if no phone."""
    if phone_number:
        clean_digits = "".join(c for c in str(phone_number) if c.isdigit())
        if clean_digits:
            hash_val = sum(int(d) for d in clean_digits)
            return _DEVICE_POOL[hash_val % len(_DEVICE_POOL)]
    return random.choice(_DEVICE_POOL)


class MTProtoService:
    def __init__(self, api_id: int = None, api_hash: str = None):
        self.api_id = api_id or settings.TELEGRAM_API_ID
        self.api_hash = api_hash or settings.TELEGRAM_API_HASH
        self._account_locks: dict = {}

    def get_account_lock(self, phone_number: Optional[str]) -> asyncio.Lock:
        """Returns a dedicated asyncio.Lock for the given phone number to ensure single-instance connection safety."""
        clean = "".join(c for c in str(phone_number or "") if c.isdigit()) or "default"
        if clean not in self._account_locks:
            self._account_locks[clean] = asyncio.Lock()
        return self._account_locks[clean]

    def _create_client(self, session: StringSession, phone_number: Optional[str] = None) -> TelegramClient:
        """Creates TelegramClient with varied, authentic device headers to prevent account fingerprint clustering."""
        device = _get_device_fingerprint(phone_number)
        return TelegramClient(
            session,
            self.api_id,
            self.api_hash,
            device_model=device["device_model"],
            system_version=device["system_version"],
            app_version=device["app_version"],
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
        client = self._create_client(session, phone_number)
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
        client = self._create_client(session, phone_number)
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
        client = self._create_client(session, phone_number)
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

    async def terminate_other_sessions(
        self,
        session_str: str,
        phone_number: Optional[str] = None,
        password: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Connects via MTProto, verifies 2FA password if provided, lists active devices,
        and terminates/logs out all other devices except the current session.
        Returns (success, result_message).
        """
        if not session_str:
            return False, "Session token is invalid or empty."

        session = StringSession(session_str)
        client = self._create_client(session, phone_number)
        async with self.get_account_lock(phone_number):
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    return False, "Session expired or user unauthorized."

                if password:
                    try:
                        logger.info(f"[MTProto] Authenticating 2FA password for session termination on {phone_number}...")
                        await client.check_password(password)
                        logger.info(f"[MTProto] 2FA password authenticated successfully.")
                    except Exception as pass_err:
                        logger.warning(f"[MTProto] 2FA password authentication warning: {pass_err}")

                authorizations = await client(GetAuthorizationsRequest())
                all_auths = authorizations.authorizations
                other_auths = [a for a in all_auths if not a.current]

                if not other_auths:
                    return True, "🟢 <b>No other active devices found.</b> This session is the only active one!"

                terminated_count = 0
                blocked_count = 0
                device_blocks = []

                for idx, auth in enumerate(other_auths, start=1):
                    device = auth.device_model or "Unknown Device"
                    platform = f"{auth.platform} {auth.system_version}".strip() or "Unknown OS"
                    app_info = f"{auth.app_name} {auth.app_version}".strip() or "Telegram App"
                    ip_addr = auth.ip or "Unknown IP"
                    country = auth.country or "Unknown Location"
                    
                    # Format last active time if available
                    last_active_str = auth.date_active.strftime('%Y-%m-%d %H:%M UTC') if hasattr(auth, 'date_active') and auth.date_active else "Recently"

                    # Device icon based on platform/device type
                    icon = "📱" if "Android" in platform or "iOS" in platform or "iPhone" in device else ("💻" if "Windows" in platform or "Mac" in platform or "PC" in device else "🖥️")

                    status_str = ""

                    # Try resetting authorization by hash
                    try:
                        await client(ResetAuthorizationRequest(hash=auth.hash))
                        terminated_count += 1
                        status_str = "✅ <b>Terminated & Logged Out</b>"
                    except FreshResetAuthorisationForbiddenError as e:
                        blocked_count += 1
                        status_str = f"🔒 <b>Blocked by Telegram Security:</b> {e} (Requires 24-48h active session history)"
                    except Exception as e:
                        err_txt = str(e)
                        blocked_count += 1
                        if any(kw in err_txt.upper() for kw in ("PASSWORD", "2FA", "AUTHENTICATION")):
                            status_str = f"🔐 <b>2FA Password Required:</b> Telegram demands 2FA verification. Re-run: <code>/terminatesessions {phone_number or ''} &lt;2fa_password&gt;</code>"
                        else:
                            status_str = f"❌ <b>Telegram API Error:</b> {err_txt}"

                    block = (
                        f"<b>{idx}. {icon} {device}</b>\n"
                        f"   ├ <b>OS/Platform:</b> {platform}\n"
                        f"   ├ <b>App:</b> {app_info}\n"
                        f"   ├ <b>IP Address:</b> <code>{ip_addr}</code> ({country})\n"
                        f"   ├ <b>Last Active:</b> {last_active_str}\n"
                        f"   └ <b>Status:</b> {status_str}"
                    )
                    device_blocks.append(block)

                summary_header = f"<b>📱 Detected Active Devices ({len(other_auths)} Total):</b>\n"
                if terminated_count > 0 and blocked_count == 0:
                    result_title = f"✅ <b>Successfully Terminated All {terminated_count} Other Devices!</b>"
                elif terminated_count > 0 and blocked_count > 0:
                    result_title = f"⚠️ <b>Terminated {terminated_count} device(s), {blocked_count} device(s) blocked by Telegram security.</b>"
                else:
                    result_title = (
                        f"🔒 <b>Telegram 24-Hour Security Protection Active!</b>\n\n"
                        f"Telegram's official security rules prevent newly connected sessions from terminating older devices for <b>24 hours</b> after sign-in.\n\n"
                        f"👉 <b>Action Needed:</b> Wait 24 hours after signing into TelePilot, or terminate older devices directly from your official Telegram mobile app:\n"
                        f"<i>Settings ➔ Devices ➔ Terminate all other sessions</i>"
                    )

                final_msg = f"{result_title}\n\n{summary_header}\n" + "\n\n".join(device_blocks)
                return (terminated_count > 0), final_msg


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
        delay_between_groups: float = 1.5,
        phone_number: Optional[str] = None,
        seq_index: Optional[int] = None
    ) -> List[Tuple[str, bool, str, Optional[int]]]:
        """
        Connects once via MTProto session, fetches joined groups, and broadcasts messages with inter-group delay.
        Supports sequential message rotation if seq_index is provided.
        Returns list of (group_title, success, log_msg, flood_wait_seconds).
        """
        if not message_variants:
            return []

        session = StringSession(session_str)
        client = self._create_client(session, phone_number)
        results = []

        async with self.get_account_lock(phone_number):
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

                consecutive_skips = 0
                for index, (group_entity, group_title) in enumerate(groups):
                    if index > 0:
                        # Human-like delay: 2.5s base + 0.5-2.0s jitter = ~3.0s-4.5s between groups
                        # Prevents Telegram anti-spam shadow-muting and keeps group post views & RPM high
                        jitter = random.uniform(0.5, 2.0)
                        await asyncio.sleep(2.5 + jitter)

                    if seq_index is not None and message_variants:
                        raw_variant = message_variants[seq_index % len(message_variants)]
                    else:
                        raw_variant = random.choice(message_variants)

                    message_text = process_spintax(raw_variant)
                    sent = False

                    for attempt in range(2):  # 1 initial attempt + 1 retry on transient errors
                        try:
                            if media_url:
                                try:
                                    await client.send_file(group_entity, media_url, caption=message_text, parse_mode='html')
                                except Exception:
                                    await client.send_file(group_entity, media_url, caption=message_text)
                            else:
                                try:
                                    await client.send_message(group_entity, message_text, parse_mode='html', link_preview=True)
                                except Exception:
                                    await client.send_message(group_entity, message_text, link_preview=True)

                            results.append((group_title, True, f"Sent to {group_title}", None))
                            sent = True
                            consecutive_skips = 0
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
                            consecutive_skips += 1
                            break

                        except (ChatWriteForbiddenError, ChatAdminRequiredError) as e:
                            # No write permission (broadcast channel, muted, admin-only) — permanent skip
                            logger.warning(f"[Broadcast] No write permission in '{group_title}': {e}")
                            results.append((group_title, False, f"Write not allowed: {e}", None))
                            sent = True  # No point retrying
                            consecutive_skips += 1
                            break

                        except ChannelPrivateError as e:
                            # Channel became private — permanent skip
                            logger.warning(f"[Broadcast] Channel private '{group_title}': {e}")
                            results.append((group_title, False, f"Channel is now private: {e}", None))
                            sent = True
                            consecutive_skips += 1
                            break

                        except Exception as e:
                            err_str = str(e)
                            # Check for known permanent errors — retry is pointless
                            if any(kw in err_str for kw in _PERMANENT_ERROR_KEYWORDS):
                                logger.warning(f"[Broadcast] Permanent skip '{group_title}': {err_str}")
                                results.append((group_title, False, f"Permanent: {err_str}", None))
                                sent = True
                                consecutive_skips += 1
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

                    if consecutive_skips >= 10:
                        logger.warning(f"[Broadcast] 10 consecutive non-writable groups for {phone_number} — early stopping broadcast cycle for efficiency.")
                        break

                    if not sent:
                        results.append((group_title, False, "Unknown failure", None))

                return results

            except AuthKeyDuplicatedError as e:
                # Session used from two IPs simultaneously (Railway rolling deploy / concurrent workers) — temporary conflict, not revoked
                logger.warning(f"[Broadcast] Auth key duplicated (dual-IP conflict) for {phone_number}: {e} — skipping cycle")
                return [("All Groups", False, "DUAL_IP_CONFLICT", None)]
            except (UserDeactivatedError, AuthKeyInvalidError) as e:
                logger.error(f"[Broadcast] Session revoked/invalidated for {phone_number}: {e}")
                return [("All Groups", False, "SESSION_REVOKED", None)]

            except Exception as e:
                logger.error(f"[Broadcast] Unexpected broadcast exception: {type(e).__name__}: {e}")
                return [("All Groups", False, f"Error: {str(e)}", None)]
            finally:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def broadcast_multi_account_stacked(
        self,
        accounts_data: List[dict],
        media_url: Optional[str] = None
    ) -> dict:
        """
        Executes stacked multi-account broadcasts for a user's accounts.
        For each target group G:
            Account 1 sends to G -> Account 2 sends to G -> Account 3 sends to G (<0.2s apart).
        In Telegram's chat window, posts land stacked directly one below another.
        Then waits inter-group delay (3.0s-4.5s) before moving to the next group.
        Returns dict mapping account_id -> list of (group_title, success, log_msg, flood_seconds).
        """
        if not accounts_data:
            return {}

        results_by_account = {acc["id"]: [] for acc in accounts_data}
        clients = {}
        account_groups = {}

        try:
            async def connect_acc(acc):
                session = StringSession(acc["session_str"])
                client = self._create_client(session, acc["phone_number"])
                try:
                    await client.connect()
                    if not await client.is_user_authorized():
                        return acc["id"], client, None, "SESSION_REVOKED"

                    groups = {}
                    async for dialog in client.iter_dialogs():
                        if dialog.is_group:
                            group_key = str(getattr(dialog.entity, 'id', dialog.id))
                            groups[group_key] = (dialog.entity, dialog.name or str(dialog.id))
                    return acc["id"], client, groups, None
                except (UserDeactivatedError, AuthKeyInvalidError):
                    return acc["id"], client, None, "SESSION_REVOKED"
                except AuthKeyDuplicatedError:
                    return acc["id"], client, None, "DUAL_IP_CONFLICT"
                except Exception as e:
                    return acc["id"], client, None, str(e)

            connect_tasks = [connect_acc(acc) for acc in accounts_data]
            connect_results = await asyncio.gather(*connect_tasks, return_exceptions=True)

            active_accounts = []
            for res in connect_results:
                if isinstance(res, Exception):
                    continue
                acc_id, client, groups, err_msg = res
                clients[acc_id] = client
                if err_msg:
                    results_by_account[acc_id].append(("All Groups", False, err_msg, None))
                elif groups:
                    account_groups[acc_id] = groups
                    acc_info = next((a for a in accounts_data if a["id"] == acc_id), None)
                    if acc_info:
                        active_accounts.append(acc_info)

            if not active_accounts:
                return results_by_account

            all_group_keys = []
            seen_keys = set()
            for acc in active_accounts:
                g_map = account_groups.get(acc["id"], {})
                for g_key in g_map:
                    if g_key not in seen_keys:
                        seen_keys.add(g_key)
                        all_group_keys.append(g_key)

            flood_paused = set()
            consecutive_failures = {acc["id"]: 0 for acc in active_accounts}

            for group_idx, g_key in enumerate(all_group_keys):
                if group_idx > 0:
                    jitter = random.uniform(0.5, 2.0)
                    await asyncio.sleep(2.5 + jitter)

                for acc in active_accounts:
                    acc_id = acc["id"]
                    if acc_id in flood_paused or consecutive_failures.get(acc_id, 0) >= 10:
                        continue

                    g_map = account_groups.get(acc_id, {})
                    if g_key not in g_map:
                        continue

                    group_entity, group_title = g_map[g_key]
                    client = clients[acc_id]

                    variants = acc["variants"]
                    seq_idx = acc["seq_index"]
                    if seq_idx is not None and variants:
                        raw_variant = variants[seq_idx % len(variants)]
                    else:
                        raw_variant = random.choice(variants)

                    message_text = process_spintax(raw_variant)
                    sent = False

                    for attempt in range(2):
                        try:
                            if media_url:
                                try:
                                    await client.send_file(group_entity, media_url, caption=message_text, parse_mode='html')
                                except Exception:
                                    await client.send_file(group_entity, media_url, caption=message_text)
                            else:
                                try:
                                    await client.send_message(group_entity, message_text, parse_mode='html', link_preview=True)
                                except Exception:
                                    await client.send_message(group_entity, message_text, link_preview=True)

                            results_by_account[acc_id].append((group_title, True, f"Sent to {group_title}", None))
                            sent = True
                            consecutive_failures[acc_id] = 0
                            break

                        except FloodWaitError as e:
                            logger.warning(f"[BroadcastStacked] FloodWait for {acc['phone_number']} on '{group_title}': {e.seconds}s")
                            results_by_account[acc_id].append((group_title, False, f"FloodWait: retry in {e.seconds}s", e.seconds))
                            flood_paused.add(acc_id)
                            break

                        except SlowModeWaitError as e:
                            logger.info(f"[BroadcastStacked] SlowMode on '{group_title}': {e.seconds}s wait — skipping group")
                            results_by_account[acc_id].append((group_title, False, f"SlowMode: {e.seconds}s", None))
                            sent = True
                            break

                        except (UserBannedInChannelError, UserNotParticipantError, PeerIdInvalidError, ChatWriteForbiddenError, ChatAdminRequiredError, ChannelPrivateError) as e:
                            logger.warning(f"[BroadcastStacked] Skip group '{group_title}' for {acc['phone_number']}: {e}")
                            results_by_account[acc_id].append((group_title, False, f"Skip: {e}", None))
                            sent = True
                            consecutive_failures[acc_id] += 1
                            break

                        except Exception as e:
                            err_str = str(e)
                            if any(kw in err_str for kw in _PERMANENT_ERROR_KEYWORDS):
                                results_by_account[acc_id].append((group_title, False, f"Permanent: {err_str}", None))
                                sent = True
                                consecutive_failures[acc_id] += 1
                                break
                            elif attempt == 0:
                                await asyncio.sleep(1.5)
                            else:
                                results_by_account[acc_id].append((group_title, False, f"Failed: {err_str}", None))
                                sent = True

                    if not sent and acc_id not in flood_paused:
                        results_by_account[acc_id].append((group_title, False, "Unknown failure", None))

                    # 0.15s micro-delay between accounts in the same group so messages land stacked one directly below another
                    await asyncio.sleep(0.15)

            return results_by_account

        finally:
            for client in clients.values():
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def fetch_joined_groups(self, session_str: str, phone_number: Optional[str] = None) -> List[Tuple[any, str]]:
        """
        Fetches all joined groups and supergroups for an account.
        Returns list of (dialog_entity, dialog_title).
        """
        if not session_str:
            return []
        session = StringSession(session_str)
        client = self._create_client(session, phone_number)
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
            logger.error(f"Error fetching dialogs for {phone_number}: {e}")
            return []
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def get_joined_group_count(self, session_str: str, phone_number: Optional[str] = None, timeout: float = 1.5) -> int:
        """
        Fetches joined group count for an account session with non-blocking lock and timeout safety.
        """
        if not session_str:
            return 0
        try:
            lock = self.get_account_lock(phone_number)
            if lock.locked():
                return 0
            async with lock:
                groups = await asyncio.wait_for(self.fetch_joined_groups(session_str, phone_number=phone_number), timeout=timeout)
                return len(groups)
        except Exception as e:
            logger.warning(f"Error fetching joined group count for {phone_number}: {e}")
            return 0


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

        raw_variant = random.choice(message_variants)
        message_text = process_spintax(raw_variant)
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
                try:
                    await client.send_file(target_chat, media_url, caption=message_text, parse_mode='html')
                except Exception:
                    await client.send_file(target_chat, media_url, caption=message_text)
            else:
                try:
                    await client.send_message(target_chat, message_text, parse_mode='html', link_preview=True)
                except Exception:
                    await client.send_message(target_chat, message_text, link_preview=True)

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

    async def fetch_latest_otp(self, session_str: str, phone_number: Optional[str] = None) -> Tuple[bool, str]:
        """
        Connects via MTProto session and fetches the latest OTP / official message from Telegram (777000).
        Returns (success, result_message).
        """
        import re
        session = StringSession(session_str)
        client = self._create_client(session, phone_number)

        async with self.get_account_lock(phone_number):
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
                logger.error(f"Failed to fetch OTP for {phone_number}: {e}")
                return False, f"Error fetching OTP: {e}"

            finally:
                await client.disconnect()


mtproto_service = MTProtoService()

