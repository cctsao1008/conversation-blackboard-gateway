#!/usr/bin/env python3
"""Read-only GitHub Issue adapter for Conversation Blackboard.

Writes no longer transit GitHub Actions. A `[blackboard]` Issue is delivered by
GitHub's signed webhook directly to Conversation Blackboard, where GitHub actor
identity is matched to the requested participant owner.

This script remains only for `[blackboard-read]` Issue requests that need an
Action result comment.
"""

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
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
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


def validate_read_request(request: dict[str, Any]) -> dict[str, Any]:
    allowed = {"channel", "after", "limit"}
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
    return {"channel": channel, "after": after, "limit": limit}


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
            "User-Agent": "conversation-blackboard-gateway/0.5",
        },
    )


def call_blackboard_read(mcp_url: str, arguments: dict[str, Any]) -> dict[str, Any]:
    _, initialized = mcp_post(
        mcp_url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "conversation-blackboard-gateway", "version": "0.5.0"},
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
            "params": {"name": "blackboard_read", "arguments": arguments},
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
        arguments = validate_read_request(parse_request(issue_body))
        result = call_blackboard_read(mcp_url, arguments)
        add_issue_comment(repository, issue_number, "Conversation Blackboard read result", result)
        close_issue(repository, issue_number)
        print("Gateway read request completed.")
        return 0
    except Exception as exc:
        safe_message = str(exc)
        print(f"Gateway read request failed: {safe_message}", file=sys.stderr)
        try:
            add_issue_comment(
                repository,
                issue_number,
                "Conversation Blackboard gateway error",
                {"error": safe_message},
            )
        except Exception as report_exc:
            print(f"Gateway error reporting also failed: {report_exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
