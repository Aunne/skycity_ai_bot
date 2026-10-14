import asyncio

from .knowledge import GameKnowledge
from .ollama import OllamaClient
from .settings import load_settings
from .storage import Database, KnowledgeIndexStore


async def main() -> None:
    settings = load_settings()
    database = Database(settings.database_path)
    database.create_schema()
    ollama = OllamaClient(
        settings.ollama_base_url,
        settings.chat_model,
        settings.embedding_model,
        settings.ollama_api_key,
        settings.embedding_base_url,
        settings.embedding_api_key,
    )
    try:
        knowledge = GameKnowledge(
            settings.knowledge_documents_path,
            KnowledgeIndexStore(database),
            ollama,
            settings.embedding_model,
        )
        count = await knowledge.rebuild_index()
        print(f"已建立 {count} 個知識切塊。")
    finally:
        database.close()


if __name__ == "__main__":
    asyncio.run(main())
