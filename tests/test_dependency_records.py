"""Check public dependency records without network or private build settings."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


firmware = load_tool("firmware_lock")
audit = load_tool("audit_dependencies")


class DependencyRecordTests(unittest.TestCase):
    def setUp(self):
        self.lock_bytes = (ROOT / "locks/firmware/dependencies.lock").read_bytes()
        self.firmware = yaml.safe_load(self.lock_bytes)

    def test_public_firmware_resolution_and_input_hashes_match_record(self):
        firmware.validate_lock(self.firmware)
        self.assertEqual(json.loads((ROOT / "locks/firmware/build-record.json").read_text()),
                         firmware.record(self.firmware, self.lock_bytes))

    def test_private_registry_and_local_component_sources_cannot_be_exported(self):
        component = next(name for name in self.firmware["dependencies"] if name != "idf")
        for source in ({"type": "local", "path": "/synthetic/private/component"},
                       {"type": "service", "registry_url": "https://test:fake@components.espressif.com/"},
                       {"type": "service", "registry_url": "https://private.invalid/"}):
            data = copy.deepcopy(self.firmware)
            data["dependencies"][component]["source"] = source
            with self.subTest(source_type=source["type"]), self.assertRaises(ValueError):
                firmware.validate_lock(data)

    def test_unreviewed_lock_fields_or_missing_hashes_are_rejected(self):
        data = copy.deepcopy(self.firmware)
        data["local_settings"] = "synthetic private metadata"
        with self.assertRaises(ValueError):
            firmware.validate_lock(data)
        data = copy.deepcopy(self.firmware)
        component = next(name for name in data["dependencies"] if name != "idf")
        del data["dependencies"][component]["component_hash"]
        with self.assertRaises(ValueError):
            firmware.validate_lock(data)

    def test_all_python_sets_have_exact_pins_and_hashes(self):
        pins = {kind: set(audit.locked_pins(ROOT / "locks" / f"python-{kind}.txt"))
                for kind in ("web", "device", "audit")}
        for filename, kind in (("requirements.txt", "web"), ("requirements-device.txt", "device")):
            directives = [line.strip() for line in (ROOT / filename).read_text().splitlines()
                          if line.strip() and not line.lstrip().startswith("#")]
            self.assertEqual(directives, ["--require-hashes", f"-r locks/python-{kind}.txt"])
        self.assertEqual(pins["device"] - pins["web"], {("opuslib", "3.0.1"), ("pyserial", "3.5")})
        self.assertTrue(pins["web"] <= pins["device"])
        self.assertIn(("pip-audit", "2.10.1"), pins["audit"])
        # These markers must be audited even when this test runs on new macOS.
        self.assertIn(("colorama", "0.4.6"), pins["web"])
        self.assertIn(("exceptiongroup", "1.3.1"), pins["web"])


if __name__ == "__main__":
    unittest.main()
