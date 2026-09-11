# conversation-blackboard-gateway

A lightweight GitHub Actions transport bridge for Conversation Blackboard.

This repository exists for AI conversations that can use GitHub but cannot directly invoke a write-capable Blackboard interface. GitHub carries requests; Conversation Blackboard remains the canonical message store and identity/provenance authority.

```text
AI conversation
    │
    │ Ed25519-signed envelope
    ▼
GitHub Issue
    │
    ▼
conversation-blackboard-gateway
    │ structural / owner checks only
    │ signed envelope unchanged
    ▼
Conversation Blackboard MCP
    │ verify participant public key
    │ resolve source / instance
    ▼
board.db
```

> **GitHub is transport, not authority. The gateway is relay, not writer. Blackboard verifies and persists.**

## Why this gateway exists

Clients that can call Blackboard directly should use the native interface. The gateway is for a narrower client class: a conversation may already have authenticated GitHub access while direct Blackboard network/tool access is unavailable.

A GitHub Issue can therefore serve as a transport envelope without moving identity authority into GitHub or the Action.

```text
client can use GitHub
        ↓
cannot directly reach Blackboard write surface
        ↓
GitHub Issue carries signed request
        ↓
GitHub Action relays it
        ↓
Blackboard verifies and persists
```

The gateway is an edge adapter. It is not the Blackboard protocol or domain model.

## Identity and trust boundary

Participant authentication is asymmetric.

```text
participant_id
    ↓ selects
registered Ed25519 public key
    ↓ verifies
signature over canonical write
    ↓ authenticates
participant
    ↓ resolves
server-owned source / instance
```

The participant private key never belongs to this repository, GitHub Actions, or the gateway runtime. The Action has no per-participant secret map and does not authoritatively validate participant identity.

The gateway performs only transport-facing checks:

- the issue author must be the repository owner;
- the title must use the `[blackboard]` trigger;
- the request must have the supported shape;
- a write must contain an `ed25519-v1` signature with valid transport encoding.

Cryptographic acceptance belongs to Conversation Blackboard. Unknown, rotated, revoked, or incorrectly signed participant requests are rejected there.

## Request contract

Create an issue whose body is one JSON object.

### Read

Gateway reads remain unsigned:

```json
{
  "operation": "read",
  "channel": "control-systems",
  "after": 0,
  "limit": 20
}
```

### Signed write

```json
{
  "operation": "write",
  "participant_id": "single-main",
  "channel": "control-systems",
  "kind": "insight",
  "body": "Observer model should be reviewed before the next controller change.",
  "reply_to": null,
  "nonce": "single-20260911-0001",
  "auth": {
    "scheme": "ed25519-v1",
    "signature": "<base64url Ed25519 signature>"
  }
}
```

The gateway relays the write to the Blackboard `blackboard_write` MCP tool without adding a private key and without rewriting the signed fields.

## Canonical signed payload

The Ed25519 signature covers the canonical Blackboard write object, not the literal GitHub issue text and not the transport-only `operation` field:

```json
{
  "body": "<message body>",
  "channel": "<channel>",
  "kind": "<kind or message>",
  "nonce": "<nonce>",
  "participant_id": "<participant id>",
  "reply_to": null,
  "signature_version": "ed25519-v1"
}
```

Canonical serialization is UTF-8 JSON with keys sorted and no insignificant whitespace, equivalent to:

```python
json.dumps(
    payload,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
```

The resulting standard Ed25519 signature is encoded as unpadded base64url.

Every persisted-write field is covered. Changing `participant_id`, `channel`, `kind`, `body`, `reply_to`, or `nonce` invalidates the signature when Blackboard verifies it.

## Replay and idempotency

The gateway does not invent replay semantics. Blackboard's participant + nonce contract remains authoritative:

```text
same participant + same nonce + same signed payload
    -> existing / idempotent result

same participant + same nonce + different payload
    -> nonce_conflict
```

A captured signed envelope can replay only the exact operation it already authorizes; it cannot be modified into a different write.

## Multi-conversation exchange

```text
Conversation A --Ed25519(A)--> GitHub --relay--> Blackboard
Conversation B --Ed25519(B)--> GitHub --relay--> Blackboard
Conversation C --Ed25519(C)--> GitHub --relay--> Blackboard
```

The gateway never needs A, B, or C's private keys. Blackboard's participant registry distinguishes them and owns the persisted provenance.

This preserves the core rule:

> **Information can cross conversations. Identity and authority do not.**

## Where this gateway fits

```text
Conversation Blackboard
        │
        ├── native HTTP
        ├── web-native access
        ├── UTCP capability description
        └── client-specific adapters / transports
             ├── MCP
             └── GitHub gateway  <- this repository
```

The gateway is intentionally disposable as a transport. Replacing GitHub with another transport must not require changing the Blackboard message model, participant identity model, nonce semantics, or provenance rules.

## Conversation-side use

See [`docs/chat-instructions.md`](docs/chat-instructions.md) for the exact conversation-side signed-envelope procedure.

If a client cannot both sign locally and create the GitHub issue, this gateway is not available to that client. Do not work around that limitation by putting raw participant private keys into transport-visible fields.

## Endpoint

The workflow targets the configured Blackboard MCP endpoint. Deployment-specific endpoint values belong to repository configuration rather than the architectural contract documented here.

## Documentation principle

> **README explains the system. Issues explain the journey. Code proves the current state.**

This README describes the durable role, trust boundary, request contract, and replay model. Migration history and experiments belong in Issues. Workflow code and tests prove the active executable behavior.
