"""DB 엔진·세션."""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import DATA_DIR, database_url
from app.db.models import Base


def normalize_url(url: str) -> str:
    """Supabase·Heroku 형식(postgres://, postgresql://)을 SQLAlchemy psycopg3 드라이버 URL로 바꾼다."""
    url = url.strip()
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg://" + url[len(prefix):]
            break
    if url.startswith("postgresql+psycopg://") and "sslmode=" not in url and not _is_local(url):
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def _is_local(url: str) -> bool:
    host = url.split("@")[-1].split("/")[0]
    return host.startswith(("localhost", "127.0.0.1")) or "host=/" in url or host == ""


def get_engine(url: str | None = None):
    # 환경변수(Streamlit Secrets 포함)를 읽은 뒤의 실제 URL 기준으로 캐시한다
    return _engine(normalize_url(url or database_url()))


@lru_cache(maxsize=4)
def _engine(url: str):
    if url.startswith("sqlite:///"):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, future=True)
    else:
        # 외부 DB: 끊긴 연결 자동 복구, 풀러(Supabase pooler) 친화적인 작은 풀
        engine = create_engine(url, future=True, pool_pre_ping=True, pool_size=3, max_overflow=5, pool_recycle=1800)
    Base.metadata.create_all(engine)
    add_missing_columns(engine)
    return engine


def add_missing_columns(engine) -> list[str]:
    """모델에 새로 생긴 컬럼을 기존 테이블에 추가하는 최소 마이그레이션(nullable 컬럼만)."""
    added = []
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in tables:
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing or not column.nullable:
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))
                added.append(f"{table.name}.{column.name}")
    return added


def make_session_factory(url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(url), expire_on_commit=False, future=True)


@contextmanager
def session_scope(url: str | None = None):
    session = make_session_factory(url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
