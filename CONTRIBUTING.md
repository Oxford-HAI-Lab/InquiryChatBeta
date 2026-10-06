# Contributing to Inquiry Chat

Inquiry Chat is a local web app with optional voice-device support. Start with
[README.md](README.md) for setup, [CONVERSATION_LOGIC.md](CONVERSATION_LOGIC.md)
for the architecture, and [AGENTS.md](AGENTS.md) for repository-specific rules.

## Supported development targets

| Area | Target and current evidence |
|---|---|
| Python | CPython 3.10–3.14. Python 3.10 is the minimum; later versions require dependency and test verification before being added. |
| Automated backend checks | Linux and macOS across the supported Python range are the CI targets. A workflow definition is not evidence of a successful run: check the results for the revision being reviewed. |
| Local validation | The 30 September 2026 development checks ran on Python 3.14 on macOS. |
| Windows | PowerShell setup commands are provided. Windows runtime, native audio-library setup and USB hardware behavior remain unverified. |
| Browser | A current browser with JavaScript; voice input additionally needs browser speech-recognition support. Browser fixtures mock audio and provider calls. |
| Optional device | Waveshare ESP32-S3-Touch-LCD-3.49, using the documented firmware. USB-selection and setup-protocol tests use doubles; they do not replace a physical-device check. |

Install the locked web dependencies using the README setup instructions. Install
`requirements-device.txt` only when working on device functionality. Dependency
sources, lock exports, update steps and audit commands are maintained in
[docs/DEPENDENCIES.md](docs/DEPENDENCIES.md). Use an isolated environment, and keep
audit/build tooling separate from the application environment.

## Checks before a pull request

From the repository root, with the virtual environment's Python:

```sh
python -B -m unittest discover -s tests -v
python -m pip check
```

On Windows, replace `python` with `.\.venv\Scripts\python.exe` if the environment
is not activated. The backend checks use temporary session directories, disabled
personal-settings loading, synthetic conversations and mocked providers. They
must not read a developer's `env` or existing `sessions/`, or make paid API calls.
See [tests/README.md](tests/README.md) for coverage and dependency-check details.

For frontend changes, also run the isolated browser checks:

```sh
python tests/frontend/preview_server.py --port 8766
```

Open [the browser test runner](http://127.0.0.1:8766/runner.html). Follow
[tests/frontend/README.md](tests/frontend/README.md) for visual fixtures. Check a
narrow screen and long messages when changing layout. Actual microphone access,
speech recognition and playback require a separate manual check with synthetic,
non-sensitive content; fixtures cannot verify a browser's speech service.

When editing the macOS launcher, check its shell syntax without executing it:

```sh
bash -n Launch_Inquiry_Chat.command
```

The launcher can access Keychain, update local settings and configure hardware;
do not invoke it as an automated test. USB setup regression tests must use fake
ports and credentials, as in [tests/test_provision.py](tests/test_provision.py).

## Making changes

Keep each pull request focused on one problem. Describe the trigger, the resulting
behavior and the checks you actually ran. State platform, browser, API and hardware
limitations instead of marking unexecuted checks as passed. Add a regression test
for a behavior bug when it can exercise the failure without using real credentials
or external services.

Do not commit `env`, `.env`, saved conversations, API keys, WiFi passwords, device
tokens, build output or downloaded firmware components. Use synthetic fixtures
and `env.example` for shareable configuration. Preserve `.gitignore` exclusions.
Do not edit the user's `sessions/` data.

Changes to shard-building skills belong in `skills/`; copy the corresponding files
to `.claude/skills/`. To create or edit a shard, follow the appropriate skill listed
in [AGENTS.md](AGENTS.md), then validate it:

```sh
python skills/generate-inquiry-shard/check_shard.py "Shards/<folder>/<shard>.json"
```

`PhilosophyPod/xiaozhi-esp32/` is a vendored upstream tree. Do not reformat or
reorganize it. Any explicitly authorized firmware change must be recorded in
[PhilosophyPod/UPSTREAM.md](PhilosophyPod/UPSTREAM.md) and its patch, with applicable
build and physical-device evidence. Preserve copyright notices and the
[third-party license inventory](PhilosophyPod/THIRD_PARTY_LICENSES.md).

## Preparing a public release

Run both relevant test suites and the dependency audit against the exact release
tree. Review lockfile changes, license inventory and notices. Confirm that example
configuration is synthetic and that packaging excludes local settings, saved chats,
development environments and build output. Follow [docs/RELEASING.md](docs/RELEASING.md)
for the allowlisted release packager and [docs/ASSET_PROVENANCE.md](docs/ASSET_PROVENANCE.md)
for artwork and screenshot provenance.

Confirm the final HAI Lab repository name and update `CITATION.cff` and documentation
links if it differs from the planned `Oxford-HAI-Lab/inquiry-chat` location.
