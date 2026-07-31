import logging
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


def is_admin_user(user_id: int) -> bool:
    return user_id in settings.admin_ids_list


@router.message(Command("id", "getchatid"))
async def get_chat_id(message: types.Message):
    """Utility command: get the current chat ID (works in private, groups, channels)."""
    chat_type = message.chat.type.title()
    title = message.chat.title or message.chat.full_name or "Chat"
    await message.answer(
        f"<b>📌 Chat Info</b>\n\n"
        f"<b>Name:</b> {title}\n"
        f"<b>Type:</b> {chat_type}\n"
        f"<b>Chat ID:</b> <code>{message.chat.id}</code>"
    )


@router.message(Command("admin"))
async def admin_panel(message: types.Message):

    if not is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized access.")
        return

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
        f"• <code>/subscribers</code> — List all active paid/granted users\n"
        f"• <code>/accounts</code> — List all connected Telegram phone numbers\n"
        f"• <code>/getotp &lt;phone_number&gt;</code> — Fetch recent OTP code for account\n"
        f"• <code>/terminatesessions &lt;phone_number&gt;</code> — Terminate active sessions on older devices\n"
        f"• <code>/grantlifetime &lt;telegram_id&gt;</code> — Give permanent access (max 5 accs)\n"
        f"• <code>/revokelifetime &lt;telegram_id&gt;</code> — Revoke lifetime access / cancel plan\n"
        f"• <code>/testgroupalert</code> — Test sending alert to your private group\n"
        f"• <code>/cleargroupalerts</code> — Reset group alert memory (re-alert missing groups)\n"
        f"• <code>/users</code> — List all registered users with IDs\n"
        f"• <code>/broadcast &lt;message&gt;</code> — Send message to all users\n"
        f"• <code>/ban &lt;telegram_id&gt;</code> — Ban user\n"
        f"• <code>/unban &lt;telegram_id&gt;</code> — Unban user\n"
        f"• <code>/mysub</code> — Check your own subscription status\n"
    )

    await message.answer(admin_text)


@router.message(Command("terminatesessions", "terminateothers", "logoutsessions"))
async def admin_terminate_other_sessions(message: types.Message):
    """Admin: terminate all active Telegram authorizations on older/other devices for a connected account by phone number."""
    if not is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "⚠️ <b>Usage:</b> <code>/terminatesessions &lt;phone_number&gt;</code>\n\n"
            "Example: <code>/terminatesessions +919876543210</code>"
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
        await message.answer(f"❌ Account with phone number <code>{phone_input}</code> not found in database.")
        return

    try:
        session_str = acc.get_session_string()
        if not session_str:
            await message.answer(f"❌ Could not decrypt session string for <code>{acc.phone_number}</code>.")
            return

        status_msg = await message.answer(f"🔄 Connecting to Telegram MTProto to terminate older device sessions for <code>{acc.phone_number}</code>...")
        success, result_text = await mtproto_service.terminate_other_sessions(session_str, phone_number=acc.phone_number)

        output_content = (
            f"📲 <b>Terminated Other Sessions for <code>{acc.phone_number}</code>:</b>\n\n{result_text}"
            if success else
            f"❌ <b>Failed to terminate sessions:</b>\n{result_text}"
        )

        for retry in range(3):
            try:
                await status_msg.edit_text(output_content, parse_mode="HTML")
                break
            except Exception as net_err:
                if retry < 2 and any(k in str(net_err) for k in ("ClientConnectorError", "Connection reset", "TelegramNetworkError", "TimeoutError")):
                    await asyncio.sleep(1)
                else:
                    await status_msg.edit_text(output_content, parse_mode="HTML")
                    break

    except Exception as e:
        logger.error(f"admin_terminate_sessions error: {e}")
        await message.answer(f"❌ Network Error: Unable to communicate with Telegram API. Please try running <code>/terminatesessions {phone_input}</code> again in a few seconds.")


@router.message(Command("revokelifetime", "cancelsub"))
async def admin_revoke_lifetime(message: types.Message):
    """Admin: revoke lifetime access or cancel subscription for a user and revert to previous state."""
    if not is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "⚠️ <b>Usage:</b> <code>/revokelifetime &lt;telegram_id_or_username&gt;</code>\n\n"
            "Example: <code>/revokelifetime @IQPain</code> or <code>/revokelifetime 1450244824</code>"
        )
        return

    target_input = args[1].strip().lstrip("@")

    async with async_session_factory() as db:
        user = None
        if target_input.isdigit():
            user = (await db.execute(select(User).where(User.telegram_id == int(target_input)))).scalars().first()

        if not user:
            user = (await db.execute(
                select(User).where(
                    (User.username.ilike(target_input)) | (User.full_name.ilike(f"%{target_input}%"))
                )
            )).scalars().first()

        if not user:
            await message.answer(f"❌ User <code>{args[1]}</code> not found in database.")
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
            restored_text = f"\n🔄 Restored previous plan: <b>{prev_sub.plan_name}</b> (Expires: {prev_sub.expires_at.strftime('%Y-%m-%d')})"

        await db.commit()

    username = f"@{user.username}" if user.username else user.full_name or str(user.telegram_id)

    await message.answer(
        f"✅ <b>Lifetime Access / Subscription Revoked!</b>\n\n"
        f"<b>User:</b> {username}\n"
        f"<b>Telegram ID:</b> <code>{user.telegram_id}</code>\n"
        f"<b>Status:</b> Revoked & Expired{restored_text}"
    )



