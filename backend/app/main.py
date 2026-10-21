import os
from datetime import datetime, timedelta, timezone
from typing import Literal
import jwt
from .security import passwords
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.exc import IntegrityError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, or_, func, cast, String
from sqlalchemy.orm import Session
from .db import database
from .models import User, Ticket, Event, Team
from .accounts import throttle, profile

app = FastAPI(title="TicketFlow", version="0.1.0")
_dummy_password_hash = passwords.hash("dummy-password-for-timing-only")
bearer = HTTPBearer(auto_error=False)
COOKIE_NAME = "ticketflow_session"


def cookie_options():
    return dict(
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "1") == "1",
        samesite="strict",
        path=os.getenv("SESSION_COOKIE_PATH", "/api"),
    )


def secret():
    value = os.environ.get("SECRET_KEY", "")
    if len(value) < 32:
        raise RuntimeError("SECRET_KEY must contain at least 32 characters")
    return value


class Login(BaseModel):
    username: str = Field(max_length=80)
    password: str = Field(max_length=128)
    remember: bool = False


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
    request: Request,
    auth: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(database),
):
    try:
        encoded = auth.credentials if auth else request.cookies.get(COOKIE_NAME)
        if not encoded:
            raise ValueError()
        data = jwt.decode(encoded, secret(), algorithms=["HS256"])
        user = db.get(User, int(data["sub"]))
        if not user or not user.active or data.get("ver", 0) != user.token_version:
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


@app.middleware("http")
async def protect_cookie_writes(request: Request, call_next):
    # SameSite cookies plus an Origin check protect writes and login against CSRF.
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        expected = str(request.base_url).rstrip("/")
        trusted = {v for v in os.getenv("TRUSTED_ORIGINS", "").split(",") if v}
        if origin and origin != expected and origin not in trusted:
            return JSONResponse({"detail": "Untrusted request origin"}, status_code=403)
        if (
            request.cookies.get(COOKIE_NAME)
            and not request.headers.get("authorization")
            and not origin
        ):
            return JSONResponse({"detail": "Origin header required"}, status_code=403)
    return await call_next(request)


@app.post("/api/auth/login")
def login(
    body: Login, request: Request, response: Response, db: Session = Depends(database)
):
    throttle(db, request, "login", 30)
    user = db.scalar(
        select(User).where(func.lower(User.username) == body.username.strip().lower())
    )
    valid_password = passwords.verify(
        body.password, user.password_hash if user else _dummy_password_hash
    )
    if not user or not user.active or not valid_password:
        raise HTTPException(401, "Invalid credentials")
    lifetime = timedelta(days=30) if body.remember else timedelta(hours=8)
    encoded = jwt.encode(
        {
            "sub": str(user.id),
            "ver": user.token_version,
            "exp": datetime.now(timezone.utc) + lifetime,
        },
        secret(),
        algorithm="HS256",
    )
    response.set_cookie(
        COOKIE_NAME,
        encoded,
        max_age=int(lifetime.total_seconds()) if body.remember else None,
        **cookie_options(),
    )
    response.headers["Cache-Control"] = "no-store"
    return {"access_token": encoded, "token_type": "bearer", "role": user.role}


@app.post("/api/auth/logout")
def logout(
    response: Response, db: Session = Depends(database), user: User = Depends(current)
):
    user.token_version += 1
    db.commit()
    response.delete_cookie(COOKIE_NAME, **cookie_options())
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


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
    records = db.scalars(
        select(Event)
        .where(
            Event.ticket_id == ticket_id,
            Event.internal.is_(False) if user.role == "requester" else True,
        )
        .order_by(Event.id)
    ).all()
    actor_ids = {e.actor_id for e in records}
    names = (
        {
            u.id: u.display_name or u.username
            for u in db.scalars(select(User).where(User.id.in_(actor_ids)))
        }
        if actor_ids
        else {}
    )
    return [
        {
            "id": e.id,
            "actor_id": e.actor_id,
            "actor_name": names.get(e.actor_id, "工单成员"),
            "message": e.message,
            "created_at": e.created_at,
            "internal": e.internal,
            "kind": e.kind,
        }
        for e in records
    ]


@app.exception_handler(StaleDataError)
async def stale_handler(request: Request, exc: StaleDataError):
    return JSONResponse(
        status_code=409, content={"detail": "Ticket changed; reload before retry"}
    )


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class UserIn(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,39}$")
    display_name: str = Field(default="", max_length=80)
    password: str = Field(min_length=12, max_length=128)
    role: Literal["requester", "agent", "admin"] = "requester"
    team_id: int | None = None


class UserChange(BaseModel):
    active: bool | None = None
    team_id: int | None = None
    display_name: str | None = Field(default=None, max_length=80)


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
        profile(u)
        for u in db.scalars(
            query.order_by(User.registration_pending.desc(), User.username)
        )
    ]


