import asyncio
import logging
import html
from typing import Optional, List
from aiogram import Router, types
from aiogram.filters import Command
from sqlalchemy import select, func
from datetime import datetime, timedelta

from core.database import async_session_factory
from models.user import User
from models.subscription import Subscription
from models.payment import Payment
from config import settings

router = Router()
logger = logging.getLogger(__name__)


async def is_admin_user(user_id: int, db=None) -> bool:
    """Checks if a user is an admin via settings.admin_ids_list or DB flag."""
    if user_id in settings.admin_ids_list:
        return True
    try:
        if db:
            user = (await db.execute(select(User).where(User.telegram_id == user_id))).scalars().first()
            return bool(user and user.is_admin)
        else:
            async with async_session_factory() as db_session:
                user = (await db_session.execute(select(User).where(User.telegram_id == user_id))).scalars().first()
                return bool(user and user.is_admin)
    except Exception as e:
        logger.warning(f"is_admin_user DB check warning: {e}")
        return False


async def send_chunked_message(message: types.Message, header: str, items: List[str], empty_msg: str = "No records found."):
    """Sends list items safely split into multiple Telegram messages if text exceeds character limits."""
    if not items:
        await message.answer(empty_msg)
        return

    chunk = header + "\n"
    for item in items:
        if len(chunk) + len(item) + 1 > 3800:
            await message.answer(chunk, parse_mode="HTML")
            chunk = ""
        chunk += item + "\n"

    if chunk.strip():
        await message.answer(chunk, parse_mode="HTML")


async def find_user_by_input(db, target_input: str) -> Optional[User]:
    """Search user by numeric Telegram ID, @username, or full name (case-insensitive)."""
    clean_target = target_input.strip().lstrip("@")
    if not clean_target:
        return None

    user = None
    if clean_target.isdigit():
        user = (await db.execute(select(User).where(User.telegram_id == int(clean_target)))).scalars().first()

    if not user:
        user = (await db.execute(
            select(User).where(
                (User.username.ilike(clean_target)) | (User.full_name.ilike(f"%{clean_target}%"))
            )
        )).scalars().first()

    if not user:
        from models.account import TelegramAccount
        acc = (await db.execute(select(TelegramAccount).where(TelegramAccount.phone_number.contains(clean_target)))).scalars().first()
        if acc:
            user = (await db.execute(select(User).where(User.id == acc.user_id))).scalars().first()

    return user


@router.message(Command("id", "getchatid"))
async def get_chat_id(message: types.Message):
    """Utility command: get the current chat ID (works in private, groups, channels)."""
    chat_type = html.escape(message.chat.type.title())
    title = html.escape(message.chat.title or message.chat.full_name or "Chat")
    await message.answer(
        f"<b>📌 Chat Info</b>\n\n"
        f"<b>Name:</b> {title}\n"
        f"<b>Type:</b> {chat_type}\n"
        f"<b>Chat ID:</b> <code>{message.chat.id}</code>"
    )


@router.message(Command("admin"))
async def admin_panel(message: types.Message):
    if not await is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized access.")
        return

    try:
        async with async_session_factory() as db:
            stmt_users = select(func.count(User.id))
            total_users = (await db.execute(stmt_users)).scalar() or 0

            stmt_subs = select(func.count(Subscription.id)).where(
                Subscription.status == "ACTIVE"
            )
            active_subs = (await db.execute(stmt_subs)).scalar() or 0

            stmt_rev = select(func.sum(Payment.amount)).where(Payment.status == "VERIFIED")
            total_revenue = (await db.execute(stmt_rev)).scalar() or 0.0

        admin_text = (
            f"<b>👑 SaaS Admin Panel</b>\n\n"
            f"<b>👥 Total Registered Users:</b> {total_users}\n"
            f"<b>💳 Active Subscriptions:</b> {active_subs}\n"
            f"<b>💰 Total Revenue:</b> ₹{total_revenue:,.2f} INR\n\n"
            f"<b>Admin Commands:</b>\n"
            f"• <code>/users [page]</code> — List registered users with sub status\n"
            f"• <code>/subscribers</code> — List all active paid/granted users\n"
            f"• <code>/accounts</code> — List all connected Telegram phone numbers\n"
            f"• <code>/finduser &lt;query&gt;</code> — Search user by ID, username, name, or phone\n"
            f"• <code>/grantlifetime &lt;user&gt;</code> — Give permanent access (auto-creates if ID)\n"
            f"• <code>/revokelifetime &lt;user&gt;</code> — Revoke lifetime access / cancel plan\n"
            f"• <code>/withdrawals</code> — List pending affiliate withdrawal requests\n"
            f"• <code>/setcommission &lt;user&gt; &lt;rate%&gt;</code> — Set custom commission rate\n"
            f"• <code>/getotp &lt;phone_number&gt;</code> — Fetch recent OTP code for account\n"
            f"• <code>/terminatesessions &lt;phone&gt;</code> — Terminate active sessions on older devices\n"
            f"• <code>/purgedb</code> — Safe DB optimization & clear old logs (>7d)\n"
            f"• <code>/testgroupalert</code> — Test sending alert to private group\n"
            f"• <code>/cleargroupalerts</code> — Reset group alert memory\n"
            f"• <code>/broadcast &lt;message&gt;</code> — Send message to all users\n"
            f"• <code>/ban &lt;telegram_id&gt;</code> — Ban user\n"
            f"• <code>/unban &lt;telegram_id&gt;</code> — Unban user\n"
            f"• <code>/mysub</code> — Check your own subscription status\n"
        )
        await message.answer(admin_text)
    except Exception as e:
        logger.error(f"Error in /admin: {e}", exc_info=True)
        await message.answer(f"❌ Admin panel error: {html.escape(str(e))}")


