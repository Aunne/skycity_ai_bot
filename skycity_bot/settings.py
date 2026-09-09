from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Settings:
    discord_token: str
    database_path: Path
    ollama_base_url: str
    chat_model: str
    embedding_model: str
    knowledge_documents_path: Path
    structured_knowledge_path: Path
    allowed_channels: frozenset[int]
    limit_speaking_channels: bool
    knowledge_top_k: int
    memory_message_limit: int

    def channel_is_allowed(self, channel_id: int) -> bool:
        return not self.limit_speaking_channels or channel_id in self.allowed_channels


def load_settings(config_path: str | Path = "config.yaml") -> Settings:
    project_root = Path.cwd()
    path = Path(config_path)
    if not path.is_absolute():
        path = project_root / path

    if path.exists():
        with path.open("r", encoding="utf-8") as file:
            raw: dict[str, Any] = yaml.safe_load(file) or {}
    else:
        raw = {}

    documents_path = Path(raw.get("KNOWLEDGE_DOCUMENTS_PATH", "knowledge/documents"))
    if not documents_path.is_absolute():
        documents_path = project_root / documents_path

    database_value = raw.get("DATABASE_PATH")
    if database_value is None:
        legacy_url = str(raw.get("SQLALCHEMY_DATABASE_URI", "sqlite:///data.db"))
        if not legacy_url.startswith("sqlite:///"):
            raise ValueError("此專案只支援 SQLite；請設定 DATABASE_PATH")
        database_value = legacy_url.removeprefix("sqlite:///")
    database_path = Path(str(database_value))
    if not database_path.is_absolute():
        database_path = project_root / database_path

    return Settings(
        discord_token=str(raw.get("DISCORD_BOT_TOKEN", "")),
        database_path=database_path,
        ollama_base_url=str(raw.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/"),
        chat_model=str(raw.get("OLLAMA_CHAT_MODEL", "qwen3.5:4b")),
        embedding_model=str(raw.get("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text-v2-moe")),
        knowledge_documents_path=documents_path,
        structured_knowledge_path=project_root / "knowledge" / "structured.yaml",
        allowed_channels=frozenset(int(value) for value in raw.get("ALLOWED_CHANNELS", [])),
        limit_speaking_channels=bool(raw.get("LIMIT_SPEAKING_CHANNELS", False)),
        knowledge_top_k=max(1, int(raw.get("KNOWLEDGE_TOP_K", 5))),
        memory_message_limit=max(2, int(raw.get("MEMORY_MESSAGE_LIMIT", 12))),
    )
