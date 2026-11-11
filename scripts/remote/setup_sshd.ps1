# One-time, hardened OpenSSH server setup on the Windows test machine.  Run it yourself in an *administrator*
# PowerShell after reading it; see docs/WINDOWS_WSL_TESTING.md.  Safe to run again.
#
#   powershell -ExecutionPolicy Bypass -File setup_sshd.ps1 -User <account> -MacIp 192.168.0.23 -PublicKey "ssh-ed25519 AAAA... coat-win"
#   (-MacIp LocalSubnet: accept any address of the local subnet, for a Mac whose DHCP address changes)
#
# -User is the account the Mac logs in as (the one whose WSL distro runs the Linux tests).  It is required: in an
# elevated PowerShell started with another administrator's credentials, $env:USERNAME is that other account.
# Keep this file ASCII (Windows PowerShell 5.1 reads a .ps1 without BOM in the ANSI code page).
#
# What it does:
#   - installs the OpenSSH Server capability and sets how sshd starts (-StartMode: Automatic, the default, or
#     Manual to keep it off except while testing); sshd is restarted (Automatic) or left stopped (Manual) so that
#     it reads the new settings
#   - sshd_config: key login only (PasswordAuthentication no), only -User may log in (AllowUsers); the old file is
#     kept as sshd_config.bak-<time> and restored if `sshd -t` rejects the new one
#   - firewall: the sshd rule accepts only -MacIp (one address, or the keyword LocalSubnet), on private networks only
#   - adds -PublicKey to the right authorized_keys file (administrators_authorized_keys for administrators), saved
#     without a BOM and readable only by its owner(s); UTF-16 or loose permissions make sshd ignore the key
param(
    [Parameter(Mandatory = $true)][string]$MacIp,
    [Parameter(Mandatory = $true)][string]$PublicKey,
    [Parameter(Mandatory = $true)][string]$User,
    [ValidateSet("Automatic", "Manual")][string]$StartMode = "Automatic"  # Manual: on only while testing
)
$ErrorActionPreference = "Stop"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this in an administrator PowerShell."
}
if ($PublicKey -notmatch '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-\S+) \S+') { throw "-PublicKey does not look like a public key line" }
if ($MacIp -ne "LocalSubnet") { [void][System.Net.IPAddress]::Parse($MacIp) }
if ($User -match '\s') { throw "Account names with spaces cannot be written to AllowUsers safely; use another account." }
$userSid = (New-Object Security.Principal.NTAccount($User)).Translate([Security.Principal.SecurityIdentifier]).Value
if ($User -ne $env:USERNAME) { Write-Warning "Setting up '$User' while running as '$env:USERNAME'." }

# 1. OpenSSH Server, manual start
$cap = Get-WindowsCapability -Online -Name "OpenSSH.Server*"
if ($cap.State -ne "Installed") { Add-WindowsCapability -Online -Name $cap.Name | Out-Null }
Set-Service -Name sshd -StartupType $StartMode
$cfgPath = Join-Path $env:ProgramData "ssh\sshd_config"
if (-not (Test-Path $cfgPath)) { Start-Service sshd; Stop-Service sshd }  # the first start writes the default file

# 2. sshd_config: our directives go at the top, before any Match block (sshd uses the first value it reads, and
#    lines after "Match" only apply inside that block).  Earlier copies of these directives are removed.
$backup = "$cfgPath.bak-" + (Get-Date -Format "yyyyMMdd-HHmmss")
Copy-Item $cfgPath $backup
$marker = "# coat-test hardening (scripts/remote/setup_sshd.ps1)"
$old = Get-Content $cfgPath | Where-Object {
    $_ -ne $marker -and $_ -notmatch '^\s*#?\s*(PasswordAuthentication|PubkeyAuthentication|AllowUsers|KbdInteractiveAuthentication|PermitEmptyPasswords)\b'
}
$new = @($marker, "PubkeyAuthentication yes", "PasswordAuthentication no", "KbdInteractiveAuthentication no",
         "PermitEmptyPasswords no", "AllowUsers $($User.ToLower())", "") + $old
