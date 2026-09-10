#!/usr/bin/env python3
"""Relay a repository-owner GitHub issue to Conversation Blackboard MCP."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any

PROTOCOL_VERSION = "2025-11-25"
DEFAULT_MCP_URL = "https://board.cafefeed.idv.tw/mcp"
GATEWAY_PARTICIPANT_ID = "github-gateway"


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing environment variable: {name}")
    return value


def parse_request(body: str) -> dict[str, Any]:
    text = body.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"issue body is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("issue body must be one JSON object")
    return value


def validate_request(request: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    operation = request.get("operation")
    if operation == "read":
        allowed = {"operation", "channel", "after", "limit"}
        unknown = set(request) - allowed
        if unknown:
            raise ValueError(f"unsupported read fields: {', '.join(sorted(unknown))}")
        channel = request.get("channel")
        if not isinstance(channel, str) or not channel:
            raise ValueError("read requires a non-empty channel")
        after = request.get("after", 0)
        limit = request.get("limit", 50)
        if not isinstance(after, int) or isinstance(after, bool) or after < 0:
            raise ValueError("after must be a non-negative integer")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ValueError("limit must be an integer from 1 to 200")
        return "blackboard_read", {"channel": channel, "after": after, "limit": limit}

    if operation == "write":
        allowed = {"operation", "channel", "kind", "body", "reply_to", "nonce"}
        unknown = set(request) - allowed
        if unknown:
            raise ValueError(f"unsupported write fields: {', '.join(sorted(unknown))}")
        channel = request.get("channel")
        message_body = request.get("body")
        nonce = request.get("nonce")
        kind = request.get("kind", "message")
        reply_to = request.get("reply_to")
        if not isinstance(channel, str) or not channel:
            raise ValueError("write requires a non-empty channel")
        if not isinstance(message_body, str) or not message_body.strip():
            raise ValueError("write requires a non-empty body")
        if not isinstance(nonce, str) or not nonce:
            raise ValueError("write requires a non-empty nonce")
        if not isinstance(kind, str) or not kind:
            raise ValueError("kind must be a non-empty string")
        if reply_to is not None and (
            not isinstance(reply_to, int) or isinstance(reply_to, bool) or reply_to <= 0
        ):
            raise ValueError("reply_to must be null or a positive integer")

        private_key = required_env("BLACKBOARD_GATEWAY_KEY")
        return "blackboard_write", {
            "participant_id": GATEWAY_PARTICIPANT_ID,
            "private_key": private_key,
            "channel": channel,
            "kind": kind,
            "body": message_body,
            "reply_to": reply_to,
            "nonce": nonce,
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
            "User-Agent": "conversation-blackboard-gateway/0.1",
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
                "clientInfo": {"name": "conversation-blackboard-gateway", "version": "0.1.0"},
            },
        },
    )
    if not isinstance(initialized, dict) or "result" not in initialized:
        raise RuntimeError("Blackboard MCP initialize failed")

    # The production Blackboard MCP transport is stateless. The notification is
    # still sent so the relay follows the normal MCP initialization sequence.
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
        raise RuntimeError("Blackboard tool result has no structuredContent")
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
    issue_author = required_env("ISSUE_AUTHOR")
    repository_owner = required_env("REPOSITORY_OWNER")
    issue_body = os.environ.get("ISSUE_BODY", "")
    mcp_url = os.environ.get("BLACKBOARD_MCP_URL", DEFAULT_MCP_URL).strip() or DEFAULT_MCP_URL

    if issue_author.lower() != repository_owner.lower():
        print("Ignoring issue because the author is not the repository owner.")
        return 0

    try:
        request = parse_request(issue_body)
        tool, arguments = validate_request(request)
        result = call_blackboard(mcp_url, tool, arguments)
        add_issue_comment(repository, issue_number, "Conversation Blackboard result", result)
        close_issue(repository, issue_number)
        print(f"Gateway request completed with {tool}.")
        return 0
    except Exception as exc:  # Keep the issue open for inspection on failure.
        safe_message = str(exc)
        add_issue_comment(
            repository,
            issue_number,
            "Conversation Blackboard gateway error",
            {"error": safe_message},
        )
        print(f"Gateway request failed: {safe_message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