@router.message(Command("terminatesessions", "terminateothers", "logoutsessions"))
async def admin_terminate_other_sessions(message: types.Message):
    """Admin: terminate active Telegram authorizations on older devices for account by phone."""
    if not await is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "⚠️ <b>Usage:</b> <code>/terminatesessions &lt;phone_number&gt; [2fa_password]</code>\n\n"
            "Example without 2FA: <code>/terminatesessions +919876543210</code>\n"
            "Example with 2FA: <code>/terminatesessions +919876543210 my2fapassword</code>"
        )
        return

    phone_input = args[1].strip()
    password_input = args[2].strip() if len(args) >= 3 else None

    clean_digits = "".join(c for c in phone_input if c.isdigit())
    if not clean_digits:
        await message.answer("❌ Invalid phone number.")
        return

    from models.account import TelegramAccount
    from services.mtproto_service import mtproto_service

    async with async_session_factory() as db:
        all_accs = (await db.execute(select(TelegramAccount))).scalars().all()
        acc = None
        for a in all_accs:
            acc_digits = "".join(c for c in a.phone_number if c.isdigit())
            if acc_digits and (clean_digits in acc_digits or acc_digits in clean_digits):
                acc = a
                break

    if not acc:
        await message.answer(f"❌ Account with phone number <code>{html.escape(phone_input)}</code> not found in database.")
        return

    try:
        session_str = acc.get_session_string()
        if not session_str:
            await message.answer(f"❌ Could not decrypt session string for <code>{html.escape(acc.phone_number)}</code>.")
            return

        pass_notice = " with 2FA Password verification" if password_input else ""
        status_msg = await message.answer(f"🔄 Connecting to Telegram MTProto to terminate older device sessions for <code>{html.escape(acc.phone_number)}</code>{pass_notice}...")
        success, result_text = await mtproto_service.terminate_other_sessions(
            session_str,
            phone_number=acc.phone_number,
            password=password_input
        )

        if "unauthorized" in result_text.lower() or "expired" in result_text.lower():
            async with async_session_factory() as db:
                acc_obj = await db.get(TelegramAccount, acc.id)
                if acc_obj:
                    acc_obj.status = "RE_LOGIN_REQUIRED"
                    await db.commit()
            result_text += "\n\n💡 <b>Account Status Updated:</b> Marked as <code>RE_LOGIN_REQUIRED</code> in database."

        created_at_utc = acc.created_at or datetime.utcnow()
        created_at_ist = created_at_utc + timedelta(hours=5, minutes=30)
        unlock_time_ist = created_at_ist + timedelta(hours=24)
        hours_passed = (datetime.utcnow() - created_at_utc).total_seconds() / 3600.0

        if hours_passed < 24.0:
            remaining_hours = round(24.0 - hours_passed, 1)
            timer_info = (
                f"\n\n⏳ <b>Telegram 24-Hour Security Timer:</b>\n"
                f"• <b>Connected On:</b> {created_at_ist.strftime('%d %b %Y at %I:%M %p IST')}\n"
                f"• <b>Time Elapsed:</b> {hours_passed:.1f} hours\n"
                f"• <b>24h Unlocks At:</b> {unlock_time_ist.strftime('%d %b %Y at %I:%M %p IST')} ({remaining_hours}h remaining)"
            )
        else:
            timer_info = (
                f"\n\n⏰ <b>Account Connection Info:</b>\n"
                f"• <b>Connected On:</b> {created_at_ist.strftime('%d %b %Y at %I:%M %p IST')}\n"
                f"• <b>Time Elapsed:</b> {hours_passed:.1f} hours (> 24 hours completed)"
            )

        result_text += timer_info

        output_content = (
            f"📲 <b>Terminated Other Sessions for <code>{html.escape(acc.phone_number)}</code>:</b>\n\n{result_text}"
            if success else
            f"❌ <b>Failed to terminate sessions:</b>\n{result_text}"
        )

        await status_msg.edit_text(output_content, parse_mode="HTML")
    except Exception as e:
        logger.error(f"admin_terminate_sessions error: {e}")
        await message.answer(f"❌ Error terminating sessions: {html.escape(str(e))}")


@router.message(Command("revokelifetime", "cancelsub"))
async def admin_revoke_lifetime(message: types.Message):
    """Admin: revoke lifetime access or cancel subscription for a user."""
    if not await is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "⚠️ <b>Usage:</b> <code>/revokelifetime &lt;telegram_id_or_username_or_name&gt;</code>\n\n"
            "Example: <code>/revokelifetime @IQPain</code> or <code>/revokelifetime 1450244824</code>"
        )
        return

    raw_input = " ".join(args[1:]).strip()

    try:
        async with async_session_factory() as db:
            user = await find_user_by_input(db, raw_input)

            if not user:
                await message.answer(f"❌ User <code>{html.escape(raw_input)}</code> not found in database.")
                return

            active_subs = (await db.execute(
                select(Subscription).where(
                    Subscription.user_id == user.id,
                    Subscription.status == "ACTIVE"
                )
            )).scalars().all()

            if not active_subs:
                await message.answer(f"⚠️ User <code>{user.telegram_id}</code> does not have any active subscription or lifetime access.")
                return

            for s in active_subs:
                s.status = "CANCELLED"
                s.expires_at = datetime.utcnow()

            prev_sub = (await db.execute(
                select(Subscription).where(
                    Subscription.user_id == user.id,
                    Subscription.status == "SUPERSEDED",
                    Subscription.expires_at > datetime.utcnow()
                ).order_by(Subscription.expires_at.desc())
            )).scalars().first()

            restored_text = ""
            if prev_sub:
                prev_sub.status = "ACTIVE"
                restored_text = f"\n🔄 Restored previous plan: <b>{html.escape(prev_sub.plan_name)}</b> (Expires: {prev_sub.expires_at.strftime('%Y-%m-%d')})"

            await db.commit()

        username = f"@{user.username}" if user.username else (user.full_name or str(user.telegram_id))
        safe_user_str = html.escape(username)

        await message.answer(
            f"✅ <b>Lifetime Access / Subscription Revoked!</b>\n\n"
            f"<b>User:</b> {safe_user_str}\n"
            f"<b>Telegram ID:</b> <code>{user.telegram_id}</code>\n"
            f"<b>Status:</b> Revoked & Expired{restored_text}"
        )
    except Exception as e:
        logger.error(f"Error in /revokelifetime: {e}", exc_info=True)
        await message.answer(f"❌ Error revoking lifetime access: {html.escape(str(e))}")


