import uuid

from sqlalchemy import ARRAY, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDMixin


class Bot(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "bots"

    name: Mapped[str] = mapped_column(String(255))
    widget_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    allowed_origins: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    llm_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    embedding_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    theme: Mapped[dict] = mapped_column(JSONB, default=dict)
    retrieval_config: Mapped[dict] = mapped_column(JSONB, default=dict)


class BotMember(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "bot_members"
    __table_args__ = (UniqueConstraint("user_id", "bot_id", name="uq_bot_member"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    bot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
