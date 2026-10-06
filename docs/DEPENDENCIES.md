# Dependency maintenance

`pyproject.toml` declares direct application dependencies and the optional
`device` extra. `uv.lock` records the complete resolution, platform/Python
conditions and package SHA-256 hashes for Python 3.10 through 3.14. The project
version follows `CITATION.cff`; this file does not declare a new public release.

The normal installation commands remain:

```sh
python -m pip install -r requirements.txt
# Or, including the optional voice-device Python packages:
python -m pip install -r requirements-device.txt
```

These entrypoints require hashes and include `locks/python-web.txt` or
`locks/python-device.txt`. Use a clean virtual environment; optional native
Opus and ffmpeg still need a separate system installation. Hashes verify the
downloaded wheel or source distribution, not the result of compiling a source
package with an independently installed compiler or build backend.

Maintainers can instead install [uv](https://docs.astral.sh/uv/getting-started/installation/)
0.9.7, the version pinned in CI and the export script, and use:

```sh
uv sync --locked --no-default-groups
uv sync --locked --no-default-groups --extra device
```

`--locked` fails if project metadata and the lock disagree. Ordinary installs
must not silently refresh the resolution. [uv's lock documentation](https://docs.astral.sh/uv/concepts/projects/sync/)
explains the difference from `--frozen`, which skips that consistency check.

## Updating dependencies

1. Change intended direct pins in `pyproject.toml`, then run
   `python tools/update_dependency_locks.py`. To intentionally refresh permitted
   transitive versions too, add `--upgrade`.
2. Review `uv.lock` and all three exports under `locks/`. The updater uses only
   public PyPI and does not read private index settings. Commit the metadata,
   lock and exports together; never edit the exported hashes by hand.
3. Run `python tools/update_dependency_locks.py --check`, install into clean
   environments, run `uv pip check` and the repository tests. The consistency
   check is offline and compares each export byte for byte.
4. Run the advisory audit below and review each finding before merging.
   Recheck public firmware inputs with `python tools/firmware_lock.py` when
   relevant; it does not load private board settings.

Dependabot checks `uv.lock` and pinned GitHub Actions weekly. Its Python update
PRs still require a maintainer to regenerate the pip exports with the pinned
tool and commit them to that PR; CI rejects mismatches. Do not auto-merge
dependency PRs solely because a resolver succeeded.

## Auditing every resolved variant

Keep the audit environment separate from the application:

```sh
python -m venv .audit-venv
.audit-venv/bin/python -m pip install --require-hashes -r locks/python-audit.txt
.audit-venv/bin/python tools/audit_dependencies.py --output-dir dist/dependency-audit
```

On Windows, use `.audit-venv\Scripts\python.exe` for the last two commands.
The audit script verifies exact pins and hashes in each export, then queries
advisories for **all** listed versions, including inactive Python/platform
markers. It neither installs nor executes the target application packages.
Web, device and audit-tool resolutions receive separate JSON reports plus
an evidence file containing the input hashes and coverage counts. Vulnerabilities,
failed queries or omitted packages produce a failing exit status; there are no
blanket ignore rules. [pip-audit documentation](https://pypi.org/project/pip-audit/)
describes its advisory sources and the limits of known-vulnerability scans.

Generate fresh audit reports before each release. Local reports belong under
the ignored `dist/dependency-audit/` directory; retain the relevant report as a
CI or release artifact rather than committing dated audit output to the source
tree. A report records findings at the time of the audit, not a promise that
these versions remain free of newly discovered vulnerabilities.

## Supported and verified environments

The supported Python range is 3.10–3.14; 3.15 and later are outside the current
declaration. GitHub Actions is configured to run the isolated tests on every
version in that range on Linux and macOS, and runs dependency audits on pushes,
pull requests, manual dispatch and every Monday. Workflow configuration does
not imply that a hosted run has already succeeded: check the actual run before
releasing. Actions are pinned to immutable revisions with read-only repository
permissions; the workflows do not receive application/provider credentials.

Local checks for this update used clean hash-locked macOS environments with
Python 3.10.19 (device dependencies) and 3.14.3 (web-only dependencies), plus a
separate audit environment. Windows instructions are provided, but Windows
runtime and voice-device hardware validation remain unperformed. Audio/model
providers are mocked in the regression suite; no live-provider or hardware
success is implied.

Firmware resolution and its remaining build-verification limits are documented
in [locks/firmware/README.md](../locks/firmware/README.md).
