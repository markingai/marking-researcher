import os
from pathlib import Path

# API keys
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")

# Base URLs
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"

# Models
MODEL_PRO = "gemini-2.5-pro"
MODEL_FLASH = "gemini-2.5-flash"
MODEL_GEMINI_3 = "gemini-3-pro-preview"
MODEL_GEMINI_31 = "gemini-3.1-pro-preview"
MODEL_FLASH_35 = "gemini-3.5-flash"
MODEL_CLAUDE = "claude-opus-4-6-20260301"
MODEL_GPT = "gpt-5.2"
MODEL_DEFAULT = MODEL_PRO

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
MATHS_CSV = PROJECT_ROOT / "Evals_tracker - Raw data - maths.csv"
ENGLISH_CSV = PROJECT_ROOT / "Evals_tracker - Raw data - english .csv"
EXAMPRO_CSV = PROJECT_ROOT / "gcse_english_exampro.csv"
RESULTS_DIR = PROJECT_ROOT / "results"
AUTORESEARCH_DIR = PROJECT_ROOT / "autoresearch"

# Sampling
MATHS_SAMPLE_SIZE = 50
ENGLISH_SAMPLE_SIZE = 50
RANDOM_SEED = 42

# Rate limiting (per provider)
CALLS_PER_MINUTE = 10  # Gemini default
ANTHROPIC_CALLS_PER_MINUTE = 10
OPENAI_CALLS_PER_MINUTE = 10
RETRY_MAX = 5
RETRY_BACKOFF = 2.0
REQUEST_TIMEOUT = 300  # seconds, generous for thinking models

# Parallel execution
MAX_CONCURRENT = 5  # concurrent API requests per strategy
THINKING_BUDGET = 4096  # cap thinking tokens (was -1/unlimited, caused timeouts)

# Autoresearch budget
EXPERIMENT_BUDGET_USD = 3.00  # Max cost per single strategy evaluation
SESSION_BUDGET_USD = 20.00  # Total budget per autonomous session

# Excluded questions (require image analysis)
EXCLUDED_QUESTIONS = {"32"}

# Pricing per million tokens (USD)
# fmt: off
MODEL_PRICING: dict[str, dict[str, float]] = {
    # model_string: {"input": $/MTok, "output": $/MTok, "thinking": $/MTok (if diff)}
    "gemini-2.5-pro":           {"input": 1.25,  "output": 10.00},
    "gemini-2.5-flash":         {"input": 0.15,  "output": 0.60},
    "gemini-3.1-pro-preview":   {"input": 2.00,  "output": 12.00},
    "gemini-3-pro-preview":     {"input": 2.00,  "output": 12.00},
    "gemini-3.5-flash":         {"input": 1.50,  "output": 9.00},
    "claude-opus-4-6-20260301": {"input": 5.00,  "output": 25.00},
    "gpt-5.2":                  {"input": 1.75,  "output": 14.00},
}
# fmt: on
