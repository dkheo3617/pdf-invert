"""PDF 색상반전 — 드래그앤드롭 GUI (macOS / Windows)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

from inverter import QUALITY_PRESETS, Job, collect_jobs, invert_pdf, page_count

APP_NAME = "PDF 색상반전"
VERSION = "2.1.0"


def resource(name: str) -> str:
    base = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)
    return str(Path(base) / "assets" / name)


class Worker(QObject):
    progress = Signal(int, int)          # 처리한 페이지, 전체 페이지
    file_started = Signal(int, str)      # 순번, 파일명
    file_done = Signal(int, str, str)    # 순번, 결과 경로, 오류(없으면 "")
    finished = Signal(int, int)          # 성공 수, 실패 수

    def __init__(self, jobs: list[Job], dpi: int):
        super().__init__()
        self.jobs, self.dpi, self._stop = jobs, dpi, False

    def stop(self):
        self._stop = True

    def run(self):
        totals = []
        for j in self.jobs:
            try:
                totals.append(page_count(j.src))
            except Exception:
                totals.append(1)
        total, done, ok, fail = sum(totals) or 1, 0, 0, 0
        for idx, job in enumerate(self.jobs):
            if self._stop:
                break
            self.file_started.emit(idx, job.src.name)
            base = done
            try:
                invert_pdf(job.src, job.dst, self.dpi,
                           on_page=lambda i, n, b=base: self.progress.emit(b + i, total),
                           should_stop=lambda: self._stop)
                ok += 1
                self.file_done.emit(idx, str(job.dst), "")
            except InterruptedError:
                self.file_done.emit(idx, "", "취소됨")
                break
            except Exception as e:  # noqa: BLE001
                fail += 1
                self.file_done.emit(idx, "", str(e) or e.__class__.__name__)
            done = base + totals[idx]
            self.progress.emit(done, total)
        self.finished.emit(ok, fail)


class DropZone(QFrame):
    dropped = Signal(list)
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("drop")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(150)
        lay = QVBoxLayout(self)
        icon = QLabel("⇩")
        icon.setObjectName("dropIcon")
        icon.setAlignment(Qt.AlignCenter)
        t = QLabel("PDF 파일이나 폴더를 여기에 끌어다 놓으세요")
        t.setObjectName("dropTitle")
        t.setAlignment(Qt.AlignCenter)
        s = QLabel("또는 클릭해서 파일 선택 · 결과는 원본 옆에 [반전]파일명.pdf 로 저장")
        s.setObjectName("dropSub")
        s.setAlignment(Qt.AlignCenter)
        lay.addStretch(); lay.addWidget(icon); lay.addWidget(t); lay.addWidget(s); lay.addStretch()

    def _set_hover(self, on: bool):
        self.setProperty("hover", on)
        self.style().unpolish(self); self.style().polish(self)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction(); self._set_hover(True)

    def dragLeaveEvent(self, e):
        self._set_hover(False)

    def dropEvent(self, e):
        self._set_hover(False)
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.dropped.emit(paths)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


STYLE = """
QWidget { font-size: 13px; }
#title { font-size: 20px; font-weight: 700; }
#ver { color: #888; }
#drop { border: 2px dashed #9aa4b2; border-radius: 12px; background: palette(base); }
#drop[hover="true"] { border-color: #1a9be6; background: rgba(26,155,230,0.08); }
#dropIcon { font-size: 34px; color: #1a9be6; }
#dropTitle { font-size: 15px; font-weight: 600; }
#dropSub { color: #888; font-size: 12px; }
QPushButton { padding: 6px 14px; }
QProgressBar { height: 16px; border-radius: 6px; text-align: center; }
"""


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("Gwasaram", "PDFInvert")
        self.thread: QThread | None = None
        self.worker: Worker | None = None
        self.last_dir: str | None = None
        self.setWindowTitle(APP_NAME)
        self.resize(560, 560)
        self.setStyleSheet(STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel(APP_NAME); title.setObjectName("title")
        ver = QLabel(f"v{VERSION}"); ver.setObjectName("ver")
        head.addWidget(title); head.addStretch(); head.addWidget(ver, alignment=Qt.AlignBottom)
        root.addLayout(head)

        self.drop = DropZone()
        self.drop.dropped.connect(self.start)
        self.drop.clicked.connect(self.pick_files)
        root.addWidget(self.drop)

        row = QHBoxLayout()
        self.btn_files = QPushButton("파일 선택…"); self.btn_files.clicked.connect(self.pick_files)
        self.btn_dir = QPushButton("폴더 선택…"); self.btn_dir.clicked.connect(self.pick_dir)
        row.addWidget(self.btn_files); row.addWidget(self.btn_dir); row.addStretch()
        row.addWidget(QLabel("변환 방식"))
        self.quality = QComboBox(); self.quality.addItems(list(QUALITY_PRESETS))
        saved = self.settings.value("quality", "")
        if saved in QUALITY_PRESETS:
            self.quality.setCurrentText(saved)
        self.quality.setToolTip("빠른 변환: 몇 초 안에 끝나고 글자가 선명하며 용량도 작습니다.\n"
                                "보기 앱에서 하얗게만 보이면 이미지 변환을 선택하세요.")
        self.quality.currentTextChanged.connect(lambda t: self.settings.setValue("quality", t))
        row.addWidget(self.quality)
        root.addLayout(row)

        self.recursive = QCheckBox("폴더를 넣으면 하위 폴더의 PDF까지 모두 반전")
        self.recursive.setChecked(self.settings.value("recursive", "true") == "true")
        self.recursive.toggled.connect(lambda v: self.settings.setValue("recursive", "true" if v else "false"))
        root.addWidget(self.recursive)

        self.status = QLabel("대기 중")
        self.bar = QProgressBar(); self.bar.setValue(0)
        root.addWidget(self.status); root.addWidget(self.bar)

        self.log = QListWidget()
        root.addWidget(self.log, 1)

        bottom = QHBoxLayout()
        self.btn_open = QPushButton("결과 폴더 열기"); self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self.open_result_dir)
        self.btn_cancel = QPushButton("취소"); self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel)
        bottom.addWidget(self.btn_open); bottom.addStretch(); bottom.addWidget(self.btn_cancel)
        root.addLayout(bottom)

    # ── 입력 ──────────────────────────────────────────
    def _start_dir(self) -> str:
        return self.settings.value("last_dir", str(Path.home()))

    def pick_files(self):
        if self.busy():
            return
        files, _ = QFileDialog.getOpenFileNames(self, "반전할 PDF 선택", self._start_dir(), "PDF (*.pdf *.PDF)")
        if files:
            self.start(files)

    def pick_dir(self):
        if self.busy():
            return
        d = QFileDialog.getExistingDirectory(self, "반전할 폴더 선택", self._start_dir())
        if d:
            self.start([d])

    def busy(self) -> bool:
        return self.thread is not None

    # ── 실행 ──────────────────────────────────────────
    def start(self, paths: list[str]):
        if self.busy():
            QMessageBox.information(self, APP_NAME, "지금 작업 중입니다. 끝난 뒤 다시 넣어 주세요.")
            return
        first = Path(paths[0])
        self.settings.setValue("last_dir", str(first if first.is_dir() else first.parent))
        jobs = collect_jobs(paths, self.recursive.isChecked())
        if not jobs:
            QMessageBox.information(self, APP_NAME, "반전할 PDF가 없습니다.\n(이미 [반전]으로 시작하는 파일은 건너뜁니다.)")
            return
        if len(jobs) > 1:
            existing = sum(j.dst.exists() for j in jobs)
            msg = f"PDF {len(jobs)}개를 반전합니다."
            if existing:
                msg += f"\n이미 [반전] 파일이 있는 {existing}개는 새로 덮어씁니다."
            if QMessageBox.question(self, APP_NAME, msg + "\n계속할까요?") != QMessageBox.Yes:
                return
        self.log.clear()
        self.items = []
        for j in jobs:
            it = QListWidgetItem(f"⏳  {j.src.name}")
            self.log.addItem(it); self.items.append(it)
        self.last_dir = str(jobs[0].dst.parent)
        self.bar.setValue(0)
        self.set_busy(True)

        self.thread = QThread()
        self.worker = Worker(jobs, QUALITY_PRESETS[self.quality.currentText()])
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.file_started.connect(self.on_file_started)
        self.worker.file_done.connect(self.on_file_done)
        self.worker.finished.connect(self.on_finished)
        self.thread.start()

    def set_busy(self, on: bool):
        for w in (self.btn_files, self.btn_dir, self.quality, self.recursive):
            w.setEnabled(not on)
        self.btn_cancel.setEnabled(on)
        self.drop.setEnabled(not on)

    def cancel(self):
        if self.worker:
            self.worker.stop()
            self.status.setText("취소하는 중…")

    def on_progress(self, done: int, total: int):
        self.bar.setMaximum(total); self.bar.setValue(done)

    def on_file_started(self, idx: int, name: str):
        self.status.setText(f"({idx + 1}/{len(self.items)}) {name} 반전 중…")
        self.items[idx].setText(f"▶  {name}")
        self.log.scrollToItem(self.items[idx])

    def on_file_done(self, idx: int, out: str, err: str):
        name = self.items[idx].text()[3:]
        if err:
            self.items[idx].setText(f"✖  {name} — {err}")
        else:
            self.items[idx].setText(f"✔  {Path(out).name}")
            self.last_dir = str(Path(out).parent)

    def on_finished(self, ok: int, fail: int):
        self.thread.quit(); self.thread.wait()
        self.thread = self.worker = None
        self.set_busy(False)
        self.btn_open.setEnabled(ok > 0)
        self.status.setText(f"완료 — 성공 {ok}개" + (f", 실패 {fail}개" if fail else ""))
        if ok and not fail:
            self.bar.setValue(self.bar.maximum())

    def open_result_dir(self):
        if not self.last_dir:
            return
        if sys.platform == "darwin":
            subprocess.run(["open", self.last_dir])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_dir))

    def closeEvent(self, e):
        if self.busy():
            if QMessageBox.question(self, APP_NAME, "작업 중입니다. 취소하고 닫을까요?") != QMessageBox.Yes:
                e.ignore(); return
            self.worker.stop(); self.thread.quit(); self.thread.wait(5000)
        e.accept()


class App(QApplication):
    """macOS: Dock 아이콘에 파일을 떨어뜨리거나 '다음으로 열기'로 열 때 처리."""
    def __init__(self, argv):
        super().__init__(argv)
        self.window: MainWindow | None = None
        self.pending: list[str] = []

    def event(self, e):
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.FileOpen:
            path = e.file()
            if self.window:
                self.window.start([path])
            else:
                self.pending.append(path)
            return True
        return super().event(e)


def main():
    import multiprocessing
    multiprocessing.freeze_support()
    app = App(sys.argv)
    app.setApplicationName(APP_NAME)
    icon = resource("icon.png")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    w = MainWindow()
    app.window = w
    w.show()
    initial = [a for a in sys.argv[1:] if os.path.exists(a)] + app.pending
    if initial:
        w.start(initial)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
