param(
    [Parameter(Mandatory = $true)]
    [string]$AllowedAuthor,

    [Parameter(Mandatory = $true)]
    [string[]]$ParticipantId,

    [string]$Repository = 'cctsao1008/conversation-blackboard-gateway',
    [string]$TaskName = 'ConversationBlackboardLocalBridge'
)

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$bridgeScript = Join-Path $scriptDir 'blackboard-bridge.py'
if (-not (Test-Path -LiteralPath $bridgeScript)) {
    throw "bridge script not found: $bridgeScript"
}

$python = (Get-Command python -ErrorAction Stop).Source
$gh = (Get-Command gh -ErrorAction Stop).Source
$powershell = (Get-Command powershell.exe -ErrorAction SilentlyContinue).Source
if (-not $powershell) {
    $powershell = (Get-Command pwsh.exe -ErrorAction Stop).Source
}

$stateRoot = Join-Path $env:LOCALAPPDATA 'ConversationBlackboard\bridge'
New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
$configPath = Join-Path $stateRoot 'bridge.json'
$runnerPath = Join-Path $stateRoot 'run-bridge.ps1'

$config = [ordered]@{
    repository = $Repository
    allowed_author = $AllowedAuthor
    participants = @($ParticipantId)
    bridge_script = $bridgeScript
    python = $python
    gh = $gh
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
    '--allowed-author', $config.allowed_author
)
foreach ($participant in $config.participants) {
    $args += @('--participant', [string]$participant)
}

& $config.python @args
exit $LASTEXITCODE
'@
$runner = $runner.Replace('__CONFIG_PATH__', $configPath.Replace("'", "''"))
$runner | Set-Content -LiteralPath $runnerPath -Encoding UTF8

$action = New-ScheduledTaskAction `
    -Execute $powershell `
    -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $runnerPath + '"')

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
Write-Output ("allowed author: " + $AllowedAuthor)
Write-Output ("participants: " + (($ParticipantId | Sort-Object -Unique) -join ', '))
Write-Output 'cadence: once per minute while this Windows user is logged on'
