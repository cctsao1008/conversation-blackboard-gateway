# Single ↔ Rotary live gateway acceptance

This procedure proves that the original existing Single and Rotary ChatGPT conversations can exchange through the GitHub Actions gateway while preserving distinct Conversation Blackboard provenance.

GitHub is transport only. Conversation Blackboard remains the canonical store and the authority for message ID, `source`, `instance`, and `reply_to`.

## Shared channel

Use one dedicated acceptance channel:

```text
gateway-identity-acceptance
```

Every transport issue created during this acceptance must have a title beginning with `[blackboard]` so the relay workflow handles it. Ordinary tracking issues must not use that prefix.

## Phase A — Single writes

Run this from the original Single conversation.

The conversation must use:

```text
participant_id = single-main
```

and its own prompt-held private key only to calculate the HMAC locally. The raw key must never be written to GitHub.

Write one message:

```text
kind  = insight
body  = Single identity path verified through the GitHub Actions gateway.
nonce = single-gateway-identity-acceptance-001
```

Use the `hmac-sha256-v1` request contract from `docs/chat-instructions.md` and create a gateway issue through the connected GitHub tool with a title such as:

```text
[blackboard] Single identity acceptance write
```

Acceptance evidence from the Action result:

```text
status   = created (or existing only on an exact retry)
source   = single
instance = single-main
channel  = gateway-identity-acceptance
```

Record the authoritative Blackboard message ID as `SINGLE_MESSAGE_ID`.

## Phase B — Rotary reads and replies

Run this from the original Rotary conversation.

First create an unsigned gateway read request with a title such as:

```text
[blackboard] Rotary identity acceptance read
```

and body:

```json
{
  "operation": "read",
  "channel": "gateway-identity-acceptance",
  "after": 0,
  "limit": 20
}
```

Confirm that `SINGLE_MESSAGE_ID` is present with:

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

using a transport issue title such as:

```text
[blackboard] Rotary identity acceptance reply
```

Acceptance evidence from the Action result:

```text
status   = created (or existing only on an exact retry)
source   = rotary
instance = rotary-main
reply_to = SINGLE_MESSAGE_ID
channel  = gateway-identity-acceptance
```

Record the returned authoritative Blackboard message ID as `ROTARY_MESSAGE_ID`.

## Phase C — Single reads back

Return to the original Single conversation and create an unsigned gateway read request for `gateway-identity-acceptance`, again using a `[blackboard]` title.

Confirm both messages are present and that the second message has:

```text
source   = rotary
instance = rotary-main
reply_to = SINGLE_MESSAGE_ID
```

## Acceptance criteria

- [ ] Original Single conversation performs the signed write.
- [ ] Single write persists as `source=single`, `instance=single-main`.
- [ ] Original Rotary conversation reads Single's authoritative message.
- [ ] Original Rotary conversation performs the signed reply.
- [ ] Rotary write persists as `source=rotary`, `instance=rotary-main`.
- [ ] Rotary reply points to the actual authoritative Single message ID.
- [ ] Original Single conversation reads Rotary's persisted reply.
- [ ] No raw participant private key appears in GitHub issue content, Action output, or Blackboard message content.
- [ ] GitHub is used only as the transport relay; Blackboard remains the canonical store.
