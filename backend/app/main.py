import os
from datetime import datetime, timedelta, timezone
from typing import Literal
import jwt
from pwdlib import PasswordHash
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from .db import database
from .models import User, Ticket, Event
app = FastAPI(title="TicketFlow", version="0.1.0")
passwords = PasswordHash.recommended()
bearer = HTTPBearer()
def secret():
    value = os.environ.get("SECRET_KEY", "")
    if len(value) < 32: raise RuntimeError("SECRET_KEY must contain at least 32 characters")
    return value
class Login(BaseModel):
    username: str
    password: str
class TicketIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=20000)
    category: Literal["erp", "operations"]
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
class TicketOut(TicketIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    creator_id: int
    assignee_id: int | None
    created_at: datetime
class Change(BaseModel):
    status: Literal["open", "in_progress", "resolved", "closed"]
class Assignment(BaseModel):
    assignee_id: int
class Comment(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
def current(auth: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(database)):
    try:
        data = jwt.decode(auth.credentials, secret(), algorithms=["HS256"])
        user = db.get(User, int(data["sub"]))
        if not user: raise ValueError()
        return user
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(401, "Invalid or expired token")
def visible(ticket_id, db, user):
    ticket = db.get(Ticket, ticket_id)
    if not ticket or (user.role == "requester" and ticket.creator_id != user.id):
        raise HTTPException(404, "Ticket not found")
    return ticket
def log(db, ticket, user, message):
    db.add(Event(ticket_id=ticket.id, actor_id=user.id, message=message))
@app.get("/api/health")
def health(): return {"status": "ok"}
@app.post("/api/auth/login")
def login(body: Login, db: Session = Depends(database)):
    user = db.scalar(select(User).where(User.username == body.username))
    if not user or not passwords.verify(body.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    return {"access_token": jwt.encode({"sub": str(user.id), "exp": datetime.now(timezone.utc)+timedelta(hours=8)}, secret(), algorithm="HS256"), "token_type": "bearer", "role": user.role}
@app.get("/api/tickets", response_model=list[TicketOut])
def tickets(status: str | None = None, q: str = "", offset: int = 0, limit: int = 50, db: Session = Depends(database), user: User = Depends(current)):
    query = select(Ticket)
    if user.role == "requester": query = query.where(Ticket.creator_id == user.id)
    if status: query = query.where(Ticket.status == status)
    if q: query = query.where(or_(Ticket.title.contains(q), Ticket.description.contains(q)))
    return db.scalars(query.order_by(Ticket.id.desc()).offset(max(0,offset)).limit(max(1,min(limit,100)))).all()
@app.post("/api/tickets", response_model=TicketOut, status_code=201)
def create(body: TicketIn, db: Session = Depends(database), user: User = Depends(current)):
    ticket = Ticket(**body.model_dump(), creator_id=user.id)
    db.add(ticket); db.flush(); log(db,ticket,user,"Created"); db.commit()
    return ticket
@app.get("/api/tickets/{ticket_id}", response_model=TicketOut)
def detail(ticket_id: int, db: Session = Depends(database), user: User = Depends(current)):
    return visible(ticket_id,db,user)
@app.patch("/api/tickets/{ticket_id}/status", response_model=TicketOut)
def change(ticket_id: int, body: Change, db: Session = Depends(database), user: User = Depends(current)):
    ticket = visible(ticket_id,db,user)
    allowed = {"open": {"in_progress"}, "in_progress": {"resolved"}, "resolved": {"closed", "in_progress"}, "closed": set()}
    if user.role == "requester" and not (ticket.status == "resolved" and body.status == "closed"):
        raise HTTPException(403, "Agent role required")
    if body.status not in allowed[ticket.status]: raise HTTPException(409, "Invalid transition")
    log(db,ticket,user,f"Status {ticket.status} -> {body.status}"); ticket.status=body.status; db.commit()
    return ticket
@app.patch("/api/tickets/{ticket_id}/assignee", response_model=TicketOut)
def assign(ticket_id: int, body: Assignment, db: Session = Depends(database), user: User = Depends(current)):
    if user.role != "admin": raise HTTPException(403, "Admin role required")
    ticket=visible(ticket_id,db,user); target=db.get(User,body.assignee_id)
    if not target or target.role not in {"admin","agent"}: raise HTTPException(422,"Assignee must be an agent")
    ticket.assignee_id=target.id; log(db,ticket,user,f"Assigned to {target.id}"); db.commit(); return ticket
@app.post("/api/tickets/{ticket_id}/comments", status_code=201)
def comment(ticket_id: int, body: Comment, db: Session = Depends(database), user: User = Depends(current)):
    ticket=visible(ticket_id,db,user); log(db,ticket,user,body.message); db.commit(); return {"ok":True}
@app.get("/api/tickets/{ticket_id}/events")
def events(ticket_id: int, db: Session = Depends(database), user: User = Depends(current)):
    visible(ticket_id,db,user)
    return [{"id":e.id,"actor_id":e.actor_id,"message":e.message} for e in db.scalars(select(Event).where(Event.ticket_id==ticket_id).order_by(Event.id))]
