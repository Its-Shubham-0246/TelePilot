from aiogram import Router
from bot.handlers.start import router as start_router
from bot.handlers.dashboard import router as dashboard_router
from bot.handlers.accounts import router as accounts_router
from bot.handlers.messages import router as messages_router
from bot.handlers.scheduler import router as scheduler_router
from bot.handlers.subscription import router as subscription_router
from bot.handlers.status import router as status_router
from bot.handlers.support import router as support_router
from bot.handlers.admin import router as admin_router


def setup_routers() -> Router:
    main_router = Router()
    main_router.include_router(start_router)
    main_router.include_router(dashboard_router)
    main_router.include_router(accounts_router)
    main_router.include_router(messages_router)
    main_router.include_router(scheduler_router)
    main_router.include_router(subscription_router)
    main_router.include_router(status_router)
    main_router.include_router(support_router)
    main_router.include_router(admin_router)
    return main_router
