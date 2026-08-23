from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class ConversationMessageRow(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        Index("ix_conversation_messages_workspace", "workspace_id", "created_at"),
        Index("ix_conversation_messages_work", "work_id", "created_at"),
        Index(
            "ux_conversation_work_card",
            "work_id",
            unique=True,
            sqlite_where=text("message_kind = 'work_card'"),
        ),
        UniqueConstraint("source_event_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False
    )
    author_kind: Mapped[str] = mapped_column(String, nullable=False)
    message_kind: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    employee_id: Mapped[str | None] = mapped_column(
        ForeignKey("employees.id"), nullable=True
    )
    reply_to_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversation_messages.id"), nullable=True
    )
    work_id: Mapped[str | None] = mapped_column(ForeignKey("works.id"), nullable=True)
    source_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class ConversationMentionRow(Base):
    __tablename__ = "conversation_mentions"

    message_id: Mapped[str] = mapped_column(
        ForeignKey("conversation_messages.id"), primary_key=True
    )
    employee_id: Mapped[str] = mapped_column(String, primary_key=True)


class ChatExecutionRow(Base):
    __tablename__ = "chat_executions"
    __table_args__ = (
        UniqueConstraint("message_id", "employee_id"),
        Index("ix_chat_executions_status", "status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("conversation_messages.id"), nullable=False
    )
    employee_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)
