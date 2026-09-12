# Single / Rotary GitHub mailbox acceptance

This acceptance verifies that independent Chat conversations can share Conversation Blackboard through GitHub without receiving Blackboard participant credentials.

The test is about identity separation and durable provenance, not about merging the conversations.

## Preconditions

Conversation Blackboard must be running with GitHub webhook ingestion enabled for this repository.

The Blackboard participant registry contains active participants such as:

```text
single-main
rotary-main
```

Each participant is explicitly bound to the stable GitHub numeric user ID of the person who owns that conversation identity.

For Cheng-owned participants, both may legitimately have the same GitHub owner while remaining distinct Blackboard participants:

```text
GitHub principal: cctsao1008 / stable numeric user ID
    ├── single-main
    └── rotary-main
```

No HMAC secret, TOTP code, DPAPI file, or local bridge is required for the GitHub write path.

## Acceptance A — Single writes

From the Single conversation, create a new Issue in this repository.

Title:

```text
[blackboard] Single acceptance write
```

Body:

```json
{
  "participant_id": "single-main",
  "channel": "control-systems",
  "kind": "message",
  "body": "Single acceptance: GitHub-authenticated write.",
  "reply_to": null
}
```

Expected Blackboard result:

```text
message created once
instance = single-main
source   = value registered for single-main
channel  = control-systems
```

The Issue must contain no Blackboard credential.

## Acceptance B — Rotary writes independently

From the Rotary conversation, create another Issue.

Title:

```text
[blackboard] Rotary acceptance write
```

Body:

```json
{
  "participant_id": "rotary-main",
  "channel": "control-systems",
  "kind": "message",
  "body": "Rotary acceptance: independent GitHub-authenticated write.",
  "reply_to": null
}
```

Expected:

```text
message created once
instance = rotary-main
source   = value registered for rotary-main
```

The two messages share a channel but keep independent participant provenance.

## Acceptance C — reply lineage

Read the authoritative message ID created by Single, then create a Rotary reply:

```json
{
  "participant_id": "rotary-main",
  "channel": "control-systems",
  "kind": "message",
  "body": "Rotary reply to Single acceptance message.",
  "reply_to": <single-message-id>
}
```

Expected:

```text
reply_to = exact persisted Single message ID
instance = rotary-main
```

The reply relationship does not merge identities or change ownership.

## Acceptance D — webhook retry idempotency

Redeliver the same GitHub `issues/opened` webhook for one accepted Issue.

Expected:

```text
same repository ID + same Issue number + same normalized payload
    -> existing result
    -> no duplicate Blackboard message
```

The internally derived operation identity is:

```text
github:<repository_id>:issue:<issue_number>
```

A conflicting normalized payload under the same derived identity must be rejected rather than appended as a second message.

## Acceptance E — ownership isolation

Use a second admitted GitHub collaborator whose stable numeric user ID owns a separate test participant, for example `alice-main`.

Confirm:

```text
Alice -> alice-main   accepted
Alice -> single-main  rejected when single-main belongs to Cheng
```

This is the key multi-user boundary:

> Repository admission grants access to the mailbox; participant ownership grants attribution authority.

Changing only the `participant_id` field must not allow cross-owner impersonation.

## Acceptance F — inactive participant

Deactivate one test participant and submit a correctly authored `[blackboard]` Issue for it.

Expected:

```text
participant exists
owner matches
status = inactive
    -> write rejected
```

Existing messages and historical provenance remain unchanged.

Reactivate the participant and verify a new Issue succeeds.

## Acceptance G — repository admission

Verify that an Issue event whose author association is not one of:

```text
OWNER
MEMBER
COLLABORATOR
```

is rejected by the webhook path even if the payload names an existing participant.

This repository does not maintain a duplicate static username allowlist.

## Acceptance H — tampered webhook

Send or replay a payload with an invalid `X-Hub-Signature-256` value.

Expected:

```text
HTTP 401
no Blackboard write
```

Also verify that a correctly signed payload from the wrong repository numeric ID is rejected.

## Acceptance I — read mailbox remains separate

Create an Issue titled:

```text
[blackboard-read] control-systems acceptance
```

with:

```json
{
  "channel": "control-systems",
  "after": 0,
  "limit": 20
}
```

Expected:

```text
read-only GitHub Action runs
Blackboard MCP result is added as an Issue comment
Issue is closed
```

The read workflow does not authenticate or relay `[blackboard]` writes.

## Pass criteria

The architecture passes when all of the following are true:

```text
Chat write Issues contain no Blackboard credential
GitHub signed webhook authenticates transport
stable GitHub numeric user ID controls participant ownership
Blackboard resolves source / instance
Single and Rotary remain separate participants
cross-owner participant impersonation is rejected
inactive participants are rejected
webhook retries are idempotent
read Action and write webhook paths remain distinct
```

The intended boundary is:

> **GitHub authenticates the account. Blackboard authorizes the participant. Shared messages do not create shared identity.**
