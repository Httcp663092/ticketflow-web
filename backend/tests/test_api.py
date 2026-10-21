import os

os.environ["SECRET_KEY"] = "test-key-only-not-for-production-123456789"
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db import Base, database
from app.models import User, Team
from app.main import app, passwords
import pytest


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions() as db:
        db.add(Team(id=1, name="ERP"))
        db.commit()
        for name, role in [
            ("alice", "requester"),
            ("bob", "requester"),
            ("agent", "agent"),
            ("admin", "admin"),
        ]:
            db.add(
                User(
                    username=name,
                    password_hash=passwords.hash("test-password"),
                    role=role,
                    team_id=1,
                )
            )
        db.commit()

    def override():
        with sessions() as db:
            yield db

    app.dependency_overrides[database] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()


def auth(c, name, password="test-password"):
    return {
        "Authorization": "Bearer "
        + c.post(
            "/api/auth/login", json={"username": name, "password": password}
        ).json()["access_token"]
    }


def create(c, headers):
    return c.post(
        "/api/tickets",
        headers=headers,
        json={
            "title": "ERP unavailable",
            "description": "Cannot open ERP",
            "category": "erp",
            "priority": "urgent",
            "team_id": 1,
        },
    )


def test_auth_and_validation(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/tickets").status_code in [401, 403]
    assert (
        client.post(
            "/api/auth/login", json={"username": "alice", "password": "bad"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/tickets", headers=auth(client, "alice"), json={"title": ""}
        ).status_code
        == 422
    )


def test_isolation_and_workflow(client):
    alice = auth(client, "alice")
    bob = auth(client, "bob")
    agent = auth(client, "agent")
    result = create(client, alice)
    assert result.status_code == 201
    path = f"/api/tickets/{result.json()['id']}"
    assert client.get(path, headers=bob).status_code == 404
    assert client.get("/api/tickets", headers=bob).json() == []
    assert (
        client.post(
            path + "/comments", headers=bob, json={"message": "intrusion"}
        ).status_code
        == 404
    )
    assert (
        client.patch(
            path + "/status",
            headers=alice,
            json={
                "status": "in_progress",
                "version": client.get(path, headers=alice).json()["version"],
            },
        ).status_code
        == 403
    )
    assert (
        client.patch(
            path + "/status",
            headers=agent,
            json={
                "status": "closed",
                "version": client.get(path, headers=alice).json()["version"],
            },
        ).status_code
        == 409
    )
    for state in ["in_progress", "resolved"]:
        assert (
            client.patch(
                path + "/status",
                headers=agent,
                json={
                    "status": state,
                    "version": client.get(path, headers=alice).json()["version"],
                },
            ).status_code
            == 200
        )
    assert (
        client.patch(
            path + "/status",
            headers=alice,
            json={
                "status": "closed",
                "version": client.get(path, headers=alice).json()["version"],
            },
        ).status_code
        == 200
    )
    assert len(client.get(path + "/events", headers=alice).json()) == 4


def test_assignment_comments_and_search(client):
    alice = auth(client, "alice")
    admin = auth(client, "admin")
    ticket = create(client, alice).json()
    path = f"/api/tickets/{ticket['id']}"
    assert (
        client.patch(
            path + "/assignee",
            headers=alice,
            json={
                "assignee_id": 3,
                "version": client.get(path, headers=alice).json()["version"],
            },
        ).status_code
        == 403
    )
    assert (
        client.patch(
            path + "/assignee",
            headers=admin,
            json={
                "assignee_id": 1,
                "version": client.get(path, headers=alice).json()["version"],
            },
        ).status_code
        == 422
    )
    assert (
        client.patch(
            path + "/assignee",
            headers=admin,
            json={
                "assignee_id": 3,
                "version": client.get(path, headers=alice).json()["version"],
            },
        ).json()["assignee_id"]
        == 3
    )
    assert (
        client.post(
            path + "/comments", headers=alice, json={"message": "Updated details"}
        ).status_code
        == 201
    )
    assert len(client.get("/api/tickets?q=ERP", headers=alice).json()) == 1
    assert client.get("/api/tickets?q=missing", headers=alice).json() == []


def test_teams_disabled_accounts_and_stale_updates(client):
    admin = auth(client, "admin")
    alice = auth(client, "alice")
    team = client.post("/api/teams", headers=admin, json={"name": "Other"}).json()
    created = client.post(
        "/api/users",
        headers=admin,
        json={
            "username": "other-agent",
            "password": "strong-test-password",
            "role": "agent",
            "team_id": team["id"],
        },
    )
    assert created.status_code == 201
    other = auth(client, "other-agent", "strong-test-password")
    ticket = create(client, alice).json()
    path = f"/api/tickets/{ticket['id']}"
    assert client.get(path, headers=other).status_code == 404
    assert client.get("/api/tickets", headers=other).json() == []
    agent = auth(client, "agent")
    assert (
        client.patch(
            path + "/status",
            headers=agent,
            json={"status": "in_progress", "version": ticket["version"]},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            path + "/status",
            headers=agent,
            json={"status": "resolved", "version": ticket["version"]},
        ).status_code
        == 409
    )
    events = client.get(path + "/events", headers=alice).json()
    assert all(e["created_at"] for e in events)
    assert (
        client.patch("/api/users/3", headers=admin, json={"active": False}).status_code
        == 200
    )
    assert client.get("/api/tickets", headers=agent).status_code == 401
    assert (
        client.post("/api/teams", headers=alice, json={"name": "Forbidden"}).status_code
        == 403
    )
    assert (
        client.post(
            "/api/users",
            headers=admin,
            json={"username": "alice", "password": "strong-test-password"},
        ).status_code
        == 409
    )


def test_database_optimistic_lock():
    from sqlalchemy.orm.exc import StaleDataError
    from app.models import Ticket

    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add(User(id=1, username="writer", password_hash="unused", role="admin"))
        db.add(
            Ticket(
                id=1,
                title="Original",
                description="Description",
                category="erp",
                priority="normal",
                creator_id=1,
            )
        )
        db.commit()
    with factory() as first, factory() as second:
        a = first.get(Ticket, 1)
        b = second.get(Ticket, 1)
        a.title = "First write"
        first.commit()
        b.title = "Lost update"
        with pytest.raises(StaleDataError):
            second.commit()
        second.rollback()
    with factory() as db:
        assert db.get(Ticket, 1).title == "First write"
    engine.dispose()


def test_internal_notes_are_hidden_from_requesters(client):
    alice, agent = auth(client, "alice"), auth(client, "agent")
    ticket = create(client, alice).json()
    path = f"/api/tickets/{ticket['id']}"
    assert (
        client.post(
            path + "/comments",
            headers=alice,
            json={"message": "secret", "internal": True},
        ).status_code
        == 403
    )
    assert (
        client.post(
            path + "/comments",
            headers=agent,
            json={"message": "Staff diagnostic", "internal": True},
        ).status_code
        == 201
    )
    assert (
        client.post(
            path + "/comments", headers=alice, json={"message": "   "}
        ).status_code
        == 422
    )
    public = client.get(path + "/events", headers=alice).json()
    staff = client.get(path + "/events", headers=agent).json()
    assert not any(e["internal"] or e["message"] == "Staff diagnostic" for e in public)
    assert any(e["internal"] and e["message"] == "Staff diagnostic" for e in staff)


def test_reopen_cancel_permissions_reasons_and_versions(client):
    alice, agent, admin = (
        auth(client, "alice"),
        auth(client, "agent"),
        auth(client, "admin"),
    )
    ticket = create(client, alice).json()
    path = f"/api/tickets/{ticket['id']}"

    def change_as(headers, state, reason=""):
        version = client.get(path, headers=alice).json()["version"]
        return client.patch(
            path + "/status",
            headers=headers,
            json={"status": state, "version": version, "reason": reason},
        )

    assert change_as(agent, "in_progress").status_code == 200
    assert change_as(agent, "resolved").status_code == 200
    assert change_as(alice, "in_progress").status_code == 422
    assert change_as(alice, "in_progress", "Problem persists").status_code == 200
    assert change_as(agent, "resolved").status_code == 200
    assert change_as(alice, "closed").status_code == 200
    stale = client.get(path, headers=alice).json()["version"]
    assert change_as(alice, "in_progress", "Recurring failure").status_code == 200
    assert (
        client.patch(
            path + "/status",
            headers=admin,
            json={"status": "cancelled", "version": stale, "reason": "Duplicate"},
        ).status_code
        == 409
    )
    assert change_as(alice, "cancelled", "Duplicate").status_code == 403
    assert change_as(agent, "cancelled", "Duplicate").status_code == 403
    assert change_as(admin, "cancelled", " ").status_code == 422
    assert change_as(admin, "cancelled", "Duplicate ticket").status_code == 200
    assert change_as(admin, "in_progress", "Retry").status_code == 409
    events = client.get(path + "/events", headers=admin).json()
    assert any("Recurring failure" in e["message"] for e in events)
    assert any("Duplicate ticket" in e["message"] for e in events)


def test_attachments_download_scope_validation_and_cleanup(
    client, tmp_path, monkeypatch
):
    from app import attachments

    monkeypatch.setenv("ATTACHMENT_DIR", str(tmp_path))
    alice, bob = auth(client, "alice"), auth(client, "bob")
    ticket = create(client, alice).json()
    path = f"/api/tickets/{ticket['id']}/attachments"
    headers = {**alice, "Content-Type": "application/octet-stream"}
    upload = client.post(
        path,
        params={"filename": "说明.txt"},
        headers=headers,
        content="问题详情".encode(),
    )
    assert upload.status_code == 201
    file = upload.json()
    url = f"{path}/{file['id']}"
    assert client.get(url, headers=alice).content == "问题详情".encode()
    assert client.get(url, headers=alice).headers["x-content-type-options"] == "nosniff"
    assert (
        "attachment;" in client.get(url, headers=alice).headers["content-disposition"]
    )
    assert client.get(url, headers=bob).status_code == 404
    assert client.get(path, headers=bob).status_code == 404
    assert (
        client.post(
            path, params={"filename": "private.txt"}, headers=bob, content=b"forbidden"
        ).status_code
        == 404
    )
    assert client.get(url).status_code in {401, 403}
    other = create(client, alice).json()
    assert (
        client.get(
            f"/api/tickets/{other['id']}/attachments/{file['id']}", headers=alice
        ).status_code
        == 404
    )
    for filename, content, code in [
        ("../bad.txt", b"bad", 422),
        ("bad.html", b"<script>", 415),
        ("bad.png", b"fake image", 415),
        ("empty.txt", b"", 422),
        ("bad.txt", b"\xff", 415),
        ("binary.csv", b"a\x00b", 415),
    ]:
        assert (
            client.post(
                path, params={"filename": filename}, headers=headers, content=content
            ).status_code
            == code
        )
    monkeypatch.setattr(attachments, "MAX_BYTES", 5)
    assert (
        client.post(
            path, params={"filename": "large.txt"}, headers=headers, content=b"123456"
        ).status_code
        == 413
    )
    assert len(list(tmp_path.iterdir())) == 1
    assert len(client.get(path, headers=alice).json()) == 1


def test_attachment_failed_commit_removes_file_and_audit(client, tmp_path, monkeypatch):
    from sqlalchemy.orm import Session as SASession
    from sqlalchemy.orm.exc import StaleDataError

    monkeypatch.setenv("ATTACHMENT_DIR", str(tmp_path))
    alice = auth(client, "alice")
    ticket = create(client, alice).json()
    path = f"/api/tickets/{ticket['id']}"
    with monkeypatch.context() as patch:

        def stale(self):
            raise StaleDataError("Concurrent writer")

        patch.setattr(SASession, "commit", stale)
        response = client.post(
            path + "/attachments",
            params={"filename": "failed.txt"},
            headers=alice,
            content=b"test",
        )
        assert response.status_code == 409
    assert not list(tmp_path.iterdir())
    assert client.get(path + "/attachments", headers=alice).json() == []
    assert len(client.get(path + "/events", headers=alice).json()) == 1


def test_attachment_utf8_boundary_signatures_and_count_limit(
    client, tmp_path, monkeypatch
):
    monkeypatch.setenv("ATTACHMENT_DIR", str(tmp_path))
    alice = auth(client, "alice")
    ticket = create(client, alice).json()
    path = f"/api/tickets/{ticket['id']}/attachments"
    content = b"a" * 65535 + "中文".encode()
    uploaded = client.post(
        path, headers=alice, params={"filename": "unicode.csv"}, content=content
    )
    assert uploaded.status_code == 201
    assert (
        client.get(path + f"/{uploaded.json()['id']}", headers=alice).content == content
    )
    for name, content in [
        ("header.png", b"\x89PNG\r\n\x1a\n"),
        ("header.jpg", b"\xff\xd8\xff"),
        ("header.pdf", b"%PDF-1.7"),
    ]:
        assert (
            client.post(
                path, headers=alice, params={"filename": name}, content=content
            ).status_code
            == 201
        )
    for i in range(16):
        assert (
            client.post(
                path,
                headers=alice,
                params={"filename": f"file-{i}.txt"},
                content=b"test",
            ).status_code
            == 201
        )
    assert (
        client.post(
            path, headers=alice, params={"filename": "overflow.txt"}, content=b"test"
        ).status_code
        == 413
    )
    assert (
        len(client.get(path, headers=alice).json())
        == len(list(tmp_path.iterdir()))
        == 20
    )


def test_registration_requires_approval_and_cannot_choose_role(client):
    admin = auth(client, "admin")
    body = {
        "username": "New.Member",
        "display_name": "新成员",
        "password": "strong-member-password",
    }
    assert (
        client.post("/api/auth/register", json={**body, "role": "admin"}).status_code
        == 422
    )
    assert client.post("/api/auth/register", json=body).status_code == 201
    assert (
        client.post(
            "/api/auth/register", json={**body, "username": "NEW.MEMBER"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/auth/login",
            json={"username": "new.member", "password": body["password"]},
        ).status_code
        == 401
    )
    users = client.get("/api/users", headers=admin).json()
    new = next(u for u in users if u["username"] == "new.member")
    assert (
        new["role"] == "requester" and new["registration_pending"] and not new["active"]
    )
    assert (
        client.patch(
            f"/api/users/{new['id']}",
            headers=auth(client, "alice"),
            json={"active": True},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/users/{new['id']}",
            headers=admin,
            json={"active": True, "team_id": 1},
        ).status_code
        == 200
    )
    headers = auth(client, "NEW.MEMBER", body["password"])
    profile = client.get("/api/auth/me", headers=headers).json()
    assert profile["display_name"] == "新成员" and not profile["registration_pending"]
    assert profile["role"] == "requester" and "password_hash" not in profile


def test_password_change_revokes_all_old_sessions(client):
    alice = auth(client, "alice")
    second = auth(client, "alice")
    assert (
        client.post(
            "/api/auth/password",
            headers=alice,
            json={"current_password": "wrong", "new_password": "new-strong-password"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/auth/password",
            headers=alice,
            json={"current_password": "test-password", "new_password": "test-password"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/auth/password",
            headers=alice,
            json={
                "current_password": "test-password",
                "new_password": "new-strong-password",
            },
        ).status_code
        == 200
    )
    for old in [alice, second]:
        assert client.get("/api/auth/me", headers=old).status_code == 401
    assert (
        client.post(
            "/api/auth/login", json={"username": "alice", "password": "test-password"}
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/auth/me", headers=auth(client, "alice", "new-strong-password")
        ).status_code
        == 200
    )


def test_account_edit_and_reenable_does_not_restore_old_token(client):
    admin = auth(client, "admin")
    agent = auth(client, "agent")
    team = client.post("/api/teams", headers=admin, json={"name": "Other team"}).json()
    alice = auth(client, "alice")
    ticket = create(client, alice).json()
    assert client.get(f"/api/tickets/{ticket['id']}", headers=agent).status_code == 200
    assert (
        client.patch(
            "/api/users/3",
            headers=admin,
            json={"team_id": team["id"], "display_name": "处理人甲"},
        ).status_code
        == 200
    )
    assert client.get(f"/api/tickets/{ticket['id']}", headers=agent).status_code == 404
    assert (
        client.get("/api/auth/me", headers=agent).json()["display_name"] == "处理人甲"
    )
    assert (
        client.patch("/api/users/3", headers=admin, json={"team_id": 99999}).status_code
        == 422
    )
    assert (
        client.patch("/api/users/3", headers=admin, json={"active": False}).status_code
        == 200
    )
    assert (
        client.patch("/api/users/3", headers=admin, json={"active": True}).status_code
        == 200
    )
    assert client.get("/api/auth/me", headers=agent).status_code == 401
    assert client.get("/api/auth/me", headers=auth(client, "agent")).status_code == 200


def test_search_pagination_dashboard_and_permissions(client):
    alice = auth(client, "alice")
    bob = auth(client, "bob")
    a = create(client, alice).json()
    b = create(client, bob).json()
    client.post(
        "/api/tickets",
        headers=alice,
        json={
            "title": "Routine 100% check",
            "description": "Maintenance",
            "category": "operations",
            "priority": "low",
            "team_id": 1,
        },
    )
    result = client.get("/api/ticket-search?limit=1&offset=1", headers=alice).json()
    assert result["total"] == 2 and len(result["items"]) == 1
    assert all(t["creator_id"] == 1 for t in result["items"])
    assert (
        client.get(
            "/api/ticket-search?category=operations&priority=low", headers=alice
        ).json()["total"]
        == 1
    )
    assert client.get("/api/ticket-search?q=100%25", headers=alice).json()["total"] == 1
    assert (
        client.get("/api/ticket-search?q=" + str(b["id"]), headers=alice).json()[
            "total"
        ]
        == 0
    )
    assert (
        client.get("/api/ticket-search?q=TF-" + str(a["id"]), headers=alice).json()[
            "total"
        ]
        == 1
    )
    dashboard = client.get("/api/dashboard", headers=alice).json()
    assert (
        dashboard["total"] == 2
        and dashboard["by_status"] == {"open": 2}
        and dashboard["urgent"] == 1
    )
    assert client.get("/api/dashboard", headers=bob).json()["total"] == 1
    assert (
        client.get("/api/dashboard", headers=auth(client, "admin")).json()["total"] == 3
    )
    assert (
        client.get(
            "/api/ticket-search?mine=true", headers=auth(client, "agent")
        ).json()["total"]
        == 0
    )


def test_login_attempts_are_rate_limited(client):
    for i in range(30):
        assert (
            client.post(
                "/api/auth/login", json={"username": "unknown", "password": "wrong"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/auth/login", json={"username": "unknown", "password": "wrong"}
        ).status_code
        == 429
    )


def test_registration_rate_limit(client):
    for i in range(5):
        assert (
            client.post(
                "/api/auth/register",
                json={
                    "username": f"signup{i}",
                    "display_name": "Member",
                    "password": "strong-member-password",
                },
            ).status_code
            == 201
        )
    assert (
        client.post(
            "/api/auth/register",
            json={
                "username": "signup6",
                "display_name": "Member",
                "password": "strong-member-password",
            },
        ).status_code
        == 429
    )


def test_routing_changes_group_and_clears_assignee(client):
    admin = auth(client, "admin")
    alice = auth(client, "alice")
    agent = auth(client, "agent")
    ticket = create(client, alice).json()
    path = f"/api/tickets/{ticket['id']}"
    assigned = client.patch(
        path + "/assignee",
        headers=admin,
        json={"assignee_id": 3, "version": ticket["version"]},
    ).json()
    group = client.post(
        "/api/teams", headers=admin, json={"name": "Routed group"}
    ).json()
    body = {
        "team_id": group["id"],
        "version": assigned["version"],
        "reason": "Transferred to specialist team",
    }
    assert client.patch(path + "/team", headers=agent, json=body).status_code == 403
    routed = client.patch(path + "/team", headers=admin, json=body)
    assert routed.status_code == 200 and routed.json()["assignee_id"] is None
    assert client.get(path, headers=agent).status_code == 404
    assert client.get(path, headers=alice).status_code == 200
    assert client.patch(path + "/team", headers=admin, json=body).status_code == 409
    assert (
        client.get(
            "/api/ticket-search?q=TF-" + str(ticket["id"]).zfill(5), headers=alice
        ).json()["total"]
        == 1
    )
    assert (
        client.get("/api/ticket-search?active_only=true", headers=alice).json()["total"]
        == 1
    )
