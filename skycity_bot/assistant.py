from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .knowledge import GameKnowledge
from .ollama import OllamaClient
from .storage import MemoryStore


@dataclass(frozen=True)
class AnswerRequest:
    guild_id: str
    user_id: str
    text: str
    remember: bool = True


class SkyCityAssistant:
    """Coordinates memory, grounded knowledge, tool calls, and answer generation."""

    def __init__(
        self,
        ollama: OllamaClient,
        knowledge: GameKnowledge,
        memory: MemoryStore,
        memory_limit: int,
        top_k: int,
    ):
        self._ollama = ollama
        self._knowledge = knowledge
        self._memory = memory
        self._memory_limit = memory_limit
        self._top_k = top_k

    async def answer(self, request: AnswerRequest) -> str:
        exact_answer = self._knowledge.exact_answer(request.text)
        if exact_answer is not None:
            if request.remember:
                self._memory.record_exchange(
                    request.guild_id,
                    request.user_id,
                    request.text,
                    exact_answer,
                )
            return exact_answer

        context = await self._knowledge.semantic_context(request.text, self._top_k)
        history = (
            self._memory.recent_context(request.guild_id, request.user_id, self._memory_limit)
            if request.remember
            else []
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_message(context)},
            *history,
            {"role": "user", "content": request.text},
        ]

        answer = ""
        for _ in range(4):
            response = await self._ollama.chat(messages, self._knowledge.tools())
            messages.append(response)
            tool_calls = response.get("tool_calls") or []
            if not tool_calls:
                answer = str(response.get("content", "")).strip()
                break

            for tool_call in tool_calls:
                function = tool_call.get("function", {})
                name = str(function.get("name", ""))
                arguments = function.get("arguments", {})
                if not isinstance(arguments, dict):
                    arguments = {}
                result = self._knowledge.execute_tool(name, arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": name,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

        if not answer:
            answer = "抱歉，我目前無法完成這個問題的查詢。"

        if request.remember:
            self._memory.record_exchange(request.guild_id, request.user_id, request.text, answer)
        return answer

    def forget_user(self, user_id: str) -> int:
        return self._memory.forget_user(user_id)

    def _system_message(self, context: str) -> str:
        retrieved = context or "本次沒有檢索到相關攻略文件。"
        return f"""{self._knowledge.system_policy()}

回答規則：
1. 結構化工具結果是數值與限制的唯一依據。
2. 工具回傳 invalid_tier 時，明確回答該類型不存在這個 L 等級。
3. 不得使用其他寵物類型或其他等級的數值替代。
4. 攻略內容只根據下方檢索片段回答，資料不足時直接說知識庫沒有紀錄。
5. 有來源時在答案末尾列出來源。
6. 若檢索片段提供多種符合需求的方案，先回答問題，再簡短補充可行的替代方案。
7. 「帶寵物」只代表提升寵物自身等級並增加可用點，絕對不是提升寵物 L 等級。
8. 玩家資料中的轉數與人物等級不得標示為寵物 L 等級。
9. 所有 T、R、xb、tks、ty 的換算與多項成本合計，必須呼叫貨幣換算工具；不得自行決定匯率方向、乘除或加總。

檢索到的攻略片段：
{retrieved}"""
