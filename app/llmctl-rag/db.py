from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

_engine = None
SessionLocal = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class BaseModel(Base):
    __abstract__ = True

    @classmethod
    def create(cls, session: Session, **kwargs):
        instance = cls(**kwargs)
        session.add(instance)
        session.flush()
        return instance

    def save(self, session: Session):
        session.add(self)
        session.flush()
        return self

    def delete(self, session: Session) -> None:
        session.delete(self)


def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent] + list(here.parents):
        if (parent / ".git").exists():
            return parent
    return here.parents[2]


REPO_ROOT = _find_repo_root()

def _resolve_data_dir(repo_root: Path) -> Path:
    env_dir = os.getenv("LLMCTL_RAG_DATA_DIR") or os.getenv("RAG_DATA_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    docker_dir = Path("/data/llmctl-rag")
    if docker_dir.exists():
        return docker_dir
    return repo_root / "data" / "llmctl-rag"


DATA_DIR = _resolve_data_dir(REPO_ROOT)
DB_PATH = DATA_DIR / "llmctl-rag.db"
SSH_KEYS_DIR = DATA_DIR / "ssh"
KNOWN_HOSTS_PATH = DATA_DIR / "known_hosts"


def init_engine():
    global _engine, SessionLocal
    if _engine is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{DB_PATH}",
            connect_args={"check_same_thread": False},
            future=True,
        )
        SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, class_=Session)
    return _engine


def init_db() -> None:
    if _engine is None:
        init_engine()
    if _engine is None:
        raise RuntimeError("Database engine is not initialized")
    Base.metadata.create_all(bind=_engine)
    _ensure_source_columns()


def _ensure_source_columns() -> None:
    if _engine is None:
        return
    with _engine.begin() as conn:
        table_exists = conn.execute(
            text(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sources'"
            )
        ).fetchone()
        if not table_exists:
            return
        rows = conn.execute(text("PRAGMA table_info(sources)")).fetchall()
        existing = {row[1] for row in rows}
        additions = {
            "indexed_file_count": "INTEGER",
            "indexed_chunk_count": "INTEGER",
            "indexed_file_types": "TEXT",
        }
        for name, col_type in additions.items():
            if name in existing:
                continue
            conn.execute(text(f"ALTER TABLE sources ADD COLUMN {name} {col_type}"))


@contextmanager
def session_scope():
    if SessionLocal is None:
        init_engine()
    if SessionLocal is None:
        raise RuntimeError("Database session is not initialized")
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
