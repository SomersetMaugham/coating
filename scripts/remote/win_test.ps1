# Runs on the Windows test machine (called over ssh by scripts/remote_test.sh; Windows PowerShell 5.1 compatible).
# Tests one commit on Windows (each of -Pythons), then in the WSL distro through linux_test.sh, one after the other,
# and writes logs, JUnit XML and summary.txt to coat-test\results-<sha12>.  See docs/WINDOWS_WSL_TESTING.md.
# Keep this file ASCII: Windows PowerShell 5.1 reads a .ps1 without BOM in the ANSI code page.
#
# Exit status 0 only if every environment exited 0 with at least one test and no failed, errored or skipped test:
# a missing PySide6 makes tests/test_gui_smoke.py skip itself, which pytest reports as success.
param(
    [Parameter(Mandatory = $true)][string]$Sha,
    [Parameter(Mandatory = $true)][string]$Bundle,  # file name inside coat-test
    [string]$Distro = "",                           # empty: WSL's default distro
    [string]$Pythons = "3.10 3.13",                 # space-separated, passed on to linux_test.sh as well
    [ValidateSet("Manual", "Automatic")][string]$SshdStart = "Automatic"  # the start mode the user chose for sshd
)

$ErrorActionPreference = "Continue"  # native tools write progress to stderr; exit codes are checked explicitly
$root = $PSScriptRoot
$short = $Sha.Substring(0, 12)
$res = Join-Path $root "results-$short"
$run = Join-Path $root "run-$short"
$bundlePath = Join-Path $root $Bundle
$pyList = @($Pythons -split '\s+' | Where-Object { $_ })
$warnings = New-Object System.Collections.Generic.List[string]
$rows = New-Object System.Collections.Generic.List[object]
$utf8 = New-Object System.Text.UTF8Encoding $false

if (Test-Path $res) { Remove-Item -Recurse -Force $res }
New-Item -ItemType Directory -Force $res | Out-Null

function Write-Summary([string[]]$Lines) {
    # UTF-8 without BOM (Tee-Object / Out-File in PowerShell 5.1 would write UTF-16)
    [System.IO.File]::WriteAllLines((Join-Path $res "summary.txt"), $Lines, $utf8)
    $Lines | ForEach-Object { Write-Output $_ }
}

function Stop-Early([string]$Message) {
    $lines = @("commit $Sha", "error: $Message") + @($warnings | ForEach-Object { "warning: $_" }) + @("RESULT: FAILED")
    Write-Summary $lines
    exit 2
}

function Invoke-Logged {
    # Run a program without a shell, wait, append stdout+stderr to $Log, return the exit code (-1 if it did not start).
    param([string]$File, [string[]]$ArgList, [string]$Log, [string]$WorkDir = $root)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $File
    $quoted = foreach ($a in $ArgList) { if ($a -match '[\s"]') { '"' + ($a -replace '"', '\"') + '"' } else { $a } }
    $psi.Arguments = ($quoted -join " ")
    $psi.WorkingDirectory = $WorkDir
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    try {
        $p = [System.Diagnostics.Process]::Start($psi)
        $out = $p.StandardOutput.ReadToEndAsync()
        $err = $p.StandardError.ReadToEndAsync()
        $p.WaitForExit()
        $text = "> $File $($psi.Arguments)`r`n" + $out.Result + "`r`n--- stderr ---`r`n" + $err.Result + "`r`n"
        $code = $p.ExitCode
    } catch {
        $text = "> $File $($psi.Arguments)`r`ncould not start: $($_.Exception.Message)`r`n"
        $code = -1
    }
    [System.IO.File]::AppendAllText($Log, $text, $utf8)
    if ($null -eq $code) { return -1 }
    return [int]$code
}

