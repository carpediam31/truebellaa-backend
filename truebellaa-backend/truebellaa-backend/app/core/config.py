"""
Application settings, loaded from environment variables / .env file.

Why this file: instead of scattering os.getenv() calls everywhere, every
tunable value lives here in one typed object. Import `settings` anywhere.
"""
from functools import lru_cache
from urllib.parse import quote_plus
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    APP_NAME: str = "TrueBellaa API"
    ENV: str = "development"
    DEBUG: bool = True

    # Security
    SECRET_KEY: str = "change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    # --- Database ---
    # EASY WAY (recommended): set these 5 simple fields. No URL escaping needed,
    # so a password with special characters (@ : / etc.) just works.
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""          # e.g. 1234   (leave blank if no password)
    DB_NAME: str = "truebellaa"

    # ADVANCED (optional): to use a read replica or a full custom URL, set these
    # and they OVERRIDE the fields above. Leave blank to use the fields above.
    DATABASE_PRIMARY_URL: str = ""
    DATABASE_REPLICA_URL: str = ""

    def _build_url(self) -> str:
        # quote_plus escapes special characters in the password automatically.
        pw = quote_plus(self.DB_PASSWORD) if self.DB_PASSWORD else ""
        return (f"mysql+pymysql://{self.DB_USER}:{pw}@{self.DB_HOST}:{self.DB_PORT}"
                f"/{self.DB_NAME}?charset=utf8mb4")

    @property
    def primary_url(self) -> str:
        return self.DATABASE_PRIMARY_URL or self._build_url()

    @property
    def replica_url(self) -> str:
        return self.DATABASE_REPLICA_URL or self.primary_url

    # Razorpay
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""

    # Shiprocket
    SHIPROCKET_EMAIL: str = ""
    SHIPROCKET_PASSWORD: str = ""
    SHIPROCKET_PICKUP_LOCATION: str = "Primary"

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def razorpay_live(self) -> bool:
        """True only when real-looking Razorpay keys are configured."""
        return bool(self.RAZORPAY_KEY_ID) and "xxxx" not in self.RAZORPAY_KEY_ID and \
            self.RAZORPAY_KEY_ID != "rzp_test_xxxxxxxx" and bool(self.RAZORPAY_KEY_SECRET)

    @property
    def shiprocket_live(self) -> bool:
        return bool(self.SHIPROCKET_EMAIL) and bool(self.SHIPROCKET_PASSWORD)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
