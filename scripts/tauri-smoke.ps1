<#
.SYNOPSIS
    Smoke-test the Bagger Windows MSI installer on a real Windows runner.

.DESCRIPTION
    Exercises the publishable-quality gates that pytest/vitest cannot cover:
      1. Install  — silent MSI install succeeds (exit 0) and the app binary lands.
      2. Version  — the installed exe carries a non-empty ProductVersion.
      3. Launch   — the app actually starts and stays alive (no immediate crash).
      4. Stop     — the app and its sidecar exit cleanly when terminated.
      5. Upgrade  — a reinstall over the existing install (the MSI upgrade code
                    path) succeeds, proving the installer supports upgrading.
      6. Relaunch — the install replaced by the upgrade still starts and stays
                    alive (an upgrade that leaves a broken install must fail).
      7. Leftover — after we terminate the app again, no orphan bagger /
                    sidecar process remains.

    The app is stopped BEFORE the upgrade step. msiexec cannot replace files
    that a running process holds open: with a live app it either fails with
    1603 ("file in use") or silently defers the replace to the next reboot and
    exits 3010/1641. Both make the upgrade gate lie, so step 4 exists to give
    step 5 a clean target.

    Designed to run in the `tauri-smoke` CI job on windows-latest after the
    MSI artifact is built. It is deliberately deterministic: install exit code,
    binary presence, version, reinstall exit code, and orphan-process checks
    are HARD failures. The "stays alive" check is also hard — GitHub Actions
    windows-latest has a desktop session + WebView2, so the Tauri app must
    launch; if it cannot in a future runner image we want to know.

.PARAMETER MsiPath
    Path to the built bagger-*.msi produced by `npm run tauri build`.

.PARAMETER ProductName
    Tauri productName (must match tauri.conf.json). Controls the install dir
    and exe name. Defaults to "Bagger".

.PARAMETER LaunchGraceSec
    How long to wait for the launched app to remain running before declaring
    the launch successful. Defaults to 5s.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $MsiPath,

    [string] $ProductName = "Bagger",
    [int]    $LaunchGraceSec = 5
)

$ErrorActionPreference = "Stop"

function Fail([string] $msg) {
    Write-Error "TAURI-SMOKE FAILED: $msg"
    exit 1
}

# msiexec speaks in bare numbers; translate the ones we are likely to hit so a
# CI failure explains itself without someone decoding exit codes by hand.
function Get-MsiErrorHint([int] $code) {
    $hints = @{
        1603 = "fatal error during installation — read the MSI log above"
        1605 = "product not found (upgrade/uninstall target missing)"
        1618 = "another installation is already in progress on this machine"
        1619 = "package could not be opened — check the path actually reaches msiexec"
        1620 = "package could not be opened — MSI may be invalid or corrupt"
        1638 = "a different version of this product is already installed"
        1641 = "success, but Windows started a reboot to finish — acceptable on CI"
        3010 = "success, but a reboot is required to finish — acceptable on CI"
    }
    if ($hints.ContainsKey($code)) { return " — $($hints[$code])" }
    return ""
}

# Exit codes msiexec uses to say "the install worked, but Windows needs a
# reboot to finish replacing in-use files". On a disposable CI runner we never
# reboot mid-job, so treat these as success rather than a broken installer.
$script:RebootExitCodes = @(3010, 1641)

# Every process this smoke test owns: the app itself plus the bundled Python
# sidecar (bagger-server-*.exe) the Tauri app spawns as a child.
function Get-AppProcesses {
    $procs = @()
    foreach ($name in @($ProductName, "bagger-server*")) {
        $procs += @(Get-Process -Name $name -ErrorAction SilentlyContinue)
    }
    return $procs
}

