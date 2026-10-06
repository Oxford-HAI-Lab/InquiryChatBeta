# Repository checks

Install `requirements.txt` in a Python 3.10–3.14 environment, then run from the project root:

```sh
python -B -m unittest discover -s tests -v
```

The backend checks import the actual application with personal settings loading
disabled and temporary session storage. They use synthetic conversations and
mock providers; they do not read `env`, access existing `sessions/`, or call paid
services. Coverage includes HTTP authorization, multipart compatibility, missing
optional codecs, overlapping browser/device turns, stale evaluation and closing
results, safe context paths, third-party license inventory completeness, USB
setup with fake devices, dependency records and release-packaging boundaries.

The existing [browser checks](frontend/README.md) exercise the production
frontend with in-memory API and voice fixtures. Those fixtures require the same
CSRF header as the backend, so normal sends, rewinds, deletion and playback also
verify the browser's authorization plumbing.

Install requirements into a fresh disposable environment before checking
compatibility with `python -m pip check` (or `uv pip check`). The requirements
entrypoints now enforce SHA-256 hashes for the complete resolution in `uv.lock`.
Run `python tools/update_dependency_locks.py --check` with uv 0.9.7 to verify
the canonical metadata, lock and exports agree without changing them.

[Dependency maintenance](../docs/DEPENDENCIES.md) covers lock updates, the
separate hash-locked audit environment, and the Linux/macOS Python 3.10–3.14
CI matrix. The audit includes all resolved variants, even inactive Python and
platform markers. Rerun the advisory check before each release, generating
local reports under the ignored `dist/dependency-audit/` directory. Retain
relevant reports as CI or release artifacts; dated audit output is not kept
in the source tree.

`python tools/firmware_lock.py` verifies the public firmware component lock and
build-input hashes. It does not load private board settings, build firmware or
contact devices; [the firmware record](../locks/firmware/README.md) explains the
remaining build and hardware verification steps.
