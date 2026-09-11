from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable, Sequence

import yaml

from .ollama import OllamaClient
from .storage import KnowledgeIndexStore, StructuredKnowledgeStore


_SOURCE_URL = re.compile(r"https?://[^\s]+")
_POLICY_STEM = "機器人顧問守則"
_INDEX_EXCLUDED_STEMS = {_POLICY_STEM, "目前知識庫版本"}
_DOCUMENT_SUFFIXES = {".md", ".txt"}


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
        for suffix in (".md", ".txt"):
            policy_path = self._documents_path / f"{_POLICY_STEM}{suffix}"
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
            key=lambda chunk: _retrieval_score(query, query_embedding, chunk),
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
        currency_answer = self._exact_currency_answer(question)
        if currency_answer is not None:
            return currency_answer
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

    def _exact_currency_answer(self, question: str) -> str | None:
        amount_match = re.search(
            r"(\d+(?:\.\d+)?)\s*(台幣|台币|人民幣|人民币|天空石|統御|统御|星幣|星币|tks|ty|xb|[tr])",
            question,
            flags=re.IGNORECASE,
        )
        if amount_match is None:
            return None

        source_currency = _normalize_currency(amount_match.group(2))
        if source_currency is None:
            return None
        target_currency = None
        for token in re.finditer(
            r"台幣|台币|人民幣|人民币|天空石|統御|统御|星幣|星币|tks|ty|xb|[tr]",
            question,
            flags=re.IGNORECASE,
        ):
            if token.start() == amount_match.start(2):
                continue
            candidate = _normalize_currency(token.group())
            if candidate and candidate != source_currency:
                target_currency = candidate
                break
        if target_currency is None:
            return None

        result = self._convert_currency(
            amount_match.group(1), source_currency, target_currency
        )
        if result["status"] != "found":
            return None
        return (
            f"{_format_decimal(Decimal(amount_match.group(1)))} {source_currency} = "
            f"{result['converted_amount']} {target_currency}。"
            f"換算：{result['formula']}。來源：{result['source']}"
        )

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
            {
                "type": "function",
                "function": {
                    "name": "convert_currency",
                    "description": "依市場價格的結構化匯率換算貨幣。不得自行乘除或猜測匯率方向；凡是 xb、T、R、tks、ty 的換算都必須呼叫此工具。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "amount": {"type": "number", "description": "要換算的金額"},
                            "from_currency": {"type": "string", "description": "原貨幣：T、R、xb、tks 或 ty"},
                            "to_currency": {"type": "string", "description": "目標貨幣：T、R、xb、tks 或 ty"},
                        },
                        "required": ["amount", "from_currency", "to_currency"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "calculate_total_cost",
                    "description": "將多筆已知成本換算並加總為同一貨幣。所有成本估算都必須使用此工具，不能自行加總或換算。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "items": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "amount": {"type": "number"},
                                        "currency": {"type": "string"},
                                        "label": {"type": "string"},
                                    },
                                    "required": ["amount", "currency"],
                                },
                            },
                            "target_currency": {"type": "string", "description": "合計的目標貨幣"},
                        },
                        "required": ["items", "target_currency"],
                    },
                },
            },
        ]

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "get_pet_growth":
            return self._get_pet_growth(str(arguments.get("pet_type", "")), arguments.get("tier"))
        if name == "calculate_pet_available_points":
            return self._calculate_pet_points(arguments.get("rebirth"), arguments.get("levels_gained"))
        if name == "convert_currency":
            return self._convert_currency(
                arguments.get("amount"),
                str(arguments.get("from_currency", "")),
                str(arguments.get("to_currency", "")),
            )
        if name == "calculate_total_cost":
            return self._calculate_total_cost(
                arguments.get("items"), str(arguments.get("target_currency", ""))
            )
        return {"status": "unknown_tool", "tool": name}

    def _convert_currency(
        self, amount_value: Any, from_currency_value: str, to_currency_value: str
    ) -> dict[str, object]:
        try:
            amount = Decimal(str(amount_value))
        except (InvalidOperation, ValueError):
            return {"status": "invalid_argument", "argument": "amount"}
        from_currency = _normalize_currency(from_currency_value)
        to_currency = _normalize_currency(to_currency_value)
        if from_currency is None or to_currency is None or amount < 0:
            return {"status": "invalid_argument"}
        if from_currency == to_currency:
            return {
                "status": "found",
                "converted_amount": _format_decimal(amount),
                "formula": f"{_format_decimal(amount)} {from_currency}",
                "source": "同一貨幣無須換算",
            }
        rate_info = self._structured_store.currency_exchange_rate(
            from_currency, to_currency
        )
        if rate_info is None:
            return {
                "status": "unknown_exchange_rate",
                "from_currency": from_currency,
                "to_currency": to_currency,
            }
        rate = Decimal(str(rate_info["rate"]))
        converted = amount * rate
        return {
            "status": "found",
            "from_currency": from_currency,
            "to_currency": to_currency,
            "converted_amount": _format_decimal(converted),
            "formula": (
                f"{_format_decimal(amount)} {from_currency} × "
                f"{_format_decimal(rate)} = {_format_decimal(converted)} {to_currency}"
            ),
            "source": rate_info.get("source"),
        }

    def _calculate_total_cost(
        self, items_value: Any, target_currency_value: str
    ) -> dict[str, object]:
        target_currency = _normalize_currency(target_currency_value)
        if not isinstance(items_value, list) or target_currency is None:
            return {"status": "invalid_argument"}
        converted_items: list[dict[str, object]] = []
        total = Decimal("0")
        for item in items_value:
            if not isinstance(item, dict):
                return {"status": "invalid_argument", "argument": "items"}
            result = self._convert_currency(
                item.get("amount"), str(item.get("currency", "")), target_currency
            )
            if result["status"] != "found":
                return result
            total += Decimal(str(result["converted_amount"]))
            converted_items.append(
                {
                    "label": str(item.get("label", "")),
                    "converted_amount": result["converted_amount"],
                    "currency": target_currency,
                    "formula": result["formula"],
                }
            )
        return {
            "status": "found",
            "target_currency": target_currency,
            "total": _format_decimal(total),
            "items": converted_items,
        }

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
    for path in sorted(documents_path.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _DOCUMENT_SUFFIXES:
            continue
        if path.stem in _INDEX_EXCLUDED_STEMS:
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
        if paragraph.startswith("#") and current:
            chunks.append("\n\n".join(current))
            current = []
            current_size = 0
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


def _retrieval_score(
    query: str,
    query_embedding: Sequence[float],
    chunk: dict[str, object],
) -> float:
    candidate = f"{chunk.get('document_name', '')}\n{chunk.get('content', '')}"
    return _cosine(query_embedding, chunk["embedding"]) + _lexical_overlap(query, candidate)


def _lexical_overlap(query: str, candidate: str) -> float:
    normalized_query = _normalize_for_search(query)
    normalized_candidate = _normalize_for_search(candidate)
    weighted_matches = 0
    weighted_total = 0
    for size in (2, 3):
        grams = {
            normalized_query[index : index + size]
            for index in range(len(normalized_query) - size + 1)
        }
        for gram in grams:
            weighted_total += size
            if gram in normalized_candidate:
                weighted_matches += size
    return weighted_matches / weighted_total if weighted_total else 0.0


def _normalize_for_search(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.lower())


def _normalize(value: str) -> str:
    return re.sub(r"[\s_-]", "", value).lower()


def _normalize_currency(value: str) -> str | None:
    aliases = {
        "t": "T",
        "台幣": "T",
        "台币": "T",
        "r": "R",
        "人民幣": "R",
        "人民币": "R",
        "xb": "xb",
        "星幣": "xb",
        "星币": "xb",
        "tks": "tks",
        "天空石": "tks",
        "ty": "ty",
        "統御": "ty",
        "统御": "ty",
    }
    return aliases.get(value.strip().lower())


def _format_decimal(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(rounded, "f").rstrip("0").rstrip(".")
