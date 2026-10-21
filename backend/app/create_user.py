import argparse, getpass, re
from .db import Session
from .models import User
from .main import passwords

parser = argparse.ArgumentParser()
parser.add_argument("username")
parser.add_argument(
    "--role", choices=["requester", "agent", "admin"], default="requester"
)
if __name__ == "__main__":
    args = parser.parse_args()
    args.username = args.username.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,39}", args.username):
        raise SystemExit(
            "Username must contain 3-40 letters, digits, underscores, dots or hyphens"
        )
    password = getpass.getpass("Password (minimum 12 characters): ")
    if len(password) < 12:
        raise SystemExit("Password too short")
    with Session() as db:
        db.add(
            User(
                username=args.username,
                password_hash=passwords.hash(password),
                role=args.role,
            )
        )
        db.commit()
