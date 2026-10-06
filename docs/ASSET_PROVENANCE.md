# Source and asset provenance

This inventory describes the material retained in the public source package.
Keep it with the license notices when creating a release.

| Material | Recorded source and redistribution basis |
| --- | --- |
| Original application, documentation, shard graphs and explanatory contexts | Philipp Koralus; repository [MIT license](../LICENSE). The license covers original contributions, not the underlying books or separately licensed components. |
| Mill shards and quotations | John Stuart Mill, *On Liberty* (1859), original English text. The supplied shard metadata does not record the edition. The original work is public domain; no modern edition's notes, introduction or other editorial material is identified as included. |
| `docs/inquirychat.png` | Screenshot supplied by the maintainer for the README, showing the application's Mill inquiry welcome screen in a browser. Original interface contributions are MIT licensed. |
| `docs/quiet-dialogue-desktop.jpg` | Earlier screenshot of this application's frontend, using synthetic conversations and node states from `tests/frontend/`. No saved user session is used. Original interface contributions are MIT licensed. |
| PhilosophyPod boot animation and original artwork | Credited to Philipp Koralus in [UPSTREAM.md](../PhilosophyPod/UPSTREAM.md). On 30 September 2026, the maintainer explicitly confirmed ownership or permission to publish the boot animation and original artwork under the repository MIT license. |
| Firmware source, upstream images and other upstream assets | Retained from the exact upstream snapshot identified in [UPSTREAM.md](../PhilosophyPod/UPSTREAM.md). Keep the upstream license and file-level notices. [THIRD_PARTY_LICENSES.md](../PhilosophyPod/THIRD_PARTY_LICENSES.md) records separately licensed source, GIF/LVGL provenance and the NOTICE review. This is a record of upstream declarations, not an independent chain-of-title audit of upstream contributors. |
| Stardos-derived display font | Copyright 2011 Vernon Adams; SIL Open Font License 1.1, with reserved names and attribution in [STARDOS_STENCIL_LICENSE.txt](../PhilosophyPod/STARDOS_STENCIL_LICENSE.txt). |
| Browser Inter font | Loaded remotely through Google Fonts, not bundled in this source package. The privacy disclosure describes the external request. If a future release bundles it, include that font version's license and copyright notice. |

The source package contains no design exploration images, generation prompts or
design archives. The interface screenshots listed above are retained.
Future assets require their own source, permission and license record.

This inventory uses the supplied source declarations and the maintainer's
confirmation. It does not grant rights in third-party trademarks, modern
editions, external services or a newly assembled firmware binary. For a binary
release, review the downloaded components and assets actually linked into it.
