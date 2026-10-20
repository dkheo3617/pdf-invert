"""PDF 안의 색 지정값을 직접 뒤집는 '빠른 변환' (v2.3).

혼합 모드(Difference) 층을 덮는 대신, 글자·선·면의 색 명령과 이미지 자체를 반전하고
검은 바탕을 깐다. 어떤 보기 앱에서도 똑같이 보이며 글자는 벡터 그대로 남는다.
"""
from __future__ import annotations

import io
import re
from decimal import Decimal

import pikepdf
from pikepdf import Name, Array, Dictionary, Stream

NUM = (int, float, Decimal)


def _n(x) -> float:
    return float(x)


def _r(x: float):
    x = 0.0 if x < 0 else 1.0 if x > 1 else x
    return Decimal(f"{x:.4f}").normalize() if x not in (0.0, 1.0) else int(x)


def _inv_list(vals):
    return [_r(1 - _n(v)) for v in vals]


def _inv_cmyk(c, m, y, k):
    # 보이는 색(RGB) 기준으로 뒤집은 뒤 다시 CMYK(k=0)로
    c, m, y, k = map(_n, (c, m, y, k))
    return [_r((1 - c) * (1 - k)), _r((1 - m) * (1 - k)), _r((1 - y) * (1 - k)), 0]


# ── 색 공간 판별 ─────────────────────────────────────────
def _family(cs, resources) -> tuple[str, int]:
    """색 공간 → (종류, 성분 수). 종류: gray rgb cmyk tint idx pattern other"""
    try:
        if isinstance(cs, Name):
            s = str(cs)
            if s in ("/DeviceGray", "/G", "/CalGray"):
                return "gray", 1
            if s in ("/DeviceRGB", "/RGB", "/CalRGB"):
                return "rgb", 3
            if s in ("/DeviceCMYK", "/CMYK"):
                return "cmyk", 4
            if s == "/Pattern":
                return "pattern", 0
            if s in ("/Indexed", "/I"):
                return "idx", 1
            if resources is not None and "/ColorSpace" in resources and s in resources.ColorSpace:
                return _family(resources.ColorSpace[s], None)
            return "other", 0
        if isinstance(cs, Array) and len(cs):
            fam = str(cs[0])
            if fam == "/ICCBased":
                n = int(cs[1].get("/N", 3))
                return {1: ("gray", 1), 3: ("rgb", 3), 4: ("cmyk", 4)}.get(n, ("other", n))
            if fam == "/CalRGB":
                return "rgb", 3
            if fam == "/CalGray":
                return "gray", 1
            if fam in ("/Separation", "/DeviceN"):
                return "tint", (1 if fam == "/Separation" else len(cs[1]))
            if fam in ("/Indexed", "/I"):
                return "idx", 1
            if fam == "/Pattern":
                return "pattern", 0
    except Exception:
        pass
    return "other", 0


def _invert_color_values(fam, vals):
    if fam in ("gray", "rgb", "tint"):
        return _inv_list(vals)
    if fam == "cmyk" and len(vals) == 4:
        return _inv_cmyk(*vals)
    return None


