#!/usr/bin/env python3
"""Resolve public Python dependencies and maintain hash-checked pip exports."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
UV_VERSION = "0.9.7"
EXPORTS = {
    "python-web.txt": [],
    "python-device.txt": ["--extra", "device"],
    "python-audit.txt": ["--only-group", "audit"],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check existing locks without network access or edits")
    parser.add_argument("--upgrade", action="store_true", help="intentionally refresh allowed transitive versions")
    args = parser.parse_args()
    if args.check and args.upgrade:
        parser.error("--check and --upgrade cannot be combined")
    uv = shutil.which("uv")
    if not uv:
        parser.error(f"Install uv {UV_VERSION}; see docs/DEPENDENCIES.md")
    # Never consult private package indexes, authentication or user uv settings.
    environment = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR") if key in os.environ}
    environment["UV_NO_PROGRESS"] = "1"
    version = subprocess.check_output([uv, "--version"], text=True, env=environment).split()[1]
    if version != UV_VERSION:
        parser.error(f"Expected uv {UV_VERSION}; found {version}")
    common = ["--no-config", "--cache-dir", str(Path(tempfile.gettempdir()) / "inquiry-c02-uv-cache")]

    def run(arguments):
        subprocess.run([uv, *arguments, *common], cwd=ROOT, env=environment, check=True, stdout=subprocess.DEVNULL)

    lock_args = ["lock", "--default-index", "https://pypi.org/simple"]
    lock_args += ["--check", "--offline"] if args.check else (["--upgrade"] if args.upgrade else [])
    run(lock_args)
    with tempfile.TemporaryDirectory(prefix="inquiry-lock-exports-") as temporary:
        for name, extras in EXPORTS.items():
            generated = Path(temporary) / name
            run(["export", "--locked", "--offline", "--no-default-groups", "--no-emit-project",
                 "--no-header", "--no-annotate", *extras, "--output-file", str(generated)])
            destination = ROOT / "locks" / name
            if args.check:
                if not destination.is_file() or destination.read_bytes() != generated.read_bytes():
                    raise SystemExit(f"{destination.relative_to(ROOT)} differs from uv.lock; regenerate the exports")
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(generated.read_bytes())
    print("Python lock and all three hashed exports are consistent.")


if __name__ == "__main__":
    main()
