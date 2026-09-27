#!/usr/bin/env bash
# AI 白模渲染器 · 模型与运行时下载脚本（可续传 / 自动重试 / 校验体积）
# 用法：bash download_models.sh          （断线后重跑同一条命令即可续传）
# 说明：GitHub 直连在国内不通，故走 ghfast.top 加速；HF 走 hf-mirror.com。
#       所有目标文件均以 SHA-256 或字节数校验，避免下了半个文件却以为成功。

export PATH="/c/Users/Administrator/.workbuddy/binaries/PortableGit/versions/1.2.0/usr/bin:/c/Windows/System32:/c/Windows:$PATH"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY

ROOT=/f/AI-Renderer
LOG="$ROOT/download.log"
mkdir -p "$ROOT/packs" "$ROOT/models/checkpoints" "$ROOT/models/controlnet" "$ROOT/models/vae"

say(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

# fetch <url> <dest> <expected_bytes> <label> [fallback_url]
fetch(){
  local url="$1" dest="$2" want="$3" label="$4" alt="$5" attempt cur use
  for attempt in $(seq 1 50); do
    cur=0
    [ -f "$dest" ] && cur=$(stat -c %s "$dest" 2>/dev/null || echo 0)
    if [ "$cur" -ge "$want" ]; then
      say "OK   $label 已完成（$cur B）"
      return 0
    fi
    use="$url"
    if [ -n "$alt" ] && [ $((attempt % 3)) -eq 0 ]; then use="$alt"; fi
    say "->   $label 尝试 #$attempt（已有 $cur / $want B，$(( cur * 100 / want ))%）"
    curl -L -C - --connect-timeout 25 --max-time 5400 --retry 3 --retry-delay 5 \
         --speed-time 90 --speed-limit 15360 \
         -o "$dest" "$use" 2>>"$LOG"
    sleep 3
  done
  say "FAIL $label 重试 50 次仍未完成"
  return 1
}

GH="https://ghfast.top/https://github.com"
HF="https://hf-mirror.com"

say "===== 开始下载（目标：F:\\AI-Renderer）====="

fetch "$GH/comfyanonymous/ComfyUI/releases/latest/download/ComfyUI_windows_portable_nvidia.7z" \
      "$ROOT/packs/ComfyUI_windows_portable_nvidia.7z" 1925204508 "ComfyUI 便携版 (1.79 GiB)" \
      "https://ghproxy.net/https://github.com/comfyanonymous/ComfyUI/releases/latest/download/ComfyUI_windows_portable_nvidia.7z"

fetch "$HF/SG161222/RealVisXL_V5.0/resolve/main/RealVisXL_V5.0_fp16.safetensors" \
      "$ROOT/models/checkpoints/RealVisXL_V5.0_fp16.safetensors" 6938065488 "RealVisXL_V5.0 底模 (6.46 GiB, openrail++)"

fetch "$HF/xinsir/controlnet-union-sdxl-1.0/resolve/main/diffusion_pytorch_model_promax.safetensors" \
      "$ROOT/models/controlnet/controlnet-union-sdxl-1.0-promax.safetensors" 2513342408 "controlnet-union-sdxl-1.0 promax (2.34 GiB, Apache-2.0)"

fetch "$HF/stabilityai/sdxl-vae/resolve/main/sdxl_vae.safetensors" \
      "$ROOT/models/vae/sdxl_vae.safetensors" 334641164 "sdxl_vae (319 MiB, MIT)"

say "===== 结果校验（字节数）====="
for f in "$ROOT/packs/ComfyUI_windows_portable_nvidia.7z" \
         "$ROOT/models/checkpoints/RealVisXL_V5.0_fp16.safetensors" \
         "$ROOT/models/controlnet/controlnet-union-sdxl-1.0-promax.safetensors" \
         "$ROOT/models/vae/sdxl_vae.safetensors"; do
  if [ -f "$f" ]; then
    printf "%-64s %s B\n" "$(basename "$f")" "$(stat -c %s "$f")" | tee -a "$LOG"
  else
    printf "%-64s MISSING\n" "$(basename "$f")" | tee -a "$LOG"
  fi
done

say "===== 计算 SHA-256（写入 sha256.txt，供第 12 节登记）====="
( cd "$ROOT" && sha256sum packs/*.7z models/checkpoints/*.safetensors \
    models/controlnet/*.safetensors models/vae/*.safetensors > "$ROOT/sha256.txt" 2>>"$LOG" )
cat "$ROOT/sha256.txt" 2>/dev/null | tee -a "$LOG"

say "===== 全部结束 ====="
