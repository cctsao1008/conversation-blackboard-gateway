import base64
import hashlib
import hmac
import importlib.util
import io
import json
import os
import pathlib
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "blackboard_submit", ROOT / "scripts" / "blackboard-submit.py"
)
submitter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(submitter)


def secret(byte=0x22):
    encoded = base64.urlsafe_b64encode(bytes([byte]) * 32).rstrip(b"=").decode("ascii")
    return f"{submitter.SECRET_PREFIX}{encoded}"


class LocalHmacSubmitterTests(unittest.TestCase):
    def test_canonicalization_matches_blackboard_contract(self):
        payload = submitter.canonical_write_payload(
            "maker-main",
            "blackboard-lounge",
            "message",
            "hello",
            None,
            "maker-001",
        )
        canonical = submitter.canonical_write_bytes(payload).decode("utf-8")
        self.assertEqual(
            canonical,
            '{"auth_version":"hmac-sha256-v1","body":"hello","channel":"blackboard-lounge","kind":"message","nonce":"maker-001","participant_id":"maker-main","reply_to":null}',
        )

    def test_proof_generation_matches_independent_hmac(self):
        participant_secret = secret()
        payload = submitter.canonical_write_payload(
            "maker-main",
            "blackboard-lounge",
            "message",
            "繁體中文 payload",
            17,
            "maker-002",
        )
        proof = submitter.compute_proof(participant_secret, payload)
        key = bytes([0x22]) * 32
        expected = base64.urlsafe_b64encode(
            hmac.new(
                key,
                submitter.canonical_write_bytes(payload),
                hashlib.sha256,
            ).digest()
        ).rstrip(b"=").decode("ascii")
        self.assertEqual(proof, expected)

    def test_malformed_secret_is_rejected(self):
        for value in (
            "",
            "not-a-secret",
            f"{submitter.SECRET_PREFIX}abc",
            f"{submitter.SECRET_PREFIX}***",
        ):
            with self.assertRaises(ValueError, msg=value):
                submitter.decode_secret(value)

    def test_gateway_request_never_contains_secret(self):
        participant_secret = secret()
        request = submitter.build_gateway_request(
            participant_secret,
            "maker-main",
            "blackboard-lounge",
            "message",
            "hello",
            nonce="maker-003",
        )
        rendered = json.dumps(request, ensure_ascii=False)
        self.assertNotIn(participant_secret, rendered)
        self.assertNotIn("secret", request)
        self.assertEqual(request["auth"]["scheme"], submitter.AUTH_SCHEME)
        self.assertEqual(len(request["auth"]["proof"]), 43)

    def test_explicit_nonce_and_reply_to_are_preserved(self):
        request = submitter.build_gateway_request(
            secret(),
            "maker-main",
            "blackboard-lounge",
            "insight",
            "reply",
            reply_to=42,
            nonce="maker-fixed-004",
        )
        self.assertEqual(request["nonce"], "maker-fixed-004")
        self.assertEqual(request["reply_to"], 42)

    def test_generated_nonce_satisfies_contract(self):
        request = submitter.build_gateway_request(
            secret(),
            "maker-main",
            "blackboard-lounge",
            "message",
            "hello",
        )
        self.assertRegex(request["nonce"], submitter.NONCE_RE)
        self.assertTrue(request["nonce"].startswith("maker-main-"))

    def test_dry_run_prints_request_shape_without_submission(self):
        env = {submitter.DEFAULT_SECRET_ENV: secret()}
        stdout = io.StringIO()
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(submitter, "submit_issue") as submit_issue,
            redirect_stdout(stdout),
        ):
            rc = submitter.main(
                [
                    "--participant-id",
                    "maker-main",
                    "--channel",
                    "blackboard-lounge",
                    "--body",
                    "dry run",
                    "--nonce",
                    "maker-dry-005",
                    "--dry-run",
                ]
            )
        self.assertEqual(rc, 0)
        submit_issue.assert_not_called()
        request = json.loads(stdout.getvalue())
        self.assertEqual(request["operation"], "write")
        self.assertEqual(request["participant_id"], "maker-main")
        self.assertEqual(request["channel"], "blackboard-lounge")
        self.assertEqual(request["nonce"], "maker-dry-005")
        self.assertEqual(set(request["auth"]), {"scheme", "proof"})

    def test_submitter_strips_secret_from_gh_child_environment(self):
        request = submitter.build_gateway_request(
            secret(),
            "maker-main",
            "blackboard-lounge",
            "message",
            "hello",
            nonce="maker-006",
        )
        with (
            mock.patch.dict(
                os.environ,
                {submitter.DEFAULT_SECRET_ENV: secret(), "KEEP_ME": "yes"},
                clear=True,
            ),
            mock.patch.object(submitter.shutil, "which", return_value="gh"),
            mock.patch.object(submitter.subprocess, "run") as run,
        ):
            run.return_value.stdout = "https://github.com/example/issues/1\n"
            url = submitter.submit_issue(
                request,
                submitter.DEFAULT_REPOSITORY,
                submitter.DEFAULT_SECRET_ENV,
            )
        self.assertEqual(url, "https://github.com/example/issues/1")
        child_env = run.call_args.kwargs["env"]
        self.assertNotIn(submitter.DEFAULT_SECRET_ENV, child_env)
        self.assertEqual(child_env["KEEP_ME"], "yes")
        argv = run.call_args.args[0]
        self.assertNotIn(secret(), argv)


if __name__ == "__main__":
    unittest.main()
