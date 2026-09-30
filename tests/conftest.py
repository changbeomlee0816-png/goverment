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
    from app.db.session import make_session_factory

    s = make_session_factory(f"sqlite:///{tmp_path / 'test.db'}")()
    yield s
    s.close()