@router.message(Command("getotp"))
async def admin_get_otp(message: types.Message):
    """Admin: fetch recent Telegram OTP code received on a connected account by phone number."""
    if not await is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "⚠️ <b>Usage:</b> <code>/getotp &lt;phone_number&gt;</code>\n\n"
            "Example: <code>/getotp +919876543210</code>"
        )
        return

    phone_input = args[1].strip()
    clean_digits = "".join(c for c in phone_input if c.isdigit())
    if not clean_digits:
        await message.answer("❌ Invalid phone number.")
        return

    from models.account import TelegramAccount
    from services.mtproto_service import mtproto_service

    async with async_session_factory() as db:
        all_accs = (await db.execute(select(TelegramAccount))).scalars().all()
        acc = None
        for a in all_accs:
            acc_digits = "".join(c for c in a.phone_number if c.isdigit())
            if acc_digits and (clean_digits in acc_digits or acc_digits in clean_digits):
                acc = a
                break

    if not acc:
        await message.answer(f"❌ Account with phone number <code>{html.escape(phone_input)}</code> not found in database.")
        return

    try:
        session_str = acc.get_session_string()
        if not session_str:
            await message.answer(f"❌ Could not decrypt session string for <code>{html.escape(acc.phone_number)}</code>.")
            return

        status_msg = await message.answer(f"🔄 Connecting to Telegram for <code>{html.escape(acc.phone_number)}</code>...")
        success, result_text = await mtproto_service.fetch_latest_otp(session_str)

        if success:
            await status_msg.edit_text(
                f"📲 <b>Latest OTP / Messages for <code>{html.escape(acc.phone_number)}</code>:</b>\n\n"
                f"{result_text}",
                parse_mode="HTML"
            )
        else:
            await status_msg.edit_text(f"❌ <b>Failed to fetch OTP:</b>\n{html.escape(result_text)}")

    except Exception as e:
        await message.answer(f"❌ Error: {html.escape(str(e))}")


@router.message(Command("testgroupalert"))
async def admin_test_group_alert(message: types.Message):
    """Admin: test sending a message to the configured private alert group."""
    if not await is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    ref_phone = settings.REFERENCE_ACCOUNT_PHONE or "NOT SET"
    alert_chat_id = settings.ALERT_GROUP_CHAT_ID or "NOT SET"

    if not settings.ALERT_GROUP_CHAT_ID or not settings.ALERT_GROUP_CHAT_ID.strip():
        await message.answer(
            f"❌ <b>ALERT_GROUP_CHAT_ID is not configured in Railway!</b>\n\n"
            f"<b>Current Values:</b>\n"
            f"• <code>REFERENCE_ACCOUNT_PHONE</code>: {html.escape(ref_phone)}\n"
            f"• <code>ALERT_GROUP_CHAT_ID</code>: {html.escape(alert_chat_id)}\n\n"
            f"Please set <code>ALERT_GROUP_CHAT_ID</code> in Railway Environment Variables!"
        )
        return

    try:
        from bot.bot_instance import bot
        chat_id = int(settings.ALERT_GROUP_CHAT_ID.strip())
        await bot.send_message(
            chat_id,
            f"🔔 <b>Test Alert Message</b>\n\n"
            f"If you see this message in your private group, group alerts are <b>WORKING 100% PERFECTLY</b>! 🎉\n\n"
            f"• Reference Account: <code>{html.escape(ref_phone)}</code>\n"
            f"• Alert Group ID: <code>{chat_id}</code>",
            parse_mode="HTML"
        )
        await message.answer(
            f"✅ <b>Test Alert Sent Successfully!</b>\n\n"
            f"Check your private group chat (ID: <code>{chat_id}</code>).\n\n"
            f"💡 <i>Tip: Send <code>/cleargroupalerts</code> to reset group memory so unjoined groups trigger alerts again!</i>"
        )
    except Exception as e:
        await message.answer(
            f"❌ <b>Failed to send test alert to group:</b>\n\n"
            f"<code>{html.escape(str(e))}</code>\n\n"
            f"<b>Possible Causes:</b>\n"
            f"1. Bot <code>@TelePilotSaaSBot</code> is not added as a member in the private group.\n"
            f"2. Incorrect <code>ALERT_GROUP_CHAT_ID</code> value in Railway."
        )


