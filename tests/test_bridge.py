import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "blackboard_bridge", ROOT / "scripts" / "blackboard-bridge.py"
)
bridge = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(bridge)


def issue(number=9, participant_id="maker-main", author="cctsao1008"):
    return {
        "number": number,
        "title": "[blackboard-local] write blackboard-lounge",
        "body": json.dumps(
            {
                "participant_id": participant_id,
                "channel": "blackboard-lounge",
                "kind": "message",
                "body": "hello",
                "reply_to": None,
            }
        ),
        "author": {"login": author},
    }


class LocalBridgeTests(unittest.TestCase):
    def test_parse_valid_intent_and_derive_deterministic_nonce(self):
        intent = bridge.parse_intent(61, issue(61)["body"])
        self.assertEqual(intent["kind"], "message")
        self.assertIsNone(intent["reply_to"])
        self.assertEqual(intent["nonce"], "bridge-maker-main-61")

    def test_reject_unknown_fields(self):
        with self.assertRaisesRegex(ValueError, "unsupported intent fields"):
            bridge.parse_intent(
                1,
                json.dumps(
                    {
                        "participant_id": "maker-main",
                        "channel": "blackboard-lounge",
                        "body": "hello",
                        "secret": "must-not-exist",
                    }
                ),
            )

    def test_credential_path_rejects_path_traversal(self):
        with self.assertRaisesRegex(ValueError, "invalid participant_id"):
            bridge.credential_path(pathlib.Path("credentials"), "../maker-main")

    def test_sanitize_error_redacts_hmac_secret(self):
        rendered = bridge.sanitize_error("bad hmac-sha256-secret:abcdefghijklmnopqrstuvwxyz_0123456789-ABC")
        self.assertNotIn("hmac-sha256-secret:", rendered)
        self.assertIn("[REDACTED_SECRET]", rendered)

    def test_wrong_author_is_rejected_before_credential_or_submit(self):
        with tempfile.TemporaryDirectory() as root, \
             mock.patch.object(bridge, "has_bridge_comment", return_value=False), \
             mock.patch.object(bridge, "comment_issue") as comment, \
             mock.patch.object(bridge, "invoke_submitter") as submit:
            result = bridge.process_issue(
                issue(author="someone-else"),
                gh="gh",
                repository="owner/repo",
                allowed_author="cctsao1008",
                credential_root=pathlib.Path(root),
                powershell="powershell",
                submitter=pathlib.Path("blackboard-submit.ps1"),
            )
        self.assertEqual(result, "rejected-author")
        submit.assert_not_called()
        comment.assert_called_once()

    def test_missing_local_credential_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, \
             mock.patch.object(bridge, "has_bridge_comment", return_value=False), \
             mock.patch.object(bridge, "comment_issue") as comment, \
             mock.patch.object(bridge, "invoke_submitter") as submit:
            result = bridge.process_issue(
                issue(participant_id="new-main"),
                gh="gh",
                repository="owner/repo",
                allowed_author="cctsao1008",
                credential_root=pathlib.Path(root),
                powershell="powershell",
                submitter=pathlib.Path("blackboard-submit.ps1"),
            )
        self.assertEqual(result, "rejected-no-credential")
        submit.assert_not_called()
        self.assertIn("no local DPAPI credential", comment.call_args.args[3])

    def test_existing_credential_allows_dynamic_participant_without_allowlist(self):
        with tempfile.TemporaryDirectory() as root:
            credential_root = pathlib.Path(root)
            (credential_root / "new-main.dpapi").write_text("encrypted", encoding="utf-8")
            with mock.patch.object(
                bridge,
                "invoke_submitter",
                return_value="https://github.com/cctsao1008/conversation-blackboard-gateway/issues/999",
            ) as submit, mock.patch.object(bridge, "comment_issue") as comment, mock.patch.object(
                bridge, "close_issue"
            ) as close:
                result = bridge.process_issue(
                    issue(participant_id="new-main"),
                    gh="gh",
                    repository="owner/repo",
                    allowed_author="cctsao1008",
                    credential_root=credential_root,
                    powershell="powershell",
                    submitter=pathlib.Path("blackboard-submit.ps1"),
                )
        self.assertEqual(result, "submitted")
        submit.assert_called_once()
        self.assertEqual(submit.call_args.args[3], credential_root)
        comment.assert_called_once()
        close.assert_called_once_with("gh", "owner/repo", 9)

    def test_submit_failure_is_reported_without_closing(self):
        with tempfile.TemporaryDirectory() as root:
            credential_root = pathlib.Path(root)
            (credential_root / "maker-main.dpapi").write_text("encrypted", encoding="utf-8")
            error = subprocess.CalledProcessError(
                1,
                ["powershell"],
                stderr="failed hmac-sha256-secret:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            )
            with mock.patch.object(bridge, "invoke_submitter", side_effect=error), mock.patch.object(
                bridge, "has_bridge_comment", return_value=False
            ), mock.patch.object(bridge, "comment_issue") as comment, mock.patch.object(
                bridge, "close_issue"
            ) as close:
                result = bridge.process_issue(
                    issue(),
                    gh="gh",
                    repository="owner/repo",
                    allowed_author="cctsao1008",
                    credential_root=credential_root,
                    powershell="powershell",
                    submitter=pathlib.Path("blackboard-submit.ps1"),
                )
        self.assertEqual(result, "submit-failed")
        close.assert_not_called()
        rendered = comment.call_args.args[3]
        self.assertNotIn("hmac-sha256-secret:", rendered)
        self.assertIn("[REDACTED_SECRET]", rendered)


if __name__ == "__main__":
    unittest.main()
