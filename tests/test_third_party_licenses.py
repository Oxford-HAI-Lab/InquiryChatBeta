"""Guard the vendored source's license inventory without reading local settings.

This checks declared licenses and supplied notices, not legal provenance or the
licenses of downloaded components and resulting firmware binaries.
"""

import hashlib
import os
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
PHILOSOPHYPOD = ROOT / "PhilosophyPod"
FIRMWARE = PHILOSOPHYPOD / "xiaozhi-esp32"
INVENTORY = PHILOSOPHYPOD / "THIRD_PARTY_LICENSES.md"

# The upstream ignore rules exclude these generated/dependency directories.
# Do not recurse into them: they are not part of this source distribution.
EXCLUDED_DIRS = {
    ".git", ".cache", ".vscode", ".devcontainer", "__pycache__",
    "build", "components", "managed_components", "dist", "releases", "tmp",
}
SOURCE_SUFFIXES = {".c", ".cc", ".h", ".py", ".sh"}
LICENSE_HASHES = {
    "Apache-2.0.txt": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    "GPL-3.0.txt": "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986",
    "LVGL-MIT.txt": "27a80bd36832ab42d35ad60c08b2b230a807a9bc0d58e94ec1531543dc49cbe8",
}


def source_paths():
    for directory, dirs, files in os.walk(FIRMWARE):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS)
        for filename in sorted(files):
            if filename == "lang_config.h" or filename.startswith("mmap_generate_"):
                continue
            yield Path(directory) / filename


def declared_license(path):
    """Inspect initial source comments, not generated-header string literals."""
    header = "\n".join(path.read_text(encoding="utf-8").splitlines()[:40])
    spdx = re.search(
        r"^\s*(?:\*|#|//)\s*SPDX-License-Identifier:\s*([^\n]+)",
        header, re.MULTILINE,
    )
    if spdx:
        return spdx.group(1).strip()
    named = re.search(r"@License:\s*([^\n]+)", header)
    if named:
        name = named.group(1).strip()
        return "GPL-3.0" if name == "GPL 3.0" else name
    if "//-- GPL license" in header:
        return "GPL-unspecified"
    if "SIL Open Font License" in header:
        return "OFL-1.1"
    return None


class ThirdPartyLicenseTests(unittest.TestCase):
    def test_explicit_source_declarations_are_inventoried(self):
        documented_rows = re.findall(
            r"^\| `([^`]+)` \| `([^`]+)` \|",
            INVENTORY.read_text(encoding="utf-8"), re.MULTILINE,
        )
        documented = dict(documented_rows)
        self.assertEqual(len(documented_rows), len(documented), "Duplicate inventory path")
        observed = {}
        for path in source_paths():
            if path.suffix not in SOURCE_SUFFIXES:
                continue
            license_name = declared_license(path)
            if license_name:
                observed[path.relative_to(FIRMWARE).as_posix()] = license_name
        self.assertTrue(observed, "No source license declarations were scanned")
        self.assertEqual(documented, observed, "Update the file/license inventory")

    def test_official_license_texts_are_complete_and_unchanged(self):
        for name, expected in LICENSE_HASHES.items():
            with self.subTest(license=name):
                actual = hashlib.sha256((PHILOSOPHYPOD / "LICENSES" / name).read_bytes()).hexdigest()
                self.assertEqual(actual, expected, "License differs from its verified primary-source text")

    def test_existing_copyright_notices_are_present(self):
        required = {
            ROOT / "LICENSE": "Copyright (c) 2026 Philipp Koralus",
            FIRMWARE / "LICENSE": "Copyright (c) 2025 Shenzhen Xinzhi Future Technology Co., Ltd.",
            PHILOSOPHYPOD / "STARDOS_STENCIL_LICENSE.txt": 'with Reserved Font Names "Stardos" and "Stardos Stencil".',
            PHILOSOPHYPOD / "LICENSES" / "LVGL-MIT.txt": "Copyright (c) 2025 LVGL Kft",
            FIRMWARE / "main/display/lvgl_display/gif/LICENSE.txt": "public domain and provided without warranty of any kind.",
        }
        for path, notice in required.items():
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIn(notice, path.read_text(encoding="utf-8"))

    def test_inventory_local_links_resolve(self):
        for target in re.findall(r"\]\(([^)]+)\)", INVENTORY.read_text(encoding="utf-8")):
            if target.startswith(("https://", "http://", "#")):
                continue
            with self.subTest(target=target):
                self.assertTrue((PHILOSOPHYPOD / target).exists(), "Missing license or attribution document")

    def test_notice_review_is_current(self):
        notices = sorted(
            p.relative_to(FIRMWARE).as_posix() for p in source_paths()
            if p.name.upper() == "NOTICE" or p.name.upper().startswith("NOTICE.")
        )
        self.assertEqual(notices, [], "New upstream NOTICE found: retain it and update the NOTICE review")


if __name__ == "__main__":
    unittest.main()
