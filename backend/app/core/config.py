from pydantic import BaseSettings

from typing import List

import os



class Settings(BaseSettings):

    class Config:

        env_file = ".env"

        extra = "allow"  # Allow extra fields from environment variables

    # App settings

    APP_NAME: str = "Johnify API"

    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"

    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    

    # Security

    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-here")

    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24 hours

    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

    

    # CORS

    CORS_ORIGINS: List[str] = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:19006").split(",")

    

    # Rate limiting

    RATE_LIMIT_MAX_REQUESTS: int = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "100"))

    RATE_LIMIT_WINDOW: int = int(os.getenv("RATE_LIMIT_WINDOW", "60"))  # seconds

    

    # Database

    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/johnify")

    

    # Email

    SMTP_SERVER: str = os.getenv("SMTP_SERVER", "smtp.gmail.com")

    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))

    SMTP_USER: str = os.getenv("SMTP_USER", "")

    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")

    

    # API

    API_V1_STR: str = "/api/v1"



# Create settings instance

settings = Settings()