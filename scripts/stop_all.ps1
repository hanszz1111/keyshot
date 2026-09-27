$ErrorActionPreference = 'Continue'

# 停止由 start_all.ps1 注册的持久化服务（2026-09-27 新增）。
# 计划任务方式启动的服务不会随窗口关闭而退出，必须显式停止，否则会一直占着 8188 / 8765。

$taskNames = @('AIRender_Web', 'AIRender_ComfyUI')
$schedulerAvailable = $false
try {
    Import-Module ScheduledTasks -ErrorAction Stop
    $schedulerAvailable = $true
} catch {
    $schedulerAvailable = $false
}

$stopped = 0
foreach ($name in $taskNames) {
    $task = $null
    if ($schedulerAvailable) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    }
    if (-not $task) {
        Write-Host "$name : not registered."
        continue
    }
    if ($task.State -eq 'Running') {
        Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        Write-Host "$name : stopped (was running)."
        $stopped++
    } else {
        Write-Host "$name : already idle ($($task.State))."
    }
    # 关掉任务里已经派生的 python 进程，避免占住端口。
    $procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -like '*web\server.py*' -or $_.CommandLine -like '*ComfyUI\main.py*' -or $_.CommandLine -like '*ComfyUI/main.py*') }
    foreach ($p in $procs) {
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            Write-Host "  killed python pid $($p.ProcessId)"
            $stopped++
        } catch {
            Write-Host "  could not kill pid $($p.ProcessId): $($_.Exception.Message)"
        }
    }
}

Write-Host ""
if ($stopped -gt 0) {
    Write-Host "Stopped $stopped item(s). Ports 8188 / 8765 should be free."
} else {
    Write-Host "Nothing was running."
}
Write-Host "Re-launch any time with 一键启动.bat"
exit 0
