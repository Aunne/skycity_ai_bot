from __future__ import annotations

import hashlib
import heapq
import logging
import math
import re
from pathlib import Path
from typing import Any, Iterator, Sequence

from .ollama import OllamaClient
from .storage import KnowledgeIndexStore


logger = logging.getLogger(__name__)
_SUFFIXES = {".md", ".txt"}
_EXCLUDED = {"機器人顧問守則", "目前知識庫版本"}
_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
_IDENTIFIER = re.compile(r"(?<![a-zA-Z0-9])(?:[a-zA-Z]+\d+|\d+[a-zA-Z]+)(?![a-zA-Z0-9])")
_NUMBER = re.compile(r"(?<![a-zA-Z0-9])\d+(?:\.\d+)?(?![a-zA-Z0-9])")


def _terms(text: str) -> set[str]:
    normalized = text.casefold()
    words = set(re.findall(r"[a-z]+\d*|\d+(?:\.\d+)?", normalized))
    for run in re.findall(r"[\u3400-\u9fff]+", normalized):
        words.update(run[i:i + 2] for i in range(len(run) - 1))
        words.update(run[i:i + 3] for i in range(len(run) - 2))
    return words


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    denominator = math.sqrt(sum(x * x for x in left) * sum(x * x for x in right))
    return sum(a * b for a, b in zip(left, right)) / denominator if denominator else 0.0


def _split_columns(line: str) -> list[str]:
    if "|" in line:
        return [part.strip() for part in line.strip().strip("|").split("|")]
    return [part.strip() for part in re.split(r"\s{2,}|\s+[\\／]\s+", line.strip()) if part.strip()]


def _table_rows(lines: list[str]) -> list[list[str]] | None:
    rows = [_split_columns(line) for line in lines]
    rows = [row for row in rows if row and not all(re.fullmatch(r"[-:=+]+", cell) for cell in row)]
    if len(rows) < 2 or len(rows[0]) < 2:
        return None
    width = len(rows[0])
    if sum(len(row) == width for row in rows[1:]) < 1:
        return None
    return [row for row in rows if len(row) == width]


def _parse_blocks(document_id: str, text: str) -> list[dict[str, object]]:
    lines = text.splitlines()
    headings: list[str] = []
    section_id = f"{document_id}:0"
    blocks: list[dict[str, object]] = []
    start = 0
    index = 0

    def flush(end: int) -> None:
        nonlocal index
        if start >= end:
            return
        raw = "\n".join(lines[start:end]).strip()
        if not raw:
            return
        table = _table_rows(lines[start:end])
        # Long tables are indexed in pages. Each page repeats the header.
        pages = [table[:1] + table[i:i + 20] for i in range(1, len(table), 20)] if table and len(table) > 21 else [None]
        for page_number, page in enumerate(pages):
            content = raw if page is None else "\n".join(" | ".join(row) for row in page)
            blocks.append({
                "id": f"{document_id}:{index}", "document_id": document_id,
                "section_id": section_id, "kind": "table" if table else "text",
                "heading": " › ".join(headings), "content": content,
                "line_start": start + 1 if page is None else start + 2 + page_number * 20,
                "line_end": end if page is None else min(end, start + 1 + (page_number + 1) * 20),
            })
            index += 1

    for i, line in enumerate(lines):
        match = _HEADING.match(line)
        if match:
            flush(i)
            level = len(match.group(1))
            headings = headings[:level - 1] + [match.group(2).strip()]
            section_id = f"{document_id}:{i + 1}"
            start = i
        elif not line.strip():
            flush(i)
            start = i + 1
    flush(len(lines))
    return blocks


