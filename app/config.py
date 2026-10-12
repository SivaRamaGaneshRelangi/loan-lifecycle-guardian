import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./loan_guardian.db")
    JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me-dev-secret-change-me")
    JWT_ALG = "HS256"
    JWT_EXPIRE_MIN = int(os.getenv("JWT_EXPIRE_MIN", "120"))
    # google-genai reads either variable; we pass explicitly so both work
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    DEMO_MODE = os.getenv("DEMO_MODE", "1") == "1"
    SEED_DEMO = os.getenv("SEED_DEMO", "1") == "1"
    AUTOPAY_SCHEDULER_SECONDS = int(os.getenv("AUTOPAY_SCHEDULER_SECONDS", "0"))
    MAX_AUTOPAY_ATTEMPTS = int(os.getenv("MAX_AUTOPAY_ATTEMPTS", "5"))
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
    MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "5"))


settings = Settings()
