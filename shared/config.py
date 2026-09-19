"""Central configuration. Everything is an environment variable with a sane default."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


class Settings:
    llm_api_key: str = _env("LLM_API_KEY") or _env("GROQ_API_KEY") or _env("OPENAI_API_KEY")
    llm_base_url: str = _env("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    model_strong: str = _env("LLM_MODEL_STRONG", "openai/gpt-oss-120b")
    model_fast: str = _env("LLM_MODEL_FAST", "openai/gpt-oss-20b")
    # Hard ceiling on how much context we ever put in one call. Keeps us inside
    # free-tier rate limits and, more importantly, keeps the model focused.
    context_budget: int = int(_env("LLM_CONTEXT_BUDGET", "4200"))
    embedding_model: str = _env("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    data_dir: Path = Path(_env("DATA_DIR", str(ROOT / "data"))).resolve()

    # Task 1 connectors
    pipedrive_token: str = _env("PIPEDRIVE_API_TOKEN")
    pipedrive_base_url: str = _env("PIPEDRIVE_BASE_URL", "https://api.pipedrive.com")
    hubspot_token: str = _env("HUBSPOT_ACCESS_TOKEN")
    jira_base_url: str = _env("JIRA_BASE_URL")
    jira_email: str = _env("JIRA_EMAIL")
    jira_token: str = _env("JIRA_API_TOKEN")

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key)


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
