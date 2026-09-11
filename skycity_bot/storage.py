from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

from sqlalchemy import DateTime, Float, Integer, String, Text, create_engine, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class KnowledgeChunkRow(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_name: Mapped[str] = mapped_column(String(255), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_json: Mapped[str] = mapped_column(Text)


class PetCategoryRow(Base):
    __tablename__ = "pet_categories"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    aliases_json: Mapped[str] = mapped_column(Text)
    valid_tiers_json: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class PetGrowthRow(Base):
    __tablename__ = "pet_growth"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_key: Mapped[str] = mapped_column(String(64), index=True)
    tier: Mapped[int] = mapped_column(Integer, index=True)
    maximum_growth: Mapped[float] = mapped_column(Float)


class PetPointRateRow(Base):
    __tablename__ = "pet_point_rates"

    rebirth: Mapped[int] = mapped_column(Integer, primary_key=True)
    points_per_level: Mapped[int] = mapped_column(Integer)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class CurrencyExchangeRateRow(Base):
    __tablename__ = "currency_exchange_rates"

    from_currency: Mapped[str] = mapped_column(String(16), primary_key=True)
    to_currency: Mapped[str] = mapped_column(String(16), primary_key=True)
    rate: Mapped[float] = mapped_column(Float)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(
            f"sqlite:///{path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        self._sessions = sessionmaker(bind=self._engine, expire_on_commit=False)

    def create_schema(self) -> None:
        Base.metadata.create_all(self._engine)

    def close(self) -> None:
        """Release pooled SQLite connections and file handles."""
        self._engine.dispose()

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._sessions()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


class MemoryStore:
    def __init__(self, database: Database):
        self._database = database

    def recent_context(self, guild_id: str, user_id: str, limit: int) -> list[dict[str, str]]:
        with self._database.session() as session:
            rows = session.scalars(
                select(ChatMessage)
                .where(ChatMessage.guild_id == guild_id, ChatMessage.user_id == user_id)
                .order_by(ChatMessage.id.desc())
                .limit(limit)
            ).all()
        return [{"role": row.role, "content": row.content} for row in reversed(rows)]

    def record_exchange(
        self, guild_id: str, user_id: str, user_text: str, assistant_text: str
    ) -> None:
        with self._database.session() as session:
            session.add_all(
                [
                    ChatMessage(guild_id=guild_id, user_id=user_id, role="user", content=user_text),
                    ChatMessage(
                        guild_id=guild_id,
                        user_id=user_id,
                        role="assistant",
                        content=assistant_text,
                    ),
                ]
            )

    def forget_user(self, user_id: str) -> int:
        """Delete every stored message belonging to one Discord user."""
        with self._database.session() as session:
            message_ids = session.scalars(
                select(ChatMessage.id).where(ChatMessage.user_id == user_id)
            ).all()
            session.execute(delete(ChatMessage).where(ChatMessage.user_id == user_id))
        return len(message_ids)


class KnowledgeIndexStore:
    def __init__(self, database: Database):
        self._database = database

    def replace(self, chunks: Sequence[dict[str, object]]) -> None:
        with self._database.session() as session:
            session.execute(delete(KnowledgeChunkRow))
            session.add_all(
                KnowledgeChunkRow(
                    document_name=str(chunk["document_name"]),
                    chunk_index=int(chunk["chunk_index"]),
                    content=str(chunk["content"]),
                    source_url=str(chunk["source_url"]) if chunk.get("source_url") else None,
                    embedding_json=json.dumps(chunk["embedding"]),
                )
                for chunk in chunks
            )

    def all(self) -> list[dict[str, object]]:
        with self._database.session() as session:
            rows = session.scalars(select(KnowledgeChunkRow)).all()
        return [
            {
                "document_name": row.document_name,
                "chunk_index": row.chunk_index,
                "content": row.content,
                "source_url": row.source_url,
                "embedding": json.loads(row.embedding_json),
            }
            for row in rows
        ]


class StructuredKnowledgeStore:
    def __init__(self, database: Database):
        self._database = database

    def replace_from_mapping(self, data: dict[str, object]) -> None:
        pets = data.get("pets", {})
        if not isinstance(pets, dict):
            raise ValueError("structured.yaml 的 pets 必須是物件")

        categories = pets.get("categories", [])
        rates = pets.get("points_per_level", {})
        points_source = pets.get("points_source")
        exchange = data.get("currency_exchange", {})
        exchange_rates = exchange.get("rates", []) if isinstance(exchange, dict) else []
        with self._database.session() as session:
            session.execute(delete(PetGrowthRow))
            session.execute(delete(PetCategoryRow))
            session.execute(delete(PetPointRateRow))
            session.execute(delete(CurrencyExchangeRateRow))

            for category in categories:
                if not isinstance(category, dict):
                    continue
                key = str(category.get("key") or category["name"])
                valid_tiers = [int(tier) for tier in category.get("valid_tiers", [])]
                session.add(
                    PetCategoryRow(
                        key=key,
                        name=str(category["name"]),
                        aliases_json=json.dumps(category.get("aliases", []), ensure_ascii=False),
                        valid_tiers_json=json.dumps(valid_tiers),
                        source_url=str(category["source"]) if category.get("source") else None,
                    )
                )
                for tier_name, growth in category.get("growth_by_tier", {}).items():
                    session.add(
                        PetGrowthRow(
                            category_key=key,
                            tier=int(str(tier_name).removeprefix("L")),
                            maximum_growth=float(growth),
                        )
                    )

            if isinstance(rates, dict):
                for rebirth, points in rates.items():
                    session.add(
                        PetPointRateRow(
                            rebirth=int(rebirth),
                            points_per_level=int(points),
                            source_url=str(points_source) if points_source else None,
                        )
                    )

            if isinstance(exchange_rates, list):
                for exchange_rate in exchange_rates:
                    if not isinstance(exchange_rate, dict):
                        continue
                    session.add(
                        CurrencyExchangeRateRow(
                            from_currency=str(exchange_rate["from_currency"]).lower(),
                            to_currency=str(exchange_rate["to_currency"]).lower(),
                            rate=float(exchange_rate["rate"]),
                            source_url=(
                                str(exchange_rate["source"])
                                if exchange_rate.get("source")
                                else None
                            ),
                        )
                    )

    def pet_categories(self) -> list[dict[str, object]]:
        with self._database.session() as session:
            categories = session.scalars(select(PetCategoryRow)).all()
            growth_rows = session.scalars(select(PetGrowthRow)).all()
        growth_by_key: dict[str, dict[int, float]] = {}
        for row in growth_rows:
            growth_by_key.setdefault(row.category_key, {})[row.tier] = row.maximum_growth
        return [
            {
                "key": row.key,
                "name": row.name,
                "aliases": json.loads(row.aliases_json),
                "valid_tiers": json.loads(row.valid_tiers_json),
                "source": row.source_url,
                "growth_by_tier": growth_by_key.get(row.key, {}),
            }
            for row in categories
        ]

    def pet_point_rate(self, rebirth: int) -> dict[str, object] | None:
        with self._database.session() as session:
            row = session.get(PetPointRateRow, rebirth)
            if row is None:
                return None
            return {
                "points_per_level": row.points_per_level,
                "source": row.source_url,
            }

    def currency_exchange_rate(
        self, from_currency: str, to_currency: str
    ) -> dict[str, object] | None:
        from_currency = from_currency.lower()
        to_currency = to_currency.lower()
        with self._database.session() as session:
            direct = session.get(
                CurrencyExchangeRateRow,
                {"from_currency": from_currency, "to_currency": to_currency},
            )
            if direct is not None:
                return {"rate": direct.rate, "source": direct.source_url}
            reverse = session.get(
                CurrencyExchangeRateRow,
                {"from_currency": to_currency, "to_currency": from_currency},
            )
            if reverse is None:
                return None
            return {"rate": 1 / reverse.rate, "source": reverse.source_url}
