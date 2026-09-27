# -*- coding: utf-8 -*-
"""项目编码修正器（幂等，可反复跑）
- 所有 .bat  -> CRLF 行尾 + cp936 编码（cmd.exe 只认这条；LF 会报「此时不应有 ||」闪退）
- 所有 .ps1  -> UTF-8 with BOM（PS 5.1 无 BOM 时会把中文按 ANSI 解码 -> 乱码）
覆盖范围：项目根目录 + scripts/（不递归进 packs/outputs/assets 等大目录）
"""
import os
import glob

ROOT = "D:/Dsektop/AI渲染"
DIRS = [ROOT, os.path.join(ROOT, "scripts")]


def decode_any(raw):
    for enc in ("utf-8-sig", "utf-8", "cp936"):
        try:
            return raw.decode(enc), enc
        except Exception:
            continue
    raise SystemExit("cannot decode")


def fix_bat(path):
    raw = open(path, "rb").read()
    txt, src = decode_any(raw)
    txt = txt.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    open(path, "wb").write(txt.encode("cp936"))
    raw = open(path, "rb").read()
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    try:
        raw.decode("cp936")
        cp = "OK"
    except Exception as e:
        cp = "FAIL " + str(e)
    ok = (lf == 0 and crlf > 0 and cp == "OK" and b"||" not in raw and b"&&" not in raw)
    print("[bat] %-22s src=%-8s bytes=%-5d CRLF=%-3d bareLF=%d pipe=%s and=%s cp936=%s -> %s" % (
        os.path.basename(path), src, len(raw), crlf, lf,
        b"||" in raw, b"&&" in raw, cp, "PASS" if ok else "FAIL"))
    return ok


def fix_ps1(path):
    raw = open(path, "rb").read()
    if not raw.startswith(b"\xef\xbb\xbf"):
        txt, _ = decode_any(raw)
        open(path, "wb").write(b"\xef\xbb\xbf" + txt.encode("utf-8"))
    raw = open(path, "rb").read()
    body = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
    try:
        body.decode("utf-8")
        u8 = "OK"
    except Exception as e:
        u8 = "FAIL " + str(e)
    ok = raw.startswith(b"\xef\xbb\xbf") and u8 == "OK"
    print("[ps1] %-22s bytes=%-5d BOM=%s utf8=%s -> %s" % (
        os.path.basename(path), len(raw), raw.startswith(b"\xef\xbb\xbf"), u8,
        "PASS" if ok else "FAIL"))
    return ok


all_ok = True
seen = set()
for d in DIRS:
    for p in sorted(glob.glob(os.path.join(d, "*.bat")) + glob.glob(os.path.join(d, "*.ps1"))):
        if p in seen:
            continue
        seen.add(p)
        all_ok = (fix_bat(p) if p.lower().endswith(".bat") else fix_ps1(p)) and all_ok

print("SUMMARY:", "ALL PASS" if all_ok else "HAS FAIL")
