import os
from pathlib import Path

from dotenv import load_dotenv

# Process environment takes precedence over local development settings.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/eduinsight")
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgresql://"):]
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_ENABLED = os.getenv("OPENAI_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
OPENAI_TIMEOUT = float(os.getenv("OPENAI_TIMEOUT", "15"))
OPENAI_MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "0"))
ANALYSIS_STALE_SECONDS = int(os.getenv("ANALYSIS_STALE_SECONDS", "120"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if origin.strip()]
