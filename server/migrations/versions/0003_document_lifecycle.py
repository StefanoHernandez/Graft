"""document lifecycle fields and message attempt status

Additive only: every new document column is nullable (or has a server default) so
rows written before this revision keep their content. Legacy documents simply have
no original on disk and no embedding fingerprint, which later excludes them from
retrieval instead of deleting them.

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

MESSAGE_STATUSES = ("completed", "failed", "cancelled")


def upgrade() -> None:
    op.add_column("documents", sa.Column("storage_key", sa.String(512), nullable=True))
    op.add_column("documents", sa.Column("source_sha256", sa.String(64), nullable=True))
    op.add_column("documents", sa.Column("embedding_fingerprint", sa.String(64), nullable=True))
    op.add_column("documents", sa.Column("ingestion_run_id", UUID(as_uuid=True), nullable=True))
    op.add_column(
        "documents",
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column(
        "documents",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The dispatcher sweeps for pending documents and expired leases by status.
    op.create_index("ix_documents_status", "documents", ["status"])

    op.add_column("messages", sa.Column("request_id", UUID(as_uuid=True), nullable=True))
    op.add_column(
        "messages",
        sa.Column("status", sa.String(16), nullable=False, server_default="completed"),
    )
    statuses = ", ".join(f"'{s}'" for s in MESSAGE_STATUSES)
    op.create_check_constraint("ck_messages_status", "messages", f"status IN ({statuses})")


def downgrade() -> None:
    op.drop_constraint("ck_messages_status", "messages", type_="check")
    op.drop_column("messages", "status")
    op.drop_column("messages", "request_id")

    op.drop_index("ix_documents_status", table_name="documents")
    for column in (
        "lease_expires_at",
        "attempt_count",
        "ingestion_run_id",
        "embedding_fingerprint",
        "source_sha256",
        "storage_key",
    ):
        op.drop_column("documents", column)
