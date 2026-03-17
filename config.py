#!/usr/bin/env python3
"""
Configuration loader — reads from .env file or environment variables.
No secrets in this file. Safe to commit to GitHub.
"""

import os
from pathlib import Path

env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"\''))


def env(key, default=""):
    return os.environ.get(key, default)


# ─── LLM Backend ────────────────────────────────────────────────
LLM_BACKEND = env("LLM_BACKEND", "ollama")
OLLAMA_URL = env("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = env("OLLAMA_MODEL", "llama3")
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = env("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
OPENAI_API_KEY = env("OPENAI_API_KEY")
OPENAI_MODEL = env("OPENAI_MODEL", "gpt-4o-mini")

# ─── Data Source API Keys (optional) ────────────────────────────
YOUTUBE_API_KEY = env("YOUTUBE_API_KEY")
COINMARKETCAP_API_KEY = env("COINMARKETCAP_API_KEY")
ALPHA_VANTAGE_API_KEY = env("ALPHA_VANTAGE_API_KEY")
REDDIT_CLIENT_ID = env("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = env("REDDIT_CLIENT_SECRET")

# ─── Scraping Settings ─────────────────────────────────────────
REQUEST_DELAY = (1.5, 3.5)
MAX_RETRIES = 3
TIMEOUT = 15
CACHE_TTL_HOURS = 4
MAX_PAGES_PER_SEARCH = 5

# ─── Output ─────────────────────────────────────────────────────
OUTPUT_DIR = env("OUTPUT_DIR", "./output")
CACHE_DIR = env("CACHE_DIR", "./.cache")
OUTPUT_FORMAT = env("OUTPUT_FORMAT", "json")

# ─── YouTube CPM Estimates (USD per 1,000 views) ───────────────
CPM_RANGES = {
    "tech": (4.0, 12.0), "finance": (8.0, 20.0), "crypto": (6.0, 15.0),
    "gaming": (2.0, 6.0), "education": (4.0, 10.0), "lifestyle": (2.0, 8.0),
    "music": (1.0, 4.0), "food": (3.0, 8.0), "fitness": (3.0, 9.0),
    "news": (3.0, 8.0), "comedy": (2.0, 6.0), "default": (2.0, 8.0),
}

# ─── User Agents ───────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]
