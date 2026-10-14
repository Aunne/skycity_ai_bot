from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, create_engine, delete, select
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


class DocumentRow(Base):
    __tablename__ = "qa_documents"

    id: Mapped[str] = mapped_column(String(512), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding_model: Mapped[str] = mapped_column(String(256))
    text: Mapped[str] = mapped_column(Text)


class BlockRow(Base):
    __tablename__ = "qa_blocks"

    id: Mapped[str] = mapped_column(String(600), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(512), ForeignKey("qa_documents.id"), index=True)
    section_id: Mapped[str] = mapped_column(String(600), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    heading: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    line_start: Mapped[int] = mapped_column(Integer)
    line_end: Mapped[int] = mapped_column(Integer)
    embedding_json: Mapped[str] = mapped_column(Text)


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(
            f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False}
        )
        self._sessions = sessionmaker(bind=self._engine, expire_on_commit=False)

    def create_schema(self) -> None:
        Base.metadata.create_all(self._engine)

    def close(self) -> None:
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

    def record_exchange(self, guild_id: str, user_id: str, user_text: str, assistant_text: str) -> None:
        with self._database.session() as session:
            session.add_all([
                ChatMessage(guild_id=guild_id, user_id=user_id, role="user", content=user_text),
                ChatMessage(guild_id=guild_id, user_id=user_id, role="assistant", content=assistant_text),
            ])

    def forget_user(self, user_id: str) -> int:
        with self._database.session() as session:
            ids = session.scalars(select(ChatMessage.id).where(ChatMessage.user_id == user_id)).all()
            session.execute(delete(ChatMessage).where(ChatMessage.user_id == user_id))
        return len(ids)


def _block_dict(row: BlockRow, version: str) -> dict[str, object]:
    return {
        "id": row.id, "document_id": row.document_id, "section_id": row.section_id,
        "kind": row.kind, "heading": row.heading, "content": row.content,
        "line_start": row.line_start, "line_end": row.line_end,
        "version": version,
        "embedding": json.loads(row.embedding_json),
    }


class KnowledgeIndexStore:
    def __init__(self, database: Database):
        self._database = database

    def documents(self) -> dict[str, tuple[str, str]]:
        with self._database.session() as session:
            return {row.id: (row.content_hash, row.embedding_model) for row in session.scalars(select(DocumentRow))}

    def replace_document(self, document_id: str, content_hash: str, model: str, text: str, blocks: list[dict[str, object]]) -> None:
        # One transaction makes an updated document visible only after all its blocks are ready.
        with self._database.session() as session:
            session.execute(delete(BlockRow).where(BlockRow.document_id == document_id))
            session.execute(delete(DocumentRow).where(DocumentRow.id == document_id))
            session.add(DocumentRow(id=document_id, content_hash=content_hash, embedding_model=model, text=text))
            session.add_all(BlockRow(
                id=str(block["id"]), document_id=document_id,
                section_id=str(block["section_id"]), kind=str(block["kind"]),
                heading=str(block["heading"]), content=str(block["content"]),
                line_start=int(block["line_start"]), line_end=int(block["line_end"]),
                embedding_json=json.dumps(block["embedding"]),
            ) for block in blocks)

    def delete_document(self, document_id: str) -> None:
        with self._database.session() as session:
            session.execute(delete(BlockRow).where(BlockRow.document_id == document_id))
            session.execute(delete(DocumentRow).where(DocumentRow.id == document_id))

    def iter_blocks(self, batch_size: int = 256) -> Iterator[dict[str, object]]:
        with self._database.session() as session:
            query = select(BlockRow, DocumentRow.content_hash).join(DocumentRow).order_by(BlockRow.id)
            for row, version in session.execute(query).yield_per(batch_size):
                yield _block_dict(row, version)

    def read_section(self, document_id: str, section_id: str) -> list[dict[str, object]]:
        with self._database.session() as session:
            rows = session.execute(select(BlockRow, DocumentRow.content_hash).join(DocumentRow).where(
                BlockRow.document_id == document_id, BlockRow.section_id == section_id
            ).order_by(BlockRow.line_start)).all()
            return [_block_dict(row, version) for row, version in rows]

    def get_block(self, document_id: str, block_id: str) -> dict[str, object] | None:
        with self._database.session() as session:
            result = session.execute(select(BlockRow, DocumentRow.content_hash).join(DocumentRow).where(
                BlockRow.document_id == document_id, BlockRow.id == block_id
            )).first()
            return _block_dict(*result) if result else None

    def get_document(self, document_id: str) -> str | None:
        with self._database.session() as session:
            row = session.get(DocumentRow, document_id)
            return row.text if row else None

    def count_blocks(self) -> int:
        from sqlalchemy import func
        with self._database.session() as session:
            return int(session.scalar(select(func.count()).select_from(BlockRow)) or 0)
