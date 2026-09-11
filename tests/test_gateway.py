import base64
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("gateway", ROOT / "scripts" / "gateway.py")
gateway = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(gateway)


def test_signature(byte=0x11):
    return base64.urlsafe_b64encode(bytes([byte]) * 64).rstrip(b"=").decode("ascii")


class GatewayRelayTests(unittest.TestCase):
    def signed_request(self, participant_id="single-main", **overrides):
        request = {
            "operation": "write",
            "participant_id": participant_id,
            "channel": "control-systems",
            "kind": "insight",
            "body": "Signed gateway relay test.",
            "reply_to": None,
            "nonce": f"{participant_id}-001",
            "auth": {
                "scheme": gateway.WRITE_AUTH_SCHEME,
                "signature": test_signature(),
            },
        }
        request.update(overrides)
        return request

    def test_signed_envelope_is_relayed_without_private_key(self):
        request = self.signed_request("single-main")
        tool, arguments = gateway.validate_request(request)
        self.assertEqual(tool, "blackboard_write")
        self.assertEqual(arguments["participant_id"], "single-main")
        self.assertNotIn("private_key", arguments)
        self.assertEqual(arguments["channel"], request["channel"])
        self.assertEqual(arguments["kind"], request["kind"])
        self.assertEqual(arguments["body"], request["body"])
        self.assertEqual(arguments["reply_to"], request["reply_to"])
        self.assertEqual(arguments["nonce"], request["nonce"])
        self.assertEqual(arguments["auth"], request["auth"])

    def test_gateway_does_not_keep_participant_secret_registry(self):
        self.assertFalse(hasattr(gateway, "PARTICIPANT_KEY_ENVS"))
        self.assertFalse(hasattr(gateway, "participant_private_key"))
        self.assertFalse(hasattr(gateway, "verify_write_signature"))

    def test_gateway_does_not_authoritatively_whitelist_participants(self):
        request = self.signed_request("future-agent-main")
        tool, arguments = gateway.validate_request(request)
        self.assertEqual(tool, "blackboard_write")
        self.assertEqual(arguments["participant_id"], "future-agent-main")

    def test_signature_is_structurally_validated_but_not_verified(self):
        request = self.signed_request()
        request["body"] = "Payload may be tampered in transport; Blackboard must reject it."
        tool, arguments = gateway.validate_request(request)
        self.assertEqual(tool, "blackboard_write")
        self.assertEqual(arguments["body"], request["body"])
        self.assertEqual(arguments["auth"], request["auth"])

    def test_malformed_signature_is_rejected_at_transport_boundary(self):
        cases = ["", "***", "abc", "A" * 129]
        for signature in cases:
            request = self.signed_request()
            request["auth"] = {"scheme": gateway.WRITE_AUTH_SCHEME, "signature": signature}
            with self.assertRaises(ValueError, msg=signature):
                gateway.validate_request(request)

    def test_wrong_signature_scheme_is_rejected(self):
        request = self.signed_request()
        request["auth"] = {"scheme": "hmac-sha256-v1", "signature": test_signature()}
        with self.assertRaisesRegex(ValueError, "ed25519-v1"):
            gateway.validate_request(request)

    def test_client_cannot_supply_private_key_field(self):
        request = self.signed_request()
        request["private_key"] = "must-not-cross-gateway"
        with self.assertRaisesRegex(ValueError, "unsupported write fields"):
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
