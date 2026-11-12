"""Configuration management for PayWise Agent."""
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Base directory for the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file from the project root
load_dotenv(dotenv_path=BASE_DIR / ".env")


class Settings:
    """Application configuration and credentials."""
    
    # Base paths
    PROJECT_DIR: Path = BASE_DIR
    FRONTEND_DIR: Path = BASE_DIR / "frontend"
    
    # Google Gemini API Settings
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY", "").strip() or None
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()

    # PayPal API Settings
    PAYPAL_CLIENT_ID: Optional[str] = os.getenv("PAYPAL_CLIENT_ID", "").strip() or None
    PAYPAL_CLIENT_SECRET: Optional[str] = os.getenv("PAYPAL_CLIENT_SECRET", "").strip() or None
    PAYPAL_WEBHOOK_ID: Optional[str] = os.getenv("PAYPAL_WEBHOOK_ID", "").strip() or None
    PAYPAL_ENVIRONMENT: str = os.getenv("PAYPAL_ENVIRONMENT", "sandbox").strip().lower()

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./paywise.db").strip()

    # Server settings
    APP_HOST: str = os.getenv("APP_HOST", "127.0.0.1").strip()
    APP_PORT: int = int(os.getenv("APP_PORT", "8000"))
    DEBUG: bool = os.getenv("DEBUG", "True").strip().lower() in ("true", "1", "yes")

    @property
    def is_gemini_configured(self) -> bool:
        """Check if a valid Gemini API key is configured."""
        if not self.GEMINI_API_KEY:
            return False
        return not self.GEMINI_API_KEY.startswith("your_") and len(self.GEMINI_API_KEY) > 10

    @property
    def is_paypal_configured(self) -> bool:
        """Check if valid PayPal credentials are configured."""
        if not self.PAYPAL_CLIENT_ID or not self.PAYPAL_CLIENT_SECRET:
            return False
        if self.PAYPAL_CLIENT_ID.startswith("your_") or self.PAYPAL_CLIENT_SECRET.startswith("your_"):
            return False
        return len(self.PAYPAL_CLIENT_ID) > 5 and len(self.PAYPAL_CLIENT_SECRET) > 5

    @property
    def paypal_base_url(self) -> str:
        """Official PayPal REST API base URL."""
        if self.PAYPAL_ENVIRONMENT == "live":
            return "https://api-m.paypal.com"
        return "https://api-m.sandbox.paypal.com"


settings = Settings()
