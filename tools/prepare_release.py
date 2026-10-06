#!/usr/bin/env python3
"""Build a reviewed source archive without opening private working files.

Uses only the standard library and Git. No application imports or network calls.
Findings show paths and rule names, never matched credential values.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = {
    ".gitignore", "AGENTS.md", "CITATION.cff", "CONTRIBUTING.md",
    "CONVERSATION_LOGIC.md", "LICENSE", "README.md",
    "Launch_Inquiry_Chat.command", "app.py", "ic_engine.py", "env.example",
    "requirements.txt", "requirements-device.txt", "pyproject.toml", "uv.lock",
}
PUBLIC_DIRS = {".github", "Shards", "skills", "static", "tests", "tools", "docs", "locks", "PhilosophyPod"}
PRIVATE_PARTS = {
    ".git", ".venv", ".audit-venv", "venv", "sessions", "__pycache__", ".cache",
    "build", "dist", "managed_components", "components", "releases", "tmp",
    ".vscode", ".devcontainer", "design", "mockups", "local-firmware",
}
PRIVATE_NAMES = {
    "env", ".env", "sdkconfig", "sdkconfig.old", "sdkconfig.board",
    "settings.local.json", ".DS_Store", "lang_config.h", "RELEASE_CHECKLIST.md",
}
# Intentionally bounded patterns, supplemented by a human review of the manifest.
# Not an entropy scanner or a guarantee that an arbitrary secret is absent.
SECRET_RULES = {
    "private key": re.compile(rb"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    "OpenAI-style key": re.compile(rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{24,}"),
    "GitHub token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
    "AWS access key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "credential in URL": re.compile(rb"https?://[^\s/:@]{1,80}:[^\s/@]{8,}@"),
    "device token assignment": re.compile(rb"(?im)^\s*DEVICE_TOKEN\s*=\s*['\"]?[A-Za-z0-9_-]{24,}"),
    "provider key assignment": re.compile(rb"(?im)^\s*(?:OPENAI|ELEVENLABS)_API_KEY\s*=\s*['\"]?[A-Za-z0-9_-]{24,}"),
    "personal absolute path": re.compile(rb"(?:/Users/|[A-Z]:\\Users\\)[A-Za-z0-9_.-]+[/\\]"),
}


class ReleaseError(ValueError):
    pass


def validate_path(name):
    path = PurePosixPath(name)
    folded = PurePosixPath(name.casefold())
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ReleaseError(f"Unsafe release path: {name}")
    if (set(folded.parts) & {part.casefold() for part in PRIVATE_PARTS}
            or folded.name in {part.casefold() for part in PRIVATE_NAMES}
            or folded.name.startswith((".env.", "mmap_generate_"))
            or folded.name.endswith((".pyc", ".bin")) or ".bak" in folded.name
            or any(part.startswith(".venv.old") for part in folded.parts)):
        raise ReleaseError(f"Private/generated file in candidate tree: {name}")
    allowed = (name in PUBLIC_FILES or path.parts[0] in PUBLIC_DIRS
               or name.startswith(".claude/skills/"))
    if not allowed:
        raise ReleaseError(f"Unreviewed release location: {name}")


def git_files(root, staged=False):
    args = ["git", "-C", str(root), "ls-files", "-z", "--cached"]
    if not staged:
        args += ["--others", "--exclude-standard"]
    result = subprocess.run(args, check=True, capture_output=True)
    return sorted(set(result.stdout.decode("utf-8").rstrip("\0").split("\0")) - {""})


def read_candidates(root, staged=False):
    root = root.resolve()
    names = git_files(root, staged)
    if not names:
        raise ReleaseError("No candidate files; stage the intended release or omit --staged.")
    # Check the complete name set before reading ANY contents, including tracked secrets.
    for name in names:
        validate_path(name)
    modes = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--stage", "-z"],
        check=True, capture_output=True,
    ).stdout.decode("utf-8")
    for record in filter(None, modes.rstrip("\0").split("\0")):
        meta, name = record.split("\t", 1)
        mode, _, stage = meta.split()
        if mode not in {"100644", "100755"} or stage != "0":
            raise ReleaseError(f"Symlink, submodule or unmerged index entry: {name}")
    contents = {}
    if staged:
        for name in names:
            data = subprocess.run(
                ["git", "-C", str(root), "show", f":{name}"],
                check=True, capture_output=True,
            ).stdout
            contents[name] = data
    else:
        for name in names:
            path = root / name
            if any(root.joinpath(*PurePosixPath(name).parts[:i]).is_symlink()
                   for i in range(1, len(PurePosixPath(name).parts) + 1)):
                raise ReleaseError(f"Symlink in candidate tree: {name}")
            if not path.is_file():
                raise ReleaseError(f"Missing or nonregular candidate file: {name}")
        for name in names:
            contents[name] = (root / name).read_bytes()
    return contents


def inspect_contents(contents):
    findings = []
    for name, data in contents.items():
        for rule, pattern in SECRET_RULES.items():
            if pattern.search(data):
                findings.append(f"{name}: {rule}")
    if findings:
        raise ReleaseError("Release scan found candidates for review (values withheld):\n" + "\n".join(findings))


def build_archive(contents):
    stream = io.BytesIO()
    # Fixed metadata makes byte-for-byte repeat builds possible for the same contents.
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, data in sorted(contents.items()):
            info = tarfile.TarInfo("inquiry-chat/" + name)
            info.size = len(data)
            info.mode = 0o755 if name.endswith((".sh", ".command")) else 0o644
            archive.addfile(info, io.BytesIO(data))
    stream.seek(0)
    with tarfile.open(fileobj=stream, mode="r:") as archive:
        actual = {m.name.removeprefix("inquiry-chat/"): archive.extractfile(m).read()
                  for m in archive.getmembers()}
    if actual != contents:
        raise ReleaseError("Archive contents differ from inspected contents")
    inspect_contents(actual)
    return stream.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--staged", action="store_true", help="Archive the exact Git index, ignoring unstaged edits")
    args = parser.parse_args()
    try:
        contents = read_candidates(ROOT, args.staged)
        inspect_contents(contents)
        archive = build_archive(contents)
        manifest = {
            "format": 1,
            "source": "git-index" if args.staged else "working-tree-git-candidates",
            "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(contents.items())},
            "scan": {"rules": list(SECRET_RULES), "findings": 0,
                     "limitation": "Bounded patterns only; review the exact manifest and asset provenance before publication."},
            "archive": {"name": "inquiry-chat-source.tar", "sha256": hashlib.sha256(archive).hexdigest()},
        }
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / manifest["archive"]["name"]).write_bytes(archive)
        (args.output_dir / "release-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"Inspected {len(contents)} files; zero pattern findings. Archive and SHA-256 manifest: {args.output_dir}")
    except (ReleaseError, subprocess.CalledProcessError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
