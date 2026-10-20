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
    """원본 페이지 위에 '차이(Difference)' 혼합 모드의 흰 사각형을 덮어 색을 뒤집는다.
    다시 그리지 않으므로 매우 빠르고, 글자·도형이 벡터 그대로 남아 확대해도 선명하다."""
    s = pymupdf.open(src)
    out = pymupdf.open()
    try:
        try:
            s.bake()  # 주석·필기를 본문으로 합쳐 함께 반전되게
        except Exception:
            pass
        gs = out.get_new_xref()
        out.update_object(gs, "<</Type/ExtGState/BM/Difference/ca 1/CA 1>>")
        n = s.page_count
        for i, page in enumerate(s):
            if should_stop and should_stop():
                raise InterruptedError
            rot = page.rotation
            if rot:
                page.set_rotation(0)  # 회전은 결과 페이지에 그대로 다시 적용
            w, h = page.rect.width, page.rect.height
            new = out.new_page(width=w, height=h)
            new.draw_rect(new.rect, color=None, fill=(1, 1, 1), width=0)  # 투명 바탕 → 흰 바탕
            new.show_pdf_page(new.rect, s, i)
            new.clean_contents()
            cx = new.get_contents()[0]
            out.update_stream(cx, new.read_contents()
                              + f"\nq /InvGS gs 1 1 1 rg 0 0 {w:.3f} {h:.3f} re f Q\n".encode())
            t, v = out.xref_get_key(new.xref, "Resources")
            if t == "xref":
                out.xref_set_key(int(v.split()[0]), "ExtGState/InvGS", f"{gs} 0 R")
            else:
                out.xref_set_key(new.xref, "Resources/ExtGState/InvGS", f"{gs} 0 R")
            if rot:
                new.set_rotation(rot)
            if on_page:
                on_page(i + 1, n)
        _save(out, dst)
    finally:
        out.close()
        s.close()


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
