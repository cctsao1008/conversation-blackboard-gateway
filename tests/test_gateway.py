import hashlib
import hmac
import importlib.util
import json
import os
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("gateway", ROOT / "scripts" / "gateway.py")
gateway = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(gateway)


class GatewayIdentityTests(unittest.TestCase):
    def setUp(self):
        self.single_key = "single-test-key"
        self.rotary_key = "rotary-test-key"
        os.environ["BLACKBOARD_SINGLE_MAIN_KEY"] = self.single_key
        os.environ["BLACKBOARD_ROTARY_MAIN_KEY"] = self.rotary_key

    def tearDown(self):
        os.environ.pop("BLACKBOARD_SINGLE_MAIN_KEY", None)
        os.environ.pop("BLACKBOARD_ROTARY_MAIN_KEY", None)

    def signed_request(self, participant_id, key, **overrides):
        request = {
            "operation": "write",
            "participant_id": participant_id,
            "channel": "control-systems",
            "kind": "insight",
            "body": "Signed gateway identity test.",
            "reply_to": None,
            "nonce": f"{participant_id}-001",
        }
        request.update(overrides)
        payload = gateway.canonical_write_payload(
            request["participant_id"],
            request["channel"],
            request["kind"],
            request["body"],
            request["reply_to"],
            request["nonce"],
        )
        canonical = gateway.canonical_json(payload)
        signature = hmac.new(key.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        request["auth"] = {
            "scheme": gateway.WRITE_AUTH_SCHEME,
            "signature": signature,
        }
        return request

    def test_single_signature_selects_single_identity(self):
        tool, arguments = gateway.validate_request(
            self.signed_request("single-main", self.single_key)
        )
        self.assertEqual(tool, "blackboard_write")
        self.assertEqual(arguments["participant_id"], "single-main")
        self.assertEqual(arguments["private_key"], self.single_key)

    def test_rotary_signature_selects_rotary_identity(self):
        tool, arguments = gateway.validate_request(
            self.signed_request("rotary-main", self.rotary_key)
        )
        self.assertEqual(tool, "blackboard_write")
        self.assertEqual(arguments["participant_id"], "rotary-main")
        self.assertEqual(arguments["private_key"], self.rotary_key)

    def test_single_key_cannot_forge_rotary_identity(self):
        request = self.signed_request("rotary-main", self.single_key)
        with self.assertRaisesRegex(ValueError, "invalid write signature"):
            gateway.validate_request(request)

    def test_signature_binds_message_body(self):
        request = self.signed_request("single-main", self.single_key)
        request["body"] = "Tampered body."
        with self.assertRaisesRegex(ValueError, "invalid write signature"):
            gateway.validate_request(request)

    def test_read_remains_unsigned(self):
        tool, arguments = gateway.validate_request(
            {
                "operation": "read",
                "channel": "control-systems",
                "after": 10,
                "limit": 20,
            }
        )
        self.assertEqual(tool, "blackboard_read")
        self.assertEqual(arguments["after"], 10)
        self.assertEqual(arguments["limit"], 20)


if __name__ == "__main__":
    unittest.main()
