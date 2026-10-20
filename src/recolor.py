"""PDF 안의 색 지정값을 직접 뒤집는 '빠른 변환' (PyMuPDF만 사용).

혼합 모드 층을 덮는 대신 글자·선·면의 색 명령, 이미지, 팔레트, 그라데이션을 직접 반전하고
검은 바탕을 깐다. 어떤 보기 앱에서도 똑같이 보이며 글자는 벡터 그대로 남는다.
"""
from __future__ import annotations

import re

import pymupdf

# ── 값 계산 ──────────────────────────────────────────────


def _clip(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def _inv_list(vals):
    return [_clip(1 - float(v)) for v in vals]


def _inv_cmyk(c, m, y, k):
    # 보이는 색(RGB) 기준으로 뒤집은 뒤 k=0 인 CMYK로 표현
    c, m, y, k = (float(v) for v in (c, m, y, k))
    return [_clip((1 - c) * (1 - k)), _clip((1 - m) * (1 - k)), _clip((1 - y) * (1 - k)), 0.0]


def _invert_color_values(fam, vals):
    if fam in ("gray", "rgb", "tint"):
        return _inv_list(vals)
    if fam == "cmyk" and len(vals) == 4:
        return _inv_cmyk(*vals)
    return None


def _fmt(v) -> bytes:
    v = float(v)
    if v <= 0:
        return b"0"
    if v >= 1:
        return b"1"
    return (f"{v:.4f}".rstrip("0").rstrip(".") or "0").encode()


# ── PDF 객체 문자열 다루기 ───────────────────────────────


def _top_keys(text: str) -> list[str]:
    """'<< /A 1 0 R /B << ... >> >>' 의 맨 바깥 키 이름들."""
    keys, depth, i, n = [], 0, 0, len(text)
    expect_key = False
    while i < n:
        c = text[i]
        if text.startswith("<<", i):
            depth += 1
            i += 2
            if depth == 1:
                expect_key = True
            continue
        if text.startswith(">>", i):
            depth -= 1
            i += 2
            if depth == 1:
                expect_key = True
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 1:
                expect_key = True
        elif c == "(":
            lvl = 1
            i += 1
            while i < n and lvl:
                if text[i] == "\\":
                    i += 2
                    continue
                lvl += {"(": 1, ")": -1}.get(text[i], 0)
                i += 1
            if depth == 1:
                expect_key = True
            continue
        elif c == "/" and depth == 1:
            m = re.match(r"/([^\s/<>\[\]()]+)", text[i:])
            i += m.end()
            if expect_key:
                keys.append(m.group(1))
                expect_key = False
            else:
                expect_key = True
            continue
        elif depth == 1 and not c.isspace() and not expect_key:
            m = re.match(r"[^\s/<>\[\]()]+(?:\s+\d+\s+R)?", text[i:])
            if m:
                i += m.end()
                expect_key = True
                continue
        i += 1
    return keys


class Ref:
    """PDF 안 값의 위치: (xref, 키 경로). 간접 객체면 경로가 비어 있다."""
    __slots__ = ("doc", "xref", "path")

    def __init__(self, doc, xref, path=""):
        self.doc, self.xref, self.path = doc, xref, path

    def _k(self, key):
        return f"{self.path}/{key}" if self.path else key

    def get(self, key):
        return self.doc.xref_get_key(self.xref, self._k(key))

    def child(self, key):
        t, v = self.get(key)
        if t == "xref":
            return Ref(self.doc, int(v.split()[0]))
        if t in ("dict", "array"):
            return Ref(self.doc, self.xref, self._k(key))
        return None

    def set(self, key, value: str):
        self.doc.xref_set_key(self.xref, self._k(key), value)

    def text(self):
        if self.path:
            return self.doc.xref_get_key(self.xref, self.path)[1]
        return self.doc.xref_object(self.xref, compressed=True)

    def keys(self):
        if not self.path:
            return list(self.doc.xref_get_keys(self.xref))
        return _top_keys(self.text())

    @property
    def ident(self):
        return (self.xref, self.path)


# ── 색 공간 판별 ─────────────────────────────────────────
_CS_TABLE = {"DeviceGray": ("gray", 1), "G": ("gray", 1), "CalGray": ("gray", 1),
             "DeviceRGB": ("rgb", 3), "RGB": ("rgb", 3), "CalRGB": ("rgb", 3),
             "DeviceCMYK": ("cmyk", 4), "CMYK": ("cmyk", 4),
             "Pattern": ("pattern", 0), "Indexed": ("idx", 1), "I": ("idx", 1),
             "Separation": ("tint", 1)}


def _family_text(t: str, v: str, doc) -> tuple[str, int]:
    """xref_get_key 결과(종류, 값) 또는 객체 문자열로 색 공간 종류를 판단."""
    if t == "xref":
        return _family_text("obj", doc.xref_object(int(v.split()[0]), compressed=True), doc)
    s = (v or "").strip()
    m = re.match(r"\[?\s*/([A-Za-z0-9]+)", s)
    if not m:
        return ("other", 0)
    name = m.group(1)
    if name == "ICCBased":
        r = re.search(r"(\d+)\s+0\s+R", s)
        n = 3
        if r:
            nm = re.search(r"/N\s+(\d+)", doc.xref_object(int(r.group(1)), compressed=True))
            n = int(nm.group(1)) if nm else 3
        return {1: ("gray", 1), 3: ("rgb", 3), 4: ("cmyk", 4)}.get(n, ("other", n))
    if name == "DeviceN":
        r = re.search(r"/DeviceN\s*\[([^\]]*)\]", s)
        return ("tint", max(1, len(re.findall(r"/", r.group(1)))) if r else 1)
    return _CS_TABLE.get(name, ("other", 0))


class Recolor:
    _CAND = re.compile(rb"\(|<|%|BI|scn|SCN|sc|SC|rg|RG|k|K|g|G|/|q|Q")
    _NAMEOP = re.compile(rb"/[^\s/\[\]()<>{}%]+\s*(cs|CS|Do|sh|scn|SCN)(?=[\s\[\]()<>{}/%]|\Z)")
    _BACKNUMS = re.compile(rb"(?:(?<=[\s\[\]()<>])|^)((?:[-+]?(?:\d+\.?\d*|\.\d+)\s+){1,8})$")
    _NUM = re.compile(rb"[-+]?(?:\d+\.?\d*|\.\d+)")
    _STR = re.compile(rb"[()\\]")
    _ID = re.compile(rb"\sID\s")
    _EI = re.compile(rb"\sEI(?=\s|\Z)")
    _DELIM = frozenset(b" \t\r\n\f\x00[]()<>{}/%")
    _WS = frozenset(b" \t\r\n\f\x00")
    _QPRE = frozenset(b" \t\r\n\f\x00])>")

    def __init__(self, doc: pymupdf.Document):
        self.doc = doc
        self.done: set = set()

    def _once(self, key) -> bool:
        if key in self.done:
            return False
        self.done.add(key)
        return True

    def _family(self, name: str, res: Ref | None):
        builtin = _family_text("name", name, self.doc)
        if builtin[0] != "other" or res is None:
            return builtin
        t, v = res.get(f"ColorSpace/{name.lstrip('/')}")
        if t == "null":
            return ("other", 0)
        return _family_text(t, v, self.doc)

    # ── 내용 스트림 (바이트 단위 고속 처리) ─────────────
    def transform_bytes(self, data: bytes, res: Ref | None) -> bytes:
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
            if t == b"(":  # 문자열: 괄호 짝을 맞춰 건너뜀
                depth, k = 1, en
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
            if t == b"<":
                if en < n and data[en] == 0x3C:  # '<<' 사전
                    pos = en + 1
                    continue
                e = data.find(b">", en)
                pos = n if e < 0 else e + 1
                continue
            if t == b"%":
                e = data.find(b"\n", en)
                pos = n if e < 0 else e + 1
                continue
            if t == b"BI":
                if prev not in WS or not (en < n and (data[en] in WS or data[en] == 0x2F)):
                    pos = en
                    continue
                idp = self._ID.search(data, en)
                if not idp:
                    pos = n
                    continue
                newhead = self._inline_head(data[en:idp.start()])
                ei = self._EI.search(data, idp.end())
                if newhead is not None:
                    out.append(data[last:en])
                    out.append(newhead)
                    last = idp.start()
                pos = n if not ei else ei.end()
                continue
            if t in (b"q", b"Q"):
                if nxt_ok and prev in QPRE:
                    if t == b"q":
                        stack.append((fill, stroke))
                    elif stack:
                        fill, stroke = stack.pop()
                pos = en
                continue
            if t == b"/":
                mm = NAMEOP.match(data, st)
                if not mm:
                    pos = en
                    continue
                op = mm.group(1)
                nm = data[st:mm.start(1)].strip().decode("latin1")
                if op in (b"cs", b"CS"):
                    fam = self._family(nm, res)
                    if op == b"cs":
                        fill = fam
                    else:
                        stroke = fam
                    init = {"gray": b"1", "rgb": b"1 1 1", "cmyk": b"0 0 0 0",
                            "tint": b" ".join([b"0"] * max(fam[1], 1))}.get(fam[0])
                    if init is not None:
                        out.append(data[last:mm.end()])
                        out.append(b" " + init + (b" sc" if op == b"cs" else b" SC"))
                        last = mm.end()
                elif op == b"Do":
                    self._xobject(nm.lstrip("/"), res)
                elif op == b"sh":
                    self._shading_named(nm.lstrip("/"), res)
                pos = mm.end()
                continue
            # 색 연산자 (g G rg RG k K sc SC scn SCN)
            if not nxt_ok or prev not in WS:
                pos = en
                continue
            op = t.decode()
            bm = self._BACKNUMS.search(data, max(last, st - 160), st)
            nums = self._NUM.findall(bm.group(1)) if bm else []
            need = {"g": 1, "G": 1, "rg": 3, "RG": 3, "k": 4, "K": 4}.get(op)
            if need is None:  # sc/scn: 현재 색 공간 기준
                fam = fill if op in ("sc", "scn") else stroke
                need, fam_name = (fam[1] or len(nums)), fam[0]
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
                    out.append(b" ".join(keep + [_fmt(v) for v in new]) + b" " + t)
                    last = en
            pos = en
        out.append(data[last:])
        return b"".join(out)

    @staticmethod
    def _inline_head(head: bytes):
        """인라인 이미지(BI…ID) 사전에 반전 Decode를 넣는다."""
        if re.search(rb"/(IM|ImageMask)\s+true", head) or re.search(rb"/(D|Decode)[\s\[]", head):
            return None
        mcs = re.search(rb"/(?:CS|ColorSpace)\s*/(\w+)", head)
        n = {b"G": 1, b"DeviceGray": 1, b"RGB": 3, b"DeviceRGB": 3}.get(mcs.group(1) if mcs else b"")
        if not n:
            return None
        return head + b" /D [" + b" ".join([b"1 0"] * n) + b"]"

    def process_stream(self, xref: int, res: Ref | None, prefix: bytes = b""):
        data = self.doc.xref_stream(xref) or b""
        self.doc.update_stream(xref, prefix + self.transform_bytes(data, res), compress=0)
        self.process_resources(res)

    # ── 자원 ───────────────────────────────────────────
    def process_resources(self, res: Ref | None):
        if res is None or not self._once(("res",) + res.ident):
            return
        for cat, fn in (("ColorSpace", self._colorspace), ("Pattern", self._pattern),
                        ("Shading", self._shading), ("Font", self._font)):
            sub = res.child(cat)
            if sub is None:
                continue
            try:
                for k in sub.keys():
                    fn(sub, k, res)
            except Exception:
                pass

    def _font(self, fonts: Ref, key, res):
        f = fonts.child(key)
        if f is None or f.get("Subtype")[1] != "/Type3" or not self._once(("font",) + f.ident):
            return
        fres = f.child("Resources") or res
        procs = f.child("CharProcs")
        if procs is None:
            return
        for k in procs.keys():
            t, v = procs.get(k)
            if t == "xref":
                x = int(v.split()[0])
                if self._once(("x", x)):
                    self.process_stream(x, fres)

    def _xobject(self, name, res: Ref | None):
        if res is None:
            return
        t, v = res.get(f"XObject/{name}")
        if t != "xref":
            return
        x = int(v.split()[0])
        if not self._once(("x", x)):
            return
        obj = Ref(self.doc, x)
        sub = obj.get("Subtype")[1]
        if sub == "/Form":
            self.process_stream(x, obj.child("Resources") or res)
        elif sub == "/Image":
            self._image(x, res)

    def _colorspace(self, spaces: Ref, key, res=None):
        """Indexed 색 공간의 팔레트를 뒤집는다."""
        t, v = spaces.get(key)
        if t == "xref":
            x = int(v.split()[0])
            if self._once(("cs", x)):
                self._indexed(Ref(self.doc, x), self.doc.xref_object(x, compressed=True), whole=True)
        elif t == "array" and self._once(("cs",) + spaces.ident + (key,)):
            self._indexed(spaces, v, key=key)

    def _indexed(self, owner: Ref, text: str, key=None, whole=False):
        m = re.match(r"\s*\[\s*/(?:Indexed|I)\s*(.+?)\s*(?<=[\]>\s/A-Za-z])(\d+)\s*(<[0-9A-Fa-f\s]*>|\(.*\)|\d+\s+0\s+R)\s*\]\s*$",
                     text, re.S)
        if not m:
            return
        base, lut = m.group(1).strip(), m.group(3)
        if re.fullmatch(r"\d+\s+0\s+R", base):
            fam = _family_text("xref", base, self.doc)[0]
        else:
            fam = _family_text("obj", base, self.doc)[0]
        if fam not in ("gray", "rgb", "cmyk"):
            return
        if lut.endswith("R"):
            lx = int(lut.split()[0])
            raw = self.doc.xref_stream(lx) or b""
        elif lut.startswith("<"):
            raw = bytes.fromhex(re.sub(r"\s", "", lut[1:-1]))
        else:
            raw = _pdf_literal_bytes(lut)
        if fam == "cmyk":
            new = bytearray()
            for i in range(0, len(raw) - 3, 4):
                vals = _inv_cmyk(*(b / 255 for b in raw[i:i + 4]))
                new += bytes(int(round(255 * v)) for v in vals)
            new = bytes(new)
        else:
            new = bytes(255 - b for b in raw)
        if lut.endswith("R"):
            self.doc.update_stream(lx, new)
            return
        newtext = text[:m.start(3)] + "<" + new.hex() + ">" + text[m.end(3):]
        if whole:
            self.doc.update_object(owner.xref, newtext)
        else:
            owner.set(key, newtext)

    def _image(self, x: int, res: Ref | None):
        img = Ref(self.doc, x)
        if img.get("ImageMask")[1] == "true":
            return  # 채우기 색으로 칠해지므로 색 명령 반전으로 충분
        t, v = img.get("ColorSpace")
        if t == "null":
            return
        if t == "name":
            fam = self._family(v, res)
            cs_text = v
            if res is not None and fam[0] == "idx":
                rt, rv = res.get(f"ColorSpace/{v.lstrip('/')}")
                if rt == "xref":
                    t, v = rt, rv
                cs_text = rv
        else:
            fam = _family_text(t, v, self.doc)
            cs_text = self.doc.xref_object(int(v.split()[0]), compressed=True) if t == "xref" else v
        if fam[0] == "idx":
            if t == "xref":
                xx = int(v.split()[0])
                if self._once(("cs", xx)):
                    self._indexed(Ref(self.doc, xx), cs_text, whole=True)
            elif t == "array" and self._once(("cs", x, "ColorSpace")):
                self._indexed(img, cs_text, key="ColorSpace")
            return
        filt = img.get("Filter")[1] or ""
        if fam[0] in ("gray", "rgb", "tint") and "JPX" not in filt:
            n = max(fam[1], 1)
            dt, dv = img.get("Decode")
            nums = re.findall(r"[-+]?\d*\.?\d+", dv) if dt == "array" else []
            pairs = [(nums[2 * i], nums[2 * i + 1]) for i in range(n)] if len(nums) == 2 * n else [("0", "1")] * n
            img.set("Decode", "[" + " ".join(f"{b} {a}" for a, b in pairs) + "]")
            return
        # CMYK·JPX 등은 실제 픽셀을 RGB로 바꿔 반전
        try:
            pix = pymupdf.Pixmap(self.doc, x)
            if pix.alpha:
                pix = pymupdf.Pixmap(pix, 0)
            if pix.colorspace is None or pix.colorspace.n != 3:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            pix.invert_irect(pix.irect)
            self.doc.update_stream(x, pix.tobytes("jpeg", jpg_quality=92), compress=0)
            for k, val in (("Filter", "/DCTDecode"), ("ColorSpace", "/DeviceRGB"),
                           ("BitsPerComponent", "8"), ("Width", str(pix.width)),
                           ("Height", str(pix.height)), ("Decode", "null"), ("DecodeParms", "null")):
                self.doc.xref_set_key(x, k, val)
        except Exception:
            pass

    # ── 패턴·그라데이션 ─────────────────────────────────
    def _pattern(self, pats: Ref, key, res):
        p = pats.child(key)
        if p is None or not self._once(("pat",) + p.ident):
            return
        if p.get("PatternType")[1] == "1" and not p.path:
            if self._once(("x", p.xref)):
                self.process_stream(p.xref, p.child("Resources") or res)
        else:
            sh = p.child("Shading")
            if sh is not None:
                self._shading_ref(sh)

    def _shading(self, shs: Ref, key, res=None):
        sh = shs.child(key)
        if sh is not None:
            self._shading_ref(sh)

    def _shading_named(self, name, res):
        if res is not None:
            sh = res.child(f"Shading/{name}")
            if sh is not None:
                self._shading_ref(sh)

    def _shading_ref(self, sh: Ref):
        if not self._once(("sh",) + sh.ident):
            return
        t, v = sh.get("ColorSpace")
        fam = _family_text(t, v, self.doc)[0]
        if fam not in ("gray", "rgb", "cmyk", "tint"):
            return
        t, v = sh.get("Function")
        if t == "array":
            for mm in re.finditer(r"(\d+)\s+0\s+R", v):
                self._function(Ref(self.doc, int(mm.group(1))), fam)
        else:
            f = sh.child("Function")
            if f is not None:
                self._function(f, fam)

    def _function(self, f: Ref, fam):
        if not self._once(("fn",) + f.ident):
            return
        try:
            ftype = f.get("FunctionType")[1]
            if ftype == "2":
                for key, default in (("C0", ["0"]), ("C1", ["1"])):
                    t, v = f.get(key)
                    vals = re.findall(r"[-+]?\d*\.?\d+", v) if t == "array" else default
                    new = _invert_color_values(fam, vals)
                    if new is not None:
                        f.set(key, "[" + " ".join(_fmt(x).decode() for x in new) + "]")
            elif ftype == "3":
                t, v = f.get("Functions")
                for mm in re.finditer(r"(\d+)\s+0\s+R", v):
                    self._function(Ref(self.doc, int(mm.group(1))), fam)
        except Exception:
            pass


def _pdf_literal_bytes(s: str) -> bytes:
    """PDF 리터럴 문자열 '( ... )' → 바이트."""
    body = s[1:-1]
    out = bytearray()
    i = 0
    esc = {"n": 10, "r": 13, "t": 9, "b": 8, "f": 12, "(": 40, ")": 41, "\\": 92}
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            d = body[i + 1]
            if d in esc:
                out.append(esc[d])
                i += 2
                continue
            m = re.match(r"[0-7]{1,3}", body[i + 1:])
            if m:
                out.append(int(m.group(), 8) & 255)
                i += 1 + m.end()
                continue
            i += 2
            continue
        out.append(ord(c) & 255)
        i += 1
    return bytes(out)


def invert_document(doc: pymupdf.Document, on_page=None, should_stop=None) -> None:
    """열린 문서를 제자리에서 반전한다."""
    rc = Recolor(doc)
    n = doc.page_count
    for i, page in enumerate(doc):
        if should_stop and should_stop():
            raise InterruptedError
        t, v = doc.xref_get_key(page.xref, "Resources")
        if t == "null":  # 상속된 Resources를 페이지에 직접 붙임
            par = doc.xref_get_key(page.xref, "Parent")
            while par[0] == "xref" and t == "null":
                px = int(par[1].split()[0])
                t, v = doc.xref_get_key(px, "Resources")
                par = doc.xref_get_key(px, "Parent")
            if t != "null":
                doc.xref_set_key(page.xref, "Resources", v)
        res = Ref(doc, page.xref).child("Resources")
        box, mb = page.cropbox, page.mediabox
        x0, y0 = box.x0, mb.height - box.y1  # cropbox(위가 원점) → PDF 좌표(아래가 원점)
        prefix = (f"q 0 g {x0:.2f} {y0:.2f} {box.width:.2f} {box.height:.2f} re f Q\n1 g 1 G\n").encode()
        conts = page.get_contents()
        if conts:
            data = b"\n".join((doc.xref_stream(c) or b"") for c in conts)
            first = conts[0]
            if len(conts) > 1:
                doc.update_stream(first, data, compress=0)
                doc.xref_set_key(page.xref, "Contents", f"{first} 0 R")
            if ("x", first) not in rc.done:  # 여러 페이지가 같은 내용을 공유하면 한 번만
                rc.done.add(("x", first))
                rc.process_stream(first, res, prefix)
        else:
            x = doc.get_new_xref()
            doc.update_object(x, "<<>>")
            doc.update_stream(x, prefix)
            doc.xref_set_key(page.xref, "Contents", f"{x} 0 R")
        if on_page:
            on_page(i + 1, n)
