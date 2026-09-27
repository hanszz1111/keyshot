$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$webRoot = Join-Path $projectRoot 'web'
$webScript = Join-Path $webRoot 'server.py'
$comfyRoot = if ($env:AI_RENDER_COMFY_ROOT) { $env:AI_RENDER_COMFY_ROOT } else { 'F:\AI-Renderer\packs\ComfyUI_windows_portable' }
$comfyPython = Join-Path $comfyRoot 'python_embeded\python.exe'

# --- 服务持久化（2026-09-27）------------------------------------------------
# 直接 Start-Process 起的进程会随启动它的父进程一起被回收，窗口一关服务就没了。
# 改用 Windows 计划任务承载：任务由 Task Scheduler 服务持有，脱离父进程树，可长期存活。
# 只有计划任务不可用时才退回 Start-Process，保证脚本在任何机器上都能跑通。
$taskWebName = 'AIRender_Web'
$taskComfyName = 'AIRender_ComfyUI'
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
if ($comfyOnline) {
    Write-Host 'ComfyUI: ready on http://127.0.0.1:8188/'
    exit 0
}
Write-Warning 'ComfyUI is offline. Check its window, then click Refresh Status in the web UI.'
exit 2
