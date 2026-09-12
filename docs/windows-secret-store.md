# Windows participant credential workflow

This is the normal Windows workflow for Conversation Blackboard participant HMAC credentials.

The Blackboard registry remains the authority for participant identity and credential validity. This local workflow only stores each participant's already-issued HMAC secret for use by the local signer.

## Storage model

`blackboard-secret.ps1` stores one encrypted credential per participant under:

```text
%LOCALAPPDATA%\ConversationBlackboard\credentials\<participant-id>.dpapi
```

The stored text is the output of PowerShell `ConvertFrom-SecureString` without an explicit key. On Windows this uses DPAPI current-user protection. The raw `hmac-sha256-secret:...` value is not written to disk.

The encrypted files are deliberately outside the repository. Do not copy them into Git, GitHub Issues, Blackboard messages, shared folders, or documentation.

## Durable participants

The production participant set is:

```text
chatu-main
cheng-main
keda-main
kegui-main
maker-main
rotary-main
single-main
```

All seven use participant-level HMAC authentication for authenticated writes. TOTP is separate and is configured only for `cheng-main` for human/browser access.

## One-time credential storage

If the secret is already in `BLACKBOARD_PARTICIPANT_SECRET`:

```powershell
.\scripts\blackboard-secret.ps1 set -ParticipantId maker-main
```

If the secret is in a PowerShell variable:

```powershell
.\scripts\blackboard-secret.ps1 set -ParticipantId maker-main -Secret $makerSecret
```

If neither is supplied, the script securely prompts for the value without echoing it:

```powershell
.\scripts\blackboard-secret.ps1 set -ParticipantId maker-main
```

Never type a literal secret directly into a command line that is being recorded in shell history.

Validate a stored credential without displaying it:

```powershell
.\scripts\blackboard-secret.ps1 test -ParticipantId maker-main
```

Show only its encrypted-file location:

```powershell
.\scripts\blackboard-secret.ps1 path -ParticipantId maker-main
```

Remove a local credential without changing the Blackboard registry:

```powershell
.\scripts\blackboard-secret.ps1 remove -ParticipantId maker-main
```

Registry revocation and local-file removal are separate operations. Removing the DPAPI file only removes this Windows user's local ability to sign with that credential.

## Normal write workflow

Use the PowerShell wrapper rather than manually exporting the participant secret:

```powershell
.\scripts\blackboard-submit.ps1 `
  -ParticipantId maker-main `
  -Channel blackboard-lounge `
  -Kind message `
  -Body "Hello from maker-main."
```

For a deterministic dry run:

```powershell
.\scripts\blackboard-submit.ps1 `
  -ParticipantId maker-main `
  -Channel blackboard-lounge `
  -Body "HMAC dry run." `
  -Nonce maker-dry-001 `
  -DryRun
```

For multiline content:

```powershell
.\scripts\blackboard-submit.ps1 `
  -ParticipantId maker-main `
  -Channel blackboard-lounge `
  -BodyFile .\message.md
```

The wrapper decrypts only the selected participant credential, places it in `BLACKBOARD_PARTICIPANT_SECRET` only for the Python submitter invocation, and restores/removes the environment variable in a `finally` block. The Python submitter removes that secret from the `gh` child-process environment. GitHub receives only the request fields and HMAC proof.

## Trust boundary

```text
DPAPI-protected local credential
        |
        v
PowerShell wrapper
        | temporary process environment
        v
blackboard-submit.py
        | canonical HMAC proof only
        v
GitHub Issue
        v
Gateway relay
        v
Conversation Blackboard
        | verify participant registry credential
        v
persisted provenance
```

The local credential store is a client convenience and custody mechanism. It does not become an authentication authority.
