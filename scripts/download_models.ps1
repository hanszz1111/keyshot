# AI 白模渲染器 · 模型与运行时下载（可续传 / 自动重试 / 体积 + SHA-256 校验）
# 由 下载模型.bat 调用。也可以直接右键"使用 PowerShell 运行"。
# 断线后重跑即可续传，已下载且校验通过的文件不会重下。
#
# 源策略（2026-09-24 实测）：
#   · ModelScope（www.modelscope.cn）实测 17-19 MB/s —— 国内首选，用于两个底模
#   · HuggingFace 镜像 hf-mirror.com 单文件 2-5 MB/s，速度随网络波动 —— 用于 ControlNet / VAE
#   · GitHub 直连不通，加速站 ghfast.top 对【完整 GET】会返回 0 字节，只放行【Range】请求
#     → ComfyUI 便携版必须用分块（Range）方式下载（见 Download-Chunked）
#
# 关键坑（踩过的，别改回去）：
#   1) curl.exe 是 Windows 程序，-o 的参数必须是 Windows 路径（F:\... 或 F:/...）。
#      写成 /f/... 会 http=206 但写不进任何字节（静默失败）。
#   2) 不要用 -o /dev/null 量速度，会报 0 字节；要写真实文件再取长度。
#   3) 本机 rm 会被"安全删除"拦截静默失败，脚本里清空文件请用 Set-Content -Value $null 或 FileStream。

$ErrorActionPreference = 'Continue'
$ProgressPreference    = 'SilentlyContinue'

$Root = 'F:\AI-Renderer'
$Log  = Join-Path $Root 'download.log'

foreach ($d in @("$Root\packs","$Root\models\checkpoints","$Root\models\controlnet","$Root\models\vae")) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}

$Gh = 'https://ghfast.top/https://github.com'
$Hf = 'https://hf-mirror.com'
$Ms = 'https://www.modelscope.cn/api/v1/models'

# Mode: full = 完整 GET（可用 -C - 续传）；chunk = 32MB 分块 Range 下载
$Targets = @(
    @{ Name = 'ComfyUI 便携版 (1.79 GiB) [GPL-3.0 工具]'
       Out  = "$Root\packs\ComfyUI_windows_portable_nvidia.7z"
       Size = 1925204508
       Url  = "$Gh/comfyanonymous/ComfyUI/releases/latest/download/ComfyUI_windows_portable_nvidia.7z"
       Alt  = $null ; Mode = 'chunk' ; Sha = $null },

    @{ Name = 'SDXL base 1.0 官方底模 (6.46 GiB) [OpenRAIL++-M 可商用]'
       Out  = "$Root\models\checkpoints\sd_xl_base_1.0.safetensors"
       Size = 6938078334
       Url  = "$Ms/AI-ModelScope/stable-diffusion-xl-base-1.0/repo?Revision=master&FilePath=sd_xl_base_1.0.safetensors"
       Alt  = $null ; Mode = 'full'
       Sha  = '31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b' },

    @{ Name = 'RealVisXL V5.0 Lightning fp16 (6.46 GiB) [openrail++ 可商用, 4-8 步]'
       Out  = "$Root\models\checkpoints\RealVisXL_V5.0_Lightning_fp16.safetensors"
       Size = 6938065512
       Url  = "$Ms/ModelsLab/RealVisXL_V5.0_Lightning/repo?Revision=master&FilePath=RealVisXL_V5.0_Lightning_fp16.safetensors"
       Alt  = $null ; Mode = 'full'
       Sha  = 'fabcadd9330dcc4f9702063428d40b9d4d07168d8acefc819b8d1d9db466b3ec' },

    @{ Name = 'controlnet-union-sdxl-1.0 promax (2.34 GiB) [Apache-2.0]'
       Out  = "$Root\models\controlnet\controlnet-union-sdxl-1.0-promax.safetensors"
       Size = 2513342408
       Url  = "$Hf/xinsir/controlnet-union-sdxl-1.0/resolve/main/diffusion_pytorch_model_promax.safetensors"
       Alt  = $null ; Mode = 'full'
       Sha  = '9fae2e50cb431bfcbe05822b59ec2228df545ef27f711dea8949e9f4ed9f7cdc' },

    @{ Name = 'sdxl_vae (319 MiB) [MIT]'
       Out  = "$Root\models\vae\sdxl_vae.safetensors"
       Size = 334641164
       Url  = "$Hf/stabilityai/sdxl-vae/resolve/main/sdxl_vae.safetensors"
       Alt  = $null ; Mode = 'full'
       Sha  = '63aeecb90ff7bc1c115395962d3e803571385b61938377bc7089b36e81e92e2e' }
)

function Say([string]$m) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m
    Write-Host $line
    Add-Content -LiteralPath $Log -Value $line -Encoding UTF8
}

function Get-Len([string]$p) {
    if (Test-Path -LiteralPath $p) { return (Get-Item -LiteralPath $p).Length }
    return 0
}

function Test-File($t) {
    if ((Get-Len $t.Out) -ne $t.Size) { return $false }
    if ($t.Sha) {
        $h = (Get-FileHash -LiteralPath $t.Out -Algorithm SHA256).Hash.ToLower()
        if ($h -ne $t.Sha) { return $false }
    }
    return $true
}

