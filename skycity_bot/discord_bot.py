from __future__ import annotations

import logging

import discord

from .assistant import AnswerRequest, SkyCityAssistant
from .knowledge import GameKnowledge
from .ollama import OllamaClient, OllamaError
from .settings import Settings, load_settings
from .storage import Database, KnowledgeIndexStore, MemoryStore, StructuredKnowledgeStore


logger = logging.getLogger(__name__)


class SkyCityDiscordClient(discord.Client):
    def __init__(self, database: Database, **options: object):
        super().__init__(**options)
        self._database = database

    async def close(self) -> None:
        try:
            await super().close()
        finally:
            self._database.close()


class DiscordCommandRouter:
    def __init__(self, settings: Settings, assistant: SkyCityAssistant):
        self._settings = settings
        self._assistant = assistant

    async def handle(self, message: discord.Message) -> None:
        if not self._settings.channel_is_allowed(message.channel.id):
            return

        content = message.content.strip()
        if content.startswith("顧問"):
            await self._chat(message, content.removeprefix("顧問").strip(), remember=True)
        elif content.startswith("/test"):
            await self._chat(message, content.removeprefix("/test").strip(), remember=False)
        elif content == "/inviteurl":
            await self._create_invite(message)
        elif content == "/forget":
            await self._forget(message)
        elif content == "/setPass" or content.startswith("/setPass "):
            await self._grant_role(message)

    async def _chat(self, message: discord.Message, question: str, remember: bool) -> None:
        if not question:
            await message.channel.send("請在指令後輸入問題。")
            return
        if question == "你好":
            await message.channel.send("你好，有什麼可以幫助您的？")
            return

        request = AnswerRequest(
            guild_id=str(message.guild.id) if message.guild else "dm",
            user_id=str(message.author.id),
            text=question,
            remember=remember,
        )
        try:
            async with message.channel.typing():
                answer = await self._assistant.answer(request)
        except OllamaError:
            logger.exception("Ollama request failed")
            await message.channel.send("本地 AI 服務目前無法使用，請稍後再試。")
            return
        except Exception:
            logger.exception("Advisor request failed")
            await message.channel.send("處理問題時發生錯誤，請稍後再試。")
            return

        for start in range(0, len(answer), 2000):
            await message.channel.send(answer[start : start + 2000])

    async def _forget(self, message: discord.Message) -> None:
        deleted = self._assistant.forget_user(str(message.author.id))
        if deleted:
            await message.channel.send(f"已清除你的所有對話紀錄（共 {deleted} 則訊息）。")
        else:
            await message.channel.send("目前沒有保存你的對話紀錄。")

    async def _create_invite(self, message: discord.Message) -> None:
        role_names = {role.name for role in getattr(message.author, "roles", [])}
        if "invite" not in role_names:
            await message.channel.send("您沒有建立邀請的權限，請洽有權限的人！")
            return

        invite = await message.channel.create_invite(max_uses=1, max_age=86400, unique=True)
        logger.info("%s 在 %s 產生邀請：%s", message.author, message.channel, invite.url)
        await message.channel.send("邀請連結已傳送至私人訊息！")
        await message.author.send(f"邀請連結：{invite.url}")

    async def _grant_role(self, message: discord.Message) -> None:
        role_names = {role.name for role in getattr(message.author, "roles", [])}
        if "foot-businessman" not in role_names:
            await message.channel.send("您沒有權限使用此指令！")
            return
        if message.channel.id != 713523805233872966:
            return
        if not message.guild or not message.mentions:
            await message.channel.send("請標記一位成員（@某人）")
            return

        role = discord.utils.get(message.guild.roles, name="天空之城居民")
        if role is None:
            await message.channel.send("找不到身分組 天空之城居民")
            return
        await message.mentions[0].add_roles(role)
        await message.channel.send(
            f"已給 {message.mentions[0].mention} 身分組 {role.name}"
        )


def build_client(settings: Settings) -> discord.Client:
    database = Database(settings.database_path)
    database.create_schema()
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
    router = DiscordCommandRouter(settings, assistant)

    intents = discord.Intents.default()
    intents.message_content = True
    client = SkyCityDiscordClient(database, intents=intents)

    @client.event
    async def on_ready() -> None:
        logger.info("Discord bot logged in as %s", client.user)

    @client.event
    async def on_message(message: discord.Message) -> None:
        if message.author == client.user:
            return
        await router.handle(message)

    return client


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler("bot.log", encoding="utf-8"), logging.StreamHandler()],
    )
    settings = load_settings()
    if not settings.discord_token or settings.discord_token.startswith("your_"):
        raise ValueError("config.yaml 缺少有效的 DISCORD_BOT_TOKEN")
    build_client(settings).run(settings.discord_token)