@router.message(Command("getotp"))
async def admin_get_otp(message: types.Message):
    """Admin: fetch recent Telegram OTP code received on a connected account by phone number."""
    if not is_admin_user(message.from_user.id):
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
        await message.answer(f"❌ Account with phone number <code>{phone_input}</code> not found in database.")
        return

    try:
        session_str = acc.get_session_string()
        if not session_str:
            await message.answer(f"❌ Could not decrypt session string for <code>{acc.phone_number}</code>.")
            return

        status_msg = await message.answer(f"🔄 Connecting to Telegram for <code>{acc.phone_number}</code>...")
        success, result_text = await mtproto_service.fetch_latest_otp(session_str)

        if success:
            await status_msg.edit_text(
                f"📲 <b>Latest OTP / Messages for <code>{acc.phone_number}</code>:</b>\n\n"
                f"{result_text}",
                parse_mode="HTML"
            )
        else:
            await status_msg.edit_text(f"❌ <b>Failed to fetch OTP:</b>\n{result_text}")

    except Exception as e:
        await message.answer(f"❌ Error: {e}")



@router.message(Command("testgroupalert"))
async def admin_test_group_alert(message: types.Message):
    """Admin: test sending a message to the configured private alert group."""
    if not is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    ref_phone = settings.REFERENCE_ACCOUNT_PHONE or "NOT SET"
    alert_chat_id = settings.ALERT_GROUP_CHAT_ID or "NOT SET"

    if not settings.ALERT_GROUP_CHAT_ID or not settings.ALERT_GROUP_CHAT_ID.strip():
        await message.answer(
            f"❌ <b>ALERT_GROUP_CHAT_ID is not configured in Railway!</b>\n\n"
            f"<b>Current Values:</b>\n"
            f"• <code>REFERENCE_ACCOUNT_PHONE</code>: {ref_phone}\n"
            f"• <code>ALERT_GROUP_CHAT_ID</code>: {alert_chat_id}\n\n"
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
            f"• Reference Account: <code>{ref_phone}</code>\n"
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
            f"<code>{e}</code>\n\n"
            f"<b>Possible Causes:</b>\n"
            f"1. Bot <code>@TelePilotSaaSBot</code> is not added as a member in the private group.\n"
            f"2. Incorrect <code>ALERT_GROUP_CHAT_ID</code> value in Railway."
        )



@router.message(Command("accounts"))
async def admin_list_accounts(message: types.Message):
    """Admin: list all connected Telegram accounts across all users."""
    if not is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    from models.account import TelegramAccount

    async with async_session_factory() as db:
        stmt = (
            select(TelegramAccount, User)
            .join(User, TelegramAccount.user_id == User.id)
            .order_by(TelegramAccount.id.desc())
        )
        result = await db.execute(stmt)
        accounts_data = result.all()

    if not accounts_data:
        await message.answer("📲 No Telegram accounts connected yet.")
        return

    lines = [f"<b>📱 Connected Telegram Accounts ({len(accounts_data)})</b>\n"]
    for acc, u in accounts_data:
        username = f"@{u.username}" if u.username else u.full_name or "Unknown"
        status_icon = "🟢" if acc.status == "ACTIVE" else "🔴"
        lines.append(
            f"• {status_icon} <code>{acc.phone_number}</code>\n"
            f"  └ <b>User:</b> {username} (<code>{u.telegram_id}</code>)\n"
            f"  └ <b>Status:</b> {acc.status} | <b>Interval:</b> {acc.interval_minutes}m"
        )

    await message.answer("\n".join(lines))



@router.message(Command("cleargroupalerts"))
async def admin_clear_group_alerts(message: types.Message):
    """Admin: clear discovered_groups memory so missing group alerts trigger again on next broadcast."""
    if not is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    from models.discovered_group import DiscoveredGroup
    from sqlalchemy import delete

    async with async_session_factory() as db:
        await db.execute(delete(DiscoveredGroup))
        await db.commit()

    await message.answer(
        "✅ <b>Group Alert Memory Cleared!</b>\n\n"
        "All group discovery records have been reset.\n"
        "On the next broadcast cycle, any group missing from your reference account will trigger an immediate alert in your private group!"
    )



