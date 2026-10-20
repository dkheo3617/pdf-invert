"""PDF 색상 반전 핵심 로직 (GUI와 분리)."""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import pymupdf

PREFIX = "[반전]"

# 변환 방식: 0 = 빠른 변환(벡터, 원본 화질 그대로), 그 외 = 이미지 변환 dpi
QUALITY_PRESETS = {
    "빠른 변환 (원본 화질 · 권장)": 0,
    "이미지 변환 · 고화질 300dpi": 300,
    "이미지 변환 · 표준 200dpi": 200,
    "이미지 변환 · 저용량 150dpi": 150,
}
PARALLEL_MIN_PAGES = 4


@dataclass
class Job:
    src: Path
    dst: Path
    dst_exists: bool = False


def output_path(src: Path) -> Path:
    return src.with_name(f"{PREFIX}{src.stem}.pdf")


def _is_target_name(name: str) -> bool:
    return name.lower().endswith(".pdf") and not name.startswith(PREFIX) and not name.startswith(".")


def is_target(p: Path) -> bool:
    return _is_target_name(p.name) and p.is_file()


SKIP_DIR_SUFFIXES = (".app", ".photoslibrary", ".bundle", ".framework")


def _scan_dir(root: str, recursive: bool, should_stop):
    """폴더 하나를 빠르게 훑는다: 파일 이름으로 먼저 거르고(디스크 조회 최소화),
    같은 폴더의 이름 목록으로 [반전] 파일 존재 여부도 함께 판단한다."""
    stack = [root]
    while stack:
        if should_stop and should_stop():
            raise InterruptedError
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                entries = list(it)
        except OSError:
            continue
        names = {e.name for e in entries}
        pdfs, subdirs = [], []
        for e in entries:
            n = e.name
            if _is_target_name(n):
                try:
                    if e.is_file():
                        pdfs.append(n)
                except OSError:
                    pass
            elif recursive and not n.startswith(".") and not n.lower().endswith(SKIP_DIR_SUFFIXES):
                try:
                    if e.is_dir(follow_symlinks=False):
                        subdirs.append(e.path)
                except OSError:
                    pass
        for n in sorted(pdfs):
            src = Path(d, n)
            yield Job(src, output_path(src), f"{PREFIX}{Path(n).stem}.pdf" in names)
        stack.extend(sorted(subdirs, reverse=True))


def collect_jobs(paths: Iterable[str | os.PathLike], recursive: bool = True,
                 on_found: Callable[[int], None] | None = None,
                 should_stop: Callable[[], bool] | None = None) -> list[Job]:
    """파일·폴더 목록을 받아 반전할 PDF 작업 목록을 만든다 (중복 제거)."""
    seen: set[str] = set()
    jobs: list[Job] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            found = _scan_dir(str(p), recursive, should_stop)
        elif is_target(p):
            found = [Job(p, output_path(p), output_path(p).exists())]
        else:
            found = []
        for job in found:
            key = os.path.normcase(os.path.abspath(job.src))
            if key not in seen:
                seen.add(key)
                jobs.append(job)
                if on_found and len(jobs) % 20 == 0:
                    on_found(len(jobs))
    return jobs


def page_count(src: Path) -> int:
    with pymupdf.open(src) as d:
        return d.page_count


def invert_pdf(
    src: Path,
    dst: Path,
    dpi: int = 0,
    on_page: Callable[[int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    jpeg_quality: int = 90,
) -> None:
    """dpi=0이면 빠른 변환, 아니면 페이지를 이미지로 렌더링해 반전한다."""
    with pymupdf.open(src) as probe:
        if probe.needs_pass:
            raise ValueError("암호가 걸린 PDF는 반전할 수 없습니다.")
    if dpi <= 0:
        _invert_vector(src, dst, on_page, should_stop)
    else:
        _invert_raster(src, dst, dpi, on_page, should_stop, jpeg_quality)


def _save(doc: pymupdf.Document, dst: Path) -> None:
    tmp = dst.with_name(dst.name + ".tmp")
    doc.save(tmp, garbage=3, deflate=True)
    os.replace(tmp, dst)


def _invert_vector(src, dst, on_page, should_stop) -> None:
    """빠른 변환: PDF 안의 색 명령·이미지를 직접 뒤집고 검은 바탕을 깐다.
    다시 그리지 않으므로 매우 빠르고, 글자·도형이 벡터 그대로 남는다."""
    from recolor import invert_document
    doc = pymupdf.open(src)
    try:
        if any(True for p in doc for _ in p.annots()) or any(True for p in doc for _ in p.widgets()):
            doc.bake()  # 주석·필기를 본문으로 합쳐 함께 반전되게
        invert_document(doc, on_page, should_stop)
        _save(doc, dst)
    finally:
        doc.close()


def _render_page(args):
    src, i, dpi, q = args
    with pymupdf.open(src) as d:
        page = d[i]
        pix = page.get_pixmap(dpi=dpi, alpha=False, colorspace=pymupdf.csRGB)
        pix.invert_irect(pix.irect)
        return page.rect.width, page.rect.height, pix.tobytes("jpeg", jpg_quality=q)


def _invert_raster(src, dst, dpi, on_page, should_stop, q) -> None:
    """페이지를 이미지로 렌더링해 반전 (모든 뷰어에서 똑같이 보이는 호환 모드).
    페이지가 많으면 CPU 코어 여러 개로 동시에 처리한다."""
    with pymupdf.open(src) as d:
        n = d.page_count
    tasks = [(str(src), i, dpi, q) for i in range(n)]
    out = pymupdf.open()
    ex = ProcessPoolExecutor(max_workers=max(1, min(os.cpu_count() or 1, 8))) if n >= PARALLEL_MIN_PAGES else None
    try:
        results = ex.map(_render_page, tasks) if ex else map(_render_page, tasks)
        for i, (w, h, jpg) in enumerate(results):
            if should_stop and should_stop():
                raise InterruptedError
            page = out.new_page(width=w, height=h)
            page.insert_image(page.rect, stream=jpg)
            if on_page:
                on_page(i + 1, n)
        _save(out, dst)
    finally:
        if ex:
            ex.shutdown(wait=False, cancel_futures=True)
        out.close()
