param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('set', 'test', 'remove', 'path')]
    [string]$Operation,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$')]
    [string]$ParticipantId,

    [string]$Secret,

    [string]$CredentialRoot = $(Join-Path $env:LOCALAPPDATA 'ConversationBlackboard\credentials')
)

$ErrorActionPreference = 'Stop'
$SecretPrefix = 'hmac-sha256-secret:'

function Get-CredentialPath {
    param([string]$Id)
    if (-not $CredentialRoot) {
        throw 'LOCALAPPDATA is not available; specify -CredentialRoot explicitly.'
    }
    return Join-Path $CredentialRoot ($Id + '.dpapi')
}

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

function Assert-SecretFormat {
    param([string]$Value)
    if (-not $Value.StartsWith($SecretPrefix)) {
        throw "participant secret must start with $SecretPrefix"
    }
    $encoded = $Value.Substring($SecretPrefix.Length)
    if ($encoded -notmatch '^[A-Za-z0-9_-]+$' -or $encoded.Contains('=')) {
        throw 'participant secret must contain unpadded base64url material'
    }
    $padded = $encoded + ('=' * ((4 - ($encoded.Length % 4)) % 4))
    try {
        $bytes = [Convert]::FromBase64String($padded.Replace('-', '+').Replace('_', '/'))
    }
    catch {
        throw 'participant secret contains invalid base64url material'
    }
    if ($bytes.Length -ne 32) {
        throw 'participant secret must encode exactly 32 bytes'
    }
}

$credentialPath = Get-CredentialPath -Id $ParticipantId

switch ($Operation) {
    'path' {
        Write-Output $credentialPath
        break
    }

    'set' {
        if (-not (Test-Path -LiteralPath $CredentialRoot)) {
            New-Item -ItemType Directory -Path $CredentialRoot -Force | Out-Null
        }

        $secure = $null
        if ($Secret) {
            Assert-SecretFormat -Value $Secret
            $secure = ConvertTo-SecureString -String $Secret -AsPlainText -Force
        }
        elseif ($env:BLACKBOARD_PARTICIPANT_SECRET) {
            Assert-SecretFormat -Value $env:BLACKBOARD_PARTICIPANT_SECRET
            $secure = ConvertTo-SecureString -String $env:BLACKBOARD_PARTICIPANT_SECRET -AsPlainText -Force
        }
        else {
            $secure = Read-Host "HMAC secret for $ParticipantId" -AsSecureString
            $plain = Convert-SecureStringToPlainText -Secure $secure
            try {
                Assert-SecretFormat -Value $plain
            }
            finally {
                $plain = $null
            }
        }

        $encrypted = ConvertFrom-SecureString -SecureString $secure
        Set-Content -LiteralPath $credentialPath -Value $encrypted -Encoding UTF8 -NoNewline
        Write-Output "stored: $ParticipantId"
        Write-Output "path: $credentialPath"
        break
    }

    'test' {
        if (-not (Test-Path -LiteralPath $credentialPath)) {
            throw "credential not found for $ParticipantId"
        }
        $encrypted = (Get-Content -LiteralPath $credentialPath -Raw).Trim()
        $secure = ConvertTo-SecureString -String $encrypted
        $plain = Convert-SecureStringToPlainText -Secure $secure
        try {
            Assert-SecretFormat -Value $plain
        }
        finally {
            $plain = $null
        }
        Write-Output "ok: $ParticipantId"
        break
    }

    'remove' {
        if (Test-Path -LiteralPath $credentialPath) {
            Remove-Item -LiteralPath $credentialPath -Force
            Write-Output "removed: $ParticipantId"
        }
        else {
            Write-Output "not-found: $ParticipantId"
        }
        break
    }
}
