import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text


def test_upgrade_preserves_existing_ticket_history(tmp_path):
    root = Path(__file__).resolve().parents[1]
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    env = {**os.environ, "DATABASE_URL": url}

    def migrate(target, direction="upgrade"):
        subprocess.run(
            [sys.executable, "-m", "alembic", direction, target],
            cwd=root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

    migrate("0001")
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO users (id,username,password_hash,role) VALUES (1,'legacy','unused','requester')"
            )
        )
        db.execute(
            text(
                "INSERT INTO tickets (id,title,description,category,priority,status,creator_id,created_at) VALUES (1,'Existing','Keep content','erp','normal','open',1,'2026-10-20 12:00:00')"
            )
        )
        db.execute(
            text(
                "INSERT INTO events (id,ticket_id,actor_id,message) VALUES (1,1,1,'Historical event')"
            )
        )
    migrate("head")
    with engine.connect() as db:
        ticket = db.execute(
            text("SELECT title,version,created_at,updated_at FROM tickets")
        ).one()
        assert ticket.title == "Existing" and ticket.version == 1
        assert ticket.updated_at == ticket.created_at
        assert db.execute(text("SELECT created_at FROM events")).scalar() is None
        assert db.execute(text("SELECT active FROM users")).scalar() == 1
        assert db.execute(text("SELECT internal FROM events")).scalar() == 0
        assert db.execute(text("SELECT kind FROM events")).scalar() == "legacy"
    migrate("0001", "downgrade")
    migrate("head")
    with engine.connect() as db:
        assert (
            db.execute(text("SELECT message FROM events")).scalar()
            == "Historical event"
        )
    engine.dispose()