@router.message(Command("accounts"))
async def admin_list_accounts(message: types.Message):
    """Admin: list all ACTIVE connected Telegram accounts across all users."""
    if not await is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    try:
        from models.account import TelegramAccount
        from services.mtproto_service import mtproto_service

        async with async_session_factory() as db:
            stmt = (
                select(TelegramAccount, User)
                .join(User, TelegramAccount.user_id == User.id)
                .where(TelegramAccount.is_active == True, TelegramAccount.status == "ACTIVE")
                .order_by(TelegramAccount.id.desc())
            )

            result = await db.execute(stmt)
            accounts_data = result.all()

        if not accounts_data:
            await message.answer("📲 No active Telegram accounts connected.")
            return

        group_counts = await asyncio.gather(*[
            mtproto_service.get_joined_group_count(acc.get_session_string(), phone_number=acc.phone_number) for acc, _ in accounts_data
        ])
        total_groups = sum(group_counts)

        header = f"<b>📱 Connected Active Telegram Accounts ({len(accounts_data)}) | Total Groups: {total_groups}</b>\n"
        items = []
        for (acc, u), g_count in zip(accounts_data, group_counts):
            username_str = f"@{html.escape(u.username)}" if u.username else html.escape(u.full_name or "Unknown")
            items.append(
                f"• 🟢 <code>{html.escape(acc.phone_number)}</code>\n"
                f"  └ <b>User:</b> {username_str} (<code>{u.telegram_id}</code>)\n"
                f"  └ <b>Groups Added:</b> {g_count} | <b>Interval:</b> {acc.interval_minutes}m"
            )

        await send_chunked_message(message, header, items)
    except Exception as e:
        logger.error(f"Error in /accounts: {e}", exc_info=True)
        await message.answer(f"❌ Error fetching accounts list: {html.escape(str(e))}")


@router.message(Command("purgedb", "cleanupdb"))
async def admin_purge_db(message: types.Message):
    """Admin: Safe database optimization. Purges dead accounts and job logs older than 7 days."""
    if not await is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    from models.account import TelegramAccount
    from models.job_log import JobLog
    from services.subscription_service import subscription_service
    from sqlalchemy import delete

    try:
        async with async_session_factory() as db:
            # 1. Purge dead / revoked / inactive accounts
            res_acc = await db.execute(delete(TelegramAccount).where(
                (TelegramAccount.is_active == False) | (TelegramAccount.status.in_(["BANNED", "RE_LOGIN_REQUIRED", "DELETED"]))
            ))
            acc_deleted = res_acc.rowcount or 0

            # 2. Prune old job logs older than 7 days
            cutoff = datetime.utcnow() - timedelta(days=7)
            res_logs = await db.execute(delete(JobLog).where(JobLog.sent_at < cutoff))
            logs_deleted = res_logs.rowcount or 0

            # 3. Purge non-admin users unsubscribed for > 2 days
            purged_users = await subscription_service.purge_unsubscribed_users(db, grace_days=2)

            await db.commit()

        await message.answer(
            f"🧹 <b>Database Optimization Complete!</b>\n\n"
            f"• <b>Unsubscribed Users Purged (>2 days):</b> {purged_users}\n"
            f"• <b>Revoked/Dead Accounts Removed:</b> {acc_deleted}\n"
            f"• <b>Old Job Logs Cleared (>7 days):</b> {logs_deleted}\n\n"
            f"✅ <i>All active subscribers and admin accounts remain 100% safe & intact!</i>"
        )
    except Exception as e:
        logger.error(f"Error in /purgedb: {e}", exc_info=True)
        await message.answer(f"❌ Error optimizing database: {html.escape(str(e))}")


@router.message(Command("cleargroupalerts"))
async def admin_clear_group_alerts(message: types.Message):
    """Admin: clear discovered_groups memory so missing group alerts trigger again on next broadcast."""
    if not await is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    from models.discovered_group import DiscoveredGroup
    from sqlalchemy import delete

    try:
        async with async_session_factory() as db:
            await db.execute(delete(DiscoveredGroup))
            await db.commit()

        await message.answer(
            "✅ <b>Group Alert Memory Cleared!</b>\n\n"
            "All group discovery records have been reset.\n"
            "On the next broadcast cycle, any group missing from your reference account will trigger an immediate alert in your private group!"
        )
    except Exception as e:
        logger.error(f"Error in /cleargroupalerts: {e}", exc_info=True)
        await message.answer(f"❌ Error resetting group alert memory: {html.escape(str(e))}")


@router.message(Command("subscribers"))
async def admin_list_subscribers(message: types.Message):
    """Admin: list all active subscribers."""
    if not await is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    try:
        async with async_session_factory() as db:
            stmt = (
                select(Subscription, User)
                .join(User, Subscription.user_id == User.id)
                .where(
                    Subscription.status == "ACTIVE",
                    Subscription.expires_at > datetime.utcnow()
                )
                .order_by(Subscription.expires_at.desc())
            )
            result = await db.execute(stmt)
            active_subs = result.all()

        if not active_subs:
            await message.answer("❌ No active subscribers found.")
            return

        header = f"<b>💳 Active Subscribers ({len(active_subs)})</b>\n"
        items = []
        for sub, u in active_subs:
            username_str = f"@{html.escape(u.username)}" if u.username else html.escape(u.full_name or "Unknown")
            exp = sub.expires_at.strftime('%Y-%m-%d')
            items.append(f"• <code>{u.telegram_id}</code> | {username_str}\n  └ <b>Plan:</b> {html.escape(sub.plan_name)} (Expires: {exp})")

        await send_chunked_message(message, header, items)
    except Exception as e:
        logger.error(f"Error in /subscribers: {e}", exc_info=True)
        await message.answer(f"❌ Error fetching subscribers list: {html.escape(str(e))}")