@app.post("/api/users", status_code=201)
def add_user(
    body: UserIn, db: Session = Depends(database), user: User = Depends(admin)
):
    if body.team_id is not None and not db.get(Team, body.team_id):
        raise HTTPException(422, "Unknown team")
    username = body.username.strip().lower()
    if not username:
        raise HTTPException(422, "Username required")
    if db.scalar(select(User.id).where(func.lower(User.username) == username)):
        raise HTTPException(409, "Username already exists")
    new = User(
        username=username,
        display_name=body.display_name.strip(),
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
    if target.role == "admin" and body.active is not None:
        raise HTTPException(409, "Admin account state cannot be changed here")
    if "team_id" in body.model_fields_set:
        if body.team_id is not None and not db.get(Team, body.team_id):
            raise HTTPException(422, "Unknown team")
        target.team_id = body.team_id
    if body.display_name is not None:
        target.display_name = body.display_name.strip()
    if body.active is not None:
        target.active = body.active
        target.token_version += 1
        if body.active:
            target.registration_pending = False
    db.commit()
    return profile(target)


from .attachments import make_router

app.include_router(make_router(current, visible, log))


from .accounts import make_router as accounts_router

app.include_router(accounts_router(current, passwords))


def scoped_tickets(user):
    query = select(Ticket)
    if user.role == "admin":
        return query
    scope = Ticket.creator_id == user.id
    if user.role == "agent" and user.team_id is not None:
        scope = or_(scope, Ticket.team_id == user.team_id)
    return query.where(scope)


@app.get("/api/ticket-search")
def search(
    q: str = "",
    status: str = "",
    category: str = "",
    priority: str = "",
    mine: bool = False,
    active_only: bool = False,
    offset: int = 0,
    limit: int = 20,
    db: Session = Depends(database),
    user: User = Depends(current),
):
    query = scoped_tickets(user)
    if mine:
        query = query.where(Ticket.creator_id == user.id)
    if active_only:
        query = query.where(Ticket.status.in_(["open", "in_progress", "resolved"]))
    if status:
        query = query.where(Ticket.status == status)
    if category:
        query = query.where(Ticket.category == category)
    if priority:
        query = query.where(Ticket.priority == priority)
    if q:
        q = q[:200]
        number = q.removeprefix("TF-")
        if number.isascii() and number.isdecimal():
            number = str(int(number))
        query = query.where(
            or_(
                Ticket.title.contains(q, autoescape=True),
                Ticket.description.contains(q, autoescape=True),
                cast(Ticket.id, String) == number,
            )
        )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(Ticket.updated_at.desc(), Ticket.id.desc())
        .offset(max(0, offset))
        .limit(max(1, min(limit, 100)))
    ).all()
    ids = {id for t in rows for id in [t.creator_id, t.assignee_id] if id is not None}
    names = (
        {
            u.id: u.display_name or u.username
            for u in db.scalars(select(User).where(User.id.in_(ids)))
        }
        if ids
        else {}
    )
    return {
        "items": [
            {
                **TicketOut.model_validate(t).model_dump(),
                "creator_name": names.get(t.creator_id, ""),
                "assignee_name": names.get(t.assignee_id, ""),
            }
            for t in rows
        ],
        "total": total,
        "offset": max(0, offset),
        "limit": max(1, min(limit, 100)),
    }


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(database), user: User = Depends(current)):
    scoped = scoped_tickets(user).subquery()
    counts = dict(
        db.execute(
            select(scoped.c.status, func.count()).group_by(scoped.c.status)
        ).all()
    )
    return {
        "total": sum(counts.values()),
        "by_status": counts,
        "urgent": db.scalar(
            select(func.count())
            .select_from(scoped)
            .where(
                scoped.c.priority == "urgent",
                scoped.c.status.in_(["open", "in_progress", "resolved"]),
            )
        )
        or 0,
    }


class Routing(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    reason: str = Field(min_length=1, max_length=1000)
    team_id: int = Field(gt=0)
    version: int = Field(ge=1)


@app.patch("/api/tickets/{ticket_id}/team", response_model=TicketOut)
def route_ticket(
    ticket_id: int,
    body: Routing,
    db: Session = Depends(database),
    user: User = Depends(admin),
):
    ticket = visible(ticket_id, db, user)
    if ticket.version != body.version:
        raise HTTPException(409, "Ticket changed; reload before retry")
    team = db.get(Team, body.team_id)
    if not team:
        raise HTTPException(422, "Unknown team")
    ticket.team_id = team.id
    # A previous assignee may no longer have access to the new team.
    ticket.assignee_id = None
    log(
        db,
        ticket,
        user,
        f"Routed to team: {team.name}; assignee cleared; Reason: {body.reason}",
    )
    db.commit()
    return ticket


from .analytics import make_router as analytics_router

app.include_router(analytics_router(current))
