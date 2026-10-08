# 정부지원사업 매칭·사업계획서 도우미

자사 기업정보와 아이템 포트폴리오를 등록하면 다음을 지원합니다.
- 기업마당·K-Startup 공고를 **주기적으로 자동 수집**합니다.
- 적합한 사업을 **자격 하드필터와 점수**로 추천합니다.
- 공고의 **사업계획서 양식(HWP/HWPX/DOCX/PDF)과 평가표**를 올리면, 양식의 섹션 순서와 ※작성 지시문, 배점에 맞춘 **사업계획서 초안**을 만듭니다.
- 작성한 초안을 **자체 점검(레드팀)**합니다.
- 워드 문서(.docx)를 올리면 **한/글 문서(.hwpx/.hwp)로 바로 변환**합니다(한/글 프로그램 불필요).

상세 요구사항은 [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md), 개발 규칙은 [`CLAUDE.md`](CLAUDE.md)를 보세요.

## 빠른 시작

```bash
pip install -r requirements.txt
cp .env.example .env            # API 키 입력 (없어도 규칙 기반 모드로 동작)
python -m app.db.seed           # 샘플 기업(에너지 관리 솔루션)·공고 3건 등록
streamlit run app/ui/Home.py    # http://localhost:8501
```

| .env 키 | 용도 | 발급처 |
|---|---|---|
| `ANTHROPIC_API_KEY` | AI 양식 구조화·인터뷰·초안·가상 채점·자격요건 추출 | platform.claude.com |
| `BIZINFO_API_KEY` | 기업마당 공고 수집 | 기업마당 > 활용정보 > 정책정보 개방 |
| `DATA_GO_KR_KEY` | K-Startup 공고 수집 | 공공데이터포털 15125364 활용신청 |
| `NTIS_API_KEY` | 국가R&D 유사과제 검색(참고용) | NTIS 회원정보 소속기관 등록 후 신청 |

## 웹 배포 (Streamlit Community Cloud, 무료)

1. https://share.streamlit.io 에 GitHub 계정으로 로그인합니다.
2. **Create app → Deploy a public app from GitHub**를 선택하고 다음과 같이 입력합니다.
   - Repository: `changbeomlee0816-png/goverment`
   - Branch: `claude/tender-ramanujan-w0ioh1` (main에 병합했다면 `main`)
   - Main file path: `app/ui/Home.py`
3. **Advanced settings → Secrets**에 아래 내용을 붙여 넣습니다. 값은 필요한 것만 넣으면 됩니다.
   ```toml
   APP_PASSWORD = "사내 접속 비밀번호"   # 꼭 설정하세요. 설정하면 접속 시 비밀번호를 묻습니다
   ANTHROPIC_API_KEY = ""
   BIZINFO_API_KEY = ""
   DATA_GO_KR_KEY = ""
   NTIS_API_KEY = ""
   DATABASE_URL = ""   # 아래 '외부 DB 연결' 참고 (비우면 재시작 시 데이터 초기화)
   ```
4. **Deploy**를 누르면 `https://<앱이름>.streamlit.app` 주소가 생깁니다.
5. 처음 접속하면 홈 화면의 **샘플 데이터 불러오기**로 기능을 둘러볼 수 있습니다.

> ⚠️ Streamlit Cloud는 앱이 재시작되면 로컬 파일이 초기화됩니다. 실제 업무 데이터는 아래처럼 외부 DB(Supabase)에 보관하세요.

### 외부 DB 연결 (Supabase 무료 PostgreSQL)
1. https://supabase.com/dashboard/projects 에서 **New project**를 만듭니다. Region은 `Northeast Asia (Seoul)`, DB 비밀번호는 따로 기록해 둡니다.
2. 프로젝트 상단의 **Connect** 버튼을 누르고 **Session pooler** 연결 문자열을 복사합니다.
   - Streamlit Cloud는 IPv4만 지원하므로 Direct connection이 아니라 **Session pooler**를 써야 합니다.
3. Secrets에 `DATABASE_URL`로 넣고 `[YOUR-PASSWORD]` 부분을 DB 비밀번호로 바꿉니다.
   ```toml
   DATABASE_URL = "postgresql://postgres.xxxxxxxx:비밀번호@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres"
   ```
   - 비밀번호에 `@ : / ? #` 같은 특수문자가 있으면 URL 인코딩하세요(예: `@` → `%40`).
4. 앱이 처음 접속될 때 테이블을 자동으로 만듭니다.
   - SSL은 자동 적용됩니다.
   - 모델에 새 컬럼이 생기면 다음 실행 때 자동으로 추가됩니다.

외부 DB를 쓰면 기업정보, 공고, 신청, 계획서 초안뿐 아니라 **서류 보관함 파일(10MB 이하)**도 DB에 저장되어 재시작 후에도 유지됩니다.
공고 원본 스냅샷(`data/snapshots/`)은 로컬 파일이므로 Cloud에서는 재시작 시 사라지지만, 수집된 공고 데이터 자체는 DB에 남습니다.

### API 키 발급 링크
| 키 | 발급 페이지 | 비고 |
|---|---|---|
| `ANTHROPIC_API_KEY` | https://platform.claude.com/settings/keys | 결제수단 등록 필요 |
| `BIZINFO_API_KEY` | https://www.bizinfo.go.kr/apiList.do | "지원사업정보 API" 활용 신청 → 인증키 발급 |
| `DATA_GO_KR_KEY` | https://www.data.go.kr/data/15125364/openapi.do | 로그인 → 활용신청(자동승인) → 마이페이지의 **일반 인증키(Decoding)** |
| `NTIS_API_KEY` | https://www.ntis.go.kr/rndopen/api/mng/apiMain.do | 회원정보에 소속기관 등록 후 신청(선택) |
> 서버 상주 스케줄러(`--schedule`)는 Cloud에서 돌릴 수 없습니다. 대신 앱을 열 때 수집 주기가 지났으면 자동으로 수집합니다.

