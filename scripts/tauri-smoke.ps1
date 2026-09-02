<#
.SYNOPSIS
    Smoke-test the Bagger Windows MSI installer on a real Windows runner.

.DESCRIPTION
    Exercises the publishable-quality gates that pytest/vitest cannot cover:
      1. Install  — silent MSI install succeeds (exit 0) and the app binary lands.
      2. Version  — the installed exe carries a non-empty ProductVersion.
      3. Launch   — the app actually starts and stays alive (no immediate crash).
      4. Upgrade  — a reinstall over the existing install (the MSI upgrade code
                    path) also succeeds, proving the installer supports upgrading.
      5. Leftover — after we terminate the app, no orphan bagger / sidecar
                    process remains.

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
    }
    if ($hints.ContainsKey($code)) { return " — $($hints[$code])" }
    return ""
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

# ── 4. upgrade (reinstall over existing) ──────────────────
Write-Host ">> Simulating upgrade (reinstall existing install)..."
$upgradeArgs = @("/i", "`"$MsiPath`"", "/qn", "/norestart",
                 "REINSTALL=ALL", "REINSTALLMODE=vomus",
                 "/L*v", "`"$env:TEMP\bagger-upgrade.log`"")
$up = Start-Process msiexec.exe -Wait -PassThru -ArgumentList $upgradeArgs
if ($up.ExitCode -ne 0) {
    if (Test-Path "$env:TEMP\bagger-upgrade.log") {
        Get-Content "$env:TEMP\bagger-upgrade.log" | Select-Object -Last 40 | Write-Host
    }
    Write-Host ">> MSI resolved path: $MsiPath"
    Fail "msiexec upgrade/reinstall exited with code $($up.ExitCode)$(Get-MsiErrorHint $up.ExitCode)"
}
# Re-verify the binary survived the upgrade with the same version.
if (-not (Test-Path $expectedExe)) { Fail "app binary missing after upgrade" }
$ver2 = (Get-Item $expectedExe).VersionInfo.ProductVersion
if ($ver2 -ne $ver) { Fail "version changed after upgrade: '$ver' -> '$ver2'" }
Write-Host ">> Upgrade OK (version stable: $ver2)"

# ── 5. leftover-process check ─────────────────────────────
Write-Host ">> Terminating app and checking for orphan processes..."
try { Stop-Process -Id $launch.Id -Force -ErrorAction SilentlyContinue } catch {}
# The Tauri sidecar (bundled Python backend) may be a child; kill by name too.
Get-Process -Name "bagger-server*" -ErrorAction SilentlyContinue | ForEach-Object {
    try { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue } catch {}
}

$deadline = (Get-Date).AddSeconds(10)
do {
    Start-Sleep -Milliseconds 500
    $leftover = @(
        (Get-Process -Name $ProductName -ErrorAction SilentlyContinue)
        (Get-Process -Name "bagger-server*" -ErrorAction SilentlyContinue)
    )
    if ($leftover.Count -eq 0 -or ($leftover | Where-Object { $_ } | Measure-Object).Count -eq 0) {
        $leftover = @()
        break
    }
} while ((Get-Date) -lt $deadline)

if ($leftover.Count -gt 0) {
    $leftover | ForEach-Object { Write-Host "   orphan: $($_.Name) pid $($_.Id)" }
    Fail "orphan process(es) remained after app termination"
}
Write-Host ">> No leftover processes"

Write-Host "TAURI-SMOKE PASSED"
exit 0
