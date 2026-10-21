from alembic import op
import sqlalchemy as sa
revision="0001"
down_revision=None
def upgrade():
    op.create_table("users",sa.Column("id",sa.Integer,primary_key=True),sa.Column("username",sa.String(80),nullable=False,unique=True),sa.Column("password_hash",sa.String(255),nullable=False),sa.Column("role",sa.String(20),nullable=False))
    op.create_table("tickets",sa.Column("id",sa.Integer,primary_key=True),sa.Column("title",sa.String(200),nullable=False),sa.Column("description",sa.Text,nullable=False),sa.Column("category",sa.String(20),nullable=False),sa.Column("priority",sa.String(10),nullable=False),sa.Column("status",sa.String(20),nullable=False),sa.Column("creator_id",sa.Integer,sa.ForeignKey("users.id"),nullable=False),sa.Column("assignee_id",sa.Integer,sa.ForeignKey("users.id")),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_table("events",sa.Column("id",sa.Integer,primary_key=True),sa.Column("ticket_id",sa.Integer,sa.ForeignKey("tickets.id"),nullable=False),sa.Column("actor_id",sa.Integer,sa.ForeignKey("users.id"),nullable=False),sa.Column("message",sa.Text,nullable=False))
def downgrade():
    op.drop_table("events"); op.drop_table("tickets"); op.drop_table("users")
