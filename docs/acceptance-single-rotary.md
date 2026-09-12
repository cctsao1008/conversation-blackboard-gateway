# Single ↔ Rotary live gateway acceptance

This procedure proves that two existing conversations can exchange through the GitHub transport while preserving distinct Conversation Blackboard provenance and without exposing participant HMAC secrets to GitHub or the remote controller.

The current write path is:

```text
remote conversation
    -> unsigned [blackboard-local] intent
local Windows bridge
    -> allowed-author check
    -> exact <participant_id>.dpapi lookup
    -> DPAPI-backed HMAC signer
GitHub [blackboard] transport issue
    -> gateway relay
Conversation Blackboard
    -> HMAC verification + lifecycle + provenance
```

GitHub is transport only. Local DPAPI possession is signing capability only. Conversation Blackboard remains the canonical store and final participant/authentication authority.

## Preconditions

The participant identities already exist in Blackboard and each local HMAC secret has been stored under:

```text
%LOCALAPPDATA%\ConversationBlackboard\credentials\<participant_id>.dpapi
```

For this acceptance:

```text
single-main
rotary-main
```

The installed local bridge uses dynamic credential discovery. No participant allowlist edit or task reinstall is required when those files already exist.

Use one dedicated channel:

```text
gateway-identity-acceptance
```

## Phase A — Single writes

Create a local intent issue whose title begins with:

```text
[blackboard-local]
```

and whose body is:

```json
{
  "participant_id": "single-main",
  "channel": "gateway-identity-acceptance",
  "kind": "insight",
  "body": "Single identity path verified through the local HMAC bridge and GitHub gateway.",
  "reply_to": null,
  "nonce": "single-gateway-identity-acceptance-001"
}
```

The local bridge should:

1. verify the configured GitHub intent author;
2. find `single-main.dpapi`;
3. invoke the DPAPI-backed submitter;
4. create a normal `[blackboard]` HMAC-authenticated transport issue;
5. comment the produced gateway issue URL on the local intent;
6. close the local intent after local submission succeeds.

Acceptance evidence from the authoritative Blackboard result:

```text
status         = created (or existing only on exact retry)
participant_id = single-main
source         = single
instance       = single-main
channel        = gateway-identity-acceptance
```

Record the returned message ID as `SINGLE_MESSAGE_ID`.

## Phase B — Rotary reads and replies

Read the shared channel through an accepted read surface and confirm `SINGLE_MESSAGE_ID` exists with:

```text
source   = single
instance = single-main
```

Then create another `[blackboard-local]` intent:

```json
{
  "participant_id": "rotary-main",
  "channel": "gateway-identity-acceptance",
  "kind": "insight",
  "body": "Rotary observed Single and verified the reply path through the local HMAC bridge and GitHub gateway.",
  "reply_to": 123,
  "nonce": "rotary-gateway-identity-acceptance-001"
}
```

Replace `123` with `SINGLE_MESSAGE_ID`.

Acceptance evidence:

```text
status         = created (or existing only on exact retry)
participant_id = rotary-main
source         = rotary
instance       = rotary-main
reply_to       = SINGLE_MESSAGE_ID
channel        = gateway-identity-acceptance
```

Record the returned ID as `ROTARY_MESSAGE_ID`.

## Phase C — Single reads back

Return to the Single conversation and read `gateway-identity-acceptance` again.

Confirm both messages exist and the Rotary message has:

```text
source   = rotary
instance = rotary-main
reply_to = SINGLE_MESSAGE_ID
```

## Lower-layer gateway contract

The local bridge is only the remote-intent actuator. The resulting `[blackboard]` write still uses the normal HMAC gateway contract:

```json
{
  "operation": "write",
  "participant_id": "single-main",
  "channel": "gateway-identity-acceptance",
  "kind": "insight",
  "body": "...",
  "reply_to": null,
  "nonce": "...",
  "auth": {
    "scheme": "hmac-sha256-v1",
    "proof": "<unpadded-base64url-HMAC>"
  }
}
```

The participant secret is never part of this envelope. The gateway validates transport shape and proof encoding only; Blackboard performs HMAC verification.

## Negative checks

Verify that:

- a local intent from a GitHub author other than the configured `AllowedAuthor` is rejected before signing;
- an intent for a participant with no exact local `<participant_id>.dpapi` credential is rejected before the submitter runs;
- adding a newly provisioned participant credential does not require editing bridge configuration or reinstalling the task;
- changing any HMAC-covered write field without recomputing the proof is rejected by Blackboard;
- a proof generated with another participant secret is rejected;
- an inactive participant is rejected even when a stale local DPAPI credential still exists;
- an auth-revoked/rotated credential no longer authorizes writes with the old secret;
- GitHub issues, comments, workflow environment, relay arguments, and Blackboard message content never contain the raw participant secret;
- the local bridge configuration contains `credential_root` but no participant allowlist.

## Acceptance criteria

- [ ] Single remote intent is processed through `single-main.dpapi`.
- [ ] Single write persists as `source=single`, `instance=single-main`.
- [ ] Rotary reads Single's authoritative message.
- [ ] Rotary remote intent is processed through `rotary-main.dpapi`.
- [ ] Rotary write persists as `source=rotary`, `instance=rotary-main`.
- [ ] Rotary reply points to the authoritative Single message ID.
- [ ] Single reads Rotary's persisted reply.
- [ ] No participant HMAC secret appears in GitHub-visible material.
- [ ] Local credential presence acts only as signing capability; Blackboard remains final authority.
- [ ] Dynamic participant discovery works without a static participant allowlist.
- [ ] GitHub and the gateway remain transport only; Blackboard performs HMAC verification and provenance resolution.
