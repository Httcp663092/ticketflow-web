from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"


def upgrade():
    op.add_column(
        "users",
        sa.Column("display_name", sa.String(80), nullable=False, server_default=""),
    )
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column(
            "registration_pending",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        "rate_buckets",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("bucket", sa.Integer, primary_key=True),
        sa.Column("attempts", sa.Integer, nullable=False),
    )


def downgrade():
    op.drop_table("rate_buckets")
    with op.batch_alter_table("users") as batch:
        for name in ["registration_pending", "token_version", "display_name"]:
            batch.drop_column(name)
