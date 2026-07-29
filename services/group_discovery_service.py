import logging
from typing import Set
from sqlalchemy import select

from config import settings
from core.database import async_session_factory
from models.account import TelegramAccount
from models.discovered_group import DiscoveredGroup
from services.mtproto_service import mtproto_service

logger = logging.getLogger(__name__)


async def _notify_alert(text: str):
    """Send alert to the configured alert group chat."""
    try:
        from bot.bot_instance import bot

        # Send to configured alert group
        if settings.ALERT_GROUP_CHAT_ID and settings.ALERT_GROUP_CHAT_ID.strip():
            try:
                chat_id = int(settings.ALERT_GROUP_CHAT_ID.strip())
                await bot.send_message(chat_id, text, parse_mode="HTML")
                return
            except Exception as e:
                logger.warning(f"[GroupAlert] Failed to send to alert group {settings.ALERT_GROUP_CHAT_ID}: {e}")

        # Fallback to admin DM if no group chat ID set
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

    clean_ref = "".join(c for c in ref_phone if c.isdigit())
    if not clean_ref:
        return set()

    async with async_session_factory() as db:
        all_accs = (await db.execute(select(TelegramAccount))).scalars().all()
        acc = None
        for a in all_accs:
            acc_digits = "".join(c for c in a.phone_number if c.isdigit())
            if acc_digits and (clean_ref in acc_digits or acc_digits in clean_ref):
                acc = a
                break

    if not acc:
        logger.warning(f"[GroupAlert] Reference account '{ref_phone}' (digits: {clean_ref}) not found in DB.")
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
    After an account broadcasts:
    1. Fetch its joined groups.
    2. For any group NOT in DiscoveredGroup DB AND NOT joined by reference account:
       - Instantly alert to private group.
       - Mark as notified in DB so it NEVER alerts again for this group.
    """
    ref_phone = settings.REFERENCE_ACCOUNT_PHONE.strip()
    if not ref_phone:
        return  # Feature disabled — no reference account configured

    # Skip if discovering account IS the reference account itself
    clean_disc = "".join(c for c in discovering_phone if c.isdigit())
    clean_ref = "".join(c for c in ref_phone if c.isdigit())
    if clean_disc and clean_ref and (clean_disc in clean_ref or clean_ref in clean_disc):
        return


    try:
        groups = await mtproto_service.fetch_joined_groups(session_str)
        if not groups:
            return

        ref_group_ids = await _get_reference_group_ids()

        async with async_session_factory() as db:
            for entity, title in groups:
                try:
                    group_id = entity.id
                except Exception:
                    continue

                # 1. Check if already alerted/discovered in DB
                existing = (await db.execute(
                    select(DiscoveredGroup).where(DiscoveredGroup.group_id == group_id)
                )).scalars().first()

                if existing:
                    continue  # Already notified once — NEVER repeat alert for this group!

                # 2. Check if reference account is already in this group
                if group_id in ref_group_ids:
                    # Save to DB so we don't re-check, but don't notify
                    new_group = DiscoveredGroup(
                        group_id=group_id,
                        group_title=title,
                        discovered_by_phone=discovering_phone,
                        notified=True
                    )
                    db.add(new_group)
                    await db.commit()
                    continue

                # 3. NEW UNJOINED GROUP DETECTED! Save to DB & Send alert IMMEDIATELY!
                new_group = DiscoveredGroup(
                    group_id=group_id,
                    group_title=title,
                    discovered_by_phone=discovering_phone,
                    notified=True
                )
                db.add(new_group)
                await db.commit()

                username = getattr(entity, 'username', None)
                if username:
                    group_link = f"https://t.me/{username}"
                else:
                    group_link = f"(Private Group ID: <code>{group_id}</code>)"

                alert_text = (
                    f"🔔 <b>New Group Discovered!</b>\n\n"
                    f"<b>Group:</b> {title}\n"
                    f"<b>Link:</b> {group_link}\n"
                    f"<b>Discovered by:</b> <code>{discovering_phone}</code>\n\n"
                    f"⚠️ Reference account <code>{ref_phone}</code> is <b>NOT</b> in this group.\n"
                    f"Join this group so your reference account can broadcast here too! 🚀"
                )
                await _notify_alert(alert_text)
                logger.info(f"[GroupAlert] Immediately alerted new group '{title}' (ID={group_id})")

    except Exception as e:
        logger.error(f"[GroupAlert] check_and_alert_new_groups failed for {discovering_phone}: {e}")
