from __future__ import annotations

import argparse
import asyncio

from .assistant import AnswerRequest, SkyCityAssistant
from .knowledge import GameKnowledge
from .ollama import OllamaClient
from .settings import load_settings
from .storage import Database, KnowledgeIndexStore, MemoryStore, StructuredKnowledgeStore


async def ask(question: str) -> str:
    settings = load_settings()
    database = Database(settings.database_path)
    database.create_schema()
    try:
        ollama = OllamaClient(
            settings.ollama_base_url,
            settings.chat_model,
            settings.embedding_model,
        )
        knowledge = GameKnowledge(
            settings.knowledge_documents_path,
            settings.structured_knowledge_path,
            KnowledgeIndexStore(database),
            StructuredKnowledgeStore(database),
            ollama,
        )
        assistant = SkyCityAssistant(
            ollama,
            knowledge,
            MemoryStore(database),
            settings.memory_message_limit,
            settings.knowledge_top_k,
        )
        return await assistant.answer(
            AnswerRequest("local", "local", question, remember=False)
        )
    finally:
        database.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="直接測試本機天空之城遊戲顧問")
    parser.add_argument("question", nargs="*", help="要詢問的問題")
    arguments = parser.parse_args()
    question = " ".join(arguments.question).strip() or input("問題：").strip()
    if not question:
        parser.error("請輸入問題")
    print(asyncio.run(ask(question)))


if __name__ == "__main__":
    main()
