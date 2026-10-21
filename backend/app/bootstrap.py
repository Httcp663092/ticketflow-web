"""Create the initial administrator from private stdin; never overwrite an account."""

import json
import sys
from sqlalchemy import select
from .db import Session
from .models import User
from .security import passwords


def main():
    values = json.load(sys.stdin)
    username = values["username"]
    password = values["password"]
    if len(password) < 20:
        raise SystemExit("Initial password must be at least 20 characters")
    with Session() as db:
        if db.scalar(select(User).where(User.username == username)):
            raise SystemExit("Account already exists; refusing to overwrite")
        db.add(
            User(
                username=username,
                display_name="系统管理员",
                password_hash=passwords.hash(password),
                role="admin",
                active=True,
            )
        )
        db.commit()
    print("Initial administrator created; change the password after first sign-in")


if __name__ == "__main__":
    main()
