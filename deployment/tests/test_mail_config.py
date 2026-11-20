"""Private provider configuration stays data and cannot alter auth policy."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

_CONFIG = Path(__file__).resolve().parents[1] / "mail_config.py"
_SERVICES = _CONFIG.with_name("services.sh")
_spec = importlib.util.spec_from_file_location("mail_config_under_test", _CONFIG)
_tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tool)


class PrivateMailConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "mail.json"

    def write(self, data):
        self.path.write_text(json.dumps(data), encoding="utf-8")
        self.path.chmod(0o600)
        return self.path

    def test_quoted_values_round_trip_without_command_execution(self):
        marker = self.root / "executed"
        value = f"CryoStack 'quote' \"double\" $(touch {marker}) `touch {marker}`;\nsecond line"
        self.write({"CRYOSTACK_MAIL_FROM": value, "CRYOSTACK_MAIL_MODE": "resend"})
        script = _tool.exports(self.path)
        script += "\nexec " + shlex.quote(sys.executable) + " -c " + shlex.quote(
            "import json,os; print(json.dumps({k:os.environ[k] for k in "
            "('CRYOSTACK_MAIL_FROM','CRYOSTACK_MAIL_MODE')}))")
        result = subprocess.run(["/bin/bash", "-c", script], check=True,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(json.loads(result.stdout), {
            "CRYOSTACK_MAIL_FROM": value, "CRYOSTACK_MAIL_MODE": "resend"})
        self.assertFalse(marker.exists())

    def test_configuration_cannot_override_auth_or_arbitrary_settings(self):
        for key in ("CRYOSTACK_REGISTRATION_APPROVAL", "CRYOSTACK_APPROVAL_OWNER_ONLY",
                    "CRYOSTACK_APPROVAL_ADMIN_EMAILS", "PATH", "BASH_ENV"):
            with self.subTest(key=key):
                self.write({"CRYOSTACK_MAIL_MODE": "postmark", key: "0"})
                with self.assertRaises(ValueError):
                    _tool.exports(self.path)

    def test_gt_tls_policy_is_a_permitted_mail_only_setting(self):
        self.write({"CRYOSTACK_SMTP_TLS_POLICY": "gt-relay-exception"})
        self.assertIn("export CRYOSTACK_SMTP_TLS_POLICY=gt-relay-exception", _tool.exports(self.path))

    def test_only_string_values_without_nul_are_accepted(self):
        for value in (None, True, 587, ["resend"], {"mode": "resend"}, "resend\0smtp"):
            with self.subTest(value=value):
                self.write({"CRYOSTACK_MAIL_MODE": value})
                with self.assertRaises(ValueError):
                    _tool.exports(self.path)
        for document in ([], "resend", None):
            with self.subTest(document=document):
                self.write(document)
                with self.assertRaises(ValueError):
                    _tool.exports(self.path)

    def test_group_or_world_readable_configuration_is_rejected(self):
        self.write({"CRYOSTACK_MAIL_MODE": "resend"})
        for mode in (0o640, 0o604, 0o644):
            with self.subTest(mode=oct(mode)):
                self.path.chmod(mode)
                with self.assertRaises(ValueError):
                    _tool.exports(self.path)

    def test_symlink_and_fifo_are_rejected_without_blocking(self):
        target = self.root / "target.json"
        target.write_text('{}', encoding="utf-8")
        target.chmod(0o600)
        self.path.symlink_to(target)
        with self.assertRaises(OSError):
            _tool.exports(self.path)
        self.path.unlink()
        os.mkfifo(self.path, 0o600)
        # A FIFO has no writer: O_NONBLOCK must prevent an indefinite wait.
        with self.assertRaises(ValueError):
            _tool.exports(self.path)

    def test_oversized_configuration_is_rejected(self):
        self.write({"CRYOSTACK_MAIL_FROM": "x" * 65537})
        with self.assertRaises(ValueError):
            _tool.exports(self.path)

    def test_cli_error_does_not_echo_configuration_values(self):
        self.path.write_text('{"secret-provider-token": "not-json', encoding="utf-8")
        self.path.chmod(0o600)
        result = subprocess.run([sys.executable, str(_CONFIG), str(self.path)],
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("Cannot load private mail configuration", result.stderr)
        self.assertNotIn("secret-provider-token", result.stderr)
        self.assertNotIn("not-json", result.stderr)

    def test_stop_and_status_skip_invalid_mail_config_without_service_effects(self):
        deployment = self.root / "deployment"
        deployment.mkdir()
        script = deployment / "services.sh"
        shutil.copyfile(_SERVICES, script)
        self.write({"CRYOSTACK_REGISTRATION_APPROVAL": "0"})
        marker = self.root / "loader-was-called"
        no_effects = self.root / "bash-env.sh"
        # Intercept every service/process operation. An invalid mail file must
        # not prevent an operator from stopping services or inspecting status.
        no_effects.write_text(
            "pgrep() { return 1; }\n"
            "pkill() { return 0; }\n"
            "kill() { return 0; }\n"
            "ps() { return 0; }\n"
            "sleep() { return 0; }\n"
            "python3() { touch " + shlex.quote(str(marker)) + "; return 99; }\n",
            encoding="utf-8")
        env = dict(os.environ, BASH_ENV=str(no_effects),
                   CRYOSTACK_RELAY_CONTROL_TOKEN="isolated-test-token",
                   CRYOSTACK_MAIL_CONFIG_FILE=str(self.path))
        for action in ("stop", "status"):
            with self.subTest(action=action):
                result = subprocess.run(["/bin/bash", str(script), action], env=env,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(marker.exists())
                self.assertNotIn("Cannot load private mail configuration", result.stderr)


if __name__ == "__main__":
    unittest.main()