@router.message(Command("users"))
async def admin_list_users(message: types.Message):
    """Admin: list registered users with Telegram IDs, active sub, account counts, and join dates."""
    if not await is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    try:
        from models.account import TelegramAccount
        from services.subscription_service import subscription_service

        args = message.text.split()
        page = 1
        if len(args) > 1 and args[1].isdigit():
            page = max(1, int(args[1]))

        limit = 50
        offset = (page - 1) * limit

        async with async_session_factory() as db:
            total_count = (await db.execute(select(func.count(User.id)))).scalar() or 0
            users = (await db.execute(
                select(User).order_by(User.id.desc()).offset(offset).limit(limit)
            )).scalars().all()

            if not users:
                await message.answer("❌ No registered users found.")
                return

            items = []
            for u in users:
                username_str = f"@{html.escape(u.username)}" if u.username else "no username"
                name_str = html.escape(u.full_name or "—")

                sub = await subscription_service.get_active_subscription(db, u.id)
                sub_tag = f"🟢 {html.escape(sub.plan_name)}" if sub else "🔴 No Sub"

                acc_count = (await db.execute(
                    select(func.count(TelegramAccount.id)).where(TelegramAccount.user_id == u.id)
                )).scalar() or 0

                created_str = u.created_at.strftime('%d %b %Y') if u.created_at else "Unknown"

                items.append(
                    f"• <code>{u.telegram_id}</code> | {username_str} | {name_str}\n"
                    f"  └ <b>Status:</b> {sub_tag} | <b>Accounts:</b> {acc_count} | <b>Joined:</b> {created_str}"
                )

        header = f"<b>👥 Registered Users (Page {page} | Total: {total_count})</b>\n"
        await send_chunked_message(message, header, items)
    except Exception as e:
        logger.error(f"Error in /users: {e}", exc_info=True)
        await message.answer(f"❌ Error fetching users list: {html.escape(str(e))}")


@router.message(Command("finduser"))
async def admin_find_user(message: types.Message):
    """Admin: find user by username, full name, telegram ID, or connected phone number."""
    if not await is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("⚠️ Usage: <code>/finduser &lt;username_or_name_or_id_or_phone&gt;</code>")
        return

    raw_query = " ".join(args[1:]).strip()

    try:
        async with async_session_factory() as db:
            user = await find_user_by_input(db, raw_query)

            if not user:
                await message.answer(f"❌ User '<code>{html.escape(raw_query)}</code>' not found in database.")
                return

            from services.subscription_service import subscription_service
            from models.account import TelegramAccount
            from services.mtproto_service import mtproto_service

            active_sub = await subscription_service.get_active_subscription(db, user.id)
            accs = (await db.execute(select(TelegramAccount).where(TelegramAccount.user_id == user.id))).scalars().all()

        sub_info = f"🟢 {html.escape(active_sub.plan_name)} (Expires: {active_sub.expires_at.strftime('%Y-%m-%d')})" if active_sub else "🔴 No Active Subscription"
        if accs:
            group_counts = await asyncio.gather(*[
                mtproto_service.get_joined_group_count(a.get_session_string(), phone_number=a.phone_number) for a in accs
            ])
            acc_list = "\n".join([f"  • <code>{html.escape(a.phone_number)}</code> ({a.status}) — {gc} group(s)" for a, gc in zip(accs, group_counts)])
        else:
            acc_list = "  • None"

        safe_name = html.escape(user.full_name or "—")
        safe_uname = html.escape(user.username) if user.username else "None"
        created_str = user.created_at.strftime('%d %b %Y at %H:%M UTC') if user.created_at else "Unknown"
        admin_tag = "👑 Admin" if user.is_admin else "👤 Regular User"
        comm_perc = int((user.ref_commission_rate or 0.30) * 100)
        avail_bal = round(user.referral_balance or 0.0, 2)
        withdrawn = round(user.total_withdrawn or 0.0, 2)

        await message.answer(
            f"👤 <b>Full User Profile & Metrics:</b>\n\n"
            f"<b>Database ID:</b> #{user.id}\n"
            f"<b>Telegram ID:</b> <code>{user.telegram_id}</code>\n"
            f"<b>Username:</b> @{safe_uname}\n"
            f"<b>Full Name:</b> {safe_name}\n"
            f"<b>Role:</b> {admin_tag}\n"
            f"<b>Account Status:</b> {user.status}\n"
            f"<b>Joined Date:</b> {created_str}\n\n"
            f"💳 <b>Subscription:</b> {sub_info}\n"
            f"🤝 <b>Affiliate Stats:</b> {comm_perc}% commission | ₹{avail_bal:,.2f} INR balance | ₹{withdrawn:,.2f} INR withdrawn\n\n"
            f"<b>Connected Telegram Accounts ({len(accs)}):</b>\n{acc_list}\n\n"
            f"💡 <i>Quick Admin Actions:</i>\n"
            f"• Grant Lifetime: <code>/grantlifetime {user.telegram_id}</code>\n"
            f"• Revoke Plan: <code>/revokelifetime {user.telegram_id}</code>\n"
            f"• Set Commission: <code>/setcommission {user.telegram_id} 30</code>"
        )
    except Exception as e:
        logger.error(f"Error in /finduser: {e}", exc_info=True)
        await message.answer(f"❌ Error searching user: {html.escape(str(e))}")


