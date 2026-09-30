import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    """테스트는 LLM 없이(규칙 기반) 실행."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")


@pytest.fixture
def session(tmp_path):
    """기본은 임시 SQLite. TEST_DATABASE_URL을 주면 그 DB(예: PostgreSQL)를 비우고 사용."""
    from app.db.models import Base
    from app.db.session import get_engine, make_session_factory

    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"
    engine = get_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    s = make_session_factory(url)()
    yield s
    s.close()
