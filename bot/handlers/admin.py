from aiogram import Router, types
from aiogram.filters import Command
from sqlalchemy import select, func

from core.database import async_session_factory
from models.user import User
from models.subscription import Subscription
from models.payment import Payment
from config import settings

router = Router()


def is_admin_user(user_id: int) -> bool:
    return user_id in settings.admin_ids_list


@router.message(Command("admin"))
async def admin_panel(message: types.Message):
    if not is_admin_user(message.from_user.id):
        await message.answer("❌ Unauthorized access.")
        return

    async with async_session_factory() as db:
        # Total Users
        stmt_users = select(func.count(User.id))
        total_users = (await db.execute(stmt_users)).scalar() or 0

        # Active Subscriptions
        stmt_subs = select(func.count(Subscription.id)).where(
            Subscription.status == "ACTIVE"
        )
        active_subs = (await db.execute(stmt_subs)).scalar() or 0

        # Total Revenue
        stmt_rev = select(func.sum(Payment.amount)).where(Payment.status == "VERIFIED")
        total_revenue = (await db.execute(stmt_rev)).scalar() or 0.0

    admin_text = (
        f"<b>👑 SaaS Admin Panel</b>\n\n"
        f"<b>👥 Total Registered Users:</b> {total_users}\n"
        f"<b>💳 Active Subscriptions:</b> {active_subs}\n"
        f"<b>💰 Total Revenue:</b> ₹{total_revenue:,.2f} INR\n\n"
        f"<b>Admin Commands:</b>\n"
        f"• <code>/broadcast &lt;message&gt;</code> - Send message to all users\n"
        f"• <code>/ban &lt;telegram_id&gt;</code> - Ban user from system\n"
        f"• <code>/unban &lt;telegram_id&gt;</code> - Unban user\n"
    )

    await message.answer(admin_text)


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
