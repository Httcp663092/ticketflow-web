import hashlib
import time
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update, delete, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .db import database
from .models import User, RateBucket


class Registration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,39}$")
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=12, max_length=128)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


def profile(user):
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
        "role": user.role,
        "team_id": user.team_id,
        "active": user.active,
        "registration_pending": user.registration_pending,
    }


def throttle(db, request, action, limit):
    # Persist counts across workers; atomic updates prevent concurrent bypass.
    bucket = int(time.time() // 900)
    address = request.client.host if request.client else "unknown"
    key = hashlib.sha256((action + ":" + address).encode()).hexdigest()
    query = (
        update(RateBucket)
        .where(RateBucket.key == key, RateBucket.bucket == bucket)
        .values(attempts=RateBucket.attempts + 1)
        .returning(RateBucket.attempts)
    )
    count = db.execute(query).scalar()
    if count is None:
        db.add(RateBucket(key=key, bucket=bucket, attempts=1))
        try:
            db.flush()
            count = 1
        except IntegrityError:
            db.rollback()
            count = db.execute(query).scalar()
    db.execute(delete(RateBucket).where(RateBucket.bucket < bucket - 1))
    db.commit()
    if count > limit:
        raise HTTPException(429, "Too many attempts; try again in 15 minutes")


def make_router(current, passwords):
    router = APIRouter(prefix="/api")

    @router.post("/auth/register", status_code=201)
    def register(body: Registration, request: Request, db: Session = Depends(database)):
        throttle(db, request, "register", 5)
        name = body.display_name.strip()
        if not name:
            raise HTTPException(422, "Display name required")
        username = body.username.lower()
        if db.scalar(select(User.id).where(func.lower(User.username) == username)):
            raise HTTPException(409, "Username already exists")
        user = User(
            username=username,
            display_name=name,
            password_hash=passwords.hash(body.password),
            role="requester",
            active=False,
            registration_pending=True,
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Username already exists")
        return {"message": "Registration received; administrator approval required"}

    @router.get("/auth/me")
    def me(user: User = Depends(current)):
        return profile(user)

    @router.post("/auth/password")
    def change_password(
        body: PasswordChange,
        request: Request,
        db: Session = Depends(database),
        user: User = Depends(current),
    ):
        throttle(db, request, "password", 10)
        if not passwords.verify(body.current_password, user.password_hash):
            raise HTTPException(400, "Current password incorrect")
        if body.current_password == body.new_password:
            raise HTTPException(422, "New password must be different")
        # Atomic increment invalidates all previously issued tokens.
        db.execute(
            update(User)
            .where(User.id == user.id)
            .values(
                password_hash=passwords.hash(body.new_password),
                token_version=User.token_version + 1,
            )
        )
        db.commit()
        return {"message": "Password changed; please sign in again"}

    return router
