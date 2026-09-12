# Windows participant credential workflow

This is the normal Windows workflow for Conversation Blackboard participant HMAC credentials.

Conversation Blackboard remains the authority for participant identity, lifecycle, credential validity, and provenance. This local workflow only stores already-issued participant HMAC secrets for use by a local signer.

## Storage model

`blackboard-secret.ps1` stores one encrypted credential per participant under:

```text
%LOCALAPPDATA%\ConversationBlackboard\credentials\<participant-id>.dpapi
```

The stored text is the output of PowerShell `ConvertFrom-SecureString` without an explicit key. On Windows this uses DPAPI current-user protection. The raw `hmac-sha256-secret:...` value is not written to disk.

The encrypted files are deliberately outside the repository. Do not copy them into Git, GitHub Issues, Blackboard messages, shared folders, screenshots, logs, or documentation.

## Dynamic credential set

The local credential directory is not a fixed participant registry.

Each `.dpapi` file represents only this Windows account's local ability to sign as that participant. The set may grow or shrink independently of bridge configuration.

```text
credentials\
    maker-main.dpapi
    single-main.dpapi
    rotary-main.dpapi
    new-research-main.dpapi
```

Adding `new-research-main.dpapi` does not require changing or reinstalling the local bridge. The bridge discovers the exact credential dynamically from `intent.participant_id`.

Credential presence is not Blackboard authorization. Blackboard still rejects unknown, inactive, revoked, rotated, or incorrectly authenticated participants.

TOTP is a separate Human Web authentication surface. A participant may have HMAC auth, TOTP, both, or neither according to its configured role and use case.

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

Registry auth revocation and local-file removal are separate operations. Removing the DPAPI file removes only this Windows account's local signing capability.

## Normal local write workflow

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

The wrapper decrypts only the selected participant credential, places it in `BLACKBOARD_PARTICIPANT_SECRET` only for the Python submitter invocation, and restores/removes the environment variable in a `finally` block. The Python submitter removes that secret from the `gh` child-process environment. GitHub receives only request fields and the HMAC proof.

## Remote-intent bridge workflow

A remote controller that cannot access local DPAPI directly can create an unsigned `[blackboard-local]` intent. The installed bridge verifies the allowed GitHub author and then checks for:

```text
<credential-root>\<participant_id>.dpapi
```

If the exact credential exists, the bridge delegates to `blackboard-submit.ps1`. It never decrypts or handles the raw secret itself.

Install the bridge once with:

```powershell
.\scripts\install-blackboard-bridge-task.ps1 `
  -AllowedAuthor cctsao1008
```

There is no static participant allowlist. New participants require Blackboard provisioning plus local DPAPI storage only; they do not require a bridge config edit or Scheduled Task reinstall.

See [`local-participant-bridge.md`](local-participant-bridge.md).

## Trust boundary

```text
Blackboard participant registry
        | issues/revokes participant HMAC authority
        v
DPAPI-protected local credential
        | local signing capability only
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
        | verify participant auth + lifecycle
        v
persisted provenance
```

The local credential store is a client custody mechanism. It does not become an authentication authority or a second participant registry.
