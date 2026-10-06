from sqlalchemy import create_engine, inspect, text

from app.db.session import add_missing_columns, normalize_url


def test_normalize_supabase_url():
    url = "postgresql://postgres.abcd:pw@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres"
    assert normalize_url(url) == "postgresql+psycopg://postgres.abcd:pw@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres?sslmode=require"
    assert normalize_url("postgres://u:p@localhost:5432/db") == "postgresql+psycopg://u:p@localhost:5432/db"
    assert normalize_url("sqlite:///data/app.db") == "sqlite:///data/app.db"
    assert normalize_url(url + "?sslmode=disable").endswith("sslmode=disable")


def test_add_missing_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:  # 이전 버전 스키마(파일 컬럼 없음)
        conn.execute(text("CREATE TABLE document (id INTEGER PRIMARY KEY, company_id INTEGER, doc_type VARCHAR(50), file_path VARCHAR(1000), issued_date DATE, expires_date DATE)"))
    added = add_missing_columns(engine)
    assert "document.file_data" in added and "document.file_name" in added
    assert {"file_data", "file_name"} <= {c["name"] for c in inspect(engine).get_columns("document")}


def test_diagnose_common_mistakes():
    from app.db.session import diagnose_url, redact

    assert any("YOUR-PASSWORD" in h for h in diagnose_url("postgresql://postgres.abc:[YOUR-PASSWORD]@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres"))
    assert any("Direct connection" in h for h in diagnose_url("postgresql://postgres:pw@db.abc.supabase.co:5432/postgres"))
    assert any("6543" in h for h in diagnose_url("postgresql://postgres.abc:pw@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres"))
    assert any("postgres.<프로젝트ID>" in h for h in diagnose_url("postgresql://postgres:pw@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres"))
    assert diagnose_url("postgresql://postgres.abc:pw@aws-1-ap-northeast-2.pooler.supabase.com:5432/postgres") == []
    msg = redact("password authentication failed: s3cret", "postgresql://postgres.abc:s3cret@h:5432/postgres")
    assert "s3cret" not in msg