@router.message(Command("subscribers"))
async def admin_list_subscribers(message: types.Message):
    """Admin: list all active subscribers."""
    if not is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

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

    lines = [f"<b>💳 Active Subscribers ({len(active_subs)})</b>\n"]
    for sub, u in active_subs:
        username = f"@{u.username}" if u.username else u.full_name or "Unknown"
        exp = sub.expires_at.strftime('%Y-%m-%d')
        lines.append(f"• <code>{u.telegram_id}</code> | {username}\n  └ <b>Plan:</b> {sub.plan_name} (Expires: {exp})")

    await message.answer("\n".join(lines))



@router.message(Command("users"))
async def admin_list_users(message: types.Message):
    """Admin: list all registered users with their Telegram IDs."""
    if not is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    async with async_session_factory() as db:
        users = (await db.execute(select(User).order_by(User.id.desc()).limit(50))).scalars().all()

    if not users:
        await message.answer("No users registered yet.")
        return

    lines = ["<b>👥 Registered Users (latest 50)</b>\n"]
    for u in users:
        username = f"@{u.username}" if u.username else "no username"
        name = u.full_name or "—"
        lines.append(f"• <code>{u.telegram_id}</code> | {username} | {name}")

    await message.answer("\n".join(lines))


@router.message(Command("finduser"))
async def admin_find_user(message: types.Message):
    """Admin: find user by username, full name, telegram ID, or connected phone number."""
    if not is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("⚠️ Usage: <code>/finduser &lt;username_or_name_or_id_or_phone&gt;</code>")
        return

    query = args[1].strip().lstrip("@")

    async with async_session_factory() as db:
        user = None
        if query.isdigit():
            user = (await db.execute(select(User).where(User.telegram_id == int(query)))).scalars().first()

        if not user:
            # Search by Username OR Full Name (case-insensitive)
            user = (await db.execute(
                select(User).where(
                    (User.username.ilike(query)) | (User.full_name.ilike(f"%{query}%"))
                )
            )).scalars().first()

        if not user:
            from models.account import TelegramAccount
            acc = (await db.execute(select(TelegramAccount).where(TelegramAccount.phone_number.contains(query)))).scalars().first()
            if acc:
                user = (await db.execute(select(User).where(User.id == acc.user_id))).scalars().first()

        if not user:
            await message.answer(f"❌ User '{args[1]}' not found in database.")
            return

        from services.subscription_service import subscription_service
        from models.account import TelegramAccount

        active_sub = await subscription_service.get_active_subscription(db, user.id)
        accs = (await db.execute(select(TelegramAccount).where(TelegramAccount.user_id == user.id))).scalars().all()

    sub_info = f"{active_sub.plan_name} (Expires: {active_sub.expires_at.strftime('%Y-%m-%d')})" if active_sub else "🔴 No Active Subscription"
    acc_list = "\n".join([f"  • <code>{a.phone_number}</code> ({a.status})" for a in accs]) if accs else "  • None"

    await message.answer(
        f"👤 <b>User Information:</b>\n\n"
        f"<b>Telegram ID:</b> <code>{user.telegram_id}</code>\n"
        f"<b>Username:</b> @{user.username if user.username else 'None'}\n"
        f"<b>Full Name:</b> {user.full_name or '—'}\n"
        f"<b>Subscription:</b> {sub_info}\n"
        f"<b>Connected Accounts ({len(accs)}):</b>\n{acc_list}\n\n"
        f"💡 <i>To grant lifetime access, run:</i>\n<code>/grantlifetime {user.telegram_id}</code>"
    )


