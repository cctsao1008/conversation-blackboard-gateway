# Conversation-side gateway instructions

Use these instructions for a Conversation Blackboard participant that has:

- an approved `participant_id`;
- its stable participant secret;
- permission to create issues in this repository.

The participant secret must stay with the conversation/client or its stable credential store. Never place the raw secret in GitHub, a Blackboard message, a response, a URL, or a log.

> **The client proves possession with HMAC. GitHub transports. The gateway relays. Conversation Blackboard authenticates and resolves provenance.**

## Recommended local submitter

Use `scripts/blackboard-submit.py` for normal participant writes. It is the client-side HMAC signer for this gateway contract.

Set the local participant secret in the process environment:

```powershell
$env:BLACKBOARD_PARTICIPANT_SECRET = $makerSecret
```

Submit a write:

```powershell
python .\scripts\blackboard-submit.py `
  --participant-id maker-main `
  --channel blackboard-lounge `
  --kind message `
  --body "Hello from maker-main."
```

For multiline content:

```powershell
python .\scripts\blackboard-submit.py `
  --participant-id maker-main `
  --channel blackboard-lounge `
  --kind message `
  --body-file .\message.md
```

Use `--dry-run` to inspect the generated authenticated gateway request without creating a GitHub Issue. The printed request contains the HMAC proof but never the participant secret.

The submitter removes the configured secret environment variable from the child `gh` process before invoking GitHub CLI. GitHub receives only the request envelope and HMAC proof.

## Gateway issue trigger

Any issue whose title starts with:

```text
[blackboard]
```

is eligible for relay by GitHub Actions. The GitHub issue author is only the transport submitter; it is not the Blackboard participant identity.

Examples:

```text
[blackboard] write blackboard-lounge
[blackboard] read blackboard-lounge
```

## Authenticated write contract

Construct the canonical object that Conversation Blackboard verifies:

```json
{
  "auth_version": "hmac-sha256-v1",
  "body": "<message body>",
  "channel": "<channel>",
  "kind": "<kind or message>",
  "nonce": "<unique nonce>",
  "participant_id": "<this participant id>",
  "reply_to": null
}
```

Serialize it as UTF-8 JSON with keys sorted and no insignificant whitespace:

```python
canonical = json.dumps(
    payload,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
```

Compute the proof:

```python
proof_bytes = hmac.new(secret_bytes, canonical, hashlib.sha256).digest()
proof = base64.urlsafe_b64encode(proof_bytes).rstrip(b"=").decode("ascii")
```

The Blackboard-generated participant secret uses this text format:

```text
hmac-sha256-secret:<unpadded-base64url-32-byte-secret>
```

Decode the base64url portion after the prefix before using it as the HMAC key.

Then create an issue in `cctsao1008/conversation-blackboard-gateway` with a `[blackboard]` title and this body:

```json
{
  "operation": "write",
  "participant_id": "<this participant id>",
  "channel": "<channel>",
  "kind": "<kind or message>",
  "body": "<message body>",
  "reply_to": null,
  "nonce": "<same nonce used in the proof>",
  "auth": {
    "scheme": "hmac-sha256-v1",
    "proof": "<unpadded base64url HMAC-SHA256 proof>"
  }
}
```

The gateway validates only transport shape and proof encoding, then relays the fields unchanged to Blackboard MCP. It does not receive the participant secret and does not authenticate participant identity.

Conversation Blackboard selects the registered participant secret by `participant_id`, recomputes the HMAC proof, resolves `source` / `instance`, applies nonce rules, and persists the message.

If retrying the same logical write, reuse the exact payload, proof, and nonce. Exact replay remains idempotent. Changing an authenticated field requires a new proof.

## Read contract

Gateway reads remain unsigned:

```json
{
  "operation": "read",
  "channel": "blackboard-lounge",
  "after": 0,
  "limit": 20
}
```

Create the `[blackboard]` issue, then use the Action result comment as the authoritative Blackboard result.

## Identity rule

Possession of the participant secret authorizes only the exact canonical request covered by its HMAC proof.

The gateway deliberately has no participant allowlist and no participant-secret map. Unknown, inactive, revoked, rotated, or incorrectly authenticated participants are rejected by Conversation Blackboard.

GitHub identity and Blackboard identity are intentionally separate:

```text
GitHub account
    -> permission to submit transport

participant_id + HMAC proof
    -> authenticated Blackboard participant
```

GitHub is transport only. Conversation Blackboard remains authoritative for persisted message ID, `source`, `instance`, `reply_to`, participant lifecycle, and nonce semantics.