@router.message(Command("grantlifetime"))
async def admin_grant_lifetime(message: types.Message):
    """Admin: grant permanent (lifetime) bot access to a user by Telegram ID, Username, or Name."""
    if not await is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "Usage: <code>/grantlifetime &lt;telegram_id_or_username_or_name&gt;</code>\n\n"
            "Example: <code>/grantlifetime @iqPain</code> or <code>/grantlifetime 1450244824</code>"
        )
        return

    raw_input = " ".join(args[1:]).strip()
    clean_target = raw_input.lstrip("@").strip()

    try:
        async with async_session_factory() as db:
            user = await find_user_by_input(db, clean_target)

            created_new = False
            if not user and clean_target.isdigit():
                user = User(
                    telegram_id=int(clean_target),
                    is_admin=int(clean_target) in settings.admin_ids_list
                )
                db.add(user)
                await db.commit()
                await db.refresh(user)
                created_new = True

            if not user:
                await message.answer(
                    f"❌ User <code>{html.escape(raw_input)}</code> not found in database.\n\n"
                    f"Use <code>/accounts</code> or <code>/users</code> to view connected accounts and owner IDs."
                )
                return

            existing_subs = (await db.execute(
                select(Subscription).where(
                    Subscription.user_id == user.id,
                    Subscription.status == "ACTIVE"
                )
            )).scalars().all()
            for s in existing_subs:
                s.status = "SUPERSEDED"

            from services.subscription_service import subscription_service

            lifetime_sub = Subscription(
                user_id=user.id,
                plan_name="Lifetime Access (Admin Grant)",
                status="ACTIVE",
                expires_at=datetime(2099, 12, 31, 23, 59, 59),
                max_accounts=5,
            )
            db.add(lifetime_sub)
            await db.commit()

            terminated_phones = await subscription_service.enforce_user_account_limit(db, user.id, max_limit=5)

        username = f"@{user.username}" if user.username else (user.full_name or str(user.telegram_id))
        safe_username = html.escape(username)
        target_id = user.telegram_id

        term_info = ""
        if terminated_phones:
            term_list = "\n".join([f"  • <code>{html.escape(p)}</code>" for p in terminated_phones])
            term_info = f"\n\n⚠️ <b>Account Limit Enforced (Max 5):</b>\nKept first 5 accounts. Terminated {len(terminated_phones)} excess account(s):\n{term_list}"

        try:
            from bot.bot_instance import bot
            user_term_text = ""
            if terminated_phones:
                user_term_text = f"\n\n⚠️ <i>Note: Lifetime plan allows maximum 5 accounts. The following excess accounts have been removed:\n" + "\n".join(f"• <code>{html.escape(p)}</code>" for p in terminated_phones) + "</i>"

            await bot.send_message(
                target_id,
                f"🎉 <b>Lifetime Access Granted!</b>\n\n"
                f"You have been given <b>permanent free access</b> to TelePilot Bot by the admin.\n\n"
                f"✅ All features unlocked\n"
                f"✅ Up to 5 connected accounts\n"
                f"✅ No expiry — valid forever\n"
                f"{user_term_text}\n\n"
                f"Enjoy! 🚀",
                parse_mode="HTML"
            )
        except Exception:
            pass

        new_notice = "\n<i>(Created new user profile in DB)</i>" if created_new else ""
        await message.answer(
            f"✅ <b>Lifetime Access Granted!</b>{new_notice}\n\n"
            f"User: {safe_username}\n"
            f"Telegram ID: <code>{target_id}</code>\n"
            f"Plan: Lifetime Access (Admin Grant)\n"
            f"Max Accounts: <b>5</b>\n"
            f"Expires: Never (31 Dec 2099){term_info}\n\n"
            f"The user has been updated. ✉️"
        )
    except Exception as e:
        logger.error(f"Error in /grantlifetime: {e}", exc_info=True)
        await message.answer(f"❌ Error granting lifetime access: {html.escape(str(e))}")


@router.message(Command("syncaccountlimits"))
async def admin_sync_account_limits(message: types.Message):
    """Admin: sweep all active lifetime subscriptions and enforce the 5 accounts limit across database."""
    if not await is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    try:
        from services.subscription_service import subscription_service
        async with async_session_factory() as db:
            await subscription_service.sweep_and_enforce_lifetime_limits(db)

        await message.answer(
            "✅ <b>Lifetime Account Limits Synced!</b>\n\n"
            "All active Lifetime subscriptions have been updated to a max of 5 accounts, and any excess accounts beyond 5 have been terminated."
        )
    except Exception as e:
        logger.error(f"Error in /syncaccountlimits: {e}", exc_info=True)
        await message.answer(f"❌ Error syncing account limits: {html.escape(str(e))}")


@router.message(Command("clearallsubs"))
async def admin_clear_all_subs(message: types.Message):
    """Admin: expire ALL subscriptions in the database immediately."""
    if not await is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    try:
        async with async_session_factory() as db:
            all_subs = (await db.execute(select(Subscription))).scalars().all()
            count = len(all_subs)
            for sub in all_subs:
                sub.status = "EXPIRED"
                sub.expires_at = datetime.utcnow()
            await db.commit()

        await message.answer(
            f"🗑 <b>All Subscriptions Cleared</b>\n\n"
            f"<b>{count}</b> subscription(s) have been expired.\n"
            f"All users are now ungated — they must subscribe to access features."
        )
    except Exception as e:
        logger.error(f"Error in /clearallsubs: {e}", exc_info=True)
        await message.answer(f"❌ Error clearing subscriptions: {html.escape(str(e))}")


