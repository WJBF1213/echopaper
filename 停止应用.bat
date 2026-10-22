@echo off
chcp 65001 >nul
setlocal EnableExtensions

echo [INFO] Stopping the IELTS app on port 8300 ...

where powershell >nul 2>nul
if errorlevel 1 goto netstat_fallback

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; try { $conns = @(Get-NetTCPConnection -LocalPort 8300 -State Listen -ErrorAction SilentlyContinue); if ($conns.Count -gt 0) { foreach ($procId in @($conns | Select-Object -ExpandProperty OwningProcess -Unique)) { try { Stop-Process -Id $procId -Force -ErrorAction Stop; Write-Host ('[OK] Stopped process ' + $procId) } catch { Write-Host ('[WARN] Could not stop process ' + $procId) } } } else { Write-Host '[INFO] Nothing is listening on port 8300.' } } catch { Write-Host '[WARN] Get-NetTCPConnection failed; falling back to netstat/taskkill.'; exit 2 }"
if not errorlevel 1 goto done

:netstat_fallback
set "FOUND="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8300 " ^| findstr "LISTENING"') do (
  set "FOUND=1"
  taskkill /PID %%P /T /F >nul 2>&1
  if errorlevel 1 (
    echo [WARN] Could not stop process %%P.
  ) else (
    echo [OK] Stopped process %%P.
  )
)
if not defined FOUND echo [INFO] Nothing is listening on port 8300.

:done
endlocal
