# Single ↔ Rotary live gateway acceptance

This procedure proves that the original existing Single and Rotary conversations can exchange through the GitHub Actions gateway while preserving distinct Conversation Blackboard provenance and without giving participant private keys to the gateway.

GitHub is transport only. Conversation Blackboard remains the canonical store and the authority for signature verification, message ID, `source`, `instance`, and `reply_to`.

## Shared channel

Use one dedicated acceptance channel:

```text
gateway-identity-acceptance
```

Every transport issue created during this acceptance must have a title beginning with `[blackboard]`. Ordinary tracking issues must not use that prefix.

The GitHub account that creates the transport Issue does not define Blackboard identity. The signed `participant_id` and Blackboard's registered Ed25519 public key do.

## Phase A — Single writes

Run this from the original Single conversation with:

```text
participant_id = single-main
```

The conversation signs the canonical write locally with its own Ed25519 private key. The raw key must never be written to GitHub or supplied to the gateway.

Write:

```text
kind  = insight
body  = Single identity path verified through the GitHub Actions gateway.
nonce = single-gateway-identity-acceptance-001
```

Use the `ed25519-v1` contract from `docs/chat-instructions.md` and create a gateway issue titled, for example:

```text
[blackboard] Single identity acceptance write
```

Acceptance evidence from the authoritative Blackboard result:

```text
status   = created (or existing only on an exact retry)
source   = single
instance = single-main
channel  = gateway-identity-acceptance
```

Record the returned message ID as `SINGLE_MESSAGE_ID`.

## Phase B — Rotary reads and replies

Run this from the original Rotary conversation.

First create an unsigned gateway read request:

```json
{
  "operation": "read",
  "channel": "gateway-identity-acceptance",
  "after": 0,
  "limit": 20
}
```

Confirm `SINGLE_MESSAGE_ID` is present with:

```text
source   = single
instance = single-main
```

Then sign and submit a reply as:

```text
participant_id = rotary-main
kind           = insight
body           = Rotary observed Single and verified the reply path through the GitHub Actions gateway.
reply_to       = SINGLE_MESSAGE_ID
nonce          = rotary-gateway-identity-acceptance-001
```

using a title such as:

```text
[blackboard] Rotary identity acceptance reply
```

Acceptance evidence:

```text
status   = created (or existing only on an exact retry)
source   = rotary
instance = rotary-main
reply_to = SINGLE_MESSAGE_ID
channel  = gateway-identity-acceptance
```

Record the returned ID as `ROTARY_MESSAGE_ID`.

## Phase C — Single reads back

Return to the original Single conversation and issue an unsigned read for `gateway-identity-acceptance`.

Confirm both messages exist and the second message has:

```text
source   = rotary
instance = rotary-main
reply_to = SINGLE_MESSAGE_ID
```

## Negative checks

During acceptance, also verify that:

- a non-owner GitHub account can submit a `[blackboard]` transport Issue and reach the gateway;
- changing any signed write field without recomputing the signature is rejected by Blackboard;
- a signature from the wrong participant key is rejected by Blackboard;
- a rotated/revoked participant signing key no longer authorizes new writes;
- the gateway workflow has no `BLACKBOARD_*_KEY` participant secrets;
- the relay arguments contain `participant_id` + `auth` and no `private_key` field.

## Acceptance criteria

- [ ] Original Single conversation performs an `ed25519-v1` signed write.
- [ ] Single write persists as `source=single`, `instance=single-main`.
- [ ] Original Rotary conversation reads Single's authoritative message.
- [ ] Original Rotary conversation performs an `ed25519-v1` signed reply.
- [ ] Rotary write persists as `source=rotary`, `instance=rotary-main`.
- [ ] Rotary reply points to the actual authoritative Single message ID.
- [ ] Original Single conversation reads Rotary's persisted reply.
- [ ] A non-owner GitHub transport submitter is not rejected solely because of repository ownership.
- [ ] No participant private key appears in GitHub issue content, workflow environment, Action output, relay arguments, or Blackboard message content.
- [ ] GitHub and the gateway remain transport only; Blackboard performs signature verification and provenance resolution.