[System.IO.File]::WriteAllLines($cfgPath, $new, (New-Object System.Text.UTF8Encoding $false))
$sshd = Join-Path $env:WINDIR "System32\OpenSSH\sshd.exe"
& $sshd -t
if ($LASTEXITCODE -ne 0) {
    Copy-Item $backup $cfgPath -Force
    throw "sshd -t rejected the new sshd_config; the old one was restored"
}

# 3. Firewall: only the Mac (or the local subnet), only on private networks
$rule = Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue
if (-not $rule) {
    New-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -DisplayName "OpenSSH SSH Server (sshd)" -Direction Inbound `
        -Protocol TCP -LocalPort 22 -Action Allow | Out-Null
}
Set-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -Enabled True -Profile Private -RemoteAddress $MacIp
$profiles = Get-NetConnectionProfile | Select-Object -ExpandProperty NetworkCategory
if ($profiles -notcontains "Private") {
    Write-Warning "No network is set to Private, so the rule will not let the Mac in. Set the home network to Private."
}

# 4. Public key
# Is -User a direct member of the local Administrators group?  Compared by SID: the group name depends on the
# Windows language, and member names need not match the account name (Microsoft accounts).  sshd decides the same
# way (Match Group administrators), and a key in the wrong file means no login at all once passwords are off.
$adminGroup = (New-Object Security.Principal.SecurityIdentifier("S-1-5-32-544")).Translate(
    [Security.Principal.NTAccount]).Value.Split("\")[-1]
$memberSids = @(([ADSI]"WinNT://./$adminGroup,group").Invoke("Members") | ForEach-Object {
    $bytes = $_.GetType().InvokeMember("objectSid", "GetProperty", $null, $_, $null)
    (New-Object Security.Principal.SecurityIdentifier($bytes, 0)).Value
})
$isAdmin = $memberSids -contains $userSid
if ($isAdmin) {
    $keyFile = Join-Path $env:ProgramData "ssh\administrators_authorized_keys"
    $grants = @("*S-1-5-32-544:F", "*S-1-5-18:F")      # Administrators, SYSTEM (SIDs work in any Windows language)
} else {
    $profileDir = (Get-CimInstance Win32_UserProfile | Where-Object { $_.SID -eq $userSid } |
                   Select-Object -First 1).LocalPath  # by SID: the folder name can differ from the account name
    if (-not $profileDir) { throw "profile folder of $User not found" }
    $sshDir = Join-Path $profileDir ".ssh"
    New-Item -ItemType Directory -Force $sshDir | Out-Null
    $keyFile = Join-Path $sshDir "authorized_keys"
    $grants = @("${User}:F", "*S-1-5-18:F")
}
$keys = @()
if (Test-Path $keyFile) { $keys = @(Get-Content $keyFile | Where-Object { $_.Trim() -ne "" }) }
if ($keys -notcontains $PublicKey.Trim()) { $keys += $PublicKey.Trim() }
[System.IO.File]::WriteAllLines($keyFile, $keys, (New-Object System.Text.UTF8Encoding $false))
$icaclsArgs = @($keyFile, "/inheritance:r") + ($grants | ForEach-Object { @("/grant", $_) })
& icacls @icaclsArgs | Out-Null
if ($LASTEXITCODE -ne 0) { throw "icacls failed on $keyFile" }

# Restart (Automatic) or stop (Manual) sshd: a running sshd keeps the settings it started with.
Stop-Service sshd -ErrorAction SilentlyContinue
if ($StartMode -eq "Automatic") { Start-Service sshd }
Write-Output "Done. sshd: $StartMode start, now $((Get-Service sshd).Status). Key file: $keyFile. Backup: $backup"
Write-Output "If the Mac cannot log in, restore the old settings: Copy-Item '$backup' '$cfgPath' -Force"
if ($StartMode -eq "Manual") { Write-Output "Before a test run: Start-Service sshd    After it: Stop-Service sshd" }