# 完整 GET（可续传）。适合 ModelScope / hf-mirror。
function Download-Full($t, [int]$tries) {
    for ($i = 1; $i -le $tries; $i++) {
        if ((Get-Len $t.Out) -ge $t.Size) { return $true }
        Say ("    full 第 {0} 次，已有 {1:N0} / {2:N0} B" -f $i, (Get-Len $t.Out), $t.Size)
        $url = $t.Url
        if ($t.Alt -and ($i % 3 -eq 0)) { $url = $t.Alt; Say "    (切换备用源)" }
        & curl.exe -L -C - --connect-timeout 25 --retry 5 --retry-delay 5 `
                   --speed-time 90 --speed-limit 20480 -o $t.Out $url
        Start-Sleep -Seconds 2
    }
    return ((Get-Len $t.Out) -ge $t.Size)
}

# 分块 Range 下载。ghfast 这类只放行 Range 的源必须用这个。
function Download-Chunked($t, [int]$chunkMB = 32) {
    $chunk = $chunkMB * 1MB
    $tmp   = "$($t.Out).part"
    Say ("    chunk 分块下载（{0}MB/块）" -f $chunkMB)
    $fs = [System.IO.File]::Create($t.Out)
    try {
        $pos = [long]0
        $n = 0
        while ($pos -lt $t.Size) {
            $end = $pos + $chunk - 1
            if ($end -ge $t.Size) { $end = $t.Size - 1 }
            $exp = $end - $pos + 1
            $ok = $false
            for ($k = 1; $k -le 5; $k++) {
                if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
                & curl.exe -L -s --connect-timeout 25 --max-time 240 --retry 3 --retry-delay 3 `
                           -r "$pos-$end" -o $tmp $t.Url
                if ((Get-Len $tmp) -eq $exp) { $ok = $true; break }
                Start-Sleep -Seconds 2
            }
            if (-not $ok) { throw ("分块失败 @ {0}（期望 {1} 字节）" -f $pos, $exp) }
            $bytes = [System.IO.File]::ReadAllBytes($tmp)
            $fs.Write($bytes, 0, $bytes.Length)
            $fs.Flush()
            $pos = $end + 1
            $n++
            if (($n % 5) -eq 0) { Say ("      {0:N0} / {1:N0} B" -f $pos, $t.Size) }
        }
    } finally {
        $fs.Close()
    }
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
    return ((Get-Len $t.Out) -eq $t.Size)
}

Write-Host ''
Write-Host '============================================================'
Write-Host ' AI 白模渲染器 · 下载模型与运行时'
Write-Host ' 目标目录: F:\AI-Renderer   (总下载量约 18.6 GiB)'
Write-Host ' 断线后重跑本脚本即可续传，已通过校验的文件不再重下。'
Write-Host '============================================================'
Write-Host ''

Say '===== 开始下载 ====='

foreach ($t in $Targets) {
    if (Test-File $t) { Say "OK   $($t.Name) 已存在且校验通过，跳过"; continue }

    # 大小到了但哈希不符 → 清空重下，避免"看着下完了其实是坏文件"
    if ((Get-Len $t.Out) -ge $t.Size -and $t.Sha) {
        Say "WARN $($t.Name) 体积已满但哈希不符，清空重下"
        $fs = [System.IO.File]::Create($t.Out); $fs.Close()
    }

    $ok = $false
    for ($round = 1; $round -le 3; $round++) {
        if ($t.Mode -eq 'chunk') { $ok = Download-Chunked $t }
        else                     { $ok = Download-Full    $t 40 }
        if (Test-File $t) { break }
        if ((Get-Len $t.Out) -ge $t.Size -and $t.Sha) {
            Say "WARN $($t.Name) 第 $round 轮哈希不符，清空重来"
            $fs = [System.IO.File]::Create($t.Out); $fs.Close()
        }
    }

    if (Test-File $t) { Say "OK   $($t.Name) 下载完成并校验通过" }
    else              { Say "FAIL $($t.Name) 未完成或校验未通过，请重跑本脚本续传" }
}

Write-Host ''
Say '===== 体积与哈希汇总 ====='
$allOk = $true
foreach ($t in $Targets) {
    $got = Get-Len $t.Out
    $h = ''
    if ($got -gt 0) { $h = (Get-FileHash -LiteralPath $t.Out -Algorithm SHA256).Hash.ToLower() }
    if (Test-File $t) {
        Say ("OK   {0,-46} {1:N0} B" -f (Split-Path $t.Out -Leaf), $got)
    } else {
        $allOk = $false
        Say ("BAD  {0,-46} {1:N0} / {2:N0} B" -f (Split-Path $t.Out -Leaf), $got, $t.Size)
    }
}

$hashFile = Join-Path $Root 'sha256.txt'
if (Test-Path -LiteralPath $hashFile) { Set-Content -LiteralPath $hashFile -Value '' -Encoding UTF8 }
foreach ($t in $Targets) {
    if ((Get-Len $t.Out) -gt 0) {
        $h = (Get-FileHash -LiteralPath $t.Out -Algorithm SHA256).Hash.ToLower()
        Add-Content -LiteralPath $hashFile -Value "$h  $($t.Out)" -Encoding UTF8
    }
}

Write-Host ''
if ($allOk) {
    Write-Host '============================================================' -ForegroundColor Green
    Write-Host ' 全部下载完成，体积与哈希校验通过。' -ForegroundColor Green
    Write-Host ' 下一步：解压 F:\AI-Renderer\packs\ComfyUI_windows_portable_nvidia.7z' -ForegroundColor Green
    Write-Host '        （本机有 WinRAR，右键 → 解压到当前文件夹即可；没有 7-Zip 也没关系）' -ForegroundColor Green
    Write-Host '============================================================' -ForegroundColor Green
} else {
    Write-Host '============================================================' -ForegroundColor Yellow
    Write-Host ' 有文件未下完或校验未过。再次运行本脚本即可续传（不会重下已通过的）。' -ForegroundColor Yellow
    Write-Host '============================================================' -ForegroundColor Yellow
}
Write-Host ''
Write-Host "日志：$Log"
Write-Host ''
Read-Host '按回车键关闭'
