from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"


def upgrade():
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
    )
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true())
        )
        batch.add_column(sa.Column("team_id", sa.Integer, nullable=True))
        batch.create_foreign_key("fk_users_team", "teams", ["team_id"], ["id"])
    with op.batch_alter_table("tickets") as batch:
        batch.add_column(sa.Column("team_id", sa.Integer, nullable=True))
        batch.add_column(
            sa.Column("version", sa.Integer, nullable=False, server_default="1")
        )
        batch.add_column(
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_foreign_key("fk_tickets_team", "teams", ["team_id"], ["id"])
    op.execute("UPDATE tickets SET updated_at=created_at")
    with op.batch_alter_table("tickets") as batch:
        batch.alter_column(
            "updated_at", existing_type=sa.DateTime(timezone=True), nullable=False
        )
    with op.batch_alter_table("events") as batch:
        batch.add_column(
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True)
        )
    # Historical events have no known timestamp; preserve NULL instead of inventing one.


def downgrade():
    with op.batch_alter_table("events") as batch:
        batch.drop_column("created_at")
    with op.batch_alter_table("tickets") as batch:
        batch.drop_constraint("fk_tickets_team", type_="foreignkey")
        for column in ["updated_at", "version", "team_id"]:
            batch.drop_column(column)
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("fk_users_team", type_="foreignkey")
        batch.drop_column("team_id")
        batch.drop_column("active")
    op.drop_table("teams")
