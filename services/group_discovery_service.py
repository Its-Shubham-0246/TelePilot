import logging
from typing import Set, Tuple, Optional, List, Dict
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
                username = getattr(entity, 'username', None)
                can_write = mtproto_service.check_group_write_permission(entity)

                new_group = DiscoveredGroup(
                    group_id=group_id,
                    group_title=title,
                    discovered_by_phone=discovering_phone,
                    username=username,
                    can_send_msgs=can_write,
                    notified=True
                )
                db.add(new_group)
                await db.commit()

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

                # Auto-join any accounts that have auto_join_enabled == True into this newly found group if writable!
                if can_write and (username or group_link):
                    target_link = username or group_link
                    enabled_accs = (await db.execute(
                        select(TelegramAccount).where(
                            TelegramAccount.is_active == True,
                            TelegramAccount.auto_join_enabled == True,
                            TelegramAccount.status.in_(["ACTIVE", "FLOOD_WAIT"])
                        )
                    )).scalars().all()

                    for auto_acc in enabled_accs:
                        if auto_acc.phone_number == discovering_phone:
                            continue
                        try:
                            acc_session = auto_acc.get_session_string()
                            if acc_session:
                                await mtproto_service.join_chat_or_channel(acc_session, target_link, auto_acc.phone_number)
                                logger.info(f"[AutoJoin] Auto-joined account {auto_acc.phone_number} to new group '{title}'")
                        except Exception as join_err:
                            logger.warning(f"[AutoJoin] Failed auto-joining {auto_acc.phone_number} to '{title}': {join_err}")

    except Exception as e:
        logger.error(f"[GroupAlert] check_and_alert_new_groups failed for {discovering_phone}: {e}")


async def scan_all_accounts_for_groups() -> dict:
    """
    Scans all active Telegram accounts in DB and collects all detected groups where message sending is permitted.
    Saves/updates discovered groups in DB with username, invite links, and permission flags.
    Returns dict mapping group_id -> group details dict.
    """
    detected_groups = {}

    async with async_session_factory() as db:
        all_accs = (await db.execute(
            select(TelegramAccount).where(
                TelegramAccount.is_active == True,
                TelegramAccount.status.in_(["ACTIVE", "FLOOD_WAIT"])
            )
        )).scalars().all()

        if not all_accs:
            return {}

        for acc in all_accs:
            try:
                session_str = acc.get_session_string()
                if not session_str:
                    continue

                groups = await mtproto_service.fetch_joined_groups(session_str, phone_number=acc.phone_number)
                for entity, title in groups:
                    try:
                        g_id = entity.id
                    except Exception:
                        continue

                    can_write = mtproto_service.check_group_write_permission(entity)
                    username = getattr(entity, 'username', None)

                    if g_id not in detected_groups:
                        detected_groups[g_id] = {
                            "group_id": g_id,
                            "title": title,
                            "username": username,
                            "invite_link": f"https://t.me/{username}" if username else None,
                            "can_send_msgs": can_write,
                            "discovered_by": acc.phone_number
                        }

                    # Sync DB record
                    existing = (await db.execute(
                        select(DiscoveredGroup).where(DiscoveredGroup.group_id == g_id)
                    )).scalars().first()

                    if not existing:
                        dg = DiscoveredGroup(
                            group_id=g_id,
                            group_title=title,
                            discovered_by_phone=acc.phone_number,
                            username=username,
                            invite_link=f"https://t.me/{username}" if username else None,
                            can_send_msgs=can_write,
                            notified=False
                        )
                        db.add(dg)
                    else:
                        if username and not existing.username:
                            existing.username = username
                            existing.invite_link = f"https://t.me/{username}"
                        existing.can_send_msgs = can_write

            except Exception as e:
                logger.warning(f"[GroupScan] Failed scanning groups for {acc.phone_number}: {e}")

        await db.commit()

    return detected_groups


