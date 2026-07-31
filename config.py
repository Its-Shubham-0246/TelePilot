import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from cryptography.fernet import Fernet


class Settings(BaseSettings):
    BOT_TOKEN: str = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
    TELEGRAM_API_ID: int = 12345678
    TELEGRAM_API_HASH: str = "0123456789abcdef0123456789abcdef"
    
    # Secret Key for AES-256 Fernet Session Encryption (set via ENCRYPTION_SECRET_KEY env var)
    ENCRYPTION_SECRET_KEY: str = ""



    
    # Database URL (AsyncPG)
    DATABASE_URL: str = "sqlite+aiosqlite:///./telegram_saas.db"
    
    # Redis URL
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Admin Telegram IDs (list or comma-separated)
    ADMIN_TELEGRAM_IDS: str = "123456789"

    # Group Discovery Alert Feature:
    # The phone number of the reference account (e.g. the account you use most)
    # When any other account finds a group that this account is NOT in, you get an alert.
    REFERENCE_ACCOUNT_PHONE: str = ""

    # Chat ID of the Telegram group where new group alerts will be sent.
    # Add the bot to your private group, get the chat ID, and set it here.
    ALERT_GROUP_CHAT_ID: str = ""
    
    # App Settings
    MAX_ACCOUNTS_PER_USER: int = 15
    MAX_CONCURRENT_BROADCASTS: int = 20
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # Razorpay Payment Gateway Config
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def admin_ids_list(self) -> List[int]:
        if not self.ADMIN_TELEGRAM_IDS:
            return []
        return [int(x.strip()) for x in self.ADMIN_TELEGRAM_IDS.split(",") if x.strip().isdigit()]


settings = Settings()
