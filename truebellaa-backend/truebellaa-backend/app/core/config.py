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
    # This API's own public origin — used to build absolute image URLs for
    # locally-stored (DEMO mode) uploads, since the admin panel runs on a
    # different origin/port than the API.
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    # Require an emailed OTP before a customer account can be created.
    # Leaving this off would let anyone register on someone else's address.
    REQUIRE_OTP_SIGNUP: bool = True

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
    # Live by default. Point this at the sandbox host to test without
    # booking real couriers — Shiprocket shows the sandbox base URL inside
    # its own sandbox panel ("Go to Sandbox"), so paste it here rather than
    # guessing it.
    SHIPROCKET_BASE_URL: str = "https://apiv2.shiprocket.in/v1/external"

    # MilesWeb file storage (product image uploads) — plain FTP, the protocol
    # every MilesWeb shared-hosting/mPanel account exposes for its file manager.
    # NOTE: credentials are intentionally blank here. This file IS tracked in
    # git, so a real username/password written as a default would be committed
    # to version control. The live values belong in .env (which is gitignored).
    FTP_HOST: str = ""
    FTP_PORT: int = 21
    FTP_USER: str = ""
    FTP_PASSWORD: str = ""
    FTP_USE_TLS: bool = False               # turn on if MilesWeb gives you FTPS
    FTP_BASE_DIR: str = "/public_html/Images"  # must be inside the web root
    FTP_PUBLIC_BASE_URL: str = "https://truebellaa.in/Images"  # how that folder is served publicly
    # How uploaded images reach the browser:
    #   "proxy"  -> this API streams them from MilesWeb (works with NO DNS
    #               setup; the files still live on MilesWeb). Use this until
    #               the domain's A record points at the hosting box.
    #   "direct" -> the browser loads FTP_PUBLIC_BASE_URL straight from the
    #               web server. Faster; needs DNS + SSL working first.
    # Switching later needs no re-upload — only new URLs for new images, and
    # `python scripts/rewrite_image_urls.py` to move the existing ones over.
    MEDIA_DELIVERY: str = "proxy"
    MEDIA_CACHE_DIR: str = "uploads/cache"

    # Local fallback used whenever FTP isn't configured (dev machines, first run).
    LOCAL_UPLOAD_DIR: str = "uploads/products"
    LOCAL_UPLOAD_PUBLIC_BASE_URL: str = "/uploads/products"
    MAX_IMAGE_SIZE_MB: int = 8

    # Email (SMTP) — transactional emails: welcome, order placed, payment confirmed
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_NAME: str = "TrueBellaa"

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
        """True only when real-looking Shiprocket credentials are configured."""
        placeholder_emails = {"", "you@example.com"}
        placeholder_passwords = {"", "your_shiprocket_password"}
        return (self.SHIPROCKET_EMAIL not in placeholder_emails
                and self.SHIPROCKET_PASSWORD not in placeholder_passwords)

    @property
    def smtp_live(self) -> bool:
        """True only when real-looking SMTP credentials are configured."""
        placeholder_passwords = {"", "your_email_password"}
        return bool(self.SMTP_HOST) and bool(self.SMTP_USER) \
            and self.SMTP_PASSWORD not in placeholder_passwords

    @property
    def ftp_live(self) -> bool:
        """True only when real-looking MilesWeb FTP credentials are configured."""
        placeholder_hosts = {"", "ftp.yourdomain.com"}
        placeholder_passwords = {"", "your_ftp_password"}
        return (bool(self.FTP_HOST) and self.FTP_HOST not in placeholder_hosts
                and bool(self.FTP_USER) and self.FTP_PASSWORD not in placeholder_passwords)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
