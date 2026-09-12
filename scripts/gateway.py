#!/usr/bin/env python3
"""Relay GitHub Issue requests to Conversation Blackboard MCP.

The gateway is a transport adapter, not an identity authority. Signed writes are
validated structurally and relayed unchanged; Conversation Blackboard verifies
the Ed25519 signature against the participant registry.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any

PROTOCOL_VERSION = "2025-11-25"
DEFAULT_MCP_URL = "https://board.cafefeed.idv.tw/mcp"
WRITE_AUTH_SCHEME = "ed25519-v1"
PARTICIPANT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
KIND_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
NONCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
FENCED_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing environment variable: {name}")
    return value


def parse_request(body: str) -> dict[str, Any]:
    text = body.strip()
    fenced_blocks = FENCED_BLOCK_RE.findall(text)
    if len(fenced_blocks) > 1:
        raise ValueError("issue body must contain at most one fenced JSON block")
    if fenced_blocks:
        text = fenced_blocks[0].strip()
    elif "```" in text:
        raise ValueError("issue body contains an incomplete fenced JSON block")

    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"issue body is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("issue body must be one JSON object")
    return value


def validate_signature_encoding(signature: str) -> None:
    if not isinstance(signature, str) or not signature:
        raise ValueError("write auth signature must be a non-empty string")
    if len(signature) > 128 or not re.fullmatch(r"[A-Za-z0-9_-]+", signature):
        raise ValueError("write auth signature must be base64url without padding")
    padded = signature + "=" * ((4 - len(signature) % 4) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ValueError("write auth signature must be valid base64url") from exc
    if len(decoded) != 64:
        raise ValueError("write auth signature must encode exactly 64 bytes")


def validate_request(request: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    operation = request.get("operation")
    if operation == "read":
        allowed = {"operation", "channel", "after", "limit"}
        unknown = set(request) - allowed
        if unknown:
            raise ValueError(f"unsupported read fields: {', '.join(sorted(unknown))}")
        channel = request.get("channel")
        if not isinstance(channel, str) or not NAME_RE.fullmatch(channel):
            raise ValueError("read requires a valid channel")
        after = request.get("after", 0)
        limit = request.get("limit", 50)
        if not isinstance(after, int) or isinstance(after, bool) or after < 0:
            raise ValueError("after must be a non-negative integer")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ValueError("limit must be an integer from 1 to 200")
        return "blackboard_read", {"channel": channel, "after": after, "limit": limit}

    if operation == "write":
        allowed = {
            "operation",
            "participant_id",
            "channel",
            "kind",
            "body",
            "reply_to",
            "nonce",
            "auth",
        }
        unknown = set(request) - allowed
        if unknown:
            raise ValueError(f"unsupported write fields: {', '.join(sorted(unknown))}")

        participant_id = request.get("participant_id")
        channel = request.get("channel")
        message_body = request.get("body")
        nonce = request.get("nonce")
        kind = request.get("kind", "message")
        reply_to = request.get("reply_to")
        auth = request.get("auth")

        if not isinstance(participant_id, str) or not PARTICIPANT_ID_RE.fullmatch(participant_id):
            raise ValueError("write requires a valid participant_id")
        if not isinstance(channel, str) or not NAME_RE.fullmatch(channel):
            raise ValueError("write requires a valid channel")
        if not isinstance(message_body, str) or not message_body.strip():
            raise ValueError("write requires a non-empty body")
        if len(message_body.encode("utf-8")) > 64 * 1024:
            raise ValueError("write body is too large")
        if not isinstance(nonce, str) or not NONCE_RE.fullmatch(nonce):
            raise ValueError("write requires a valid nonce")
        if not isinstance(kind, str) or not KIND_RE.fullmatch(kind):
            raise ValueError("kind must be a valid string")
        if reply_to is not None and (
            not isinstance(reply_to, int) or isinstance(reply_to, bool) or reply_to <= 0
        ):
            raise ValueError("reply_to must be null or a positive integer")
        if not isinstance(auth, dict):
            raise ValueError("write requires an auth object")
        if set(auth) != {"scheme", "signature"}:
            raise ValueError("write auth must contain exactly scheme and signature")
        if auth.get("scheme") != WRITE_AUTH_SCHEME:
            raise ValueError(f"write auth scheme must be {WRITE_AUTH_SCHEME}")
        signature = auth.get("signature")
        validate_signature_encoding(signature)

        # Relay the signed fields unchanged. Do not resolve participant identity,
        # fetch participant secrets, or verify the signature here. Blackboard is
        # the authority that maps participant_id to a public key and provenance.
        return "blackboard_write", {
            "participant_id": participant_id,
            "channel": channel,
            "kind": kind,
            "body": message_body,
            "reply_to": reply_to,
            "nonce": nonce,
            "auth": {
                "scheme": WRITE_AUTH_SCHEME,
                "signature": signature,
            },
        }

    raise ValueError("operation must be 'read' or 'write'")


def http_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> tuple[int, Any]:
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    for key, value in headers.items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            if not raw:
                return response.status, None
            return response.status, json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {raw[:1000]}") from exc


def mcp_post(mcp_url: str, payload: dict[str, Any]) -> tuple[int, Any]:
    return http_json(
        mcp_url,
        payload,
        {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "User-Agent": "conversation-blackboard-gateway/0.3",
        },
    )


def call_blackboard(mcp_url: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    _, initialized = mcp_post(
        mcp_url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "conversation-blackboard-gateway", "version": "0.3.0"},
            },
        },
    )
    if not isinstance(initialized, dict) or "result" not in initialized:
        raise RuntimeError("Blackboard MCP initialize failed")

    status, _ = mcp_post(
        mcp_url,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    if status not in (200, 202, 204):
        raise RuntimeError(f"unexpected initialized notification status: {status}")

    _, response = mcp_post(
        mcp_url,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        },
    )
    if not isinstance(response, dict):
        raise RuntimeError("Blackboard MCP returned an invalid response")
    if "error" in response:
        message = response.get("error", {}).get("message", "unknown MCP error")
        raise RuntimeError(f"MCP error: {message}")
    result = response.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Blackboard MCP response has no tool result")
    if result.get("isError") is True:
        content = result.get("content")
        message = "Blackboard tool error"
        if isinstance(content, list) and content and isinstance(content[0], dict):
            message = str(content[0].get("text", message))
        raise RuntimeError(message)
    structured = result.get("structuredContent")
    if not isinstance(structured, dict):
        raise RuntimeError("Blackboard MCP tool result has no structuredContent")
    return structured


def github_request(method: str, url: str, payload: dict[str, Any]) -> Any:
    token = required_env("GITHUB_TOKEN")
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else None


def add_issue_comment(repository: str, issue_number: int, heading: str, payload: Any) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    body = (
        "<!-- conversation-blackboard-gateway-result -->\n"
        f"### {heading}\n\n"
        "```json\n"
        f"{rendered}\n"
        "```"
    )
    github_request(
        "POST",
        f"https://api.github.com/repos/{repository}/issues/{issue_number}/comments",
        {"body": body},
    )


def close_issue(repository: str, issue_number: int) -> None:
    github_request(
        "PATCH",
        f"https://api.github.com/repos/{repository}/issues/{issue_number}",
        {"state": "closed", "state_reason": "completed"},
    )


def main() -> int:
    repository = required_env("GITHUB_REPOSITORY")
    issue_number = int(required_env("ISSUE_NUMBER"))
    issue_body = os.environ.get("ISSUE_BODY", "")
    mcp_url = os.environ.get("BLACKBOARD_MCP_URL", DEFAULT_MCP_URL).strip() or DEFAULT_MCP_URL

    try:
        request = parse_request(issue_body)
        tool, arguments = validate_request(request)
        result = call_blackboard(mcp_url, tool, arguments)
        add_issue_comment(repository, issue_number, "Conversation Blackboard result", result)
        close_issue(repository, issue_number)
        print(f"Gateway request completed with {tool}.")
        return 0
    except Exception as exc:
        safe_message = str(exc)
        print(f"Gateway request failed: {safe_message}", file=sys.stderr)
        try:
            add_issue_comment(
                repository,
                issue_number,
                "Conversation Blackboard gateway error",
                {"error": safe_message},
            )
        except Exception as report_exc:
            print(
                f"Gateway error reporting also failed: {report_exc}",
                file=sys.stderr,
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
