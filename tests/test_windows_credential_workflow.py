import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SECRET_SCRIPT = (ROOT / "scripts" / "blackboard-secret.ps1").read_text(encoding="utf-8")
SUBMIT_SCRIPT = (ROOT / "scripts" / "blackboard-submit.ps1").read_text(encoding="utf-8")
DOC = (ROOT / "docs" / "windows-secret-store.md").read_text(encoding="utf-8")


class WindowsCredentialWorkflowTests(unittest.TestCase):
    def test_secret_store_uses_dpapi_current_user_primitives(self):
        self.assertIn("ConvertFrom-SecureString", SECRET_SCRIPT)
        self.assertIn("ConvertTo-SecureString", SECRET_SCRIPT)
        self.assertNotIn("-Key", SECRET_SCRIPT)
        self.assertNotIn("-SecureKey", SECRET_SCRIPT)
        self.assertIn("ConversationBlackboard\\credentials", SECRET_SCRIPT)

    def test_secret_helper_never_outputs_decrypted_secret(self):
        self.assertNotIn("Write-Output $Secret", SECRET_SCRIPT)
        self.assertNotIn("Write-Host $Secret", SECRET_SCRIPT)
        self.assertNotIn("Write-Output $plain", SECRET_SCRIPT)
        self.assertNotIn("Write-Host $plain", SECRET_SCRIPT)
        self.assertIn("stored: $ParticipantId", SECRET_SCRIPT)
        self.assertIn("ok: $ParticipantId", SECRET_SCRIPT)

    def test_submit_wrapper_scopes_secret_to_python_invocation(self):
        self.assertIn("$env:BLACKBOARD_PARTICIPANT_SECRET = $secret", SUBMIT_SCRIPT)
        self.assertIn("finally", SUBMIT_SCRIPT)
        self.assertIn("Remove-Item Env:BLACKBOARD_PARTICIPANT_SECRET", SUBMIT_SCRIPT)
        self.assertIn("blackboard-submit.py", SUBMIT_SCRIPT)
        self.assertNotIn("Write-Output $secret", SUBMIT_SCRIPT)
        self.assertNotIn("Write-Host $secret", SUBMIT_SCRIPT)

    def test_docs_define_seven_participants_and_totp_boundary(self):
        for participant in (
            "chatu-main",
            "cheng-main",
            "keda-main",
            "kegui-main",
            "maker-main",
            "rotary-main",
            "single-main",
        ):
            self.assertIn(participant, DOC)
        self.assertIn("TOTP", DOC)
        self.assertIn("only for `cheng-main`", DOC)


if __name__ == "__main__":
    unittest.main()
