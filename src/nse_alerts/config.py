import os
from dataclasses import dataclass
from dotenv import load_dotenv


load_dotenv()


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


@dataclass
class Settings:
    xai_api_key: str
    telegram_token: str
    telegram_chat_id: str
    nse_index: str = "equities"
    poll_interval_seconds: int = 60
    mock_llm: bool = False

    @classmethod
    def load(cls) -> "Settings":
        api_key = _env("XAI_API_KEY") or _env("OPENAI_API_KEY")  # Allow fallback or both? Prefer XAI first
        token = _env("TELEGRAM_BOT_TOKEN")
        chat_id = _env("TELEGRAM_CHAT_ID")
        if not api_key and not _env("MOCK_LLM"):
            raise RuntimeError("XAI_API_KEY (or MOCK_LLM) missing")
        # Relaxed Telegram requirements for testing
        if not token:
             # raise RuntimeError("TELEGRAM_BOT_TOKEN missing")
             pass
        if not chat_id:
             # raise RuntimeError("TELEGRAM_CHAT_ID missing")
             pass
        return cls(
            xai_api_key=api_key or "",
            telegram_token=token or "",
            telegram_chat_id=chat_id or "",
            nse_index=_env("NSE_INDEX", "equities") or "equities",
            poll_interval_seconds=int(_env("POLL_INTERVAL_SECONDS", "60")),
            mock_llm=bool(int(_env("MOCK_LLM", "0"))),
        )
