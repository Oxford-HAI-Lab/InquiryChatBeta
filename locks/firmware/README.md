# Public firmware resolution and build record

`dependencies.lock` is a validated public export of the component resolution
recorded for PhilosophyPod's ESP32-S3 firmware. It contains 74 components,
including ESP-IDF 6.0.3, with the component hashes, constraints and targets
needed by the IDF Component Manager. All downloaded sources use the public
Espressif registry. The local upstream lock remains ignored inside the vendor
tree; this maintained copy is deliberately outside that tree.

`build-record.json` records the upstream tag and commit, target, exact IDF
version, exported-lock digest and hashes of eight public build inputs. It does
not contain `sdkconfig`, `sdkconfig.board`, Wi-Fi settings, addresses or tokens.
It records **no new firmware build, flash or binary checksum**: those have not
been performed for this maintenance update. The historical build claim remains
in [UPSTREAM.md](../../PhilosophyPod/UPSTREAM.md).

## Reproducing the recorded resolution

Use a clean copy of the reviewed source archive and ESP-IDF **6.0.3**, with its
matching tools installed according to the
[Espressif setup instructions](https://docs.espressif.com/projects/esp-idf/en/v6.0.3/esp32s3/get-started/).
Do not substitute “latest” IDF when comparing builds.

From the repository root, check the public record and restore the lock:

```sh
python tools/firmware_lock.py
cp locks/firmware/dependencies.lock PhilosophyPod/xiaozhi-esp32/dependencies.lock
cp PhilosophyPod/xiaozhi-esp32/sdkconfig.board.example PhilosophyPod/xiaozhi-esp32/sdkconfig.board
```

Set the server address in the private copy of `sdkconfig.board` as described in
[the device setup guide](../../PhilosophyPod/README.md). Keep that file out of
the release. After activating ESP-IDF 6.0.3:

```sh
cd PhilosophyPod/xiaozhi-esp32
idf.py --version
idf.py -B build/philosophypod -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.esp32s3;sdkconfig.philosophypod;sdkconfig.board" set-target esp32s3
idf.py -B build/philosophypod build
cd ../..
python tools/firmware_lock.py --check-build-lock
```

The separate `build/philosophypod/` directory avoids reusing cached absolute paths from before the device-folder rename and preserves existing flash binaries in `build/`.

The final check must pass: if the component manager rewrites the resolution,
stop and review the difference before publishing an artifact. See
[Espressif's lockfile reference](https://docs.espressif.com/projects/idf-component-manager/en/latest/reference/dependencies_lock.html)
for its manifest and target checks. CI validates the public record and public
input hashes; it does not download or compile the firmware components.

## Deliberate updates and artifact evidence

After an intentional dependency/build-input change, a successful reviewed build
and a comparison with the existing record, run:

```sh
python tools/firmware_lock.py --refresh --check-build-lock
```

The exporter rejects local/Git/private-registry sources, credentials, unknown
metadata fields and missing component hashes. It preserves symbolic component
conditions without evaluating or exporting private settings. Review the public
lock and record diff, update `PhilosophyPod/UPSTREAM.md`, and commit them together.
Changes inside the firmware tree still require its established provenance
workflow; this exporter does not make those changes for you.

For a future binary release, retain the compiler/toolchain versions, clean build
log, reviewed nonsecret configuration choices and SHA-256 checksums of the exact
binary files being distributed with that release. Review downloaded component
licenses and notices too. Do not attach the complete build directory or private
settings. A matching component lock alone does not establish byte-identical
firmware: toolchains, configuration and generated assets also affect the result.