## 공고 자동 업데이트

공고는 세 가지 방법으로 갱신됩니다. 주기는 [설정] 화면에서 바꿀 수 있고 기본값은 24시간입니다.

1. **앱을 열 때**: 마지막 수집 후 주기가 지났으면 홈 화면에서 자동으로 수집합니다.
2. **상시 실행**: `python -m app.collectors.run --schedule --extract`를 띄워 두면 주기마다 수집하고, 새 공고의 자격요건도 추출합니다.
3. **cron / 작업 스케줄러**: `10 6 * * * cd /path/goverment && python -m app.collectors.run --extract`

수집한 원본 응답은 `data/snapshots/YYYYMMDD/`에 저장됩니다. 중복 여부는 제목+기관+접수기간으로 판단합니다.
> ⚠️ API 응답 필드명은 인증키가 없어 실제 응답으로 검증하지 못했습니다. 키 발급 후 첫 스냅샷을 열어 `app/collectors/bizinfo.py`·`kstartup.py`의 `pick()` 후보 필드명과 맞는지 확인하세요.

## 사업계획서 작성 흐름 ([계획서] 화면)

1. **양식·평가표 업로드**
   - 양식에서 번호 체계(Ⅰ., 1., 1-1., 가., □)로 섹션을 나누고, ※·* 작성 지시문과 분량 제한을 인식합니다.
   - 평가표에서는 평가항목과 배점을 읽어 섹션에 연결합니다.
   - API 키가 있으면 AI가 표 안의 지시문까지 구조화합니다.
   - 양식이 없으면 교육 기준 R&D 표준 구성(`data/templates/default_rnd.json`)을 씁니다.
2. **섹션별 요구사항 확인·수정**: 섹션, 지시문, 평가항목 연결, 배점을 확인하고 필요하면 고칩니다.
3. **인터뷰**: 평가항목 대비 부족한 정보를 질문하고, 사용자가 답합니다.
4. **보조도구**: 시장규모(TAM-SAM-SOM), 5개년 매출표(A=B+D, C=B/A×100), 업무분담표를 계산합니다.
5. **섹션 초안 → 수정 → 내보내기**
   - DOCX로 내보내면 양식 순서를 따릅니다.
   - 섹션별로 "HWP 붙여넣기용 텍스트"도 제공합니다.
   - 출처 없는 수치 문장과 `[확인 필요]` 항목은 노란색으로 표시됩니다.

AI는 **제공된 기업·아이템 정보, 인터뷰 답변, 보조도구 결과만** 근거로 씁니다. 없는 수치는 만들지 않고 `[확인 필요: …]`로 남깁니다.

## 화면 구성

| 화면 | 기능 |
|---|---|
| 기업정보 | 기업 등록(사업자등록증 업로드 자동 추출), 선행연구, 서류 보관함(유효기간) |
| 포트폴리오 | 아이템 요약맵(이슈→성능지표→측정방식), Discovery/Project/Asset, NTIS 참고 검색 |
| 공고 | 목록·필터, 지금 수집, 공고문 업로드, 자격요건 추출·확인(근거 문장), 연간 후보 리스트 |
| 매칭 | 하드필터 + 5차원 점수, ①부처 / ②지자체·지역기관 분리, R&D 태그, 요약표, Excel |
| 계획서 | 양식·평가표 → 인터뷰 → 보조도구 → 섹션 초안 → DOCX |
| 점검 | 규칙 점검(누락·정량·출처·분량·지표연계) + 가상 채점, 외부 계획서 업로드 점검 |
| 캘린더 | 칸반/리스트/캘린더, D-14/7/3 알림, 제출서류 체크리스트·발급처 안내 |
| 설정 | 매칭 가중치, 수집 주기, 알림, AI 모델, 프롬프트 파일 편집 |

## 구조 원칙
- **규칙과 LLM의 역할 분리**: 자격 판정과 점수 계산은 `app/matching/rules.py`, `scoring.py`의 Python 코드가 합니다. LLM은 설명, 추출, 초안 작성만 맡습니다.
- **근거 추적**: 자격요건은 원문 근거 문장과 함께 저장하고 사람이 확인 체크합니다. 매칭 결과에는 원문 링크를 붙입니다.
- **수집과 표시 분리**: API는 서버 측(수집기)에서만 호출합니다. 키는 `.env`에만 두고 로그에 남기지 않습니다.

## 테스트

```bash
python -m pytest -q
```
규칙, 점수, 양식 파서, 수집기 파서, 문서 추출, 매출표를 검사합니다. 샘플 기업으로 전체 흐름(매칭 → 양식 → 인터뷰 → 초안 → DOCX → 점검)도 실행합니다.

## 알려진 제약
- HWP(5.0)는 외부 프로그램 없이 직접 파싱합니다.
  - 배포용·암호 문서는 추출할 수 없으므로 PDF나 HWPX로 저장해 올리세요.
  - `hwp5txt`나 LibreOffice가 설치돼 있으면 파싱 실패 시 자동으로 대체합니다.
- 규칙 기반 모드(API 키 없음)의 초안은 지시문별 작성 골격과 입력 자료 표로 구성됩니다. 문장 작성과 가상 채점은 API 키를 설정해야 활성화됩니다.
