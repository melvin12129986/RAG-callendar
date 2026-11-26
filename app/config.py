import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

load_dotenv(override=True)

def _parse_port(raw: Optional[str], default: int = 8000) -> int:
    if not raw:
        return default
    clean = str(raw).strip().strip("'\"")
    if clean.isdigit():
        return int(clean)
    return default

@dataclass
class Settings:
    APP_NAME: str = "BERT Calendar RAG & Groq AI Reasoning"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = _parse_port(os.getenv("PORT"), 8000)
    
    # Groq Settings (Free 14,400 requests/day, Ultra-low latency)
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    ACTIVE_LLM_PROVIDER: str = os.getenv("ACTIVE_LLM_PROVIDER", "groq")
    
    # Google Calendar Settings
    GOOGLE_CREDENTIALS_FILE: str = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    GOOGLE_TOKEN_FILE: str = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
    USE_MOCK_CALENDAR_IF_NO_CREDENTIALS: bool = True
    
    # BERT Model config
    # Fast lightweight BERT model with full BERT forward pass architecture
    BERT_MODEL_NAME: str = os.getenv("BERT_MODEL_NAME", "prajjwal1/bert-tiny")

    # Supabase Settings (Cloud Database & Google OAuth)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

settings = Settings()
