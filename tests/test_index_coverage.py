import asyncio
import tempfile
import unittest
from pathlib import Path

from skycity_bot.knowledge import GameKnowledge
from skycity_bot.storage import Database, KnowledgeIndexStore


class FakeEmbeddings:
    async def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


class IndexCoverageTests(unittest.TestCase):
    def test_every_markdown_document_is_indexed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            documents = root / "documents"
            documents.mkdir()
            (documents / "一般資料.md").write_text("# 一般資料\n玩家知識。", encoding="utf-8")
            (documents / "機器人顧問守則.md").write_text("# 機器人顧問守則\n作者是武林鬼武者。", encoding="utf-8")
            database = Database(root / "index.db")
            database.create_schema()
            try:
                store = KnowledgeIndexStore(database)
                knowledge = GameKnowledge(documents, store, FakeEmbeddings(), "test-embedding")
                asyncio.run(knowledge.rebuild_index())
                self.assertEqual(set(store.documents()), {"一般資料.md", "機器人顧問守則.md"})
                self.assertEqual({block["document_id"] for block in store.iter_blocks()}, set(store.documents()))
            finally:
                database.close()


if __name__ == "__main__":
    unittest.main()
