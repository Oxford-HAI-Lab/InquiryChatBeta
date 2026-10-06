#!/usr/bin/env python3
"""Validate/export public firmware resolution without reading private settings."""
import argparse
import hashlib
import json
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "PhilosophyPod" / "xiaozhi-esp32"
PUBLIC = ROOT / "locks" / "firmware"
INPUTS = (
    "PhilosophyPod/philosophypod-firmware-changes.patch",
    "PhilosophyPod/xiaozhi-esp32/CMakeLists.txt",
    "PhilosophyPod/xiaozhi-esp32/main/CMakeLists.txt",
    "PhilosophyPod/xiaozhi-esp32/main/idf_component.yml",
    "PhilosophyPod/xiaozhi-esp32/sdkconfig.defaults",
    "PhilosophyPod/xiaozhi-esp32/sdkconfig.defaults.esp32s3",
    "PhilosophyPod/xiaozhi-esp32/sdkconfig.philosophypod",
    "PhilosophyPod/xiaozhi-esp32/sdkconfig.board.example",
)
NAME = re.compile(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)?")
VERSION = re.compile(r"[A-Za-z0-9.<>!=~^*+, -]+")
HASH = re.compile(r"[0-9a-f]{64}")
REGISTRIES = {"https://components.espressif.com", "https://components.espressif.com/"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fields(value, required, optional=()):
    require(isinstance(value, dict), "Expected a metadata object")
    require(set(required) <= value.keys() <= set(required) | set(optional), "Unexpected or missing metadata fields")


def name(value):
    require(isinstance(value, str) and NAME.fullmatch(value), "Invalid public component name")


def version(value):
    require(isinstance(value, str) and VERSION.fullmatch(value), "Invalid public version constraint")
    require(any(c.isdigit() for c in value) or value == "*", "Version constraint has no version")


def validate_lock(data):
    """Reject unsupported/private sources rather than silently publishing them."""
    fields(data, {"dependencies", "direct_dependencies", "manifest_hash", "target", "version"})
    require(data["version"] == "3.0.0", "Review a changed lock schema before exporting")
    require(data["target"] == "esp32s3", "Expected the PhilosophyPod ESP32-S3 target")
    require(isinstance(data["manifest_hash"], str) and HASH.fullmatch(data["manifest_hash"]), "Invalid manifest digest")
    require(isinstance(data["dependencies"], dict) and data["dependencies"], "Missing component resolution")
    require(isinstance(data["direct_dependencies"], list), "Invalid direct dependency list")
    for direct in data["direct_dependencies"]:
        name(direct)
        require(direct in data["dependencies"], "Unresolved direct component")
    for component, entry in data["dependencies"].items():
        name(component)
        fields(entry, {"source", "version"}, {"component_hash", "dependencies", "targets"})
        version(entry["version"])
        source = entry["source"]
        if component == "idf":
            require(source == {"type": "idf"}, "Unexpected IDF source")
        else:
            fields(source, {"type", "registry_url"})
            require(source["type"] == "service" and source["registry_url"] in REGISTRIES,
                    "Only the uncredentialed public Espressif registry may be exported")
            require(isinstance(entry.get("component_hash"), str) and HASH.fullmatch(entry["component_hash"]), "Missing component digest")
        require(isinstance(entry.get("targets", []), list), "Invalid targets")
        for target in entry.get("targets", []):
            require(isinstance(target, str) and re.fullmatch(r"(?:esp32[a-z0-9]*|linux)", target), "Unexpected target")
        require(isinstance(entry.get("dependencies", []), list), "Invalid dependency declarations")
        for dependency in entry.get("dependencies", []):
            fields(dependency, {"name", "require", "version"}, {"registry_url", "rules", "matches"})
            name(dependency["name"])
            version(dependency["version"])
            require(dependency["require"] in {"public", "private"}, "Invalid component visibility")
            if "registry_url" in dependency:
                require(dependency["registry_url"] in REGISTRIES, "Private dependency registry is not publishable")
            for key in ("rules", "matches"):
                require(isinstance(dependency.get(key, []), list), "Invalid component condition list")
                for rule in dependency.get(key, []):
                    fields(rule, {"if"})
                    expression = rule["if"]
                    require(isinstance(expression, str), "Invalid component condition")
                    # Preserve symbolic public build flags, never their values.
                    expression = re.sub(r"\$CONFIG\{[A-Z0-9_]+\}", "CONFIG_FLAG", expression)
                    require(re.fullmatch(r"[A-Za-z0-9._ <>=!,'\"\[\]()-]+", expression), "Unsupported component condition")
    require("idf" in data["dependencies"], "Missing IDF version")
    return data


def public_input_hashes(root=ROOT):
    result = {}
    for relative in INPUTS:
        path = root / relative
        require(path.is_file() and not path.is_symlink(), "Missing or symlinked public build input")
        result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def record(data, lock_bytes):
    return {
        "schema_version": 1,
        "upstream_url": "https://github.com/78/xiaozhi-esp32",
        "upstream_tag": "v2.5.0",
        "upstream_commit": "ac6deed3d8e75348475364bf40ad953c6cd48054",
        "esp_idf_version": data["dependencies"]["idf"]["version"],
        "target": data["target"],
        "component_count": len(data["dependencies"]),
        "lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
        "public_build_input_sha256": public_input_hashes(),
        "validation": "Resolution exported and public inputs checked; firmware was not rebuilt or flashed for this record.",
        "firmware_artifact_sha256": None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="export the local ignored dependency lock after public-source validation")
    parser.add_argument("--check-build-lock", action="store_true", help="also compare a local build's dependency lock to the public record")
    args = parser.parse_args()
    lock = PUBLIC / "dependencies.lock"
    metadata = PUBLIC / "build-record.json"
    if args.refresh:
        source = FIRMWARE / "dependencies.lock"
        require(not source.is_symlink(), "Do not export a symlinked dependency lock")
        data = validate_lock(yaml.safe_load(source.read_text(encoding="utf-8")))
        lock_bytes = yaml.safe_dump(data, sort_keys=False, allow_unicode=False).encode("utf-8")
        PUBLIC.mkdir(parents=True, exist_ok=True)
        lock.write_bytes(lock_bytes)
        metadata.write_text(json.dumps(record(data, lock_bytes), indent=2) + "\n", encoding="utf-8")
    else:
        lock_bytes = lock.read_bytes()
        data = validate_lock(yaml.safe_load(lock_bytes))
        require(json.loads(metadata.read_text(encoding="utf-8")) == record(data, lock_bytes),
                "Public firmware lock or build inputs changed; review and refresh the record")
    if args.check_build_lock:
        build = validate_lock(yaml.safe_load((FIRMWARE / "dependencies.lock").read_text(encoding="utf-8")))
        require(build == data, "Build resolved different firmware dependencies; review before releasing")
    print(f"Verified {len(data['dependencies'])} public firmware components and {len(INPUTS)} public build inputs.")


if __name__ == "__main__":
    main()
