# DeepDive — Weekly Archive Pull
#
# Pulls persistent tester state from the Fly.io volume to a local snapshot:
#   - runs.jsonl             (aggregate manifest)
#   - results/               (per-run synthesis + state + parser QC)
#   - logs/                  (per-run logs, success AND failure)
#
# Each run creates a timestamped snapshot under $ArchiveRoot so you keep
# weekly history, not just the latest.
#
# Requires:
#   - flyctl installed at the default path or on PATH
#   - flyctl auth already logged in (one-time via `flyctl auth login`)
#
# Register with Task Scheduler — see bottom of this file for the one-liner.

$ErrorActionPreference = "Stop"

# ── Config ────────────────────────────────────────────────────────
$AppName      = "deepdive"
$RemoteRoot   = "/app/.chromadb"             # matches PERSIST_DIR in fly.toml
$ArchiveRoot  = "C:\DeepDive_Archives"
$FlyCtl       = if (Test-Path "$env:USERPROFILE\.fly\bin\flyctl.exe") {
                    "$env:USERPROFILE\.fly\bin\flyctl.exe"
                } else {
                    "flyctl"  # fall back to PATH
                }

# ── Paths for this run ────────────────────────────────────────────
$Stamp        = Get-Date -Format "yyyy-MM-dd_HHmmss"
$DateFolder   = Get-Date -Format "yyyy-MM-dd"
$SnapshotDir  = Join-Path $ArchiveRoot $DateFolder
$TarName      = "deepdive_$Stamp.tar.gz"
$RemoteTarPath = "/tmp/$TarName"
$LocalTarPath = Join-Path $SnapshotDir $TarName
$HistoryLog   = Join-Path $ArchiveRoot "pull_history.log"

New-Item -ItemType Directory -Path $SnapshotDir -Force | Out-Null
New-Item -ItemType Directory -Path $ArchiveRoot -Force | Out-Null

function Log-Line($msg) {
    $line = "$(Get-Date -Format 'u')  $msg"
    Add-Content -Path $HistoryLog -Value $line
    Write-Host $line
}

try {
    Log-Line "START pull for app=$AppName -> $SnapshotDir"

    # Step 1: tar runs.jsonl + results + logs on the remote side
    Log-Line "  Remote-tarring state..."
    $tarCmd = "tar -czf $RemoteTarPath -C $RemoteRoot runs.jsonl results logs 2>/dev/null || tar -czf $RemoteTarPath -C $RemoteRoot runs.jsonl results 2>/dev/null || tar -czf $RemoteTarPath -C $RemoteRoot runs.jsonl"
    & $FlyCtl ssh console -a $AppName -C "sh -c `"$tarCmd`""
    if ($LASTEXITCODE -ne 0) { throw "Remote tar failed (exit $LASTEXITCODE)" }

    # Step 2: sftp get the tar
    Log-Line "  Fetching tar to $LocalTarPath..."
    & $FlyCtl ssh sftp get $RemoteTarPath $LocalTarPath -a $AppName
    if ($LASTEXITCODE -ne 0) { throw "sftp get failed (exit $LASTEXITCODE)" }

    # Step 3: unpack locally. Windows 10+ includes tar.exe in System32.
    Log-Line "  Extracting..."
    tar -xzf $LocalTarPath -C $SnapshotDir
    if ($LASTEXITCODE -ne 0) { throw "Local tar extract failed" }

    # Step 4: delete the tar; clean up the remote tar too
    Remove-Item $LocalTarPath -Force
    & $FlyCtl ssh console -a $AppName -C "rm -f $RemoteTarPath" | Out-Null

    # Step 5: write a small snapshot manifest for quick grok-ability
    $manifestPath = Join-Path $SnapshotDir "_snapshot_info.txt"
    $runCount = 0
    $runsFile = Join-Path $SnapshotDir "runs.jsonl"
    if (Test-Path $runsFile) { $runCount = (Get-Content $runsFile | Measure-Object -Line).Lines }
    @(
        "DeepDive weekly snapshot"
        "Pulled: $(Get-Date -Format 'u')"
        "App: $AppName"
        "Remote root: $RemoteRoot"
        "Total runs in runs.jsonl: $runCount"
    ) | Set-Content -Path $manifestPath -Encoding UTF8

    Log-Line "OK pull complete — $runCount runs archived to $SnapshotDir"
}
catch {
    Log-Line "FAIL $($_.Exception.Message)"
    exit 1
}

# ── Register with Task Scheduler (run once, interactively) ────────
# Weekly on Sundays at 9:00 AM:
#
#   schtasks /Create /SC WEEKLY /D SUN /ST 09:00 `
#     /TN "DeepDive Weekly Pull" `
#     /TR "powershell -NoProfile -ExecutionPolicy Bypass -File `"C:\DeepDive\scripts\weekly_pull.ps1`"" `
#     /RL LIMITED /F
#
# To verify / manually trigger:
#   schtasks /Run /TN "DeepDive Weekly Pull"
#   schtasks /Query /TN "DeepDive Weekly Pull" /V /FO LIST
#
# To remove:
#   schtasks /Delete /TN "DeepDive Weekly Pull" /F
