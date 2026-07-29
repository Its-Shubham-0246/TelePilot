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
    
    # App Settings
    MAX_ACCOUNTS_PER_USER: int = 15
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
