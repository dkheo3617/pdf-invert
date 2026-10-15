# PDF 색상반전 v2

PDF의 모든 페이지를 색 반전(흰 바탕 ↔ 검은 바탕)해 원본 옆에 `[반전]파일명.pdf`로 저장합니다.
기존 Automator 앱(ImageMagick·Ghostscript 필요)을 Python(PyMuPDF + PySide6)으로 새로 만든 버전으로,
**설치파일 하나만 설치하면 맥·윈도우 어디서나** 동작합니다.

## 기능
- 창에 PDF 파일/폴더 드래그앤드롭 (여러 개 동시)
- 폴더를 넣으면 안의 PDF 전체 반전 (하위 폴더 포함 여부 선택)
- 화질 선택: 고화질 300dpi / 표준 200dpi / 저용량 150dpi
- 진행률, 파일별 결과, 결과 폴더 열기, 작업 취소
- 이미 `[반전]`으로 시작하는 파일은 건너뜀
- 맥: Dock 아이콘에 PDF 떨어뜨리기 / 윈도우: 오른쪽 클릭 메뉴·보내기 메뉴

## 설치파일 받기
GitHub의 **Releases** 또는 **Actions → 최근 빌드 → Artifacts**에서
- 맥: `PDFInvert-2.0.0-mac.dmg` (Apple Silicon)
- 윈도우: `PDFInvert-2.0.0-Windows-Setup.exe`

새 버전 배포: `git tag v2.0.1 && git push --tags` → 자동으로 Release 생성.

## 직접 실행 (개발용)
```bash
pip install -r requirements.txt
python src/app.py
pyinstaller pdf_invert.spec   # 현재 OS용 앱 빌드
```
