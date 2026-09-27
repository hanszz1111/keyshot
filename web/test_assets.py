# -*- coding: utf-8 -*-
"""投放区归类规则的离线自测（不依赖 web 服务）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server as S

LOG = []


def P(s=""):
    LOG.append(str(s))


# (相对路径, fb_sku, fb_view, 期望 kind, 期望 sku, 期望 view, 期望 role)
CASES = [
    ("LS-360G/front/depth.png",                    "",        "", "pass",      "LS-360G", "front",     "depth"),
    ("LS-360G/3q4_left/normal.png",                "",        "", "pass",      "LS-360G", "3q4_left",  "normal"),
    ("passes/LS-360G/top/clay.png",                "",        "", "pass",      "LS-360G", "top",       "clay"),
    ("assets/passes/LS-360G/side/beauty.jpg",      "",        "", "pass",      "LS-360G", "side",      "clay"),
    ("LS-360G_front_depth.png",                    "",        "", "pass",      "LS-360G", "front",     "depth"),
    ("LS-360G_左前_法线.png",                       "",        "", "pass",      "LS-360G", "3q4_left",  "normal"),
    ("LS-360G/深度.png",                            "",        "front", "pass",  "LS-360G", "front",     "depth"),
    ("LS-360G/深度.png",                            "",        "", "pass_noview", "LS-360G", "",       "depth"),
    ("LS-360G/_待分机位/normal.png",                 "",        "front", "pass_noview", "LS-360G", "",    "normal"),
    ("正面/深度.png",                               "",        "", "inbox",      "",        "front",   "depth"),
    ("depth.png",                                  "",        "front", "inbox",      "",        "front",   "depth"),
    ("depth.png",                                  "",        "", "inbox",      "",        "",        "depth"),
    ("depth.png",                                  "LS-360G", "front", "pass", "LS-360G", "front",   "depth"),
    ("随便一个文件.xlsx",                            "",        "front", "inbox",   "",        "",       ""),
    ("说明.psd",                                    "",        "front", "inbox",   "",        "",       ""),
    # --- 文件名有没有「剥离证据」决定谁说了算 ---
    ("My Product.png",                             "QA-200",  "front", "pass",    "QA-200",  "front",  "clay"),
    ("毫无线索.png",                                "",        "side",  "inbox",   "",        "side",   "clay"),
    ("LS-360G_front_depth.png",                    "QA-200",  "front", "pass",    "LS-360G", "front",  "depth"),
    ("新建文件夹/depth.png",                        "QA-200",  "front", "pass",    "QA-200",  "front",  "depth"),
    ("LS-360G/abc.png",                            "",        "",      "pass_noview", "LS-360G", "",    "clay"),
    ("白模/LS-360G.ksp",                            "",        "", "model",     "LS-360G", "",        ""),
    ("output/LS-360G.glb",                         "",        "", "model",     "LS-360G", "",        ""),
    ("我的白模/QA-200.stp",                         "",        "", "model",     "QA-200",  "",        ""),
]

fails = 0
P("=== 归类规则 ===")
for rel, fb_sku, fb_view, kind, sku, view, role in CASES:
    k, s, v, r = S.parse_asset_rel(rel, fb_sku=fb_sku, fb_view=fb_view)
    ok = (k == kind and s == sku and v == view and r == role)
    if not ok:
        fails += 1
    P("%s  %-38s -> kind=%-11s sku=%-9s view=%-13s role=%s"
      % ("OK  " if ok else "FAIL", rel, k, s, v, r))
    if not ok:
        P("      期望: kind=%-11s sku=%-9s view=%-13s role=%s" % (kind, sku, view, role))

P("")
P("=== 落盘位置（fb_sku=LS-360G, fb_view=front）===")
for rel in ["LS-360G_front_depth.png", "LS-360G/front/normal.png",
            "LS-360G/深度.png", "白模/LS-360G.ksp", "认不出来.xyz"]:
    d, kind, meta = S.plan_upload(rel, fb_sku="LS-360G", fb_view="front")
    P("  %-30s -> %-48s [%s]" % (rel, os.path.relpath(d, S.ROOT).replace("\\", "/"), kind))

P("")
P("=== 别名覆盖 ===")
P("  view: " + " ".join("%s=%s" % (t, S.detect_view(t))
                       for t in ["正面", "left", "3q4l", "俯视", "透明件", "按键", "侧视", "topdown"]))
P("  role: " + " ".join("%s=%s" % (t, S.detect_role(t))
                       for t in ["白模", "beauty", "深度图", "nrm", "蒙版", "灰模"]))

P("")
P("=== 当前投放区实况 ===")
rep = S.asset_report()
P("  assets  : " + rep["assets"])
P("  白模    : %d 个 %s" % (len(rep["models"]), [m["file"] for m in rep["models"]]))
P("  passes  : %d 个 SKU %s" % (len(rep["items"]), [i["sku"] for i in rep["items"]]))
P("  散落    : %d | 待归类: %d" % (len(rep["loose"]), len(rep["inbox"])))

P("")
P("结果: " + ("全部通过" if fails == 0 else "%d 项失败" % fails))

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_test_out_utf8.txt")
with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(LOG))
print("\n".join(LOG))
print("\n[written] " + out)
