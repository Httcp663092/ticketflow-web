import os
from datetime import datetime, timedelta, timezone
from typing import Literal
import jwt
from pwdlib import PasswordHash
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.exc import IntegrityError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from .db import database
from .models import User, Ticket, Event, Team

app = FastAPI(title="TicketFlow", version="0.1.0")
passwords = PasswordHash.recommended()
bearer = HTTPBearer()


def secret():
    value = os.environ.get("SECRET_KEY", "")
    if len(value) < 32:
        raise RuntimeError("SECRET_KEY must contain at least 32 characters")
    return value


class Login(BaseModel):
    username: str
    password: str


class TicketIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=20000)
    category: Literal["erp", "operations"]
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    team_id: int | None = None


class TicketOut(TicketIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    creator_id: int
    assignee_id: int | None
    created_at: datetime
    updated_at: datetime
    version: int


class Change(BaseModel):
    status: Literal["open", "in_progress", "resolved", "closed", "cancelled"]
    reason: str = Field(default="", max_length=1000)
    version: int = Field(ge=1)


class Assignment(BaseModel):
    assignee_id: int
    version: int = Field(ge=1)


class Comment(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    internal: bool = False
    message: str = Field(min_length=1, max_length=10000)


def current(
    auth: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(database),
):
    try:
        data = jwt.decode(auth.credentials, secret(), algorithms=["HS256"])
        user = db.get(User, int(data["sub"]))
        if not user or not user.active:
            raise ValueError()
        return user
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(401, "Invalid or expired token")


def visible(ticket_id, db, user):
    ticket = db.get(Ticket, ticket_id)
    if not ticket or (
        user.role != "admin"
        and ticket.creator_id != user.id
        and not (
            user.role == "agent"
            and user.team_id is not None
            and ticket.team_id == user.team_id
        )
    ):
        raise HTTPException(404, "Ticket not found")
    return ticket


def log(db, ticket, user, message, internal=False, kind="system"):
    db.add(
        Event(
            ticket_id=ticket.id,
            actor_id=user.id,
            message=message,
            internal=internal,
            kind=kind,
        )
    )
    ticket.updated_at = datetime.now(timezone.utc)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(body: Login, db: Session = Depends(database)):
    user = db.scalar(select(User).where(User.username == body.username))
    if (
        not user
        or not user.active
        or not passwords.verify(body.password, user.password_hash)
    ):
        raise HTTPException(401, "Invalid credentials")
    return {
        "access_token": jwt.encode(
            {
                "sub": str(user.id),
                "exp": datetime.now(timezone.utc) + timedelta(hours=8),
            },
            secret(),
            algorithm="HS256",
        ),
        "token_type": "bearer",
        "role": user.role,
    }


@app.get("/api/tickets", response_model=list[TicketOut])
def tickets(
    status: str | None = None,
    q: str = "",
    offset: int = 0,
    limit: int = 50,
    db: Session = Depends(database),
    user: User = Depends(current),
):
    query = select(Ticket)
    if user.role != "admin":
        scope = Ticket.creator_id == user.id
        if user.role == "agent" and user.team_id is not None:
            scope = or_(scope, Ticket.team_id == user.team_id)
        query = query.where(scope)
    if status:
        query = query.where(Ticket.status == status)
    if q:
        query = query.where(
            or_(Ticket.title.contains(q), Ticket.description.contains(q))
        )
    return db.scalars(
        query.order_by(Ticket.id.desc())
        .offset(max(0, offset))
        .limit(max(1, min(limit, 100)))
    ).all()


@app.post("/api/tickets", response_model=TicketOut, status_code=201)
def create(
    body: TicketIn, db: Session = Depends(database), user: User = Depends(current)
):
    if body.team_id is not None and not db.get(Team, body.team_id):
        raise HTTPException(422, "Unknown team")
    ticket = Ticket(**body.model_dump(), creator_id=user.id)
    db.add(ticket)
    db.flush()
    log(db, ticket, user, "Created")
    db.commit()
    return ticket


@app.get("/api/tickets/{ticket_id}", response_model=TicketOut)
def detail(
    ticket_id: int, db: Session = Depends(database), user: User = Depends(current)
):
    return visible(ticket_id, db, user)


@app.patch("/api/tickets/{ticket_id}/status", response_model=TicketOut)
def change(
    ticket_id: int,
    body: Change,
    db: Session = Depends(database),
    user: User = Depends(current),
):
    ticket = visible(ticket_id, db, user)
    if ticket.version != body.version:
        raise HTTPException(409, "Ticket changed; reload before retry")
    allowed = {
        "open": {"in_progress", "cancelled"},
        "in_progress": {"resolved", "cancelled"},
        "resolved": {"closed", "in_progress", "cancelled"},
        "closed": {"in_progress"},
        "cancelled": set(),
    }
    if body.status == "cancelled" and user.role != "admin":
        raise HTTPException(403, "Admin role required to cancel")
    needs_reason = body.status == "cancelled" or (
        ticket.status in {"closed", "resolved"} and body.status == "in_progress"
    )
    reason = body.reason.strip()
    if needs_reason and not reason:
        raise HTTPException(422, "A reason is required")
    if user.role == "requester" and not (
        ticket.status == "resolved"
        and body.status in {"closed", "in_progress"}
        or ticket.status == "closed"
        and body.status == "in_progress"
    ):
        raise HTTPException(403, "Agent role required")
    if body.status not in allowed[ticket.status]:
        raise HTTPException(409, "Invalid transition")
    log(
        db,
        ticket,
        user,
        f"Status {ticket.status} -> {body.status}"
        + (f"; Reason: {reason}" if reason else ""),
    )
    ticket.status = body.status
    db.commit()
    return ticket


@app.patch("/api/tickets/{ticket_id}/assignee", response_model=TicketOut)
def assign(
    ticket_id: int,
    body: Assignment,
    db: Session = Depends(database),
    user: User = Depends(current),
):
    if user.role != "admin":
        raise HTTPException(403, "Admin role required")
    ticket = visible(ticket_id, db, user)
    target = db.get(User, body.assignee_id)
    if not target or not target.active or target.role not in {"admin", "agent"}:
        raise HTTPException(422, "Assignee must be an agent")
    if ticket.version != body.version:
        raise HTTPException(409, "Ticket changed; reload before retry")
    if target.role == "agent" and (
        target.team_id is None or target.team_id != ticket.team_id
    ):
        raise HTTPException(422, "Assignee must belong to ticket team")
    ticket.assignee_id = target.id
    log(db, ticket, user, f"Assigned to {target.id}")
    db.commit()
    return ticket


@app.post("/api/tickets/{ticket_id}/comments", status_code=201)
def comment(
    ticket_id: int,
    body: Comment,
    db: Session = Depends(database),
    user: User = Depends(current),
):
    ticket = visible(ticket_id, db, user)
    if body.internal and user.role == "requester":
        raise HTTPException(403, "Staff role required for internal notes")
    log(db, ticket, user, body.message, internal=body.internal, kind="comment")
    db.commit()
    return {"ok": True}


@app.get("/api/tickets/{ticket_id}/events")
def events(
    ticket_id: int, db: Session = Depends(database), user: User = Depends(current)
):
    visible(ticket_id, db, user)
    return [
        {
            "id": e.id,
            "actor_id": e.actor_id,
            "message": e.message,
            "created_at": e.created_at,
            "internal": e.internal,
            "kind": e.kind,
        }
        for e in db.scalars(
            select(Event)
            .where(
                Event.ticket_id == ticket_id,
                Event.internal.is_(False) if user.role == "requester" else True,
            )
            .order_by(Event.id)
        )
    ]


@app.exception_handler(StaleDataError)
async def stale_handler(request: Request, exc: StaleDataError):
    return JSONResponse(
        status_code=409, content={"detail": "Ticket changed; reload before retry"}
    )


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=12, max_length=128)
    role: Literal["requester", "agent", "admin"] = "requester"
    team_id: int | None = None


class UserChange(BaseModel):
    active: bool


def admin(user: User = Depends(current)):
    if user.role != "admin":
        raise HTTPException(403, "Admin role required")
    return user


@app.get("/api/teams")
def teams(db: Session = Depends(database), user: User = Depends(current)):
    return [
        {"id": t.id, "name": t.name}
        for t in db.scalars(select(Team).order_by(Team.name))
    ]


@app.post("/api/teams", status_code=201)
def add_team(
    body: TeamIn, db: Session = Depends(database), user: User = Depends(admin)
):
    team = Team(name=body.name.strip())
    if not team.name:
        raise HTTPException(422, "Team name required")
    db.add(team)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Team already exists")
    return {"id": team.id, "name": team.name}


@app.get("/api/users")
def users(db: Session = Depends(database), user: User = Depends(current)):
    if user.role == "requester":
        raise HTTPException(403, "Staff role required")
    query = select(User)
    if user.role != "admin":
        query = (
            query.where(User.team_id == user.team_id, User.active.is_(True))
            if user.team_id
            else query.where(User.id == user.id)
        )
    return [
        {
            "id": u.id,
            "username": u.username,
            "role": u.role,
            "team_id": u.team_id,
            "active": u.active,
        }
        for u in db.scalars(query.order_by(User.username))
    ]


@app.post("/api/users", status_code=201)
def add_user(
    body: UserIn, db: Session = Depends(database), user: User = Depends(admin)
):
    if body.team_id is not None and not db.get(Team, body.team_id):
        raise HTTPException(422, "Unknown team")
    username = body.username.strip()
    if not username:
        raise HTTPException(422, "Username required")
    new = User(
        username=username,
        password_hash=passwords.hash(body.password),
        role=body.role,
        team_id=body.team_id,
    )
    db.add(new)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Username already exists")
    return {"id": new.id, "username": new.username}


@app.patch("/api/users/{user_id}")
def disable_user(
    user_id: int,
    body: UserChange,
    db: Session = Depends(database),
    user: User = Depends(admin),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    if target.role == "admin":
        raise HTTPException(409, "Admin account state cannot be changed here")
    target.active = body.active
    db.commit()
    return {"id": target.id, "active": target.active}


from .attachments import make_router

app.include_router(make_router(current, visible, log))