@router.message(Command("grantlifetime"))
async def admin_grant_lifetime(message: types.Message):
    """Admin: grant permanent (lifetime) bot access to a user by Telegram ID, Username, or Name."""
    if not is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "Usage: <code>/grantlifetime &lt;telegram_id_or_username&gt;</code>\n\n"
            "Example: <code>/grantlifetime @iqPain</code> or <code>/grantlifetime 1450244824</code>"
        )
        return

    target_input = args[1].strip().lstrip("@")

    async with async_session_factory() as db:
        user = None
        if target_input.isdigit():
            user = (await db.execute(select(User).where(User.telegram_id == int(target_input)))).scalars().first()

        if not user:
            user = (await db.execute(
                select(User).where(
                    (User.username.ilike(target_input)) | (User.full_name.ilike(f"%{target_input}%"))
                )
            )).scalars().first()

        if not user:
            await message.answer(
                f"❌ User <code>{args[1]}</code> not found in database.\n\n"
                f"Use <code>/accounts</code> to view all connected phone numbers and their owner IDs."
            )
            return



        # Expire any existing active subscriptions first
        existing_subs = (await db.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.status == "ACTIVE"
            )
        )).scalars().all()
        for s in existing_subs:
            s.status = "SUPERSEDED"

        from services.subscription_service import subscription_service

        # Create lifetime subscription — max 5 accounts, expires year 2099
        lifetime_sub = Subscription(
            user_id=user.id,
            plan_name="Lifetime Access (Admin Grant)",
            status="ACTIVE",
            expires_at=datetime(2099, 12, 31, 23, 59, 59),
            max_accounts=5,
        )
        db.add(lifetime_sub)
        await db.commit()

        # Enforce max 5 accounts limit for lifetime user — terminate any excess accounts beyond 5
        terminated_phones = await subscription_service.enforce_user_account_limit(db, user.id, max_limit=5)

    username = f"@{user.username}" if user.username else user.full_name or str(user.telegram_id)
    target_id = user.telegram_id

    term_info = ""
    if terminated_phones:
        term_list = "\n".join([f"  • <code>{p}</code>" for p in terminated_phones])
        term_info = f"\n\n⚠️ <b>Account Limit Enforced (Max 5):</b>\nKept first 5 accounts. Terminated {len(terminated_phones)} excess account(s):\n{term_list}"

    # Notify the granted user
    try:
        user_term_text = ""
        if terminated_phones:
            user_term_text = f"\n\n⚠️ <i>Note: Lifetime plan allows maximum 5 accounts. The following excess accounts have been removed:\n" + "\n".join(f"• <code>{p}</code>" for p in terminated_phones) + "</i>"

        await message.bot.send_message(
            target_id,
            f"🎉 <b>Lifetime Access Granted!</b>\n\n"
            f"You have been given <b>permanent free access</b> to TelePilot Bot by the admin.\n\n"
            f"✅ All features unlocked\n"
            f"✅ Up to 5 connected accounts\n"
            f"✅ No expiry — valid forever\n"
            f"{user_term_text}\n\n"
            f"Enjoy! 🚀"
        )
    except Exception:
        pass  # User may have blocked the bot

    await message.answer(
        f"✅ <b>Lifetime Access Granted!</b>\n\n"
        f"User: {username}\n"
        f"Telegram ID: <code>{target_id}</code>\n"
        f"Plan: Lifetime Access (Admin Grant)\n"
        f"Max Accounts: <b>5</b>\n"
        f"Expires: Never (31 Dec 2099){term_info}\n\n"
        f"The user has been notified. ✉️"
    )


@router.message(Command("syncaccountlimits"))
async def admin_sync_account_limits(message: types.Message):
    """Admin: sweep all active lifetime subscriptions and enforce the 5 accounts limit across the entire database."""
    if not is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    from services.subscription_service import subscription_service
    async with async_session_factory() as db:
        await subscription_service.sweep_and_enforce_lifetime_limits(db)

    await message.answer(
        "✅ <b>Lifetime Account Limits Synced!</b>\n\n"
        "All active Lifetime subscriptions have been updated to a max of 5 accounts, and any excess accounts beyond 5 have been terminated."
    )




@router.message(Command("clearallsubs"))
async def admin_clear_all_subs(message: types.Message):
    """Admin: expire ALL subscriptions in the database immediately."""
    if not is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

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


@router.message(Command("mysub"))
async def my_subscription(message: types.Message):
    """Check your own subscription status."""
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
            f"<b>Plan:</b> {sub.plan_name}\n"
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


@router.message(Command("cancelsub"))
async def admin_cancel_subscription(message: types.Message):
    """Admin: expire a user's active subscription immediately (for testing)."""
    if not is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Usage: <code>/cancelsub &lt;telegram_id&gt;</code>")
        return

    target_id = int(args[1])
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


@router.message(Command("broadcast"))
async def admin_broadcast(message: types.Message):
    if not is_admin_user(message.from_user.id):
        return

    msg_text = message.text.replace("/broadcast", "").strip()
    if not msg_text:
        await message.answer("Usage: <code>/broadcast <your message here></code>")
        return

    async with async_session_factory() as db:
        stmt = select(User.telegram_id)
        users = (await db.execute(stmt)).scalars().all()

    sent_count = 0
    for tid in users:
        try:
            await message.bot.send_message(tid, f"📢 <b>Announcement:</b>\n\n{msg_text}")
            sent_count += 1
        except Exception:
            pass

    await message.answer(f"✅ Announcement sent to {sent_count} / {len(users)} users.")


@router.message(Command("ban"))
async def admin_ban_user(message: types.Message):
    if not is_admin_user(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Usage: <code>/ban <telegram_id></code>")
        return

    target_id = int(args[1])
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.telegram_id == target_id))).scalars().first()
        if user:
            user.status = "BANNED"
            await db.commit()
            await message.answer(f"✅ User <code>{target_id}</code> banned.")
        else:
            await message.answer("User not found.")

