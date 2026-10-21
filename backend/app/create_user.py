import argparse, getpass
from .db import Session
from .models import User
from .main import passwords
parser=argparse.ArgumentParser()
parser.add_argument("username")
parser.add_argument("--role",choices=["requester","agent","admin"],default="requester")
if __name__ == "__main__":
    args=parser.parse_args()
    password=getpass.getpass("Password (minimum 12 characters): ")
    if len(password)<12: raise SystemExit("Password too short")
    with Session() as db:
        db.add(User(username=args.username,password_hash=passwords.hash(password),role=args.role)); db.commit()
