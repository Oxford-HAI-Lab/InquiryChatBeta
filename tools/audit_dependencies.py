#!/usr/bin/env python3
"""Audit every pinned platform/Python variant without installing target packages."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PIN = re.compile(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)(?:\s*;[^\n]+)?")


def locked_pins(path):
    pins = set()
    for entry in path.read_text(encoding="utf-8").replace("\\\n", " ").splitlines():
        if not entry.strip() or entry.lstrip().startswith("#"):
            continue
        requirement, *hashes = entry.split("--hash=")
        match = PIN.fullmatch(requirement.strip())
        if not match or not hashes or not all(re.fullmatch(r"sha256:[0-9a-f]{64}", h.strip()) for h in hashes):
            raise ValueError(f"Expected an exact pin and SHA-256 hashes in {path.name}")
        # Audit all conditions, including Windows and older-Python branches.
        pins.add((match[1].lower().replace("_", "-"), match[2]))
    if not pins:
        raise ValueError(f"Empty resolution: {path.name}")
    return sorted(pins)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    evidence = {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "python": sys.version.split()[0],
                "uv_lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(), "sets": {}}
    failed = False
    with tempfile.TemporaryDirectory(prefix="inquiry-audit-") as temporary:
        for kind in ("web", "device", "audit"):
            source = ROOT / "locks" / f"python-{kind}.txt"
            pins = locked_pins(source)
            requirements = Path(temporary) / f"{kind}.txt"
            requirements.write_text("".join(f"{name}=={version}\n" for name, version in pins), encoding="utf-8")
            report = args.output_dir / f"{kind}.json"
            report.unlink(missing_ok=True)
            result = subprocess.run([sys.executable, "-m", "pip_audit", "--strict", "--disable-pip", "--no-deps",
                                     "--progress-spinner", "off", "--format", "json", "--output", str(report),
                                     "--requirement", str(requirements)])
            failed |= result.returncode != 0
            dependencies = json.loads(report.read_text(encoding="utf-8"))["dependencies"] if report.exists() else []
            covered = {(d.get("name"), d.get("version")) for d in dependencies if "skip_reason" not in d}
            complete = covered == set(pins)
            failed |= not complete
            entry = {"requirements_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                     "expected_packages": len(pins), "audited_packages": len(covered),
                     "vulnerabilities": sum(len(d.get("vulns", [])) for d in dependencies),
                     "complete": complete, "audit_exit_code": result.returncode}
            evidence["sets"][kind] = entry
            print(f"{kind}: {len(covered)}/{len(pins)} packages audited; {entry['vulnerabilities']} known vulnerabilities")
    (args.output_dir / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
