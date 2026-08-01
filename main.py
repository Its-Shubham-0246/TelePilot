import asyncio
import logging
import os
import uvicorn
from core.database import init_db
from config import settings
from bot.bot_instance import bot, dp
from bot.handlers import setup_routers
from bot.middleware import SubscriptionGateMiddleware
from services.scheduler_service import scheduler_service
from api.main import app as fastapi_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("telegram_saas_app")

# Suppress noisy Telethon internal logs (channel updates, connect/disconnect, flood-wait sleeps)
# Only surface WARNING+ from Telethon so real errors remain visible
logging.getLogger('telethon').setLevel(logging.WARNING)
logging.getLogger('telethon.client.updates').setLevel(logging.WARNING)
logging.getLogger('telethon.client.users').setLevel(logging.WARNING)
logging.getLogger('telethon.network.mtprotosender').setLevel(logging.WARNING)

# Suppress APScheduler "max instances reached" spam — fires every 5s during long broadcasts (expected behavior)
logging.getLogger('apscheduler.scheduler').setLevel(logging.ERROR)
logging.getLogger('apscheduler.executors.default').setLevel(logging.WARNING)


async def start_bot():
    logger.info("Initializing Telegram Bot...")
    # Clear any active webhooks or stuck updates so long polling gets messages immediately
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Cleared old Telegram webhooks and pending updates.")
    except Exception as e:
        logger.warning(f"delete_webhook failed: {e}")

    # Set official Telegram Bot Bio & Description (featuring 10,000+ Users badge)
    try:
        await bot.set_my_description("TelePilot SaaS Bot — Trusted by 10,000+ Users! Automate group messaging across multiple Telegram accounts effortlessly 24/7.")
        await bot.set_my_short_description("TelePilot — Telegram Group Automation | Trusted by 10,000+ Users 🚀")
        logger.info("Configured official Bot Description & Bio (10,000+ Users).")
    except Exception as desc_err:
        logger.warning(f"Failed to set bot descriptions: {desc_err}")

    # Register subscription gate middleware
    dp.message.middleware(SubscriptionGateMiddleware())
    main_router = setup_routers()
    dp.include_router(main_router)

    # Start polling loop with automatic retry
    while True:
        try:
            logger.info("Starting bot polling...")
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
            break
        except asyncio.CancelledError:
            logger.info("Bot polling cancelled.")
            break
        except Exception as e:
            logger.warning(f"Bot polling exception: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)


async def start_api():
    logger.info("Initializing FastAPI Backend Service...")
    port = int(os.getenv("PORT", settings.PORT))
    config = uvicorn.Config(
        app=fastapi_app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
    server = uvicorn.Server(config)
    await server.serve()


async def heartbeat_loop():
    """Heartbeat loop to claim & maintain Container Leader Lock during Railway rolling deploys."""
    while True:
        try:
            await scheduler_service.claim_leadership()
        except Exception:
            pass
        await asyncio.sleep(10)


async def background_startup():
    db_type = "PostgreSQL" if "postgresql" in settings.DATABASE_URL or "postgres" in settings.DATABASE_URL else "SQLite"
    logger.info(f"Starting Telegram SaaS System background services... (DB Engine: {db_type})")
    await init_db()

    # Claim Container Leadership immediately after DB init
    try:
        await scheduler_service.claim_leadership()
        asyncio.create_task(heartbeat_loop())
        logger.info("Claimed Container Leader Lock for scheduler execution.")
    except Exception as lock_err:
        logger.warning(f"Leader lock claim warning: {lock_err}")

    # Enforce 5 accounts max limit for all active lifetime subscriptions
    try:
        from core.database import async_session_factory
        from services.subscription_service import subscription_service
        async with async_session_factory() as db:
            await subscription_service.sweep_and_enforce_lifetime_limits(db)
        logger.info("Enforced 5 accounts max limit for all Lifetime subscriptions.")
    except Exception as sweep_err:
        logger.warning(f"Lifetime accounts sweep warning: {sweep_err}")

    # Start APScheduler background engine
    scheduler_service.start()

    # Start Telegram Bot Polling
    await start_bot()


async def safe_background_startup():
    try:
        await background_startup()
    except asyncio.CancelledError:
        pass
    except Exception as err:
        logger.error(f"Error during background startup: {err}")


async def main():
    logger.info("Launching TelePilot SaaS Application...")

    # Start background initialization (DB, lifetime limits sweep, scheduler, bot polling)
    bg_task = asyncio.create_task(safe_background_startup())

    try:
        # Start Web Server IMMEDIATELY so Railway Healthcheck binds to PORT in 0.01s
        await start_api()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down services...")
    finally:
        bg_task.cancel()
        scheduler_service.stop()


if __name__ == "__main__":
    asyncio.run(main())
