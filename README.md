# PDF 색상반전 v2

PDF의 모든 페이지를 색 반전(흰 바탕 ↔ 검은 바탕)해 원본 옆에 `[반전]파일명.pdf`로 저장합니다.
기존 Automator 앱(ImageMagick·Ghostscript 필요)을 Python(PyMuPDF + PySide6)으로 새로 만든 버전으로,
**설치파일 하나만 설치하면 맥·윈도우 어디서나** 동작합니다.

## 기능
- 창에 PDF 파일/폴더 드래그앤드롭 (여러 개 동시)
- 폴더를 넣으면 안의 PDF 전체 반전 (하위 폴더 포함 여부 선택)
- 변환 방식
  - **빠른 변환(기본)**: 원본 위에 '차이' 혼합 레이어를 덮어 색을 뒤집음. 20쪽 0.1초, 글자 벡터 유지, 용량 작음
  - **이미지 변환** 300/200/150dpi: 페이지를 이미지로 바꿔 반전(모든 뷰어 호환). 여러 CPU 코어로 병렬 처리
- 진행률, 파일별 결과, 결과 폴더 열기, 작업 취소
- 이미 `[반전]`으로 시작하는 파일은 건너뜀
- 맥: Dock 아이콘에 PDF 떨어뜨리기 / 윈도우: 오른쪽 클릭 메뉴·보내기 메뉴
- 앱 안에서 업데이트: 시작할 때 새 버전 확인 → [지금 업데이트]로 내려받아 설치 후 자동 재실행

## 설치파일 받기
- 맥 (Apple 칩 M1 이상): https://github.com/dkheo3617/pdf-invert/releases/latest/download/PDFInvert-mac.dmg
- 윈도우 10/11: https://github.com/dkheo3617/pdf-invert/releases/latest/download/PDFInvert-Windows-Setup.exe

main에 올리면 자동으로 빌드되어 Release(v + src/app.py의 VERSION)가 갱신됩니다.
새 버전을 낼 때는 src/app.py, pdf_invert.spec, installer/windows.iss의 버전을 함께 올리고 RELEASE_NOTES.md 맨 위에 변경 내용을 적으세요(앱의 업데이트 안내창에 표시됨).

## 직접 실행 (개발용)
```bash
pip install -r requirements.txt
python src/app.py
pyinstaller pdf_invert.spec   # 현재 OS용 앱 빌드
```