class Recolor:
    def __init__(self, pdf: pikepdf.Pdf):
        self.pdf = pdf
        self.done: set = set()  # 이미 처리한 객체(공유 자원 중복 방지)

    def _once(self, obj) -> bool:
        try:
            key = obj.objgen
        except Exception:
            return True
        if key == (0, 0):
            return True
        if key in self.done:
            return False
        self.done.add(key)
        return True

    # ── 내용 스트림 (바이트 단위 고속 처리) ─────────────────
    # 1단계: 후보 위치만 아주 빠르게 찾고(단순 대안), 2단계: 파이썬에서 앞뒤 글자를 확인
    _CAND = re.compile(rb"\(|<|%|BI|scn|SCN|sc|SC|rg|RG|k|K|g|G|/|q|Q")
    _NAMEOP = re.compile(rb"/[^\s/\[\]()<>{}%]+\s*(cs|CS|Do|sh|scn|SCN)(?=[\s\[\]()<>{}/%]|\Z)")
    _ID = re.compile(rb"\sID\s")
    _EI = re.compile(rb"\sEI(?=\s|\Z)")
    _DELIM = frozenset(b" \t\r\n\f\x00[]()<>{}/%")
    _WS = frozenset(b" \t\r\n\f\x00")
    _QPRE = frozenset(b" \t\r\n\f\x00])>")
    _BACKNUMS = re.compile(rb"(?:(?<=[\s\[\]()<>])|^)((?:[-+]?(?:\d+\.?\d*|\.\d+)\s+){1,8})$")
    _STR = re.compile(rb"[()\\]")
    _NUM = re.compile(rb"[-+]?(?:\d+\.?\d*|\.\d+)")

    @staticmethod
    def _fmt(v) -> bytes:
        v = float(v)
        if v <= 0:
            return b"0"
        if v >= 1:
            return b"1"
        return (f"{v:.4f}".rstrip("0").rstrip(".") or "0").encode()

    def transform_bytes(self, data: bytes, resources) -> bytes:
        out = []
        pos = last = 0
        fill = stroke = ("gray", 1)
        stack = []
        n = len(data)
        CAND, STR, NAMEOP = self._CAND, self._STR, self._NAMEOP
        DELIM, WS, QPRE = self._DELIM, self._WS, self._QPRE
        while True:
            m = CAND.search(data, pos)
            if not m:
                break
            t = m.group()
            st, en = m.start(), m.end()
            nxt_ok = en >= n or data[en] in DELIM
            prev = data[st - 1] if st > 0 else 0x20
            if t == b"(":
                g = "str"
            elif t == b"<":
                if en < n and data[en] == 0x3C:  # '<<' 사전
                    pos = en + 1
                    continue
                g = "hex"
            elif t == b"%":
                g = "cmt"
            elif t == b"/":
                m = NAMEOP.match(data, st)
                if not m:
                    pos = en
                    continue
                g = "nop"
            elif t == b"BI":
                if prev not in WS or not (en < n and data[en] in WS or data[en:en + 1] == b"/"):
                    pos = en
                    continue
                g = "bi"
            elif t in (b"q", b"Q"):
                if not nxt_ok or prev not in QPRE:
                    pos = en
                    continue
                g = "qq"
            else:
                if not nxt_ok or prev not in WS:
                    pos = en
                    continue
                g = "cop"
            if g == "str":  # 문자열은 괄호 짝을 맞춰 건너뜀
                depth, k = 1, m.end()
                while depth and k < n:
                    s2 = STR.search(data, k)
                    if not s2:
                        k = n
                        break
                    ch = data[s2.start()]
                    if ch == 0x5C:
                        k = s2.start() + 2
                        continue
                    depth += 1 if ch == 0x28 else -1
                    k = s2.end()
                pos = k
                continue
            if g == "hex":
                e = data.find(b">", m.end())
                pos = n if e < 0 else e + 1
                continue
            if g == "cmt":
                e = data.find(b"\n", m.end())
                pos = n if e < 0 else e + 1
                continue
            if g == "bi":
                idp = self._ID.search(data, en)
                if not idp:
                    pos = n
                    continue
                head = data[en:idp.start()]
                newhead = self._inline_head(head)
                ei = self._EI.search(data, idp.end())
                end = n if not ei else ei.end()
                if newhead is not None:
                    out.append(data[last:en]); out.append(newhead)
                    last = idp.start()
                pos = end
                continue
            if g == "qq":
                if t == b"q":
                    stack.append((fill, stroke))
                elif stack:
                    fill, stroke = stack.pop()
                pos = m.end()
                continue
            if g == "cop":
                op = t.decode()
                ws = max(last, m.start() - 160)
                bm = self._BACKNUMS.search(data, ws, m.start())
                nums = self._NUM.findall(bm.group(1)) if bm else []
                need = {"g": 1, "G": 1, "rg": 3, "RG": 3, "k": 4, "K": 4}.get(op)
                if need is None:  # sc/scn: 현재 색 공간 기준
                    fam = fill if op in ("sc", "scn") else stroke
                    need = fam[1] if fam[1] else len(nums)
                    fam_name = fam[0]
                else:
                    fam_name = {1: "gray", 3: "rgb", 4: "cmyk"}[need]
                    if op.islower():
                        fill = (fam_name, need)
                    else:
                        stroke = (fam_name, need)
                if bm and need and len(nums) >= need:
                    keep, vals = nums[:-need], nums[-need:]
                    new = _invert_color_values(fam_name, vals)
                    if new is not None:
                        out.append(data[last:bm.start(1)])
                        out.append(b" ".join(keep + [self._fmt(v) for v in new]) + b" " + t)
                        last = m.end()
                pos = m.end()
                continue
            if g == "nop":
                op = m.group(1)
                nm = data[st:m.start(1)].strip().decode("latin1")
                if op in (b"cs", b"CS"):
                    fam = _family(Name(nm), resources)
                    if op == b"cs":
                        fill = fam
                    else:
                        stroke = fam
                    init = {"gray": "1", "rgb": "1 1 1", "cmyk": "0 0 0 0",
                            "tint": " ".join(["0"] * fam[1])}.get(fam[0])
                    if init is not None:
                        out.append(data[last:m.end()])
                        out.append(f" {init} {'sc' if op == b'cs' else 'SC'}".encode())
                        last = m.end()
                elif op == b"Do":
                    self._xobject(Name(nm), resources)
                elif op == b"sh":
                    self._shading_by_name(Name(nm), resources)
                pos = m.end()
                continue
            pos = m.end()
        out.append(data[last:])
        return b"".join(out)

    def _inline_head(self, head: bytes):
        """인라인 이미지(BI…ID)의 사전에 반전 Decode를 넣는다."""
        if re.search(rb"/(IM|ImageMask)\s+true", head) or re.search(rb"/(D|Decode)[\s\[]", head):
            return None
        mcs = re.search(rb"/(?:CS|ColorSpace)\s*/(\w+)", head)
        cs = mcs.group(1) if mcs else b""
        n = {b"G": 1, b"DeviceGray": 1, b"RGB": 3, b"DeviceRGB": 3}.get(cs)
        if not n:
            return None
        return head + b" /D [" + b" ".join([b"1 0"] * n) + b"]"

    def process_stream(self, stream: Stream, resources, prefix: bytes = b""):
        data = stream.read_bytes()
        stream.write(prefix + self.transform_bytes(data, resources))
        self.process_resources(resources)

    # ── 자원 ───────────────────────────────────────────
    def process_resources(self, res):
        if res is None or not self._once(res):
            return
        try:
            for _, cs in (res.get("/ColorSpace") or {}).items():
                self._colorspace_obj(cs)
            for _, pat in (res.get("/Pattern") or {}).items():
                self._pattern(pat)
            for _, sh in (res.get("/Shading") or {}).items():
                self._shading(sh)
            for _, font in (res.get("/Font") or {}).items():
                if font.get("/Subtype") == "/Type3" and self._once(font):
                    fres = font.get("/Resources") or res
                    for _, proc in (font.get("/CharProcs") or {}).items():
                        if self._once(proc):
                            self.process_stream(proc, fres)
        except Exception:
            pass

    def _xobject(self, name, resources):
        try:
            xo = resources.XObject[str(name)]
        except Exception:
            return
        if not self._once(xo):
            return
        sub = xo.get("/Subtype")
        if sub == "/Form":
            self.process_stream(xo, xo.get("/Resources") or resources)
        elif sub == "/Image":
            self._image(xo, resources)

    def _colorspace_obj(self, cs):
        """Indexed 색 공간의 팔레트를 뒤집는다."""
        if not isinstance(cs, Array) or len(cs) < 4 or str(cs[0]) not in ("/Indexed", "/I"):
            return
        if not self._once(cs) and cs.objgen != (0, 0):
            return
        fam, n = _family(cs[1], None)
        lut = cs[3]
        raw = bytes(lut.read_bytes() if isinstance(lut, Stream) else bytes(lut))
        if fam in ("gray", "rgb"):
            new = bytes(255 - b for b in raw)
        elif fam == "cmyk":
            out = bytearray()
            for i in range(0, len(raw) - 3, 4):
                c, m, y, k = (x / 255 for x in raw[i:i + 4])
                out += bytes(int(round(255 * float(v))) for v in _inv_cmyk(c, m, y, k))
            new = bytes(out)
        else:
            return
        if isinstance(lut, Stream):
            lut.write(new)
        else:
            cs[3] = pikepdf.String(new)

    def _image(self, img: Stream, resources):
        if img.get("/ImageMask"):
            return  # 채우기 색으로 칠해지므로 색 명령 반전으로 충분
        cs = img.get("/ColorSpace")
        fam, n = _family(cs, resources) if cs is not None else ("other", 0)
        if fam == "idx":
            self._colorspace_obj(cs if isinstance(cs, Array) else resources.ColorSpace[str(cs)])
            return
        filt = img.get("/Filter")
        filters = [str(f) for f in (filt if isinstance(filt, Array) else [filt])] if filt is not None else []
        if fam in ("gray", "rgb", "tint") and "/JPXDecode" not in filters:
            bpc = int(img.get("/BitsPerComponent", 8))
            maxv = 1
            dec = img.get("/Decode")
            if dec is not None and len(dec) == 2 * n:
                pairs = [(dec[2 * i], dec[2 * i + 1]) for i in range(n)]
            else:
                pairs = [(0, maxv)] * n
            img.Decode = Array([v for a, b in pairs for v in (b, a)])
            return
        # CMYK·JPX 등은 실제 픽셀을 RGB로 바꿔 반전
        try:
            from PIL import ImageOps
            pil = pikepdf.PdfImage(img).as_pil_image().convert("RGB")
            pil = ImageOps.invert(pil)
            buf = io.BytesIO()
            pil.save(buf, format="JPEG", quality=92)
            img.write(buf.getvalue(), filter=Name.DCTDecode)
            img.ColorSpace = Name.DeviceRGB
            img.BitsPerComponent = 8
            for k in ("/Decode", "/DecodeParms"):
                if k in img:
                    del img[k]
        except Exception:
            pass

    def _inline_image(self, ii):
        try:
            d = ii.obj
            if d.get("/IM") or d.get("/ImageMask"):
                return
            cs = d.get("/CS", d.get("/ColorSpace"))
            fam, n = _family(cs, None) if cs is not None else ("other", 0)
            if fam in ("gray", "rgb"):
                d.D = Array([1, 0] * n)
        except Exception:
            pass

    # ── 패턴·그라데이션 ─────────────────────────────────
    def _pattern(self, pat):
        if not self._once(pat):
            return
        if int(pat.get("/PatternType", 0)) == 1 and isinstance(pat, Stream):
            self.process_stream(pat, pat.get("/Resources"))
        elif "/Shading" in pat:
            self._shading(pat.Shading)

    def _shading_by_name(self, name, resources):
        try:
            self._shading(resources.Shading[str(name)])
        except Exception:
            pass

    def _shading(self, sh):
        if not self._once(sh):
            return
        fam, n = _family(sh.get("/ColorSpace"), None)
        if fam not in ("gray", "rgb", "cmyk", "tint"):
            return
        if "/Function" in sh:
            fns = sh.Function if isinstance(sh.Function, Array) else [sh.Function]
            for f in fns:
                self._function(f, fam)

    def _function(self, f, fam):
        try:
            t = int(f.FunctionType)
            if t == 2:
                for key in ("/C0", "/C1"):
                    vals = f.get(key) or ([0] * 1 if key == "/C0" else [1])
                    new = _invert_color_values(fam, list(vals))
                    if new is not None:
                        f[key] = Array(new)
            elif t == 3:
                for g in f.Functions:
                    self._function(g, fam)
        except Exception:
            pass


def invert_vector_recolor(src_bytes: bytes) -> bytes:
    pdf = pikepdf.open(io.BytesIO(src_bytes))
    rc = Recolor(pdf)
    for page in pdf.pages:
        res = page.obj.get("/Resources")
        if res is None:
            par = page.obj.get("/Parent")
            while par is not None and res is None:
                res = par.get("/Resources")
                par = par.get("/Parent")
            if res is not None:
                page.obj.Resources = res
        box = page.obj.get("/CropBox") or page.obj.get("/MediaBox")
        x0, y0, x1, y1 = (float(v) for v in box)
        prefix = (f"q 0 g {x0:.2f} {y0:.2f} {x1 - x0:.2f} {y1 - y0:.2f} re f Q\n"
                  "1 g 1 G\n").encode()
        if "/Contents" in page.obj:
            page.contents_coalesce()
            rc.process_stream(page.obj.Contents, res, prefix)
        else:
            page.obj.Contents = pdf.make_stream(prefix)
        if "/Group" in page.obj:  # 투명도 그룹 배경이 흰색으로 그려지는 것을 방지할 필요는 없음
            pass
    out = io.BytesIO()
    pdf.save(out, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    return out.getvalue()
