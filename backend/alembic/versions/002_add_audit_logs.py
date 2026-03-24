"""Add audit_logs table

Revision ID: 002
Revises: 001
Create Date: 2024-01-02 00:00:00.000000

Adds a persistent, append-only audit log table with an HMAC-SHA256
``integrity_hash`` column for tamper-evidence detection.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_username", sa.String(), nullable=True),
        sa.Column("resource", sa.String(), nullable=True),
        sa.Column("resource_id", sa.String(), nullable=True),
        sa.Column("action", sa.String(), nullable=True),
        sa.Column("client_ip", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("detail", sa.String(), nullable=True),
        sa.Column("integrity_hash", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Single-column indices
    op.create_index(op.f("ix_audit_logs_id"), "audit_logs", ["id"], unique=False)
    op.create_index(
        op.f("ix_audit_logs_event_type"), "audit_logs", ["event_type"], unique=False
    )
    op.create_index(
        op.f("ix_audit_logs_timestamp"), "audit_logs", ["timestamp"], unique=False
    )
    op.create_index(
        op.f("ix_audit_logs_actor_id"), "audit_logs", ["actor_id"], unique=False
    )
    op.create_index(
        op.f("ix_audit_logs_actor_username"),
        "audit_logs",
        ["actor_username"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_logs_resource"), "audit_logs", ["resource"], unique=False
    )
    op.create_index(
        op.f("ix_audit_logs_resource_id"), "audit_logs", ["resource_id"], unique=False
    )

    # Composite indices for common search patterns
    op.create_index(
        "ix_audit_logs_event_type_timestamp",
        "audit_logs",
        ["event_type", "timestamp"],
        unique=False,
    )
    op.create_index(
        "ix_audit_logs_actor_id_timestamp",
        "audit_logs",
        ["actor_id", "timestamp"],
        unique=False,
    )
    op.create_index(
        "ix_audit_logs_resource_resource_id",
        "audit_logs",
        ["resource", "resource_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_resource_resource_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_id_timestamp", table_name="audit_logs")
    op.drop_index("ix_audit_logs_event_type_timestamp", table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_resource_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_resource"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_actor_username"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_actor_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_timestamp"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_event_type"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_id"), table_name="audit_logs")
    op.drop_table("audit_logs")
