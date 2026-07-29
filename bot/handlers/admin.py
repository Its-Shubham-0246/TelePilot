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
        f"• <code>/users</code> — List all registered users with IDs\n"
        f"• <code>/grantlifetime &lt;telegram_id&gt;</code> — Give permanent access\n"
        f"• <code>/broadcast &lt;message&gt;</code> — Send message to all users\n"
        f"• <code>/ban &lt;telegram_id&gt;</code> — Ban user\n"
        f"• <code>/unban &lt;telegram_id&gt;</code> — Unban user\n"
        f"• <code>/cancelsub &lt;telegram_id&gt;</code> — Expire user's subscription\n"
        f"• <code>/mysub</code> — Check your own subscription status\n"
    )

    await message.answer(admin_text)


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


@router.message(Command("grantlifetime"))
async def admin_grant_lifetime(message: types.Message):
    """Admin: grant permanent (lifetime) bot access to a user by Telegram ID."""
    if not is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized.")
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer(
            "Usage: <code>/grantlifetime &lt;telegram_id&gt;</code>\n\n"
            "Tip: Use /users to find the Telegram ID of any registered user."
        )
        return

    target_telegram_id = int(args[1])

    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.telegram_id == target_telegram_id))).scalars().first()
        if not user:
            await message.answer(
                f"❌ User <code>{target_telegram_id}</code> not found.\n\n"
                f"Ask them to send /start to the bot first, then try again."
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

        # Create lifetime subscription — expires year 2099
        lifetime_sub = Subscription(
            user_id=user.id,
            plan_name="Lifetime Access (Admin Grant)",
            status="ACTIVE",
            expires_at=datetime(2099, 12, 31, 23, 59, 59),
            max_accounts=15,
        )
        db.add(lifetime_sub)
        await db.commit()

    username = f"@{user.username}" if user.username else user.full_name or str(target_telegram_id)

    # Notify the granted user
    try:
        await message.bot.send_message(
            target_telegram_id,
            f"🎉 <b>Lifetime Access Granted!</b>\n\n"
            f"You have been given <b>permanent free access</b> to TelePilot Bot by the admin.\n\n"
            f"✅ All features unlocked\n"
            f"✅ Up to 15 accounts\n"
            f"✅ No expiry — valid forever\n\n"
            f"Enjoy! 🚀"
        )
    except Exception:
        pass  # User may have blocked the bot

    await message.answer(
        f"✅ <b>Lifetime Access Granted!</b>\n\n"
        f"User: {username}\n"
        f"Telegram ID: <code>{target_telegram_id}</code>\n"
        f"Plan: Lifetime Access (Admin Grant)\n"
        f"Expires: Never (31 Dec 2099)\n\n"
        f"The user has been notified. ✉️"
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