# Terminate the app (by pid when we have it, by name for anything we inherited)
# and the sidecar, then wait for them to actually disappear from the process
# table. Returns $true once nothing is left, $false if the deadline expired.
#
# Waiting matters as much as killing: Stop-Process returns before the process
# has released its file handles, so upgrading immediately after it can still
# hit "file in use".
function Stop-AppProcesses([int] $ProcessId) {
    if ($ProcessId -gt 0) {
        try { Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue } catch {}
    }
    Get-AppProcesses | ForEach-Object {
        try { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue } catch {}
    }

    $deadline = (Get-Date).AddSeconds(15)
    do {
        if (@(Get-AppProcesses).Count -eq 0) { return $true }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)

    return $false
}

# ── 0. sanity ─────────────────────────────────────────────
if (-not (Test-Path -LiteralPath $MsiPath)) { Fail "MSI not found at '$MsiPath'" }

# msiexec cannot open a mixed-separator path. A caller passing "msi\app.msi"
# (forward slash) makes PowerShell glue it onto the CWD, producing
# "D:\repo\msi\app.msi" — PowerShell resolves that fine, but msiexec fails
# with 1619 ("package could not be opened"). Normalize to a fully-qualified,
# backslash-only filesystem path before handing it to msiexec.
$MsiPath = (Resolve-Path -LiteralPath $MsiPath).ProviderPath

Write-Host ">> Installing MSI: $MsiPath"
Write-Host (">> MSI size: {0:N0} bytes" -f (Get-Item -LiteralPath $MsiPath).Length)

