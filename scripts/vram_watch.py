#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ComfyUI 显存采样器 —— 在跑长实验时旁路记录峰值显存。

为什么需要单开一个脚本：`scripts/qwen_ab_experiment.py` 只在每格结束后写记录，
那时模型已经释放，**测不到峰值**。而换更大权重的核心风险正是「峰值会不会爆」。

用法（与实验并行跑，Ctrl-C 停止）：

    python_embeded\\python.exe scripts/vram_watch.py --host http://127.0.0.1:8190 --out outputs/_AB实验/vram.csv

每 2 秒打一行 `时间, 已用MiB, 空闲MiB, 总量MiB`。只读取 `/system_stats`，不干扰生成。
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

# 本机 ComfyUI 必须直连：绕开环境里的 http_proxy，否则会被代理绕一圈（甚至 502）
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def stats(host):
    req = urllib.request.Request(host + "/system_stats")
    with _OPENER.open(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="vram_watch.py", description="ComfyUI 显存采样")
    ap.add_argument("--host", default="http://127.0.0.1:8190")
    ap.add_argument("--out", required=True, help="CSV 输出路径（Windows 形式）")
    ap.add_argument("--interval", type=float, default=2.0)
    args = ap.parse_args(argv)

    outdir = os.path.dirname(os.path.abspath(args.out))
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time", "used_mib", "free_mib", "total_mib", "peak_used_mib"])
        peak = 0
        print("采样中 → %s（Ctrl-C 停止）" % args.out, flush=True)
        try:
            while True:
                try:
                    d = stats(args.host)
                    dev = (d.get("devices") or [{}])[0]
                    total = int(dev.get("vram_total") or 0)
                    free = int(dev.get("vram_free") or 0)
                    used = max(0, total - free)
                    peak = max(peak, used)
                    w.writerow([datetime.now().strftime("%H:%M:%S"),
                                used // 1048576, free // 1048576,
                                total // 1048576, peak // 1048576])
                    f.flush()
                except Exception as exc:
                    w.writerow([datetime.now().strftime("%H:%M:%S"),
                                "ERR", str(exc)[:80], "", peak // 1048576])
                    f.flush()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("停止。峰值已用 %.2f GiB" % (peak / 1024**3), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
