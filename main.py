import asyncio
import logging
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


async def start_bot():
    logger.info("Initializing Telegram Bot...")
    # Clear any active webhooks or stuck updates so long polling gets messages immediately
    for attempt in range(10):
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("Cleared old Telegram webhooks and pending updates.")
            break
        except Exception as e:
            logger.warning(f"delete_webhook attempt {attempt+1} failed: {e}")
            await asyncio.sleep(3)

    # Register subscription gate middleware
    dp.message.middleware(SubscriptionGateMiddleware())
    main_router = setup_routers()
    dp.include_router(main_router)

    # Start polling — retry on TelegramConflictError (two instances during Railway rolling deploy)
    for attempt in range(10):
        try:
            logger.info(f"Starting bot polling (attempt {attempt+1})...")
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
            break
        except Exception as e:
            if "Conflict" in str(e) or "getUpdates" in str(e):
                wait = 5 * (attempt + 1)
                logger.warning(f"Telegram conflict detected (old instance still running). Retrying in {wait}s...")
                await asyncio.sleep(wait)
            else:
                logger.error(f"Bot polling error: {e}")
                raise




async def start_api():
    logger.info("Initializing FastAPI Backend Service...")
    config = uvicorn.Config(
        app=fastapi_app,
        host=settings.HOST,
        port=settings.PORT,
        log_level="info"
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    db_type = "PostgreSQL" if "postgresql" in settings.DATABASE_URL or "postgres" in settings.DATABASE_URL else "SQLite"
    logger.info(f"Starting Telegram SaaS System... (DB Engine: {db_type})")
    # Initialize Database tables
    await init_db()


    # Start APScheduler background engine
    scheduler_service.start()

    try:
        # Run Bot Polling and FastAPI server concurrently
        await asyncio.gather(
            start_bot(),
            start_api()
        )
    except KeyboardInterrupt:
        logger.info("Shutting down services...")
    finally:
        scheduler_service.stop()


if __name__ == "__main__":
    asyncio.run(main())
