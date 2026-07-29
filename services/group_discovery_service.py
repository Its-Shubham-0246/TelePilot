import logging
from typing import Set, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from core.database import async_session_factory
from models.account import TelegramAccount
from models.discovered_group import DiscoveredGroup
from models.user import User
from services.mtproto_service import mtproto_service

logger = logging.getLogger(__name__)


async def _notify_alert(text: str):
    """Send alert to the configured alert group chat. If not set, fallback to admin DM."""
    try:
        from bot.bot_instance import bot

        # If alert group chat ID is configured, send exclusively to the private group
        if settings.ALERT_GROUP_CHAT_ID and settings.ALERT_GROUP_CHAT_ID.strip():
            try:
                chat_id = int(settings.ALERT_GROUP_CHAT_ID.strip())
                await bot.send_message(chat_id, text, parse_mode="HTML")
                return
            except Exception as e:
                logger.warning(f"[GroupAlert] Failed to send to alert group {settings.ALERT_GROUP_CHAT_ID}: {e}")

        # Fallback: send to admin DM if no group chat ID is set
        for admin_id in settings.admin_ids_list:
            try:
                await bot.send_message(admin_id, text, parse_mode="HTML")
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[GroupAlert] _notify_alert failed: {e}")



async def _get_reference_group_ids() -> Set[int]:
    """Get the set of group IDs that the reference account is currently in."""
    ref_phone = settings.REFERENCE_ACCOUNT_PHONE.strip()
    if not ref_phone:
        return set()

    async with async_session_factory() as db:
        acc = (await db.execute(
            select(TelegramAccount).where(TelegramAccount.phone_number == ref_phone)
        )).scalars().first()

    if not acc:
        logger.warning(f"[GroupAlert] Reference account {ref_phone} not found in DB.")
        return set()

    try:
        session_str = acc.get_session_string()
        if not session_str:
            return set()
        groups = await mtproto_service.fetch_joined_groups(session_str)
        return {entity.id for entity, title in groups}
    except Exception as e:
        logger.error(f"[GroupAlert] Error fetching groups for reference account: {e}")
        return set()


async def check_and_alert_new_groups(
    discovering_phone: str,
    session_str: str,
):
    """
    After an account broadcasts, call this to:
    1. Fetch its group list.
    2. Compare against the reference account's groups.
    3. For new unknown groups, save to DB and send admin an alert.
    """
    ref_phone = settings.REFERENCE_ACCOUNT_PHONE.strip()
    if not ref_phone:
        return  # Feature disabled — no reference account configured

    try:
        # Fetch groups this account is in
        groups = await mtproto_service.fetch_joined_groups(session_str)
        if not groups:
            return

        # Fetch reference account's group IDs
        ref_group_ids = await _get_reference_group_ids()

        async with async_session_factory() as db:
            for entity, title in groups:
                try:
                    group_id = entity.id
                except Exception:
                    continue

                # Check if already tracked
                existing = (await db.execute(
                    select(DiscoveredGroup).where(DiscoveredGroup.group_id == group_id)
                )).scalars().first()

                if existing:
                    continue  # Already known — skip

                # New group found! Save to DB
                new_group = DiscoveredGroup(
                    group_id=group_id,
                    group_title=title,
                    discovered_by_phone=discovering_phone,
                    notified=False
                )
                db.add(new_group)

                # If reference account is NOT in this group, send alert
                if group_id not in ref_group_ids:
                    new_group.notified = True
                    await db.commit()

                    username = getattr(entity, 'username', None)
                    if username:
                        group_link = f"https://t.me/{username}"
                    else:
                        group_link = f"(ID: <code>{group_id}</code> — no public link)"

                    alert_text = (
                        f"🔔 <b>New Group Discovered!</b>\n\n"
                        f"<b>Group:</b> {title}\n"
                        f"<b>Link:</b> {group_link}\n"
                        f"<b>Discovered by:</b> <code>{discovering_phone}</code>\n\n"
                        f"⚠️ Your reference account <code>{ref_phone}</code> is <b>NOT</b> in this group.\n"
                        f"Join this group with your other accounts to start broadcasting there!"
                    )
                    await _notify_alert(alert_text)
                    logger.info(f"[GroupAlert] New group alert sent: '{title}' (ID={group_id})")
                else:
                    await db.commit()

    except Exception as e:
        logger.error(f"[GroupAlert] check_and_alert_new_groups failed for {discovering_phone}: {e}")


group_discovery_service = object()  # Placeholder for import compatibility
