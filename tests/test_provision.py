"""USB setup regressions using synthetic credentials and fake serial ports only."""

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location(
    "inquiry_provision_test", Path(__file__).resolve().parents[1] / "PhilosophyPod/provision.py",
)
provision = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provision)


class SerialFailure(Exception):
    pass


def port(device, vid=0x303A, pid=0x1001):
    return SimpleNamespace(device=device, vid=vid, pid=pid, description="Synthetic test device")


class FakeSerial:
    def __init__(self, lines=()):
        self.lines = iter(lines)
        self.written = []
        self.closed = False
        self.opened = False

    def open(self):
        self.opened = True

    def close(self):
        self.closed = True

    def reset_input_buffer(self):
        pass

    def readline(self):
        return next(self.lines, b"")

    def write(self, value):
        self.written.append(value)

    def flush(self):
        pass


class ProvisionTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_foreground_honors_ssid_environment_password_host_and_ports(self):
        with patch.dict(os.environ, {
            provision.PASSWORD_ENV: "synthetic-password",
            provision.TOKEN_ENV: "synthetic-token",
        }), patch.object(provision, "send_to_device", return_value=True) as send, \
                patch("builtins.input", side_effect=AssertionError("Unexpected prompt")), \
                patch.object(provision, "get_wifi_password", side_effect=AssertionError("Keychain accessed")), \
                redirect_stdout(io.StringIO()):
            result = provision.main(["--ssid", "Synthetic WiFi", "--host", "192.0.2.10",
                                     "--port", "8002", "--serial-port", "COM3"])
        self.assertEqual(result, 0)
        payload = json.loads(send.call_args.args[0])
        self.assertEqual(payload, {"ssid": "Synthetic WiFi", "password": "synthetic-password",
                                   "ota_url": "http://192.0.2.10:8002/xiaozhi/ota/", "token": "synthetic-token"})
        self.assertEqual(send.call_args.kwargs["serial_port"], "COM3")

    def test_foreground_prompts_only_for_missing_fields(self):
        with patch.object(provision.sys, "platform", "linux"), \
                patch.object(provision.getpass, "getpass", return_value="synthetic-password") as hidden, \
                patch.object(provision, "get_local_ip", return_value=None), \
                patch.object(provision, "get_wifi_ssid", side_effect=AssertionError("SSID was already supplied")), \
                patch("builtins.input", return_value="192.0.2.11") as prompt, \
                patch.object(provision, "send_to_device", return_value=True), redirect_stdout(io.StringIO()):
            self.assertEqual(provision.main(["--ssid", "Synthetic WiFi"]), 0)
        self.assertEqual(prompt.call_count, 1)
        self.assertIn("Server LAN address", prompt.call_args.args[0])
        hidden.assert_called_once()

    def test_background_never_falls_back_to_prompts(self):
        with patch("builtins.input", side_effect=AssertionError("Background mode prompted")), \
                redirect_stderr(io.StringIO()) as error:
            with self.assertRaises(SystemExit) as raised:
                provision.main(["--bg", "--ssid", "Synthetic WiFi"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("no interactive fallback", error.getvalue())

    def test_background_explicit_host_and_bridge_port(self):
        with patch.dict(os.environ, {provision.PASSWORD_ENV: "synthetic-password"}), \
                patch.object(provision, "send_to_device", return_value=True) as send, \
                patch.object(provision, "get_local_ip", side_effect=AssertionError("Explicit host ignored")), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(provision.main(["--bg", "--ssid", "Synthetic WiFi", "--host", "192.0.2.12",
                                             "--port", "8002", "--serial-port", "/dev/synthetic"]), 0)
        self.assertEqual(json.loads(send.call_args.args[0])["ota_url"], "http://192.0.2.12:8002/xiaozhi/ota/")
        self.assertEqual(send.call_args.kwargs, {"quiet": True, "serial_port": "/dev/synthetic"})

    def test_background_missing_non_macos_host_has_actionable_error(self):
        with patch.dict(os.environ, {provision.PASSWORD_ENV: "synthetic-password"}), \
                patch.object(provision.sys, "platform", "linux"), \
                patch("builtins.input", side_effect=AssertionError("Background mode prompted")), \
                patch.object(provision, "send_to_device", side_effect=AssertionError("USB accessed")), \
                redirect_stderr(io.StringIO()) as error:
            self.assertEqual(provision.main(["--bg", "--ssid", "Synthetic WiFi"]), 1)
        self.assertIn("--host", error.getvalue())

    def test_keychain_lookup_requires_consent(self):
        with patch.object(provision.sys, "platform", "darwin"), \
                patch("builtins.input", return_value="n"), \
                patch.object(provision, "get_wifi_password", side_effect=AssertionError("Unapproved Keychain lookup")), \
                patch.object(provision.getpass, "getpass", return_value="synthetic-password"), \
                patch.object(provision, "send_to_device", return_value=True), redirect_stdout(io.StringIO()):
            self.assertEqual(provision.main(["--ssid", "Synthetic WiFi", "--host", "192.0.2.10"]), 0)

    def test_multiple_matching_devices_fail_before_open_or_write(self):
        fake_api = SimpleNamespace(Serial=Mock(), SerialException=SerialFailure)
        with patch.object(provision, "available_ports", return_value=[port("COM3"), port("COM4")]), \
                patch.object(provision, "serial", fake_api):
            with self.assertRaisesRegex(RuntimeError, "Multiple compatible devices"):
                provision.send_to_device("synthetic-payload")
        fake_api.Serial.assert_not_called()

    def test_unknown_device_requires_explicit_serial_port(self):
        with patch.object(provision, "available_ports", return_value=[port("COM8", 1, 2)]):
            self.assertIsNone(provision.find_serial_port())
            self.assertEqual(provision.find_serial_port("COM8"), "COM8")
            self.assertIsNone(provision.find_serial_port("COM9"))

    def test_native_device_selected_among_unrelated_serial_ports(self):
        with patch.object(provision, "available_ports", return_value=[port("COM1", 1, 2), port("COM3")]):
            self.assertEqual(provision.find_serial_port(), "COM3")

    def test_successful_handshake_sends_payload_without_echoing_device_logs(self):
        device = FakeSerial([b"synthetic-password should never be logged\n", b"PROVISION_AVAILABLE\n",
                             b"synthetic-token should never be logged\n", b"PROVISION_OK\n"])
        fake_api = SimpleNamespace(Serial=lambda: device, SerialException=SerialFailure)
        with patch.object(provision, "serial", fake_api), \
                patch.object(provision, "find_serial_port", return_value="COM3"), \
                patch.object(provision.time, "sleep"), redirect_stdout(io.StringIO()) as output:
            self.assertTrue(provision.send_to_device("synthetic-payload"))
        self.assertEqual(device.written, [b"PROVISION\n", b"synthetic-payload\n"])
        self.assertTrue(device.closed)
        self.assertNotIn("synthetic-password", output.getvalue())
        self.assertNotIn("synthetic-token", output.getvalue())

    def test_missing_handshake_closes_port_and_sends_nothing(self):
        device = FakeSerial()
        fake_api = SimpleNamespace(Serial=lambda: device, SerialException=SerialFailure)
        with patch.object(provision, "serial", fake_api), \
                patch.object(provision, "find_serial_port", return_value="COM3"), \
                patch.object(provision, "_read_marker", return_value=False), \
                patch.object(provision.time, "sleep"), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "No credentials were sent"):
                provision.send_to_device("synthetic-payload")
        self.assertEqual(device.written, [])
        self.assertTrue(device.closed)

    def test_serial_error_closes_port_and_reports_actionable_error(self):
        device = FakeSerial()
        device.open = Mock(side_effect=SerialFailure("sensitive diagnostic must not be echoed"))
        fake_api = SimpleNamespace(Serial=lambda: device, SerialException=SerialFailure)
        with patch.object(provision, "serial", fake_api), \
                patch.object(provision, "find_serial_port", return_value="COM3"), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "Close any serial monitor") as raised:
                provision.send_to_device("synthetic-payload")
        self.assertNotIn("sensitive diagnostic", str(raised.exception))
        self.assertTrue(device.closed)

    def test_marker_requires_an_exact_line(self):
        device = FakeSerial([b"not a real PROVISION_AVAILABLE handshake\n"])
        with patch.object(provision.time, "monotonic", side_effect=[0, 0, 2]):
            self.assertFalse(provision._read_marker(device, "PROVISION_AVAILABLE", 2))

    def test_listing_ports_does_not_read_credentials_or_open_ports(self):
        read_environment = provision.os.environ.get

        def reject_credentials(key, default=None):
            if key in (provision.PASSWORD_ENV, provision.TOKEN_ENV):
                raise AssertionError("Credentials read")
            return read_environment(key, default)

        with patch.object(provision, "available_ports", return_value=[port("COM3")]), \
                patch.object(provision.os.environ, "get", side_effect=reject_credentials), \
                patch.object(provision, "send_to_device", side_effect=AssertionError("Port opened")), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(provision.main(["--list-ports"]), 0)
        self.assertIn("COM3", output.getvalue())
        self.assertIn("303a:1001", output.getvalue())

    def test_missing_pyserial_has_clear_diagnostic(self):
        with patch.object(provision, "serial", None), patch.object(provision, "list_ports", None), \
                redirect_stderr(io.StringIO()) as output:
            self.assertEqual(provision.main(["--list-ports"]), 1)
        self.assertIn("requirements-device.txt", output.getvalue())

    def test_platform_helpers_do_not_run_macos_commands_elsewhere(self):
        with patch.object(provision.sys, "platform", "win32"), \
                patch.object(provision.subprocess, "run", side_effect=AssertionError("macOS command executed")):
            self.assertIsNone(provision.get_wifi_ssid())
            self.assertIsNone(provision.get_wifi_password("Synthetic WiFi"))
            self.assertIsNone(provision.get_local_ip())

    def test_unavailable_macos_helpers_are_optional(self):
        with patch.object(provision.sys, "platform", "darwin"), \
                patch.object(provision.subprocess, "run", side_effect=FileNotFoundError):
            self.assertIsNone(provision.get_wifi_ssid())
            self.assertIsNone(provision.get_local_ip())

    def test_server_address_and_port_validation(self):
        self.assertEqual(provision.ota_url("[2001:db8::1]", 8002), "http://[2001:db8::1]:8002/xiaozhi/ota/")
        for host in ("", "http://192.0.2.1", "user:password@host", "host/path", "bad host"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                provision.ota_url(host, 8000)
        for value in ("0", "65536", "bad"):
            with self.subTest(port=value), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                provision.main(["--port", value, "--list-ports"])

    def test_oversized_payload_rejected_before_usb(self):
        with self.assertRaisesRegex(ValueError, "510-byte"):
            provision.build_payload("Synthetic WiFi", "x" * 600, "http://192.0.2.1:8000/xiaozhi/ota/")

    def test_payload_limit_reserves_space_for_firmware_newline(self):
        url = "http://192.0.2.1:8000/xiaozhi/ota/"
        fixed = len(provision.build_payload("Synthetic WiFi", "", url).encode("utf-8"))
        boundary = provision.build_payload("Synthetic WiFi", "x" * (510 - fixed), url)
        self.assertEqual(len(boundary.encode("utf-8")), 510)
        with self.assertRaises(ValueError):
            provision.build_payload("Synthetic WiFi", "x" * (511 - fixed), url)


if __name__ == "__main__":
    unittest.main()
