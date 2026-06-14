"""Database engine and session factory for EA-DIS (schema: dis)."""
from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.environ.get(
    "EA_DIS_DATABASE_URL",
    "postgresql+psycopg://localhost/ea_ai_os",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_schema(db: Session) -> None:
    db.execute(text("CREATE SCHEMA IF NOT EXISTS dis"))
    db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    db.commit()
