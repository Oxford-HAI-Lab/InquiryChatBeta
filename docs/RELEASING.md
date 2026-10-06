# Preparing a public release

Publish the reviewed source archive or the matching Git tree. Do not upload a
copy of the working folder: it contains private settings and saved conversations.
The intended home is the HAI Lab GitHub organization; verify the final repository
URL in `CITATION.cff` when creating the repository.

## Review and verify the candidate

1. Run the installation, dependency-audit and test procedures in
   [the test guide](../tests/README.md), including the browser fixtures and all
   five shard checks. Use the maintained Python lock files. Follow
   [the firmware build records](../locks/firmware/README.md) only if releasing
   firmware; a source archive is not evidence of a successful hardware build.
2. Review [asset provenance](ASSET_PROVENANCE.md), the root license,
   [third-party notices](../PhilosophyPod/THIRD_PARTY_LICENSES.md) and the Stardos
   font license. Record permission for every newly added image, font or excerpt.

Prepare a candidate archive from the current nonignored Git candidate files:

```sh
python tools/prepare_release.py --output-dir dist/release
```

The tool checks all paths before reading any contents. It rejects private or
generated files even if they were force-added, unexpected top-level locations,
symlinks and unmerged entries. It scans the selected bytes for bounded credential
and personal-path patterns without printing matched values. It builds the source
archive from those same bytes, rechecks the archive, and writes a SHA-256 file
manifest plus the archive hash. Binary files receive the same byte-pattern scan;
the tool does not OCR images or inspect Git history.

Review `dist/release/release-manifest.json` and the archive itself. The manifest
is the exact publication inventory. A zero-result pattern scan does not prove
that every possible secret is absent; review new assets, sample configurations
and endpoints yourself. Keep real `env`, `.env`, `sessions/`, private
`sdkconfig*` settings, downloaded components, caches and build output excluded.
Public `sdkconfig.philosophypod`, `sdkconfig.defaults*` and
`sdkconfig.board.example` are deliberate build templates.

## Final staged-tree check

After reviewing and staging the intended release files, prepare the **exact Git
index**, including its file contents rather than any later working edits:

```sh
python tools/prepare_release.py --staged --output-dir dist/staged-release
```

Inspect this new manifest and archive. Rerun the dependency audit immediately
before publication and keep its result with the release record. Run tests from
the unpacked candidate as a final installation check. Then make the initial
commit and tag from this same index. If any files change, repeat the preparation
and review. The archive and manifest live under ignored `dist/`; they should not
be added back to the source tree.

The tool also runs in CI. It does not publish anything, configure GitHub, create
a commit or tag, change the index, or certify that open release-review findings
have been resolved. Check the release review before calling a version stable.