async def auto_join_account_to_groups(acc: TelegramAccount, target_groups: dict) -> Tuple[int, int, int, list]:
    """
    Joins a single Telegram account to all provided target groups (if not already joined and if writable).
    Returns (joined_count, already_joined_count, failed_count, log_lines).
    """
    import asyncio
    import random

    session_str = acc.get_session_string()
    if not session_str:
        return 0, 0, 0, [f"❌ Acc {acc.phone_number}: Could not decrypt session string."]

    # Fetch currently joined group IDs for this target account to avoid unnecessary join attempts
    joined_dialogs = await mtproto_service.fetch_joined_groups(session_str, phone_number=acc.phone_number)
    joined_ids = {entity.id for entity, title in joined_dialogs}

    joined_count = 0
    already_joined_count = 0
    failed_count = 0
    logs = []

    for g_id, g_info in target_groups.items():
        title = g_info["title"]
        username = g_info.get("username")
        invite_link = g_info.get("invite_link")
        can_write = g_info.get("can_send_msgs", True)

        if not can_write:
            continue  # Skip read-only or restricted groups

        if g_id in joined_ids:
            already_joined_count += 1
            continue

        target_identifier = username or invite_link
        if not target_identifier:
            logs.append(f"⚠️ Skip '{title}' (ID: {g_id}): Private group without public link/username.")
            failed_count += 1
            continue

        # Human-like join jitter delay: 2.5s - 4.5s
        await asyncio.sleep(random.uniform(2.5, 4.5))

        success, msg, flood_sec = await mtproto_service.join_chat_or_channel(session_str, target_identifier, acc.phone_number)

        if success:
            joined_count += 1
            joined_ids.add(g_id)
            logs.append(f"✅ Joined '{title}' (target: {target_identifier})")
        else:
            failed_count += 1
            logs.append(f"❌ Failed '{title}': {msg}")
            if flood_sec:
                logs.append(f"🛑 Account {acc.phone_number} hit FloodWait ({flood_sec}s) — stopping auto-join batch.")
                break

    return joined_count, already_joined_count, failed_count, logs


async def auto_join_single_account_to_all_groups(target_input: str) -> str:
    """
    Scans all groups across all added accounts in TelePilot, then joins the specified account to all of them.
    Returns formatted result report for admin.
    """
    clean_target = target_input.strip().lstrip("@")

    async with async_session_factory() as db:
        all_accs = (await db.execute(select(TelegramAccount))).scalars().all()
        acc = None
        for a in all_accs:
            acc_digits = "".join(c for c in a.phone_number if c.isdigit())
            if acc_digits and (clean_target in acc_digits or acc_digits in clean_target):
                acc = a
                break

    if not acc:
        return f"❌ Target account '<code>{target_input}</code>' not found in database."

    target_groups = await scan_all_accounts_for_groups()
    if not target_groups:
        return "⚠️ No groups detected across any added accounts in the system."

    writable_groups = {gid: info for gid, info in target_groups.items() if info.get("can_send_msgs", True)}

    joined, already, failed, logs = await auto_join_account_to_groups(acc, writable_groups)

    report = (
        f"🚀 <b>Auto-Join Group Sync Report for <code>{acc.phone_number}</code>:</b>\n\n"
        f"• <b>Total Detected Writable Groups:</b> {len(writable_groups)}\n"
        f"• <b>Newly Joined Groups:</b> {joined}\n"
        f"• <b>Already Joined:</b> {already}\n"
        f"• <b>Failed / Skipped:</b> {failed}\n\n"
        f"<b>Activity Log:</b>\n" + "\n".join(logs[:25])
    )
    if len(logs) > 25:
        report += f"\n<i>...and {len(logs) - 25} more items.</i>"

    return report


async def auto_join_all_enabled_accounts_to_all_groups() -> str:
    """
    Scans all groups across all added accounts in TelePilot, then auto-joins ALL accounts that have auto_join_enabled == True.
    Returns formatted summary report for admin.
    """
    async with async_session_factory() as db:
        enabled_accs = (await db.execute(
            select(TelegramAccount).where(
                TelegramAccount.is_active == True,
                TelegramAccount.auto_join_enabled == True,
                TelegramAccount.status.in_(["ACTIVE", "FLOOD_WAIT"])
            )
        )).scalars().all()

    if not enabled_accs:
        return "⚠️ <b>No accounts have auto-join enabled!</b> Use <code>/autojoin &lt;phone&gt; on</code> to enable auto-join for an account first."

    target_groups = await scan_all_accounts_for_groups()
    if not target_groups:
        return "⚠️ No groups detected across any added accounts in the system."

    writable_groups = {gid: info for gid, info in target_groups.items() if info.get("can_send_msgs", True)}

    acc_reports = []
    total_new_joins = 0

    for acc in enabled_accs:
        joined, already, failed, logs = await auto_join_account_to_groups(acc, writable_groups)
        total_new_joins += joined
        acc_reports.append(
            f"📱 <b>Account <code>{acc.phone_number}</code>:</b>\n"
            f"  └ Joined: <b>{joined}</b> | Already In: <b>{already}</b> | Failed: <b>{failed}</b>"
        )

    summary = (
        f"🌐 <b>Global Auto-Join Scan & Join Completed!</b>\n\n"
        f"• <b>Auto-Join Enabled Accounts:</b> {len(enabled_accs)}\n"
        f"• <b>Total Detected Writable Groups:</b> {len(writable_groups)}\n"
        f"• <b>Total New Group Joins:</b> {total_new_joins}\n\n"
        f"<b>Account Breakdown:</b>\n" + "\n\n".join(acc_reports)
    )

    return summary
