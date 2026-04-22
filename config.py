import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
CLAUDE_MODEL_HAIKU = os.getenv("CLAUDE_MODEL_HAIKU", "claude-haiku-4-5-20251001")
MAX_CONCURRENT_AGENTS = int(os.getenv("MAX_CONCURRENT_AGENTS", "4"))
VECTOR_DB_PATH = os.getenv("VECTOR_DB_PATH", os.path.join(os.path.dirname(__file__), ".chromadb"))
