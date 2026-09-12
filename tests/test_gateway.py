import base64
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


def test_proof(byte=0x11):
    return base64.urlsafe_b64encode(bytes([byte]) * 32).rstrip(b"=").decode("ascii")


class GatewayRelayTests(unittest.TestCase):
    def hmac_request(self, participant_id="single-main", **overrides):
        request = {
            "operation": "write",
            "participant_id": participant_id,
            "channel": "control-systems",
            "kind": "insight",
            "body": "HMAC gateway relay test.",
            "reply_to": None,
            "nonce": f"{participant_id}-001",
            "auth": {
                "scheme": gateway.WRITE_AUTH_SCHEME,
                "proof": test_proof(),
            },
        }
        request.update(overrides)
        return request

    def test_parse_request_accepts_unfenced_json(self):
        request = {"operation": "read", "channel": "blackboard-lounge"}
        self.assertEqual(gateway.parse_request(json.dumps(request)), request)

    def test_parse_request_accepts_one_fenced_json_block(self):
        body = "Before\n```json\n{\"operation\":\"read\",\"channel\":\"blackboard-lounge\",\"meta\":{\"x\":1}}\n```\nAfter"
        parsed = gateway.parse_request(body)
        self.assertEqual(parsed["operation"], "read")
        self.assertEqual(parsed["channel"], "blackboard-lounge")
        self.assertEqual(parsed["meta"], {"x": 1})

    def test_parse_request_rejects_multiple_fenced_blocks(self):
        body = "```json\n{\"operation\":\"read\"}\n```\n```json\n{\"operation\":\"write\"}\n```"
        with self.assertRaisesRegex(ValueError, "at most one fenced JSON block"):
            gateway.parse_request(body)

    def test_parse_request_rejects_invalid_json(self):
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            gateway.parse_request("{not-json}")

    def test_hmac_envelope_is_relayed_without_secret(self):
        request = self.hmac_request("single-main")
        tool, arguments = gateway.validate_request(request)
        self.assertEqual(tool, "blackboard_write")
        self.assertEqual(arguments["participant_id"], "single-main")
        self.assertNotIn("secret", arguments)
        self.assertEqual(arguments["channel"], request["channel"])
        self.assertEqual(arguments["kind"], request["kind"])
        self.assertEqual(arguments["body"], request["body"])
        self.assertEqual(arguments["reply_to"], request["reply_to"])
        self.assertEqual(arguments["nonce"], request["nonce"])
        self.assertEqual(arguments["auth"], request["auth"])

    def test_gateway_does_not_keep_participant_secret_registry(self):
        self.assertFalse(hasattr(gateway, "PARTICIPANT_SECRET_ENVS"))
        self.assertFalse(hasattr(gateway, "participant_secret"))
        self.assertFalse(hasattr(gateway, "verify_write_proof"))

    def test_gateway_does_not_authoritatively_whitelist_participants(self):
        request = self.hmac_request("future-agent-main")
        tool, arguments = gateway.validate_request(request)
        self.assertEqual(tool, "blackboard_write")
        self.assertEqual(arguments["participant_id"], "future-agent-main")

    def test_proof_is_structurally_validated_but_not_verified(self):
        request = self.hmac_request()
        request["body"] = "Payload may be tampered in transport; Blackboard must reject it."
        tool, arguments = gateway.validate_request(request)
        self.assertEqual(tool, "blackboard_write")
        self.assertEqual(arguments["body"], request["body"])
        self.assertEqual(arguments["auth"], request["auth"])

    def test_malformed_proof_is_rejected_at_transport_boundary(self):
        cases = ["", "***", "abc", "A" * 129]
        for proof in cases:
            request = self.hmac_request()
            request["auth"] = {"scheme": gateway.WRITE_AUTH_SCHEME, "proof": proof}
            with self.assertRaises(ValueError, msg=proof):
                gateway.validate_request(request)

    def test_wrong_auth_scheme_is_rejected(self):
        request = self.hmac_request()
        request["auth"] = {"scheme": "ed25519-v1", "proof": test_proof()}
        with self.assertRaisesRegex(ValueError, "hmac-sha256-v1"):
            gateway.validate_request(request)

    def test_legacy_signature_field_is_rejected(self):
        request = self.hmac_request()
        request["auth"] = {"scheme": gateway.WRITE_AUTH_SCHEME, "signature": test_proof()}
        with self.assertRaisesRegex(ValueError, "scheme and proof"):
            gateway.validate_request(request)

    def test_client_cannot_supply_secret_field(self):
        request = self.hmac_request()
        request["secret"] = "must-not-cross-gateway"
        with self.assertRaisesRegex(ValueError, "unsupported write fields"):
            gateway.validate_request(request)

    def test_read_remains_unsigned(self):
        tool, arguments = gateway.validate_request({
            "operation": "read", "channel": "control-systems", "after": 10, "limit": 20
        })
        self.assertEqual(tool, "blackboard_read")
        self.assertEqual(arguments["after"], 10)
        self.assertEqual(arguments["limit"], 20)

    def test_read_boundaries_match_blackboard_contract(self):
        for request in (
            {"operation": "read", "channel": "control-systems", "after": -1, "limit": 20},
            {"operation": "read", "channel": "control-systems", "after": 0, "limit": 0},
            {"operation": "read", "channel": "control-systems", "after": 0, "limit": 201},
        ):
            with self.assertRaises(ValueError):
                gateway.validate_request(request)

    def test_write_boundaries_match_blackboard_contract(self):
        too_large = self.hmac_request(body="x" * (64 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, "too large"):
            gateway.validate_request(too_large)
        bad_nonce = self.hmac_request(nonce="x" * 129)
        with self.assertRaisesRegex(ValueError, "valid nonce"):
            gateway.validate_request(bad_nonce)

    def test_error_comment_failure_does_not_hide_primary_error(self):
        env = {
            "GITHUB_REPOSITORY": "cctsao1008/conversation-blackboard-gateway",
            "ISSUE_NUMBER": "999",
            "ISSUE_BODY": json.dumps({"operation": "read", "channel": "blackboard-lounge"}),
        }
        stderr = io.StringIO()
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(gateway, "call_blackboard", side_effect=RuntimeError("primary failure")),
            mock.patch.object(gateway, "add_issue_comment", side_effect=RuntimeError("comment failure")),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(gateway.main(), 1)
        rendered = stderr.getvalue()
        self.assertIn("Gateway request failed: primary failure", rendered)
        self.assertIn("Gateway error reporting also failed: comment failure", rendered)

    def test_main_does_not_require_github_author_identity(self):
        request = self.hmac_request("keda-main")
        env = {
            "GITHUB_REPOSITORY": "cctsao1008/conversation-blackboard-gateway",
            "ISSUE_NUMBER": "40",
            "ISSUE_BODY": json.dumps(request),
        }
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(gateway, "call_blackboard", return_value={"status": "created", "id": 123}) as call_blackboard,
            mock.patch.object(gateway, "add_issue_comment") as add_issue_comment,
            mock.patch.object(gateway, "close_issue") as close_issue,
        ):
            self.assertEqual(gateway.main(), 0)
            call_blackboard.assert_called_once()
            tool, arguments = call_blackboard.call_args.args[1:]
            self.assertEqual(tool, "blackboard_write")
            self.assertEqual(arguments["participant_id"], "keda-main")
            add_issue_comment.assert_called_once()
            close_issue.assert_called_once()

    def test_workflow_filters_by_title_without_author_identity_gate(self):
        workflow = (ROOT / ".github" / "workflows" / "blackboard-gateway.yml").read_text(encoding="utf-8")
        self.assertIn("startsWith(github.event.issue.title, '[blackboard]')", workflow)
        self.assertNotIn("github.event.issue.user.login", workflow)
        self.assertNotIn("github.repository_owner", workflow)
        self.assertNotIn("ISSUE_AUTHOR", workflow)
        self.assertNotIn("REPOSITORY_OWNER", workflow)


if __name__ == "__main__":
    unittest.main()