function Read-ExitFile([string]$Path) {
    # An exit code written by linux_test.sh; -1 if the file is missing, empty or not a number.
    if (-not (Test-Path $Path)) { return -1 }
    $t = [string](Get-Content $Path -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($t -match '^\s*(-?\d+)\s*$') { return [int]$Matches[1] }
    return -1
}

function Read-JUnit([string]$Path) {
    # @(tests, failures, errors, skipped) from a pytest --junitxml file, or $null if it is missing or unreadable.
    if (-not (Test-Path $Path)) { return $null }
    try {
        [xml]$x = Get-Content -Raw -Encoding UTF8 $Path
        $suite = $x.SelectSingleNode("//testsuite")
        return @([int]$suite.tests, [int]$suite.failures, [int]$suite.errors, [int]$suite.skipped)
    } catch { return $null }
}

function Read-Versions([string]$Path) {
    # The line the version probe marks with "VERSIONS:" (other output such as warnings is ignored).
    if (-not (Test-Path $Path)) { return "" }
    $line = Get-Content $Path | Where-Object { $_ -like "VERSIONS:*" } | Select-Object -First 1
    if ($line) { return $line.Substring(9).Trim() }
    return ""
}

function Add-Row([string]$Name, [int]$Exit, [string]$Xml, [string]$Versions) {
    $j = Read-JUnit $Xml
    if ($null -eq $j) { $j = @(0, 0, 0, 0) }
    $ok = ($Exit -eq 0) -and ($j[0] -gt 0) -and ($j[1] -eq 0) -and ($j[2] -eq 0) -and ($j[3] -eq 0)
    $rows.Add([pscustomobject]@{ Env = $Name; Exit = $Exit; Tests = $j[0]; Failed = $j[1]; Errors = $j[2];
                                 Skipped = $j[3]; Ok = $ok; Versions = $Versions })
}

# -- security self-check (warnings only; see the guide) --------------------------------------------------------
# sshd uses the first value it reads, and lines after the first "Match" only apply inside that block, so only the
# global part before it counts.
try {
    $global = @()
    foreach ($line in (Get-Content -ErrorAction Stop (Join-Path $env:ProgramData "ssh\sshd_config"))) {
        if ($line -match '^\s*Match\b') { break }
        $global += $line
    }
    $pw = $global | Where-Object { $_ -match '^\s*PasswordAuthentication\s+\S' } | Select-Object -First 1
    if (-not $pw -or $pw -notmatch '^\s*PasswordAuthentication\s+no\b') {
        $warnings.Add("sshd_config: the first global PasswordAuthentication is not 'no' (password logins may be allowed)")
    }
    if (-not ($global | Where-Object { $_ -match '^\s*AllowUsers\s+\S' })) {
        $warnings.Add("sshd_config: no global AllowUsers line (any local account may log in)")
    }
} catch { $warnings.Add("sshd_config could not be read, so it was not checked") }
try {
    $rule = Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction Stop
    $addr = @(($rule | Get-NetFirewallAddressFilter).RemoteAddress)
    if ($addr -contains "Any") { $warnings.Add("firewall rule OpenSSH-Server-In-TCP accepts any remote address") }
    if ([string]$rule.Profile -match "Public|Any") { $warnings.Add("firewall rule OpenSSH-Server-In-TCP also applies to public networks") }
} catch { $warnings.Add("firewall rule OpenSSH-Server-In-TCP not found or not readable") }
try {
    $mode = [string](Get-Service sshd -ErrorAction Stop).StartType
    if ($mode -ne $SshdStart) { $warnings.Add("sshd starts '$mode', expected '$SshdStart' (COAT_TEST_SSHD_START on the Mac)") }
} catch { }
if ($env:PYTHONUTF8) {
    $warnings.Add("PYTHONUTF8 was set ($env:PYTHONUTF8); it was cleared so encoding bugs are not hidden")
    Remove-Item Env:PYTHONUTF8
}

# -- tools (an ssh logon may not see PATH entries added after sshd started, so try the usual install places) ------
# WinGet\Links holds symbolic links, and Windows refuses to start a program through one from an ssh (service)
# logon ("untrusted mount point"): prefer real files and resolve any link to its target.
$extra = @((Join-Path $env:USERPROFILE ".local\bin"), (Join-Path $env:ProgramFiles "Git\cmd"),
           (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"))
$env:Path = (($extra | Where-Object { Test-Path $_ }) + @($env:Path)) -join ";"

function Resolve-Tool([string]$Name) {
    foreach ($c in @(Get-Command $Name -All -CommandType Application -ErrorAction SilentlyContinue)) {
        $item = Get-Item -LiteralPath $c.Source -ErrorAction SilentlyContinue
        if ($null -eq $item) { continue }
        # Only symbolic links need resolving.  A hard link is the file itself (Git for Windows installs git.exe as
        # one, and its "Target" lists the file's other names, such as git-lfs.exe: following it ran the wrong tool).
        if ($item.LinkType -ne "SymbolicLink") { return $item.FullName }
        $target = @($item.Target)[0]
        if ($target) {
            if (-not [System.IO.Path]::IsPathRooted($target)) { $target = Join-Path $item.DirectoryName $target }
            if (Test-Path -LiteralPath $target) { return (Get-Item -LiteralPath $target).FullName }
        }
    }
    return $null
}
$git = Resolve-Tool "git"
$uv = Resolve-Tool "uv"
if (-not $git) { Stop-Early "missing tool on Windows: git (see docs/WINDOWS_WSL_TESTING.md)" }
if (-not $uv) { Stop-Early "missing tool on Windows: uv (see docs/WINDOWS_WSL_TESTING.md)" }

# -- checkout (a fresh folder per commit; keep the three newest) ------------------------------------------------
if (Test-Path $run) { Remove-Item -Recurse -Force $run }
$clog = Join-Path $res "checkout.log"
$c = Invoke-Logged $git @("-c", "core.autocrlf=false", "clone", "--no-checkout", "--quiet", $bundlePath, $run) $clog
if ($c -eq 0) { $c = Invoke-Logged $git @("-c", "core.autocrlf=false", "-C", $run, "checkout", "--quiet", "--detach", $Sha) $clog }
if ($c -ne 0) { Stop-Early "checkout of $Sha failed; see checkout.log" }
Get-ChildItem $root -Directory -Filter "run-*" | Sort-Object LastWriteTime -Descending | Select-Object -Skip 3 |
    ForEach-Object { Remove-Item -Recurse -Force $_.FullName }

# -- Windows ----------------------------------------------------------------------------------------------------
$env:QT_QPA_PLATFORM = "offscreen"
$versionsCode = "import sys, numpy, scipy, matplotlib, PySide6; print('VERSIONS:', sys.version.split()[0], 'numpy', numpy.__version__, 'scipy', scipy.__version__, 'matplotlib', matplotlib.__version__, 'PySide6', PySide6.__version__)"
foreach ($py in $pyList) {
    $log = Join-Path $res "win-$py.log"
    $venv = Join-Path $root "venv-win-$py"  # reused between runs; only the project is reinstalled
    $python = Join-Path $venv "Scripts\python.exe"
    $exit = 0
    # a venv whose base Python was removed or upgraded still has python.exe but cannot start: rebuild it
    if ((Test-Path $python) -and ((Invoke-Logged $python @("-c", "import sys") $log) -ne 0)) {
        Remove-Item -Recurse -Force $venv
    }
    if (-not (Test-Path $python)) { $exit = Invoke-Logged $uv @("venv", "--quiet", "--python", $py, $venv) $log }
    if ($exit -eq 0) {
        # --upgrade: newest wheels each run, as CI installs them
        $exit = Invoke-Logged $uv @("pip", "install", "--quiet", "--upgrade", "--python", $python, "-e", "$run[dev]") $log
    }
    $versions = ""
    if ($exit -eq 0) {
        $vlog = Join-Path $res "win-$py.versions"
        Invoke-Logged $python @("-c", $versionsCode) $vlog | Out-Null
        $versions = Read-Versions $vlog
        $exit = Invoke-Logged $python @("-m", "pytest", "-n", "auto", "-q", "-rs", "-p", "no:cacheprovider", "--junitxml",
                                        (Join-Path $res "win-$py.xml")) $log $run
    }
    Add-Row "Windows Python $py" $exit (Join-Path $res "win-$py.xml") $versions
}

# -- Linux (WSL) ------------------------------------------------------------------------------------------------
function ConvertTo-WslPath([string]$p) {  # C:\Users\x -> /mnt/c/Users/x (default automount root)
    return "/mnt/" + $p.Substring(0, 1).ToLower() + ($p.Substring(2) -replace '\\', '/')
}
$env:WSL_UTF8 = "1"  # wsl.exe's own messages in UTF-8 instead of UTF-16, so wsl.log stays readable
$wlog = Join-Path $res "wsl.log"
$distroArgs = @()
if ($Distro) { $distroArgs = @("-d", $Distro) }
$distroName = $Distro
if (-not $distroName) { $distroName = "default" }
$wexit = Invoke-Logged "wsl.exe" ($distroArgs + @("-e", "bash", (ConvertTo-WslPath (Join-Path $root "linux_test.sh")),
                                   (ConvertTo-WslPath $bundlePath), $Sha, (ConvertTo-WslPath $res), $Pythons)) $wlog
if ($wexit -ne 0) { $warnings.Add("wsl.exe exited with $wexit; see wsl.log (a key-only ssh logon can stop wsl.exe from starting)") }
foreach ($py in $pyList) {
    Add-Row "Linux (WSL $distroName) Python $py" (Read-ExitFile (Join-Path $res "linux-$py.exit")) `
        (Join-Path $res "linux-$py.xml") (Read-Versions (Join-Path $res "linux-$py.versions"))
}
$lw = Join-Path $res "linux-warnings.txt"
if (Test-Path $lw) { Get-Content $lw | ForEach-Object { $warnings.Add("linux: $_") } }

# -- summary ----------------------------------------------------------------------------------------------------
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("commit $Sha")
foreach ($r in $rows) {
    $verdict = "FAIL"
    if ($r.Ok) { $verdict = "ok" }
    $lines.Add(("{0,-32} {1,-4} exit={2} tests={3} failed={4} errors={5} skipped={6}  {7}" -f $r.Env, $verdict,
                $r.Exit, $r.Tests, $r.Failed, $r.Errors, $r.Skipped, $r.Versions))
}
foreach ($w in $warnings) { $lines.Add("warning: $w") }
$allOk = ($rows.Count -eq 2 * $pyList.Count) -and -not ($rows | Where-Object { -not $_.Ok })
if ($allOk) { $lines.Add("RESULT: all environments passed") } else { $lines.Add("RESULT: FAILED") }
Write-Summary $lines.ToArray()
if ($allOk) { exit 0 } else { exit 1 }
