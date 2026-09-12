param(
    [Parameter(Mandatory = $true)]
    [string]$AllowedAuthor,

    [string]$Repository = 'cctsao1008/conversation-blackboard-gateway',
    [string]$TaskName = 'ConversationBlackboardLocalBridge',
    [string]$CredentialRoot = $(Join-Path $env:LOCALAPPDATA 'ConversationBlackboard\credentials')
)

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$bridgeScript = Join-Path $scriptDir 'blackboard-bridge.py'
if (-not (Test-Path -LiteralPath $bridgeScript)) {
    throw "bridge script not found: $bridgeScript"
}
if (-not $CredentialRoot) {
    throw 'LOCALAPPDATA is not available; specify -CredentialRoot explicitly.'
}

$python = (Get-Command python -ErrorAction Stop).Source
$gh = (Get-Command gh -ErrorAction Stop).Source
$powershell = (Get-Command powershell.exe -ErrorAction SilentlyContinue).Source
if (-not $powershell) {
    $powershell = (Get-Command pwsh.exe -ErrorAction Stop).Source
}
$wscript = Join-Path $env:WINDIR 'System32\wscript.exe'
if (-not (Test-Path -LiteralPath $wscript)) {
    throw "wscript.exe not found: $wscript"
}

$stateRoot = Join-Path $env:LOCALAPPDATA 'ConversationBlackboard\bridge'
New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
$configPath = Join-Path $stateRoot 'bridge.json'
$runnerPath = Join-Path $stateRoot 'run-bridge.ps1'
$launcherPath = Join-Path $stateRoot 'run-bridge-hidden.vbs'

$config = [ordered]@{
    repository = $Repository
    allowed_author = $AllowedAuthor
    credential_root = $CredentialRoot
    bridge_script = $bridgeScript
    python = $python
    gh = $gh
    powershell = $powershell
    repository_root = $repoRoot
}
$config | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $configPath -Encoding UTF8

$runner = @'
$ErrorActionPreference = 'Stop'
$configPath = '__CONFIG_PATH__'
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json

$env:PATH = (Split-Path -Parent $config.gh) + ';' + $env:PATH
$args = @(
    $config.bridge_script,
    '--repository', $config.repository,
    '--allowed-author', $config.allowed_author,
    '--credential-root', $config.credential_root
)

& $config.python @args
exit $LASTEXITCODE
'@
$runner = $runner.Replace('__CONFIG_PATH__', $configPath.Replace("'", "''"))
$runner | Set-Content -LiteralPath $runnerPath -Encoding UTF8

$escapedPowerShell = $powershell.Replace('"', '""')
$escapedRunner = $runnerPath.Replace('"', '""')
$launcher = @"
Set shell = CreateObject("WScript.Shell")
command = """$escapedPowerShell"" -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File ""$escapedRunner"""
result = shell.Run(command, 0, True)
WScript.Quit result
"@
$launcher | Set-Content -LiteralPath $launcherPath -Encoding ASCII

$action = New-ScheduledTaskAction `
    -Execute $wscript `
    -Argument ('//B //Nologo "' + $launcherPath + '"')

$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$principal = New-ScheduledTaskPrincipal `
    -UserId ("$env:USERDOMAIN\$env:USERNAME") `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Description 'Processes authorized Conversation Blackboard local write intents.' `
    -Force | Out-Null

Write-Output "installed: $TaskName"
Write-Output "config: $configPath"
Write-Output "runner: $runnerPath"
Write-Output "launcher: $launcherPath"
Write-Output ("allowed author: " + $AllowedAuthor)
Write-Output ("credential root: " + $CredentialRoot)
Write-Output 'participant discovery: dynamic from local DPAPI credentials'
Write-Output 'cadence: once per minute while this Windows user is logged on'
Write-Output 'window mode: background only (wscript host + hidden PowerShell)'
