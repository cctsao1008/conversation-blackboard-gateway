param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$')]
    [string]$ParticipantId,

    [Parameter(Mandatory = $true)]
    [string]$Channel,

    [string]$Kind = 'message',
    [string]$Body,
    [string]$BodyFile,
    [int]$ReplyTo,
    [string]$Nonce,
    [switch]$DryRun,
    [string]$Repository = 'cctsao1008/conversation-blackboard-gateway',
    [string]$CredentialRoot = $(Join-Path $env:LOCALAPPDATA 'ConversationBlackboard\credentials')
)

$ErrorActionPreference = 'Stop'
$SecretPrefix = 'hmac-sha256-secret:'

function Convert-SecureStringToPlainText {
    param([Security.SecureString]$Secure)
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

if (-not $CredentialRoot) {
    throw 'LOCALAPPDATA is not available; specify -CredentialRoot explicitly.'
}

$credentialPath = Join-Path $CredentialRoot ($ParticipantId + '.dpapi')
if (-not (Test-Path -LiteralPath $credentialPath)) {
    throw "credential not found for $ParticipantId at $credentialPath"
}

$encrypted = (Get-Content -LiteralPath $credentialPath -Raw).Trim()
$secure = ConvertTo-SecureString -String $encrypted
$secret = Convert-SecureStringToPlainText -Secure $secure
if (-not $secret.StartsWith($SecretPrefix)) {
    $secret = $null
    throw 'stored participant credential has an invalid secret format'
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonSubmitter = Join-Path $scriptDir 'blackboard-submit.py'
if (-not (Test-Path -LiteralPath $pythonSubmitter)) {
    $secret = $null
    throw "Python submitter not found: $pythonSubmitter"
}

if (-not $Body -and -not $BodyFile) {
    $secret = $null
    throw 'specify either -Body or -BodyFile'
}
if ($Body -and $BodyFile) {
    $secret = $null
    throw 'specify only one of -Body or -BodyFile'
}

$arguments = @(
    $pythonSubmitter,
    '--participant-id', $ParticipantId,
    '--channel', $Channel,
    '--kind', $Kind,
    '--repository', $Repository
)

if ($BodyFile) {
    $arguments += @('--body-file', $BodyFile)
}
else {
    $arguments += @('--body', $Body)
}
if ($PSBoundParameters.ContainsKey('ReplyTo')) {
    $arguments += @('--reply-to', $ReplyTo.ToString())
}
if ($Nonce) {
    $arguments += @('--nonce', $Nonce)
}
if ($DryRun) {
    $arguments += '--dry-run'
}

$previousSecret = $env:BLACKBOARD_PARTICIPANT_SECRET
try {
    $env:BLACKBOARD_PARTICIPANT_SECRET = $secret
    & python @arguments
    $exitCode = $LASTEXITCODE
}
finally {
    if ($null -eq $previousSecret) {
        Remove-Item Env:BLACKBOARD_PARTICIPANT_SECRET -ErrorAction SilentlyContinue
    }
    else {
        $env:BLACKBOARD_PARTICIPANT_SECRET = $previousSecret
    }
    $secret = $null
}

exit $exitCode
