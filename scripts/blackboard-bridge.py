#!/usr/bin/env python3
"""Process remote Blackboard write intents through the local DPAPI-backed signer.

This bridge never reads or receives participant HMAC secrets itself. It validates a
GitHub Issue intent, then invokes blackboard-submit.ps1, which owns local DPAPI
credential access and HMAC submission.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

TITLE_PREFIX = "[blackboard-local]"
RESULT_MARKER = "<!-- conversation-blackboard-local-bridge -->"
PARTICIPANT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
CHANNEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
KIND_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
NONCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ALLOWED_KEYS = {"participant_id", "channel", "kind", "body", "reply_to", "nonce"}


def parse_intent(issue_number: int, raw_body: str) -> dict[str, Any]:
    try:
        value = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ValueError("intent body must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("intent body must be one JSON object")
    unknown = set(value) - ALLOWED_KEYS
    if unknown:
        raise ValueError(f"unsupported intent fields: {', '.join(sorted(unknown))}")

    participant_id = value.get("participant_id")
    channel = value.get("channel")
    kind = value.get("kind", "message")
    body = value.get("body")
    reply_to = value.get("reply_to")
    nonce = value.get("nonce") or deterministic_nonce(participant_id, issue_number)

    if not isinstance(participant_id, str) or not PARTICIPANT_ID_RE.fullmatch(participant_id):
        raise ValueError("invalid participant_id")
    if not isinstance(channel, str) or not CHANNEL_RE.fullmatch(channel):
        raise ValueError("invalid channel")
    if not isinstance(kind, str) or not KIND_RE.fullmatch(kind):
        raise ValueError("invalid kind")
    if not isinstance(body, str) or not body.strip():
        raise ValueError("body must be a non-empty string")
    if len(body.encode("utf-8")) > 64 * 1024:
        raise ValueError("body exceeds 64 KiB")
    if reply_to is not None and (not isinstance(reply_to, int) or isinstance(reply_to, bool) or reply_to <= 0):
        raise ValueError("reply_to must be null or a positive integer")
    if not isinstance(nonce, str) or not NONCE_RE.fullmatch(nonce):
        raise ValueError("invalid nonce")

    return {
        "participant_id": participant_id,
        "channel": channel,
        "kind": kind,
        "body": body,
        "reply_to": reply_to,
        "nonce": nonce,
    }


def deterministic_nonce(participant_id: Any, issue_number: int) -> str:
    if not isinstance(participant_id, str) or not participant_id:
        participant_id = "unknown"
    nonce = f"bridge-{participant_id}-{issue_number}"
    if len(nonce) > 128:
        raise ValueError("derived nonce exceeds contract limit")
    return nonce


def sanitize_error(text: str) -> str:
    text = re.sub(r"hmac-sha256-secret:[A-Za-z0-9_-]+", "[REDACTED_SECRET]", text)
    text = text.strip().replace("\x00", "")
    if len(text) > 1500:
        text = text[:1500] + "..."
    return text or "local bridge command failed"


def gh_json(gh: str, args: list[str]) -> Any:
    completed = subprocess.run(
        [gh, *args],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(completed.stdout or "null")


def list_candidate_issues(gh: str, repository: str) -> list[dict[str, Any]]:
    issues = gh_json(
        gh,
        [
            "issue",
            "list",
            "--repo",
            repository,
            "--state",
            "open",
            "--limit",
            "100",
            "--json",
            "number,title,body,author",
        ],
    )
    return [i for i in issues if isinstance(i.get("title"), str) and i["title"].startswith(TITLE_PREFIX)]


def has_bridge_comment(gh: str, repository: str, issue_number: int) -> bool:
    data = gh_json(
        gh,
        ["issue", "view", str(issue_number), "--repo", repository, "--json", "comments"],
    )
    comments = data.get("comments", []) if isinstance(data, dict) else []
    return any(RESULT_MARKER in str(comment.get("body", "")) for comment in comments)


def comment_issue(gh: str, repository: str, issue_number: int, message: str) -> None:
    subprocess.run(
        [
            gh,
            "issue",
            "comment",
            str(issue_number),
            "--repo",
            repository,
            "--body",
            f"{RESULT_MARKER}\n{message}",
        ],
        check=True,
        text=True,
        capture_output=True,
    )


def close_issue(gh: str, repository: str, issue_number: int) -> None:
    subprocess.run(
        [gh, "issue", "close", str(issue_number), "--repo", repository, "--reason", "completed"],
        check=True,
        text=True,
        capture_output=True,
    )


def find_powershell() -> str:
    for name in ("pwsh", "powershell"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError("PowerShell was not found in PATH")


def invoke_submitter(
    powershell: str,
    submitter: Path,
    repository: str,
    intent: dict[str, Any],
) -> str:
    argv = [
        powershell,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(submitter),
        "-ParticipantId",
        intent["participant_id"],
        "-Channel",
        intent["channel"],
        "-Kind",
        intent["kind"],
        "-Body",
        intent["body"],
        "-Nonce",
        intent["nonce"],
        "-Repository",
        repository,
    ]
    if intent["reply_to"] is not None:
        argv.extend(["-ReplyTo", str(intent["reply_to"])])
    completed = subprocess.run(argv, check=True, text=True, capture_output=True)
    output = completed.stdout.strip()
    if not output:
        raise RuntimeError("local submitter returned no result")
    return output.splitlines()[-1].strip()


def process_issue(
    issue: dict[str, Any],
    *,
    gh: str,
    repository: str,
    allowed_author: str,
    allowed_participants: set[str],
    powershell: str,
    submitter: Path,
) -> str:
    issue_number = int(issue["number"])
    author = issue.get("author") or {}
    author_login = author.get("login") if isinstance(author, dict) else None

    if author_login != allowed_author:
        if not has_bridge_comment(gh, repository, issue_number):
            comment_issue(gh, repository, issue_number, "Rejected: issue author is not allowed by the local bridge.")
        return "rejected-author"

    try:
        intent = parse_intent(issue_number, issue.get("body") or "")
    except ValueError as exc:
        if not has_bridge_comment(gh, repository, issue_number):
            comment_issue(gh, repository, issue_number, f"Rejected: {sanitize_error(str(exc))}")
        return "rejected-intent"

    if intent["participant_id"] not in allowed_participants:
        if not has_bridge_comment(gh, repository, issue_number):
            comment_issue(gh, repository, issue_number, "Rejected: participant is not allowed by the local bridge.")
        return "rejected-participant"

    try:
        gateway_url = invoke_submitter(powershell, submitter, repository, intent)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        detail = str(exc)
        if isinstance(exc, subprocess.CalledProcessError):
            detail = exc.stderr or exc.stdout or str(exc)
        if not has_bridge_comment(gh, repository, issue_number):
            comment_issue(gh, repository, issue_number, f"Local submit failed: {sanitize_error(detail)}")
        return "submit-failed"

    comment_issue(
        gh,
        repository,
        issue_number,
        f"Submitted through the local participant signer: {gateway_url}",
    )
    close_issue(gh, repository, issue_number)
    return "submitted"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Process local Blackboard write intents from GitHub Issues.")
    p.add_argument("--repository", default="cctsao1008/conversation-blackboard-gateway")
    p.add_argument("--allowed-author", required=True)
    p.add_argument("--participant", action="append", dest="participants", required=True)
    p.add_argument("--submitter", type=Path)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    gh = shutil.which("gh")
    if not gh:
        print("blackboard bridge failed: GitHub CLI 'gh' was not found in PATH", file=sys.stderr)
        return 2
    try:
        powershell = find_powershell()
        script_dir = Path(__file__).resolve().parent
        submitter = args.submitter or (script_dir / "blackboard-submit.ps1")
        if not submitter.is_file():
            raise RuntimeError(f"submitter not found: {submitter}")
        issues = list_candidate_issues(gh, args.repository)
        for issue in issues:
            process_issue(
                issue,
                gh=gh,
                repository=args.repository,
                allowed_author=args.allowed_author,
                allowed_participants=set(args.participants),
                powershell=powershell,
                submitter=submitter,
            )
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"blackboard bridge failed: {sanitize_error(str(exc))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
