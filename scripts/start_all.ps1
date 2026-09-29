$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$webRoot = Join-Path $projectRoot 'web'
$webScript = Join-Path $webRoot 'server.py'
$comfyRoot = if ($env:AI_RENDER_COMFY_ROOT) { $env:AI_RENDER_COMFY_ROOT } else { 'F:\AI-Renderer\packs\ComfyUI_windows_portable' }
$comfyPython = Join-Path $comfyRoot 'python_embeded\python.exe'

# --- 实验引擎：Qwen-Image-2.1 独立实例（2026-09-29 并入一键启动）------------
# 它是**另一个** ComfyUI 进程（端口 8190），与正式实例 8188 完全隔离：
# 正式实例的模型、工作流、自定义节点都不会被它影响，反之亦然。
# 位置可用环境变量 AI_RENDER_QWEN_ROOT 覆盖；目录不存在时自动跳过，
# **不影响前两个服务的启动**。设 AI_RENDER_NO_QWEN=1 可临时只起前两个。
$qwenRoot = if ($env:AI_RENDER_QWEN_ROOT) { $env:AI_RENDER_QWEN_ROOT } else { 'F:\AI-Renderer\experiments\Qwen21\ComfyUI_windows_portable' }
$qwenPython = Join-Path $qwenRoot 'python_embeded\python.exe'
$qwenPort = 8190
$qwenEnabled = -not ($env:AI_RENDER_NO_QWEN -eq '1')

# --- 服务持久化（2026-09-27）------------------------------------------------
# 直接 Start-Process 起的进程会随启动它的父进程一起被回收，窗口一关服务就没了。
# 改用 Windows 计划任务承载：任务由 Task Scheduler 服务持有，脱离父进程树，可长期存活。
# 只有计划任务不可用时才退回 Start-Process，保证脚本在任何机器上都能跑通。
$taskWebName = 'AIRender_Web'
$taskComfyName = 'AIRender_ComfyUI'
$taskQwenName = 'AIRender_Qwen21'
$schedulerAvailable = $false
try {
    Import-Module ScheduledTasks -ErrorAction Stop
    $null = Get-ScheduledTask -TaskName $taskWebName -ErrorAction SilentlyContinue
    $schedulerAvailable = $true
} catch {
    $schedulerAvailable = $false
}

function Start-PersistentTask {
    param(
        [string]$TaskName,
        [string]$Exe,
        [string]$ArgLine,
        [string]$WorkDir
    )
    if (-not $schedulerAvailable) { return $false }
    try {
        $action = New-ScheduledTaskAction -Execute $Exe -Argument $ArgLine -WorkingDirectory $WorkDir
        # ExecutionTimeLimit=0 → 不限时；IdleSettings 设成永不停机，否则机器一空闲服务就被收走。
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -DontStopOnIdleEnd
        Register-ScheduledTask -TaskName $TaskName -Action $action -Settings $settings -Force | Out-Null
        Start-ScheduledTask -TaskName $TaskName
        return $true
    } catch {
        Write-Warning "Scheduled task '$TaskName' unavailable ($($_.Exception.Message)); falling back to a plain process."
        return $false
    }
}
# ---------------------------------------------------------------------------

function Get-JsonOrNull([string]$url) {
    try { return Invoke-RestMethod -Uri $url -TimeoutSec 2 -ErrorAction Stop }
    catch { return $null }
}

function Test-PortOpen([int]$port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $result = $client.BeginConnect('127.0.0.1', $port, $null, $null)
        if (-not $result.AsyncWaitHandle.WaitOne(250)) { return $false }
        $client.EndConnect($result)
        return $true
    } catch { return $false }
    finally { $client.Close() }
}

function Get-RendererPort {
    for ($port = 8765; $port -le 8785; $port++) {
        $health = Get-JsonOrNull "http://127.0.0.1:$port/api/health"
        if ($health -and $health.root -and
            [string]::Equals([string]$health.root, $projectRoot, [StringComparison]::OrdinalIgnoreCase)) {
            return @{ Port = $port; Existing = $true }
        }
    }
    for ($port = 8765; $port -le 8785; $port++) {
        if (-not (Test-PortOpen $port)) { return @{ Port = $port; Existing = $false } }
    }
    throw 'No free renderer port in 8765-8785.'
}

function Get-WebPython {
    if (Test-Path $comfyPython) { return @{ Exe = $comfyPython; Prefix = @() } }
    $managed = Join-Path $env:USERPROFILE '.workbuddy\binaries\python\versions\3.13.12\python.exe'
    if (Test-Path $managed) { return @{ Exe = $managed; Prefix = @() } }
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) { return @{ Exe = $py.Source; Prefix = @('-3') } }
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) { return @{ Exe = $python.Source; Prefix = @() } }
    throw 'Python not found. Install Python 3.11+ or provide the ComfyUI portable package.'
}

if (-not (Test-Path $webScript)) { throw "Renderer web server missing: $webScript" }
Write-Host "Project: $projectRoot"

