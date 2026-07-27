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


async def start_bot():
    logger.info("Initializing Telegram Bot...")
    # Register subscription gate middleware
    dp.message.middleware(SubscriptionGateMiddleware())
    main_router = setup_routers()
    dp.include_router(main_router)
    # Start polling
    await dp.start_polling(bot)


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
    logger.info("Starting Telegram SaaS System...")
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
