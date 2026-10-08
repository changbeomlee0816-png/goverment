# 워드·PDF → 한글 변환기

워드(.docx)나 PDF를 올리면 한/글 문서(.hwpx 또는 .hwp)로 바꿔 주는 단독 웹앱입니다.
DB, API 키, 비밀번호가 필요 없습니다. 변환 코드는 `app/docs/docx_to_hwp.py`, `app/docs/pdf_to_hwp.py`를 함께 씁니다.

## 웹에 올리기 (Streamlit Community Cloud, 무료)
1. https://share.streamlit.io 에 GitHub 계정으로 로그인합니다.
2. **Create app → Deploy a public app from GitHub**를 누릅니다.
3. 다음과 같이 입력합니다.
   - Repository: `changbeomlee0816-png/goverment`
   - Branch: `claude/stoic-carson-9oq1nn` (main에 병합했다면 `main`)
   - Main file path: `word2hwp/app.py`
   - App URL: 원하는 주소(예: `word2hwp`)
4. **Deploy**를 누르면 `https://<주소>.streamlit.app` 링크가 생깁니다. 이 링크로 들어가 바로 쓰면 됩니다.

## 내 PC에서 실행
```bash
pip install -r word2hwp/requirements.txt
streamlit run word2hwp/app.py
```
