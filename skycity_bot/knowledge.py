from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

import yaml

from .ollama import OllamaClient
from .storage import KnowledgeIndexStore, StructuredKnowledgeStore


_SOURCE_URL = re.compile(r"https?://[^\s]+")
_POLICY_FILE = "機器人顧問守則.txt"
_INDEX_EXCLUSIONS = {_POLICY_FILE, "目前知識庫版本.txt"}


class GameKnowledge:
    """Structured facts and semantic documents behind one query interface."""

    def __init__(
        self,
        documents_path: Path,
        structured_path: Path,
        index_store: KnowledgeIndexStore,
        structured_store: StructuredKnowledgeStore,
        ollama: OllamaClient,
    ):
        self._documents_path = documents_path
        self._index_store = index_store
        self._structured_store = structured_store
        self._ollama = ollama
        with structured_path.open("r", encoding="utf-8") as file:
            structured: dict[str, Any] = yaml.safe_load(file) or {}
        self._structured_store.replace_from_mapping(structured)

    def system_policy(self) -> str:
        policy_path = self._documents_path / _POLICY_FILE
        if policy_path.exists():
            return policy_path.read_text(encoding="utf-8-sig").strip()
        return (
            "你是天空之城遊戲顧問。只根據提供的知識內容與工具結果回答；"
            "資料不足時明確說知識庫沒有紀錄。不可把不同類別或等級的數值互相代用。"
        )

    async def rebuild_index(self) -> int:
        chunks = list(_load_document_chunks(self._documents_path))
        if not chunks:
            self._index_store.replace([])
            return 0

        embeddings: list[list[float]] = []
        for start in range(0, len(chunks), 16):
            texts = [f"search_document: {chunk['content']}" for chunk in chunks[start : start + 16]]
            embeddings.extend(await self._ollama.embed(texts))

        if len(embeddings) != len(chunks):
            raise RuntimeError("Embedding 數量與文件切塊數量不一致")

        indexed = [dict(chunk, embedding=embedding) for chunk, embedding in zip(chunks, embeddings)]
        self._index_store.replace(indexed)
        return len(indexed)

    async def semantic_context(self, query: str, top_k: int) -> str:
        chunks = self._index_store.all()
        if not chunks:
            return ""

        query_embedding = (await self._ollama.embed([f"search_query: {query}"]))[0]
        ranked = sorted(
            chunks,
            key=lambda chunk: _cosine(query_embedding, chunk["embedding"]),
            reverse=True,
        )[:top_k]

        sections: list[str] = []
        total_characters = 0
        for chunk in ranked:
            source = str(chunk["document_name"])
            if chunk.get("source_url"):
                source = f"{source} — {chunk['source_url']}"
            section = f"[來源：{source}]\n{chunk['content']}"
            if sections and total_characters + len(section) > 3500:
                break
            sections.append(section)
            total_characters += len(section)
        return "\n\n".join(sections)

    def exact_answer(self, question: str) -> str | None:
        """Answer recognized factual combinations without asking the language model to infer them."""
        if "成長" not in question:
            return None
        tier_match = re.search(r"[LlＬｌ]\s*(\d+)", question)
        if tier_match is None:
            return None

        normalized_question = _normalize(question)
        for category in self._structured_store.pet_categories():
            names = [category.get("name", ""), *category.get("aliases", [])]
            if not any(_normalize(str(name)) in normalized_question for name in names):
                continue

            result = self._get_pet_growth(str(category["name"]), int(tier_match.group(1)))
            source = result.get("source")
            source_line = f"\n來源：{source}" if source else ""
            if result["status"] == "invalid_tier":
                return (
                    f"{result['pet_type']}最高只有 L{result['maximum_tier']}，不存在 "
                    f"L{result['requested_tier']}，因此沒有該等級的最高成長值。{source_line}"
                )
            if result["status"] == "found":
                return (
                    f"{result['pet_type']} L{result['tier']} 的最高成長值是 "
                    f"{result['maximum_growth']}。{source_line}"
                )
        return None

    def tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_pet_growth",
                    "description": "查詢指定類型與 L 等級寵物的最高成長值，並驗證該組合是否存在。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pet_type": {
                                "type": "string",
                                "description": "寵物類型，例如商寵、商城寵物、道具寵。",
                            },
                            "tier": {
                                "type": "integer",
                                "description": "寵物的 L 等級數字，例如 L4 傳入 4。",
                            },
                        },
                        "required": ["pet_type", "tier"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "calculate_pet_available_points",
                    "description": "依據寵物取得經驗時的轉數與升級數，計算新增可用點。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "rebirth": {"type": "integer", "description": "經驗轉數，0 到 8。"},
                            "levels_gained": {"type": "integer", "description": "提升的寵物等級數。"},
                        },
                        "required": ["rebirth", "levels_gained"],
                    },
                },
            },
        ]

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "get_pet_growth":
            return self._get_pet_growth(str(arguments.get("pet_type", "")), arguments.get("tier"))
        if name == "calculate_pet_available_points":
            return self._calculate_pet_points(arguments.get("rebirth"), arguments.get("levels_gained"))
        return {"status": "unknown_tool", "tool": name}

    def _get_pet_growth(self, pet_type: str, tier_value: Any) -> dict[str, Any]:
        try:
            tier = int(tier_value)
        except (TypeError, ValueError):
            return {"status": "invalid_argument", "argument": "tier"}

        normalized = _normalize(pet_type)
        categories = self._structured_store.pet_categories()
        for category in categories:
            names = [category.get("name", ""), *category.get("aliases", [])]
            if normalized not in {_normalize(str(name)) for name in names}:
                continue

            valid_tiers = [int(value) for value in category.get("valid_tiers", [])]
            if tier not in valid_tiers:
                return {
                    "status": "invalid_tier",
                    "pet_type": category["name"],
                    "requested_tier": tier,
                    "valid_tiers": valid_tiers,
                    "maximum_tier": max(valid_tiers) if valid_tiers else None,
                    "source": category.get("source"),
                }
            growth = category.get("growth_by_tier", {}).get(tier)
            return {
                "status": "found",
                "pet_type": category["name"],
                "tier": tier,
                "maximum_growth": growth,
                "source": category.get("source"),
            }
        return {"status": "unknown_pet_type", "pet_type": pet_type}

    def _calculate_pet_points(self, rebirth_value: Any, levels_value: Any) -> dict[str, Any]:
        try:
            rebirth = int(rebirth_value)
            levels = int(levels_value)
        except (TypeError, ValueError):
            return {"status": "invalid_argument"}
        rate = self._structured_store.pet_point_rate(rebirth)
        if rate is None or levels < 0:
            return {"status": "invalid_argument", "rebirth": rebirth, "levels_gained": levels}
        per_level = int(rate["points_per_level"])
        return {
            "status": "calculated",
            "rebirth": rebirth,
            "levels_gained": levels,
            "points_per_level": int(per_level),
            "available_points": int(per_level) * levels,
            "source": rate.get("source"),
        }


def _load_document_chunks(documents_path: Path) -> Iterable[dict[str, object]]:
    if not documents_path.exists():
        return
    for path in sorted(documents_path.rglob("*.txt")):
        if path.name in _INDEX_EXCLUSIONS:
            continue
        text = path.read_text(encoding="utf-8-sig").strip()
        if not text:
            continue
        urls = _SOURCE_URL.findall(text)
        for index, content in enumerate(_chunk_text(text)):
            yield {
                "document_name": path.name,
                "chunk_index": index,
                "content": f"[文件：{path.stem}]\n{content}",
                "source_url": urls[-1].rstrip(").,，") if urls else None,
            }


def _chunk_text(text: str, target_chars: int = 1000) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for paragraph in paragraphs:
        if current and current_size + len(paragraph) > target_chars:
            chunks.append("\n\n".join(current))
            current = []
            current_size = 0
        current.append(paragraph)
        current_size += len(paragraph)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return -1.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return -1.0
    return dot / (left_norm * right_norm)


def _normalize(value: str) -> str:
    return re.sub(r"[\s_-]", "", value).lower()
