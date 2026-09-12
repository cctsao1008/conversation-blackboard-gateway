#!/usr/bin/env python3
"""Create HMAC-authenticated Conversation Blackboard gateway write issues locally.

The participant secret is read from the local environment, used only to compute the
HMAC proof, and is never included in the generated GitHub request.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

AUTH_SCHEME = "hmac-sha256-v1"
SECRET_PREFIX = "hmac-sha256-secret:"
DEFAULT_SECRET_ENV = "BLACKBOARD_PARTICIPANT_SECRET"
DEFAULT_REPOSITORY = "cctsao1008/conversation-blackboard-gateway"
PARTICIPANT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
KIND_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
NONCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def decode_secret(secret: str) -> bytes:
    if not secret.startswith(SECRET_PREFIX):
        raise ValueError(f"participant secret must start with {SECRET_PREFIX}")
    encoded = secret[len(SECRET_PREFIX) :]
    if not encoded or "=" in encoded or not re.fullmatch(r"[A-Za-z0-9_-]+", encoded):
        raise ValueError("participant secret must contain unpadded base64url material")
    padded = encoded + "=" * ((4 - len(encoded) % 4) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ValueError("participant secret contains invalid base64url") from exc
    if len(decoded) != 32:
        raise ValueError("participant secret must encode exactly 32 bytes")
    return decoded


def canonical_write_payload(
    participant_id: str,
    channel: str,
    kind: str,
    body: str,
    reply_to: int | None,
    nonce: str,
) -> dict[str, Any]:
    return {
        "auth_version": AUTH_SCHEME,
        "body": body,
        "channel": channel,
        "kind": kind,
        "nonce": nonce,
        "participant_id": participant_id,
        "reply_to": reply_to,
    }


def canonical_write_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def compute_proof(secret: str, payload: dict[str, Any]) -> str:
    secret_bytes = decode_secret(secret)
    proof = hmac.new(secret_bytes, canonical_write_bytes(payload), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(proof).rstrip(b"=").decode("ascii")


def validate_fields(
    participant_id: str,
    channel: str,
    kind: str,
    body: str,
    reply_to: int | None,
    nonce: str,
) -> None:
    if not PARTICIPANT_ID_RE.fullmatch(participant_id):
        raise ValueError("invalid participant_id")
    if not NAME_RE.fullmatch(channel):
        raise ValueError("invalid channel")
    if not KIND_RE.fullmatch(kind):
        raise ValueError("invalid kind")
    if not body.strip():
        raise ValueError("body must not be empty")
    if len(body.encode("utf-8")) > 64 * 1024:
        raise ValueError("body exceeds 64 KiB")
    if reply_to is not None and reply_to <= 0:
        raise ValueError("reply_to must be a positive integer")
    if not NONCE_RE.fullmatch(nonce):
        raise ValueError("invalid nonce")


def generate_nonce(participant_id: str) -> str:
    nonce = f"{participant_id}-{uuid.uuid4().hex}"
    if not NONCE_RE.fullmatch(nonce):
        raise ValueError("generated nonce does not satisfy gateway contract")
    return nonce


def build_gateway_request(
    secret: str,
    participant_id: str,
    channel: str,
    kind: str,
    body: str,
    reply_to: int | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    resolved_nonce = nonce or generate_nonce(participant_id)
    validate_fields(participant_id, channel, kind, body, reply_to, resolved_nonce)
    canonical = canonical_write_payload(
        participant_id, channel, kind, body, reply_to, resolved_nonce
    )
    proof = compute_proof(secret, canonical)
    return {
        "operation": "write",
        "participant_id": participant_id,
        "channel": channel,
        "kind": kind,
        "body": body,
        "reply_to": reply_to,
        "nonce": resolved_nonce,
        "auth": {"scheme": AUTH_SCHEME, "proof": proof},
    }


def render_request(request: dict[str, Any]) -> str:
    return json.dumps(request, ensure_ascii=False, indent=2)


def submit_issue(
    request: dict[str, Any],
    repository: str,
    secret_env_name: str,
) -> str:
    gh = shutil.which("gh")
    if not gh:
        raise RuntimeError("GitHub CLI 'gh' was not found in PATH")
    channel = request["channel"]
    title = f"[blackboard] write {channel}"
    child_env = os.environ.copy()
    child_env.pop(secret_env_name, None)
    completed = subprocess.run(
        [
            gh,
            "issue",
            "create",
            "--repo",
            repository,
            "--title",
            title,
            "--body",
            render_request(request),
        ],
        env=child_env,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Create a local HMAC-authenticated Conversation Blackboard gateway write."
    )
    p.add_argument("--participant-id", required=True)
    p.add_argument("--channel", required=True)
    p.add_argument("--kind", default="message")
    body = p.add_mutually_exclusive_group(required=True)
    body.add_argument("--body")
    body.add_argument("--body-file", type=Path)
    p.add_argument("--reply-to", type=int)
    p.add_argument("--nonce")
    p.add_argument("--repository", default=DEFAULT_REPOSITORY)
    p.add_argument("--secret-env", default=DEFAULT_SECRET_ENV)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the signed gateway request without creating a GitHub Issue.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    secret = os.environ.get(args.secret_env, "").strip()
    if not secret:
        print(f"missing participant secret environment variable: {args.secret_env}", file=sys.stderr)
        return 2
    try:
        message_body = args.body
        if args.body_file is not None:
            message_body = args.body_file.read_text(encoding="utf-8")
        assert message_body is not None
        request = build_gateway_request(
            secret=secret,
            participant_id=args.participant_id,
            channel=args.channel,
            kind=args.kind,
            body=message_body,
            reply_to=args.reply_to,
            nonce=args.nonce,
        )
        if args.dry_run:
            print(render_request(request))
            return 0
        url = submit_issue(request, args.repository, args.secret_env)
        print(url)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"blackboard submit failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
