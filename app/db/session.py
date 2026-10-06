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


def describe_url(url: str) -> dict:
    """접속 정보 요약(비밀번호 제외)."""
    from sqlalchemy.engine import make_url

    try:
        u = make_url(normalize_url(url))
    except Exception:  # noqa: BLE001
        return {"형식": "해석 불가"}
    return {"드라이버": u.drivername, "사용자": u.username, "호스트": u.host, "포트": u.port, "DB": u.database}


def diagnose_url(url: str) -> list[str]:
    """DATABASE_URL에서 흔한 설정 실수를 찾는다(Supabase 기준)."""
    hints = []
    if not url:
        return hints
    if "[YOUR-PASSWORD]" in url or "YOUR-PASSWORD" in url:
        hints.append("주소에 [YOUR-PASSWORD]가 그대로 있습니다. 대괄호까지 지우고 실제 DB 비밀번호를 넣으세요.")
    info = describe_url(url)
    host, port, user = info.get("호스트") or "", info.get("포트"), info.get("사용자") or ""
    if host.startswith("db.") and host.endswith(".supabase.co"):
        hints.append("Direct connection 주소(db.xxx.supabase.co)입니다. Streamlit Cloud는 IPv4만 지원하므로 Connect → Session pooler 주소를 쓰세요.")
    if "pooler.supabase.com" in host:
        if port == 6543:
            hints.append("포트 6543은 Transaction pooler입니다. Session pooler(포트 5432) 주소를 쓰세요.")
        if "." not in user:
            hints.append("pooler 주소의 사용자명은 'postgres.<프로젝트ID>' 형식이어야 합니다.")
    if url.count("@") > 1:
        hints.append("주소에 '@'가 두 번 이상 있습니다. 비밀번호 안의 '@'는 %40으로 바꿔 쓰세요.")
    return hints


def redact(text_: str, url: str) -> str:
    """오류 메시지에서 비밀번호를 가린다."""
    from sqlalchemy.engine import make_url

    try:
        pw = make_url(normalize_url(url)).password
    except Exception:  # noqa: BLE001
        pw = None
    if pw:
        text_ = text_.replace(pw, "****")
    return text_