$comfyOnline = [bool](Get-JsonOrNull 'http://127.0.0.1:8188/system_stats')
if ($comfyOnline) {
    Write-Host 'ComfyUI: already running.'
} elseif (Test-Path $comfyPython) {
    Write-Host "Starting ComfyUI from $comfyRoot"
    $comfyArgs = '-s ComfyUI\main.py --windows-standalone-build --lowvram'
    $usedTask = Start-PersistentTask -TaskName $taskComfyName -Exe $comfyPython -ArgLine $comfyArgs -WorkDir $comfyRoot
    if (-not $usedTask) {
        Start-Process -FilePath $comfyPython -WorkingDirectory $comfyRoot `
            -ArgumentList @('-s', 'ComfyUI\main.py', '--windows-standalone-build', '--lowvram') | Out-Null
    } else {
        Write-Host "ComfyUI: launched via scheduled task '$taskComfyName' (survives closing this window)."
    }
} else {
    Write-Warning "ComfyUI not found at $comfyRoot. The web UI will open, but rendering will be unavailable."
    Write-Warning 'Set AI_RENDER_COMFY_ROOT to your portable ComfyUI folder, then launch again.'
}

# --- 实验引擎（Qwen-Image-2.1，端口 8190）----------------------------------
$qwenOnline = [bool](Get-JsonOrNull "http://127.0.0.1:$qwenPort/system_stats")
if (-not $qwenEnabled) {
    Write-Host 'Qwen experimental engine: skipped (AI_RENDER_NO_QWEN=1).'
} elseif ($qwenOnline) {
    Write-Host "Qwen experimental engine: already running on $qwenPort."
} elseif (Test-Path $qwenPython) {
    Write-Host "Starting Qwen-Image-2.1 experimental instance from $qwenRoot"
    $qwenArgs = '-s ComfyUI\main.py --windows-standalone-build --lowvram --port ' + [string]$qwenPort
    $usedTask = Start-PersistentTask -TaskName $taskQwenName -Exe $qwenPython -ArgLine $qwenArgs -WorkDir $qwenRoot
    if (-not $usedTask) {
        Start-Process -FilePath $qwenPython -WorkingDirectory $qwenRoot `
            -ArgumentList @('-s', 'ComfyUI\main.py', '--windows-standalone-build', '--lowvram', '--port', [string]$qwenPort) | Out-Null
    } else {
        Write-Host "Qwen experimental engine: launched via scheduled task '$taskQwenName' (survives closing this window)."
    }
} else {
    Write-Warning "Qwen experimental instance not found at $qwenRoot (skipped)."
    Write-Warning 'Optional: set AI_RENDER_QWEN_ROOT to its ComfyUI_windows_portable folder; see docs/Qwen-Image-2.1-Windows-部署与模型切换执行方案.md.'
    Write-Warning 'The stable SDXL pipeline is unaffected.'
}

$renderer = Get-RendererPort
$webPort = [int]$renderer.Port
if ($renderer.Existing) {
    Write-Host "Web UI: already running on $webPort."
} else {
    $python = Get-WebPython
    $env:RENDERER_PORT = [string]$webPort
    $env:RENDERER_NO_BROWSER = '1'
    Write-Host "Starting web UI on $webPort"
    $webArgLine = 'web\server.py --port ' + [string]$webPort
    $usedTask = Start-PersistentTask -TaskName $taskWebName -Exe $python.Exe -ArgLine $webArgLine -WorkDir $projectRoot
    if (-not $usedTask) {
        $webArgs = @()
        $webArgs += $python.Prefix
        $webArgs += '"' + $webScript + '"'
        Start-Process -FilePath $python.Exe -WorkingDirectory $webRoot -ArgumentList $webArgs | Out-Null
    } else {
        Write-Host "Web UI: launched via scheduled task '$taskWebName' (survives closing this window)."
    }
}

$webUrl = "http://127.0.0.1:$webPort/"
$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    $health = Get-JsonOrNull "${webUrl}api/health"
    if ($health -and $health.root -and
        [string]::Equals([string]$health.root, $projectRoot, [StringComparison]::OrdinalIgnoreCase)) {
        $ready = $true
        break
    }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) { throw "Web UI did not become ready. Check the server window: $webUrl" }

Start-Process $webUrl | Out-Null
Write-Host "Web UI: $webUrl"
if (-not $comfyOnline -and (Test-Path $comfyPython)) {
    for ($i = 0; $i -lt 60; $i++) {
        if (Get-JsonOrNull 'http://127.0.0.1:8188/system_stats') { $comfyOnline = $true; break }
        Start-Sleep -Seconds 1
    }
}
# 实验引擎就绪确认。它首次出图才加载 7B/8B 权重，这里只等服务端口起来，
# 不等模型 —— 否则一键启动会白等好几分钟，而且看不出是在等什么。
if ($qwenEnabled -and (Test-Path $qwenPython)) {
    if (-not $qwenOnline) {
        for ($i = 0; $i -lt 45; $i++) {
            if (Get-JsonOrNull "http://127.0.0.1:$qwenPort/system_stats") { $qwenOnline = $true; break }
            Start-Sleep -Seconds 1
        }
    }
    if ($qwenOnline) {
        Write-Host "Qwen-Image-2.1 experimental engine: ready on http://127.0.0.1:$qwenPort/"
    } else {
        Write-Warning "Qwen-Image-2.1 experimental instance did not come up. Check its window; the stable pipeline still works."
    }
}

if ($comfyOnline) {
    Write-Host 'ComfyUI: ready on http://127.0.0.1:8188/'
    exit 0
}
Write-Warning 'ComfyUI is offline. Check its window, then click Refresh Status in the web UI.'
exit 2
