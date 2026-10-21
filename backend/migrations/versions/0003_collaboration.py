from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"


def upgrade():
    op.add_column(
        "events",
        sa.Column("kind", sa.String(20), nullable=False, server_default="legacy"),
    )
    op.add_column(
        "events",
        sa.Column("internal", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "attachments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticket_id", sa.Integer, sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("uploader_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("storage_key", sa.String(64), nullable=False, unique=True),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_attachments_ticket_id", "attachments", ["ticket_id"])


def downgrade():
    op.drop_table("attachments")
    with op.batch_alter_table("events") as batch:
        batch.drop_column("internal")
        batch.drop_column("kind")
