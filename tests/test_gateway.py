import contextlib
import importlib.util
import io
import json
import os
import pathlib
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("gateway", ROOT / "scripts" / "gateway.py")
gateway = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(gateway)


class GatewayReadMailboxTests(unittest.TestCase):
    def test_parse_request_accepts_unfenced_json(self):
        request = {"channel": "blackboard-lounge", "after": 0, "limit": 20}
        self.assertEqual(gateway.parse_request(json.dumps(request)), request)

    def test_parse_request_accepts_one_fenced_json_block(self):
        body = "Before\n```json\n{\"channel\":\"blackboard-lounge\",\"after\":0}\n```\nAfter"
        parsed = gateway.parse_request(body)
        self.assertEqual(parsed["channel"], "blackboard-lounge")
        self.assertEqual(parsed["after"], 0)

    def test_parse_request_rejects_multiple_fenced_blocks(self):
        body = "```json\n{\"channel\":\"one\"}\n```\n```json\n{\"channel\":\"two\"}\n```"
        with self.assertRaisesRegex(ValueError, "at most one fenced JSON block"):
            gateway.parse_request(body)

    def test_parse_request_rejects_invalid_json(self):
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            gateway.parse_request("{not-json}")

    def test_read_request_defaults_match_blackboard_contract(self):
        arguments = gateway.validate_read_request({"channel": "control-systems"})
        self.assertEqual(
            arguments,
            {"channel": "control-systems", "after": 0, "limit": 50},
        )

    def test_read_request_rejects_unknown_or_invalid_fields(self):
        cases = (
            {"channel": "control-systems", "participant_id": "maker-main"},
            {"channel": "control-systems", "after": -1},
            {"channel": "control-systems", "limit": 0},
            {"channel": "control-systems", "limit": 201},
            {"channel": "bad channel"},
        )
        for request in cases:
            with self.assertRaises(ValueError, msg=request):
                gateway.validate_read_request(request)

    def test_current_action_path_has_no_write_auth_surface(self):
        self.assertFalse(hasattr(gateway, "WRITE_AUTH_SCHEME"))
        self.assertFalse(hasattr(gateway, "validate_proof_encoding"))
        self.assertFalse(hasattr(gateway, "validate_request"))
        self.assertFalse(hasattr(gateway, "call_blackboard"))

    def test_error_comment_failure_does_not_hide_primary_error(self):
        env = {
            "GITHUB_REPOSITORY": "cctsao1008/conversation-blackboard-gateway",
            "ISSUE_NUMBER": "999",
            "ISSUE_BODY": json.dumps({"channel": "blackboard-lounge"}),
        }
        stderr = io.StringIO()
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(
                gateway,
                "call_blackboard_read",
                side_effect=RuntimeError("primary failure"),
            ),
            mock.patch.object(
                gateway,
                "add_issue_comment",
                side_effect=RuntimeError("comment failure"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(gateway.main(), 1)
        rendered = stderr.getvalue()
        self.assertIn("Gateway read request failed: primary failure", rendered)
        self.assertIn("Gateway error reporting also failed: comment failure", rendered)

    def test_main_relays_only_blackboard_read(self):
        env = {
            "GITHUB_REPOSITORY": "cctsao1008/conversation-blackboard-gateway",
            "ISSUE_NUMBER": "40",
            "ISSUE_BODY": json.dumps(
                {"channel": "blackboard-lounge", "after": 10, "limit": 20}
            ),
        }
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(
                gateway,
                "call_blackboard_read",
                return_value={"messages": []},
            ) as call_blackboard_read,
            mock.patch.object(gateway, "add_issue_comment") as add_issue_comment,
            mock.patch.object(gateway, "close_issue") as close_issue,
        ):
            self.assertEqual(gateway.main(), 0)
            call_blackboard_read.assert_called_once_with(
                gateway.DEFAULT_MCP_URL,
                {"channel": "blackboard-lounge", "after": 10, "limit": 20},
            )
            add_issue_comment.assert_called_once()
            close_issue.assert_called_once()

    def test_workflow_is_read_only_and_write_prefix_is_not_action_relayed(self):
        workflow = (
            ROOT / ".github" / "workflows" / "blackboard-gateway.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("startsWith(github.event.issue.title, '[blackboard-read]')", workflow)
        self.assertNotIn("startsWith(github.event.issue.title, '[blackboard]')", workflow)
        self.assertIn("Relay read request to Conversation Blackboard", workflow)


if __name__ == "__main__":
    unittest.main()