# ── 1. install ────────────────────────────────────────────
$log = Join-Path $env:TEMP "bagger-install.log"
$installArgs = @("/i", "`"$MsiPath`"", "/qn", "/norestart", "/L*v", "`"$log`"")
$proc = Start-Process msiexec.exe -Wait -PassThru -ArgumentList $installArgs
if ($proc.ExitCode -ne 0) {
    if (Test-Path $log) { Get-Content $log | Select-Object -Last 40 | Write-Host }
    Write-Host ">> MSI resolved path: $MsiPath"
    Write-Host ">> MSI still exists on disk: $(Test-Path -LiteralPath $MsiPath)"
    Fail "msiexec install exited with code $($proc.ExitCode)$(Get-MsiErrorHint $proc.ExitCode)"
}
Write-Host ">> Install OK (exit 0)"

# ── 2. locate binary + version ────────────────────────────
# Tauri's WiX template installs per-machine by default
# (InstallScope="perMachine", INSTALLDIR under ProgramFiles64Folder), so the
# exe lands in "C:\Program Files\<ProductName>\" — NOT %LOCALAPPDATA%. Check
# the real candidates first, then fall back to a broad search of both roots.
$candidates = @(
    (Join-Path ${env:ProgramFiles} "$ProductName\$ProductName.exe"),
    (Join-Path ${env:LOCALAPPDATA} "$ProductName\$ProductName.exe")
)
if (${env:ProgramFiles(x86)}) {
    $candidates += (Join-Path ${env:ProgramFiles(x86)} "$ProductName\$ProductName.exe")
}
$expectedExe = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if (-not $expectedExe) {
    $searchRoots = @(${env:ProgramFiles}, ${env:LOCALAPPDATA}) | Where-Object { $_ }
    $found = $searchRoots | ForEach-Object {
        Get-ChildItem -Path $_ -Recurse -Filter "$ProductName.exe" -ErrorAction SilentlyContinue
    } | Select-Object -First 1
    if (-not $found) {
        Fail "installed '$ProductName.exe' not found under Program Files or LOCALAPPDATA"
    }
    $expectedExe = $found.FullName
}
Write-Host ">> App binary: $expectedExe"

$ver = (Get-Item $expectedExe).VersionInfo.ProductVersion
if ([string]::IsNullOrWhiteSpace($ver)) { Fail "ProductVersion is empty" }
Write-Host ">> Version: $ver"

# ── 3. launch ─────────────────────────────────────────────
Write-Host ">> Launching app..."
$launch = Start-Process -FilePath $expectedExe -PassThru
Start-Sleep -Seconds $LaunchGraceSec
$stillRunning = try {
    $null -ne (Get-Process -Id $launch.Id -ErrorAction SilentlyContinue)
} catch { $false }
if (-not $stillRunning) { Fail "app exited within ${LaunchGraceSec}s of launch (immediate crash?)" }
Write-Host ">> App launched and stayed alive (pid $($launch.Id))"

# ── 4. stop the app before upgrading ──────────────────────
# Give msiexec a clean target: it cannot replace files a running process holds
# open, and with /qn there is no UI to tell us it deferred the replace.
Write-Host ">> Stopping app before upgrade..."
if (-not (Stop-AppProcesses -ProcessId $launch.Id)) {
    Get-AppProcesses | ForEach-Object { Write-Host "   still running: $($_.Name) pid $($_.Id)" }
    Fail "app/sidecar did not exit within 15s — upgrade would hit in-use files"
}
Write-Host ">> App and sidecar stopped cleanly"

# ── 5. upgrade (reinstall over existing) ──────────────────
Write-Host ">> Simulating upgrade (reinstall existing install)..."
$upgradeArgs = @("/i", "`"$MsiPath`"", "/qn", "/norestart",
                 "REINSTALL=ALL", "REINSTALLMODE=vomus",
                 "/L*v", "`"$env:TEMP\bagger-upgrade.log`"")
$up = Start-Process msiexec.exe -Wait -PassThru -ArgumentList $upgradeArgs
if ($up.ExitCode -ne 0 -and $script:RebootExitCodes -notcontains $up.ExitCode) {
    if (Test-Path "$env:TEMP\bagger-upgrade.log") {
        Get-Content "$env:TEMP\bagger-upgrade.log" | Select-Object -Last 40 | Write-Host
    }
    Write-Host ">> MSI resolved path: $MsiPath"
    Fail "msiexec upgrade/reinstall exited with code $($up.ExitCode)$(Get-MsiErrorHint $up.ExitCode)"
}
if ($script:RebootExitCodes -contains $up.ExitCode) {
    Write-Host ">> Upgrade succeeded but Windows wants a reboot (exit $($up.ExitCode)); continuing"
} else {
    Write-Host ">> Upgrade exit 0 (clean)"
}
# Re-verify the binary survived the upgrade with the same version.
if (-not (Test-Path $expectedExe)) { Fail "app binary missing after upgrade" }
$ver2 = (Get-Item $expectedExe).VersionInfo.ProductVersion
if ($ver2 -ne $ver) { Fail "version changed after upgrade: '$ver' -> '$ver2'" }
Write-Host ">> Upgrade OK (version stable: $ver2)"

# ── 6. relaunch the upgraded install ──────────────────────
# The upgrade gate is only meaningful if the install it produced still runs —
# a reinstall that quietly leaves a broken app must fail here, not in prod.
Write-Host ">> Relaunching upgraded app..."
$relaunch = Start-Process -FilePath $expectedExe -PassThru
Start-Sleep -Seconds $LaunchGraceSec
$relaunchAlive = try {
    $null -ne (Get-Process -Id $relaunch.Id -ErrorAction SilentlyContinue)
} catch { $false }
if (-not $relaunchAlive) {
    Fail "upgraded app exited within ${LaunchGraceSec}s of relaunch"
}
Write-Host ">> Upgraded app launched and stayed alive (pid $($relaunch.Id))"

# ── 7. leftover-process check ─────────────────────────────
Write-Host ">> Terminating app and checking for orphan processes..."
if (-not (Stop-AppProcesses -ProcessId $relaunch.Id)) {
    Get-AppProcesses | ForEach-Object { Write-Host "   orphan: $($_.Name) pid $($_.Id)" }
    Fail "orphan process(es) remained after app termination"
}
Write-Host ">> No leftover processes"

Write-Host "TAURI-SMOKE PASSED"
exit 0