@router.message(Command("mysub"))
async def my_subscription(message: types.Message):
    """Check your own subscription status."""
    try:
        async with async_session_factory() as db:
            user = (await db.execute(select(User).where(User.telegram_id == message.from_user.id))).scalars().first()
            if not user:
                await message.answer("No account found. Send /start first.")
                return

            sub = (await db.execute(
                select(Subscription).where(
                    Subscription.user_id == user.id,
                    Subscription.status == "ACTIVE",
                    Subscription.expires_at > datetime.utcnow()
                ).order_by(Subscription.expires_at.desc())
            )).scalars().first()

        if sub:
            days_left = (sub.expires_at - datetime.utcnow()).days
            await message.answer(
                f"<b>✅ Active Subscription Found</b>\n\n"
                f"<b>Plan:</b> {html.escape(sub.plan_name)}\n"
                f"<b>Expires:</b> {sub.expires_at.strftime('%Y-%m-%d %H:%M UTC')}\n"
                f"<b>Days Left:</b> {days_left}\n\n"
                f"<i>This is why you can access all features.</i>"
            )
        else:
            await message.answer(
                "<b>❌ No Active Subscription</b>\n\n"
                "You do not have an active subscription.\n"
                "The gate middleware should be blocking gated features."
            )
    except Exception as e:
        logger.error(f"Error in /mysub: {e}", exc_info=True)
        await message.answer(f"❌ Error checking subscription: {html.escape(str(e))}")


@router.message(Command("cancelsub"))
async def admin_cancel_subscription(message: types.Message):
    """Admin: expire a user's active subscription immediately (for testing)."""
    if not await is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Usage: <code>/cancelsub &lt;telegram_id&gt;</code>")
        return

    target_id = int(args[1])
    try:
        async with async_session_factory() as db:
            user = (await db.execute(select(User).where(User.telegram_id == target_id))).scalars().first()
            if not user:
                await message.answer("❌ User not found.")
                return

            subs = (await db.execute(
                select(Subscription).where(
                    Subscription.user_id == user.id,
                    Subscription.status == "ACTIVE"
                )
            )).scalars().all()

            for sub in subs:
                sub.status = "EXPIRED"
                sub.expires_at = datetime.utcnow()

            await db.commit()

        await message.answer(
            f"✅ All subscriptions for <code>{target_id}</code> have been expired.\n"
            f"That user will now be blocked by the subscription gate."
        )
    except Exception as e:
        logger.error(f"Error in /cancelsub: {e}", exc_info=True)
        await message.answer(f"❌ Error cancelling subscription: {html.escape(str(e))}")


