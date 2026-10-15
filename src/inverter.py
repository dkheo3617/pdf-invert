"""PDF 색상 반전 핵심 로직 (GUI와 분리)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import pymupdf

PREFIX = "[반전]"

QUALITY_PRESETS = {
    "고화질 (300dpi)": 300,
    "표준 (200dpi)": 200,
    "저용량 (150dpi)": 150,
}


@dataclass
class Job:
    src: Path
    dst: Path


def output_path(src: Path) -> Path:
    return src.with_name(f"{PREFIX}{src.stem}.pdf")


def is_target(p: Path) -> bool:
    return (
        p.is_file()
        and p.suffix.lower() == ".pdf"
        and not p.name.startswith(PREFIX)
        and not p.name.startswith("._")
    )


def collect_jobs(paths: Iterable[str | os.PathLike], recursive: bool = True) -> list[Job]:
    """파일·폴더 목록을 받아 반전할 PDF 작업 목록을 만든다 (중복 제거)."""
    seen: set[Path] = set()
    jobs: list[Job] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            it = p.rglob("*") if recursive else p.iterdir()
            files = sorted(f for f in it if is_target(f))
        elif is_target(p):
            files = [p]
        else:
            files = []
        for f in files:
            key = f.resolve()
            if key not in seen:
                seen.add(key)
                jobs.append(Job(f, output_path(f)))
    return jobs


def page_count(src: Path) -> int:
    with pymupdf.open(src) as d:
        return d.page_count


def invert_pdf(
    src: Path,
    dst: Path,
    dpi: int = 300,
    on_page: Callable[[int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    jpeg_quality: int = 90,
) -> None:
    """각 페이지를 이미지로 렌더링해 색을 뒤집고 새 PDF로 저장한다."""
    src_doc = pymupdf.open(src)
    if src_doc.needs_pass:
        src_doc.close()
        raise ValueError("암호가 걸린 PDF는 반전할 수 없습니다.")
    out = pymupdf.open()
    try:
        n = src_doc.page_count
        for i, page in enumerate(src_doc):
            if should_stop and should_stop():
                raise InterruptedError
            pix = page.get_pixmap(dpi=dpi, alpha=False, colorspace=pymupdf.csRGB)
            pix.invert_irect(pix.irect)
            r = page.rect
            new = out.new_page(width=r.width, height=r.height)
            new.insert_image(new.rect, stream=pix.tobytes("jpeg", jpg_quality=jpeg_quality))
            if on_page:
                on_page(i + 1, n)
        tmp = dst.with_name(dst.name + ".tmp")
        out.save(tmp, garbage=3, deflate=True)
        os.replace(tmp, dst)
    finally:
        out.close()
        src_doc.close()
