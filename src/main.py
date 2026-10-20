"""실행 진입점: 시작 오류를 기록·표시하고, 빌드 검증용 --selftest 를 제공한다."""
import os
import sys
import traceback


def _log_path() -> str:
    if sys.platform == "darwin":
        d = os.path.expanduser("~/Library/Logs")
    elif sys.platform == "win32":
        d = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "PDFInvert")
    else:
        d = os.path.expanduser("~")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "PDFInvert-error.log")


def _alert(msg: str) -> None:
    try:
        if sys.platform == "darwin":
            import subprocess
            subprocess.run(["osascript", "-e",
                            f'display alert "PDF색상반전을 시작하지 못했습니다" message {msg!r} as critical'],
                           timeout=60)
        elif sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg, "PDF 색상반전", 0x10)
    except Exception:
        pass


def selftest() -> int:
    """패키징된 앱이 실제로 동작하는지 확인 (CI에서 실행)."""
    import tempfile
    from pathlib import Path

    import pymupdf
    import PySide6.QtWidgets  # noqa: F401
    import updater  # noqa: F401
    from inverter import invert_pdf

    tmp = Path(tempfile.mkdtemp())
    src = tmp / "t.pdf"
    d = pymupdf.open()
    for i in range(5):
        p = d.new_page()
        p.insert_text((72, 72), f"page {i + 1}", fontsize=20)
    d.save(src)
    for dpi in (0, 72):
        out = tmp / f"o{dpi}.pdf"
        invert_pdf(src, out, dpi)
        with pymupdf.open(out) as o:
            assert o.page_count == 5
            pix = o[0].get_pixmap(dpi=20)
            assert pix.pixel(2, 2)[0] < 30, "반전되지 않음"
    print("SELFTEST OK")
    return 0


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    if "--selftest" in sys.argv:
        try:
            sys.exit(selftest())
        except Exception:
            traceback.print_exc()
            sys.exit(1)
    try:
        import app
        app.main()
    except SystemExit:
        raise
    except Exception:
        tb = traceback.format_exc()
        path = _log_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(tb)
        except Exception:
            pass
        _alert(f"{tb.strip().splitlines()[-1]}\n\n자세한 내용: {path}")
        sys.exit(1)