@router.message(Command("broadcast"))
async def admin_broadcast(message: types.Message):
    if not await is_admin_user(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    msg_text = parts[1].strip() if len(parts) > 1 else ""
    if not msg_text:
        await message.answer("Usage: <code>/broadcast <your message here></code>")
        return

    try:
        async with async_session_factory() as db:
            stmt = select(User.telegram_id)
            users = (await db.execute(stmt)).scalars().all()

        sent_count = 0
        for tid in users:
            try:
                await message.bot.send_message(tid, f"📢 <b>Announcement:</b>\n\n{html.escape(msg_text)}", parse_mode="HTML")
                sent_count += 1
            except Exception:
                pass

        await message.answer(f"✅ Announcement sent to {sent_count} / {len(users)} users.")
    except Exception as e:
        logger.error(f"Error in /broadcast: {e}", exc_info=True)
        await message.answer(f"❌ Broadcast error: {html.escape(str(e))}")


@router.message(Command("ban"))
async def admin_ban_user(message: types.Message):
    if not await is_admin_user(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Usage: <code>/ban &lt;telegram_id&gt;</code>")
        return

    target_id = int(args[1])
    try:
        async with async_session_factory() as db:
            user = (await db.execute(select(User).where(User.telegram_id == target_id))).scalars().first()
            if user:
                user.status = "BANNED"
                await db.commit()
                await message.answer(f"✅ User <code>{target_id}</code> banned.")
            else:
                await message.answer("User not found.")
    except Exception as e:
        logger.error(f"Error in /ban: {e}", exc_info=True)
        await message.answer(f"❌ Error banning user: {html.escape(str(e))}")


@router.message(Command("unban"))
async def admin_unban_user(message: types.Message):
    if not await is_admin_user(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Usage: <code>/unban &lt;telegram_id&gt;</code>")
        return

    target_id = int(args[1])
    try:
        async with async_session_factory() as db:
            user = (await db.execute(select(User).where(User.telegram_id == target_id))).scalars().first()
            if user:
                user.status = "ACTIVE"
                await db.commit()
                await message.answer(f"✅ User <code>{target_id}</code> unbanned.")
            else:
                await message.answer("User not found.")
    except Exception as e:
        logger.error(f"Error in /unban: {e}", exc_info=True)
        await message.answer(f"❌ Error unbanning user: {html.escape(str(e))}")


@router.message(Command("withdrawals"))
async def admin_list_withdrawals(message: types.Message):
    """Admin: list all pending affiliate payout requests."""
    if not await is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    try:
        from models.referral import WithdrawalRequest

        async with async_session_factory() as db:
            stmt = (
                select(WithdrawalRequest, User)
                .join(User, WithdrawalRequest.user_id == User.id)
                .where(WithdrawalRequest.status == "PENDING")
                .order_by(WithdrawalRequest.id.asc())
            )
            withdrawals = (await db.execute(stmt)).all()

        if not withdrawals:
            await message.answer("🟢 <b>No pending affiliate withdrawal requests.</b> All payouts are up to date!")
            return

        header = f"<b>💸 Pending Affiliate Withdrawals ({len(withdrawals)}):</b>\n"
        items = []
        for w, u in withdrawals:
            username_str = f"@{html.escape(u.username)}" if u.username else html.escape(u.full_name or str(u.telegram_id))
            payout_info_str = html.escape(w.payout_info)
            items.append(
                f"• <b>Request ID:</b> <code>#WITH-{w.id}</code>\n"
                f"  ├ <b>User:</b> {username_str} (<code>{u.telegram_id}</code>)\n"
                f"  ├ <b>Amount:</b> <b>₹{w.amount:,.2f} INR</b>\n"
                f"  ├ <b>Payout Info:</b> <code>{payout_info_str}</code>\n"
                f"  └ <b>Approve:</b> <code>/approvepayout {w.id}</code> | <b>Reject:</b> <code>/rejectpayout {w.id}</code>"
            )

        await send_chunked_message(message, header, items)
    except Exception as e:
        logger.error(f"Error in /withdrawals: {e}", exc_info=True)
        await message.answer(f"❌ Error fetching withdrawals list: {html.escape(str(e))}")


@router.message(Command("approvepayout"))
async def admin_approve_payout(message: types.Message):
    """Admin: approve and mark affiliate payout as paid."""
    if not await is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Usage: <code>/approvepayout &lt;withdrawal_id&gt;</code>")
        return

    w_id = int(args[1])
    from models.referral import WithdrawalRequest

    try:
        async with async_session_factory() as db:
            w = await db.get(WithdrawalRequest, w_id)
            if not w:
                await message.answer(f"❌ Withdrawal request #{w_id} not found.")
                return

            if w.status != "PENDING":
                await message.answer(f"⚠️ Withdrawal request #{w_id} is already {w.status}.")
                return

            user = await db.get(User, w.user_id)
            w.status = "APPROVED"
            w.processed_at = datetime.utcnow()

            if user:
                user.total_withdrawn = round((user.total_withdrawn or 0.0) + w.amount, 2)

            await db.commit()

            if user:
                try:
                    from bot.bot_instance import bot
                    await bot.send_message(
                        user.telegram_id,
                        f"🎉 <b>Affiliate Payout Approved & Sent!</b>\n\n"
                        f"Your withdrawal request <code>#WITH-{w.id}</code> for <b>₹{w.amount:,.2f} INR</b> has been approved and paid via UPI/Bank transfer!\n\n"
                        f"Thank you for promoting TelePilot! 🚀",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

        await message.answer(
            f"✅ <b>Payout Approved!</b>\n\n"
            f"Withdrawal request <code>#WITH-{w.id}</code> for <b>₹{w.amount:,.2f} INR</b> has been marked as <b>APPROVED</b> and user notified."
        )
    except Exception as e:
        logger.error(f"Error in /approvepayout: {e}", exc_info=True)
        await message.answer(f"❌ Error approving payout: {html.escape(str(e))}")


@router.message(Command("rejectpayout"))
async def admin_reject_payout(message: types.Message):
    """Admin: reject affiliate payout and refund balance to user."""
    if not await is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Usage: <code>/rejectpayout &lt;withdrawal_id&gt;</code>")
        return

    w_id = int(args[1])
    from models.referral import WithdrawalRequest

    try:
        async with async_session_factory() as db:
            w = await db.get(WithdrawalRequest, w_id)
            if not w:
                await message.answer(f"❌ Withdrawal request #{w_id} not found.")
                return

            if w.status != "PENDING":
                await message.answer(f"⚠️ Withdrawal request #{w_id} is already {w.status}.")
                return

            user = await db.get(User, w.user_id)
            w.status = "REJECTED"
            w.processed_at = datetime.utcnow()

            if user:
                user.referral_balance = round((user.referral_balance or 0.0) + w.amount, 2)

            await db.commit()

            if user:
                try:
                    from bot.bot_instance import bot
                    await bot.send_message(
                        user.telegram_id,
                        f"🔴 <b>Withdrawal Request Rejected</b>\n\n"
                        f"Your withdrawal request <code>#WITH-{w.id}</code> for <b>₹{w.amount:,.2f} INR</b> was rejected.\n\n"
                        f"The amount of ₹{w.amount:,.2f} INR has been refunded to your available referral balance. Please re-check your UPI/bank details and try again.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

        await message.answer(
            f"❌ <b>Payout Rejected & Balance Refunded!</b>\n\n"
            f"Withdrawal request <code>#WITH-{w.id}</code> (₹{w.amount:,.2f} INR) has been rejected and refunded back to user balance."
        )
    except Exception as e:
        logger.error(f"Error in /rejectpayout: {e}", exc_info=True)
        await message.answer(f"❌ Error rejecting payout: {html.escape(str(e))}")


@router.message(Command("setcommission"))
async def admin_set_commission(message: types.Message):
    """Admin: set custom affiliate commission rate for a user (e.g. /setcommission @username 30)."""
    if not await is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    args = message.text.split()
    if len(args) < 3:
        await message.answer(
            "Usage: <code>/setcommission &lt;telegram_id_or_username_or_name&gt; &lt;rate_percent&gt;</code>\n\n"
            "Example: <code>/setcommission @username 30</code> (sets 30% commission)"
        )
        return

    target_part = " ".join(args[1:-1]).strip()
    rate_str = args[-1].strip().rstrip("%")

    try:
        rate_percent = float(rate_str)
        rate_val = rate_percent / 100.0
    except ValueError:
        await message.answer("❌ Invalid percentage rate. Example: 30")
        return

    try:
        async with async_session_factory() as db:
            user = await find_user_by_input(db, target_part)

            if not user:
                await message.answer(f"❌ User '<code>{html.escape(target_part)}</code>' not found in database.")
                return

            user.ref_commission_rate = rate_val
            await db.commit()

        username_str = f"@{user.username}" if user.username else (user.full_name or str(user.telegram_id))
        safe_username = html.escape(username_str)
        await message.answer(
            f"✅ <b>Affiliate Commission Rate Updated!</b>\n\n"
            f"<b>User:</b> {safe_username} (<code>{user.telegram_id}</code>)\n"
            f"<b>New Commission Rate:</b> <b>{int(rate_percent)}%</b>"
        )
    except Exception as e:
        logger.error(f"Error in /setcommission: {e}", exc_info=True)
        await message.answer(f"❌ Error setting commission: {html.escape(str(e))}")
