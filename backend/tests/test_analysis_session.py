from datetime import datetime, timezone
import csv, io
import jwt
import os

os.environ.setdefault("SECRET_KEY", "test-key-only-not-for-production-123456789")
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db import Base, database
from app.main import app, passwords, secret
from app.models import User, Ticket, Team


@pytest.fixture()
def setup():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions() as db:
        db.add(Team(id=1, name="ERP"))
        for id, role in [(1, "admin"), (2, "requester"), (3, "agent")]:
            db.add(
                User(
                    id=id,
                    username=role,
                    display_name=role,
                    role=role,
                    password_hash=passwords.hash("test-password"),
                    team_id=1,
                )
            )
        db.commit()
        for id, created, status, priority in [
            (1, datetime(2026, 10, 20, 16, tzinfo=timezone.utc), "closed", "urgent"),
            (2, datetime(2026, 10, 21, 15, 59, tzinfo=timezone.utc), "open", "normal"),
            (3, datetime(2026, 10, 21, 16, tzinfo=timezone.utc), "open", "urgent"),
        ]:
            db.add(
                Ticket(
                    id=id,
                    title='=HYPERLINK("evil")' if id == 1 else "Test",
                    description="private text",
                    category="erp",
                    priority=priority,
                    status=status,
                    team_id=1,
                    creator_id=2,
                    created_at=created,
                )
            )
        db.commit()

    def override():
        with sessions() as db:
            yield db

    app.dependency_overrides[database] = override
    with TestClient(app, base_url="https://testserver") as c:
        yield c, sessions
    app.dependency_overrides.clear()
    engine.dispose()


def login(c, name="admin", remember=True):
    r = c.post(
        "/api/auth/login",
        json={"username": name, "password": "test-password", "remember": remember},
        headers={"Origin": "https://testserver"},
    )
    assert r.status_code == 200
    return r


def test_cookie_restoration_csrf_logout(setup):
    c, _ = setup
    r = login(c)
    cookie = r.headers["set-cookie"]
    assert (
        "HttpOnly" in cookie
        and "Secure" in cookie
        and "SameSite=strict" in cookie
        and "Max-Age=2592000" in cookie
    )
    assert "ticketflow_session" in c.cookies
    assert c.get("/api/auth/me").json()["role"] == "admin"
    data = jwt.decode(r.json()["access_token"], secret(), algorithms=["HS256"])
    assert data["exp"] > datetime.now(timezone.utc).timestamp() + 29 * 86400
    assert (
        c.post(
            "/api/teams",
            json={"name": "Unsafe"},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert c.post("/api/teams", json={"name": "Unsafe"}).status_code == 403
    old = r.json()["access_token"]
    assert (
        c.post("/api/auth/logout", headers={"Origin": "https://testserver"}).status_code
        == 200
    )
    assert c.get("/api/auth/me").status_code == 401
    assert (
        c.get("/api/auth/me", headers={"Authorization": "Bearer " + old}).status_code
        == 401
    )
    r = login(c, remember=False)
    assert "Max-Age=" not in r.headers["set-cookie"]
    assert (
        jwt.decode(r.json()["access_token"], secret(), algorithms=["HS256"])["exp"]
        < datetime.now(timezone.utc).timestamp() + 9 * 3600
    )


def test_disabled_account_and_password_revoke_cookie(setup):
    c, sessions = setup
    login(c)
    assert (
        c.post(
            "/api/auth/password",
            json={
                "current_password": "test-password",
                "new_password": "new-long-password",
            },
            headers={"Origin": "https://testserver"},
        ).status_code
        == 200
    )
    assert c.get("/api/auth/me").status_code == 401
    login(c, "agent")
    with sessions() as db:
        db.get(User, 3).active = False
        db.commit()
    assert c.get("/api/auth/me").status_code == 401


def test_admin_filters_timezone_export_and_scope(setup):
    c, _ = setup
    login(c)
    q = "?start=2026-10-21&end=2026-10-21"
    r = c.get("/api/admin/analytics" + q)
    assert r.status_code == 200
    data = r.json()
    assert data["summary"] == {
        "total": 2,
        "active": 1,
        "closed": 1,
        "closed_rate": 50.0,
        "unassigned_active": 1,
        "urgent_active": 0,
    }
    assert data["trend"] == [{"date": "2026-10-21", "count": 2}]
    assert (
        c.get(
            "/api/admin/analytics"
            + q
            + "&status=open&priority=normal&team_id=1&assignee_id=0"
        ).json()["summary"]["total"]
        == 1
    )
    assert (
        c.get("/api/admin/analytics" + q + "&team_id=0").json()["summary"]["total"] == 0
    )
    csv_response = c.get("/api/admin/analytics/export" + q)
    assert csv_response.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(csv_response.content.decode("utf-8-sig"))))
    assert len(rows) == 3
    assert any(row[1].startswith("'=HYPERLINK") for row in rows[1:])
    assert "private text" not in csv_response.text
    summary = c.get("/api/admin/analytics/export" + q + "&kind=summary")
    assert summary.status_code == 200 and "当前关闭率" in summary.text
    assert (
        c.get("/api/admin/analytics?start=2025-01-01&end=2026-10-21").status_code == 422
    )
    assert (
        c.get("/api/admin/analytics?start=2026-10-22&end=2026-10-21").status_code == 422
    )
    assert c.get("/api/admin/analytics" + q + "&status=invalid").status_code == 422
    for role in ["requester", "agent"]:
        login(c, role)
        assert c.get("/api/admin/analytics" + q).status_code == 403
        assert c.get("/api/admin/analytics/export" + q).status_code == 403


def test_report_limit_and_formula_guard(setup):
    from sqlalchemy import insert
    from app.analytics import safe_cell

    c, sessions = setup
    assert safe_cell("  =SUM(A1)") == "'  =SUM(A1)"
    assert safe_cell("@command") == "'@command"
    assert safe_cell("normal") == "normal"
    with sessions() as db:
        db.execute(
            insert(Ticket),
            [
                {
                    "title": "limit validation",
                    "description": "test",
                    "category": "erp",
                    "priority": "low",
                    "creator_id": 2,
                    "created_at": datetime(2026, 10, 21, 2, tzinfo=timezone.utc),
                }
                for _ in range(10000)
            ],
        )
        db.commit()
    login(c)
    assert (
        c.get("/api/admin/analytics/export?start=2026-10-21&end=2026-10-21").status_code
        == 413
    )
    assert (
        c.get("/api/admin/analytics?start=2026-10-21&end=2026-10-21").json()["summary"][
            "total"
        ]
        == 10002
    )
