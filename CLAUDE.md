# CLAUDE.md — 정부지원사업 매칭·사업계획서 도우미

이 파일은 Claude Code가 이 프로젝트에서 항상 먼저 읽는 작업 지침이다.
상세 요구사항은 `docs/REQUIREMENTS.md`를 따른다.

## 프로젝트 한 줄 요약
자사 기업정보·아이템 포트폴리오를 등록하면, 기업마당·K-Startup 등 공고를 수집해 적합 사업을 점수화해 추천하고,
선택한 사업의 평가지표에 맞춘 사업계획서 초안 작성과 자체 점검(레드팀)까지 지원하는 사내용 웹앱.

## 기술 스택 (MVP)
- Python 3.11+, Streamlit(UI), FastAPI는 2단계부터
- SQLite + SQLAlchemy (추후 PostgreSQL 전환 가능하도록 ORM 사용)
- 문서 추출: pdfplumber, HWP는 hwp5txt(pyhwp) 또는 LibreOffice 변환
- LLM: Claude API (anthropic SDK). 공고문·양식·평가표처럼 반복 참조하는 긴 텍스트는 프롬프트 캐싱 적용
- 출력: python-docx(DOCX), 표는 pandas → Excel

## 폴더 구조 (이 구조를 유지)
```
app/
  ui/            Streamlit 페이지 (1_기업정보, 2_포트폴리오, 3_공고, 4_매칭, 5_계획서, 6_점검, 7_캘린더)
  collectors/    공고 수집기 (bizinfo.py, kstartup.py, ntis.py, manual_upload.py)
  matching/      rules.py(자격 하드필터), scoring.py(점수화), report.py(보고서)
  writer/        계획서 섹션 생성, 평가지표 매핑
  review/        체크리스트·가상 채점
  llm/           claude_client.py, prompts/ (프롬프트는 .md 파일로 분리)
  db/            models.py, session.py, seed.py(샘플 데이터)
  docs/          문서 텍스트 추출(PDF/HWP/HWPX/DOCX), 사업자등록증 추출
  manage/        신청 관리 보조(마감·서류 알림, 제출서류 체크리스트)
data/
  snapshots/     수집한 공고 원본 JSON (날짜별)
  templates/     표준 사업계획서 양식, 평가표 (연도별 폴더)
docs/REQUIREMENTS.md
.env.example
```

## 반드시 지킬 규칙
1. **규칙 기반과 LLM 분리**: 자격요건 판정·점수 계산은 Python 규칙 코드로 한다. LLM은 판정 결과를 받아 설명·요약·초안 작성만 한다.
2. **근거 없는 사실 생성 금지**: 추천·수치·마감일은 반드시 공고 원문(파일/URL, 해당 문장)을 근거로 저장한다. 근거가 없으면 UI에 "확인 필요" 배지를 표시한다.
3. **수집과 표시 분리**: 공공 API는 서버/스크립트에서만 호출하고 결과를 `data/snapshots/`에 저장한 뒤 UI는 DB/스냅샷을 읽는다. API 키를 프런트엔드나 로그에 노출하지 않는다.
4. **API 키는 `.env`로만 관리**: `ANTHROPIC_API_KEY`, `BIZINFO_API_KEY`, `DATA_GO_KR_KEY`, `NTIS_API_KEY`. `.env`는 git에 올리지 않는다.
5. **출력 구분 규칙**: 매칭 결과는 항상 ①부처(중앙정부) / ②지자체·지역기관 섹션을 분리하고, 각 사업에 R&D / 비R&D 태그를 붙이며, 마지막에 요약표를 둔다.
6. **한국어 UI**, 용어는 공고·표준양식의 공식 용어를 그대로 사용한다(예: "연구개발비", "기관부담금", "기술성숙도(TRL)").
7. 화면은 단순하게: 색상은 강조 1색 이내, 표 중심.
8. 새 기능은 작은 단위로 만들고 각 단계마다 샘플 데이터로 실행 확인 후 다음 단계로 간다.

## 개발 순서
1. DB 모델 + 기업정보·포트폴리오 입력 화면
2. 공고 수동 업로드(PDF/HWP) + 기업마당 API 수집기
3. 규칙 매칭 + 점수화 + 매칭 보고서
4. 계획서 섹션 초안 + 평가지표 매핑
5. 자체 점검(체크리스트·가상 채점)
6. 신청 관리(칸반/캘린더), 서류 보관함, 알림

## 작업 방식
- 각 단계 시작 전 변경할 파일 목록과 계획을 먼저 제시하고 확인받는다.
- 외부 API 응답 형식은 추측하지 말고, 먼저 1건 호출해 원본 JSON을 `data/snapshots/`에 저장한 뒤 그 구조에 맞춰 파서를 작성한다.
- 테스트: `pytest`로 rules.py·scoring.py는 반드시 단위 테스트 작성.
