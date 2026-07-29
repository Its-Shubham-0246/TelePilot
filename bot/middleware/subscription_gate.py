from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message
from sqlalchemy import select

from core.database import async_session_factory
from models.user import User
from services.subscription_service import subscription_service
from bot.keyboards.inline import get_subscription_plans_keyboard

# Buttons that ALWAYS work — no subscription required
FREE_ACCESS = {
    "/start",
    "🏠 Dashboard",
    "💳 Subscription",
    "⚙️ Settings",
    "🆘 Support",
}

# Buttons that require an active subscription
GATED_BUTTONS = {
    "➕ Add Account",
    "👤 My Accounts",
    "💬 Messages",
    "⏰ Scheduler",
    "▶️ Start",
    "⏸ Pause",
    "⏹ Stop",
    "📊 Status",
}


class SubscriptionGateMiddleware(BaseMiddleware):
    """
    Intercepts all incoming messages.
    If the user taps a gated button without an active subscription,
    block the action and prompt them to subscribe.
    """

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        text = (event.text or "").strip()

        # Block menu button presses and general commands in group chats (redirect to private DM)
        if event.chat.type != "private":
            if text in FREE_ACCESS or text in GATED_BUTTONS or text.startswith("/"):
                # Allow utility commands like /id or /getchatid in groups
                if text.startswith("/id") or text.startswith("/getchatid"):
                    return await handler(event, data)

                await event.answer("👉 Please click @TelePilotSaaSBot to use the bot in private chat!")
                return
            return await handler(event, data)

        # Only gate specific menu button presses in private DM
        if text not in GATED_BUTTONS:
            return await handler(event, data)


        # Check subscription status
        async with async_session_factory() as db:
            user_result = await db.execute(
                select(User).where(User.telegram_id == event.from_user.id)
            )
            user = user_result.scalars().first()

            if not user:
                from config import settings
                is_admin = event.from_user.id in settings.admin_ids_list
                user = User(
                    telegram_id=event.from_user.id,
                    username=event.from_user.username,
                    full_name=event.from_user.full_name,
                    is_admin=is_admin
                )
                db.add(user)
                await db.commit()
                await db.refresh(user)


            has_sub = await subscription_service.check_user_has_active_sub(db, user.id)

        if not has_sub:
            await event.answer(
                "🔒 <b>Subscription Required</b>\n\n"
                "You need an active subscription to use this feature.\n\n"
                "Choose a plan below to get started:",
                reply_markup=get_subscription_plans_keyboard()
            )
            return

        # Subscription is active — allow through
        return await handler(event, data)
