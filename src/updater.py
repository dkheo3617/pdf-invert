"""GitHub Release 기반 자동 업데이트 (macOS / Windows)."""
from __future__ import annotations

import json
import os
import shlex
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO = "dkheo3617/pdf-invert"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
ASSET = {"darwin": "PDFInvert-mac.dmg", "win32": "PDFInvert-Windows-Setup.exe"}


def _ssl_ctx() -> ssl.SSLContext:
    try:
        import certifi  # 패키징된 앱에서 인증서 오류 방지
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _open(url: str, timeout: float = 15):
    req = urllib.request.Request(url, headers={"User-Agent": "PDFInvert-updater",
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx())


def parse_version(v: str) -> tuple[int, ...]:
    parts = []
    for x in v.strip().lstrip("vV").split("."):
        digits = "".join(c for c in x if c.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


@dataclass
class Release:
    version: str
    notes: str
    asset_url: str | None
    asset_name: str | None
    size: int


def fetch_latest() -> Release:
    with _open(API_LATEST) as r:
        d = json.load(r)
    want = ASSET.get(sys.platform)
    url = name = None
    size = 0
    for a in d.get("assets", []):
        if a.get("name") == want:
            url, name, size = a["browser_download_url"], a["name"], a.get("size", 0)
    return Release(d.get("tag_name", "").lstrip("vV"), d.get("body") or "", url, name, size)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def download(rel: Release, on_progress: Callable[[int, int], None] | None = None,
             should_stop: Callable[[], bool] | None = None) -> Path:
    dst = Path(tempfile.mkdtemp(prefix="pdfinvert-upd-")) / rel.asset_name
    with _open(rel.asset_url, timeout=60) as r, open(dst, "wb") as f:
        total = int(r.headers.get("Content-Length") or rel.size or 0)
        done = 0
        while True:
            if should_stop and should_stop():
                raise InterruptedError
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if on_progress:
                on_progress(done, total)
    return dst


def current_app_bundle() -> Path | None:
    """맥에서 실행 중인 .app 경로 (패키징된 앱일 때만)."""
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return None
    p = Path(sys.executable).resolve()
    for parent in p.parents:
        if parent.suffix == ".app":
            return parent
    return None


MAC_SCRIPT = r'''#!/bin/bash
APP={app}; DMG={dmg}; PID={pid}
while kill -0 "$PID" 2>/dev/null; do sleep 0.3; done
MNT=$(mktemp -d)
if ! hdiutil attach -nobrowse -noautoopen -mountpoint "$MNT" "$DMG" >/dev/null; then open "$DMG"; exit 1; fi
NEW=$(find "$MNT" -maxdepth 1 -name "*.app" | head -1)
TMP="$APP.updating"
rm -rf "$TMP"
if ditto "$NEW" "$TMP"; then rm -rf "$APP" && mv "$TMP" "$APP"; fi
hdiutil detach "$MNT" -quiet
xattr -cr "$APP" 2>/dev/null
open "$APP"
rm -f "$DMG" "$0"
'''


def install_and_restart(installer: Path) -> str:
    """설치를 시작한다. 반환값: 'quit'(앱을 종료해야 함) 또는 'manual'(사용자가 직접 설치)."""
    if sys.platform == "win32":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([str(installer), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                         creationflags=flags, close_fds=True)
        return "quit"
    if sys.platform == "darwin":
        app = current_app_bundle()
        if app is None or not os.access(app.parent, os.W_OK):
            subprocess.Popen(["open", str(installer)])  # dmg를 열어 직접 끌어 놓도록
            return "manual"
        script = installer.parent / "update.sh"
        script.write_text(MAC_SCRIPT.format(app=shlex.quote(str(app)), dmg=shlex.quote(str(installer)),
                                            pid=os.getpid()))
        script.chmod(0o755)
        subprocess.Popen(["/bin/bash", str(script)], start_new_session=True, close_fds=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "quit"
    return "manual"
