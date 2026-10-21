import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
class Base(DeclarativeBase): pass
engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///./ticketflow.db"))
Session = sessionmaker(engine, expire_on_commit=False)
def database():
    with Session() as session:
        yield session