class GameKnowledge:
    """Document-only index, hybrid retrieval and source reading."""

    def __init__(self, documents_path: Path, index_store: KnowledgeIndexStore, ollama: OllamaClient, embedding_model: str):
        self._documents_path = documents_path
        self._index = index_store
        self._ollama = ollama
        self._embedding_model = embedding_model

    def system_policy(self) -> str:
        return "你是天空之城遊戲顧問。只根據已讀取的文件證據回答。"

    async def rebuild_index(self) -> int:
        known = self._index.documents()
        seen: set[str] = set()
        if self._documents_path.exists():
            for path in sorted(self._documents_path.rglob("*")):
                if not path.is_file() or path.name.startswith("."):
                    continue
                if path.suffix.lower() not in _SUFFIXES:
                    logger.warning("略過不支援格式：%s", path.name)
                    continue
                if path.stem in _EXCLUDED:
                    continue
                document_id = path.relative_to(self._documents_path).as_posix()
                seen.add(document_id)
                try:
                    data = path.read_bytes()
                    content_hash = hashlib.sha256(data).hexdigest()
                    if known.get(document_id) == (content_hash, self._embedding_model):
                        continue
                    text = data.decode("utf-8-sig")
                    blocks = _parse_blocks(document_id, text)
                    for start in range(0, len(blocks), 16):
                        batch = blocks[start:start + 16]
                        embeddings = await self._ollama.embed([
                            f"search_document: {block['heading']}\n{block['content']}" for block in batch
                        ])
                        if len(embeddings) != len(batch):
                            raise RuntimeError("Embedding 數量與文件區塊數量不一致")
                        for block, embedding in zip(batch, embeddings):
                            block["embedding"] = embedding
                    self._index.replace_document(document_id, content_hash, self._embedding_model, text, blocks)
                    logger.info("已索引 %s：%d 區塊", document_id, len(blocks))
                except Exception:
                    logger.exception("文件索引失敗，保留先前版本：%s", document_id)
                    raise
        for document_id in known.keys() - seen:
            self._index.delete_document(document_id)
            logger.info("已移除刪除文件的索引：%s", document_id)
        return self._index.count_blocks()

    async def search_documents(self, query: str, limit: int = 8) -> list[dict[str, object]]:
        known = self._index.documents()
        if not known:
            return []
        models = {model for _, model in known.values()}
        if models != {self._embedding_model}:
            raise RuntimeError("Embedding 模型已更換；請先執行 python -m skycity_bot.index_knowledge")
        vector = (await self._ollama.embed([f"search_query: {query}"]))[0]
        query_terms = _terms(query)
        identifiers = {match.group().casefold() for match in _IDENTIFIER.finditer(query)}
        scored: list[tuple[float, int, dict[str, object]]] = []
        for position, block in enumerate(self._index.iter_blocks()):
            content = f"{block['heading']} {block['content']} {block['document_id']}".casefold()
            block_terms = _terms(content)
            lexical = len(query_terms & block_terms) / max(1, len(query_terms))
            identifier_bonus = sum(0.35 for term in identifiers if term in block_terms)
            score = 0.45 * _cosine(vector, block["embedding"]) + 0.55 * lexical + identifier_bonus
            item = (score, position, block)
            if len(scored) < limit:
                heapq.heappush(scored, item)
            elif score > scored[0][0]:
                heapq.heapreplace(scored, item)
        result = [dict(block, score=round(score, 4)) for score, _, block in sorted(scored, reverse=True)]
        logger.info("查詢=%r；候選=%s", query, [(b["id"], b["score"]) for b in result])
        return result

    def read_section(self, document_id: str, section_id: str, cursor: int = 0, char_budget: int = 5000) -> dict[str, object]:
        blocks = self._index.read_section(document_id, section_id)
        output: list[dict[str, object]] = []
        used = 0
        position = cursor
        while position < len(blocks):
            block = blocks[position]
            length = len(str(block["content"]))
            if output and used + length > char_budget:
                break
            output.append(block)
            used += length
            position += 1
        return {"blocks": output, "next_cursor": position if position < len(blocks) else None, "truncated": position < len(blocks)}

    def read_neighbors(self, document_id: str, block_id: str, before: int = 1, after: int = 1) -> list[dict[str, object]]:
        target = self._index.get_block(document_id, block_id)
        if target is None:
            return []
        blocks = self._index.read_section(document_id, str(target["section_id"]))
        for i, block in enumerate(blocks):
            if block["id"] == block_id:
                return blocks[max(0, i - before):i + after + 1]
        return []

    def read_table(self, document_id: str, block_id: str, cursor: int = 0, row_limit: int = 20) -> dict[str, object]:
        block = self._index.get_block(document_id, block_id)
        if block is None:
            return {"rows": [], "next_cursor": None, "truncated": False}
        rows = self.table_rows(block)
        if not rows:
            return {"rows": [], "next_cursor": None, "truncated": False}
        start = max(1, cursor + 1)
        end = min(len(rows), start + max(1, row_limit))
        return {
            "header": rows[0], "rows": rows[start:end], "source": self.source_label(block),
            "version": block["version"], "next_cursor": end - 1 if end < len(rows) else None,
            "truncated": end < len(rows),
        }

    def source_label(self, block: dict[str, object]) -> str:
        heading = f" › {block['heading']}" if block["heading"] else ""
        return f"{block['document_id']}{heading}（第 {block['line_start']}–{block['line_end']} 行）"

    @staticmethod
    def identifiers(question: str) -> set[str]:
        return {match.group().casefold() for match in _IDENTIFIER.finditer(question)}

    @staticmethod
    def numbers(text: str) -> set[str]:
        return {match.group() for match in _NUMBER.finditer(text)}

    @staticmethod
    def table_rows(block: dict[str, object]) -> list[list[str]] | None:
        if block["kind"] != "table":
            return None
        return _table_rows(str(block["content"]).splitlines())
