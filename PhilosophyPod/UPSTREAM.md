# Firmware origin

`xiaozhi-esp32/` is a modified copy of the open-source xiaozhi-esp32 firmware.

| | |
|---|---|
| Upstream project | https://github.com/78/xiaozhi-esp32 |
| Upstream license | MIT, copyright 2025 Shenzhen Xinzhi Future Technology Co., Ltd. and project contributors. See `xiaozhi-esp32/LICENSE` |
| Copied from | Release `v2.5.0`, commit `ac6deed3d8e75348475364bf40ad953c6cd48054` (2026-09-10) |
| Build tools | ESP-IDF 6.0.1 or later. Built and tested with 6.0.3 |

The copy is included here as plain files, without the upstream project's version history. Upstream's own `README.md`, `README_zh.md`, `README_ja.md`, `AGENTS.md`, `.github/` and `docker/` folders are kept unchanged inside the copy; they describe the upstream project, not this one, and GitHub ignores the nested `.github/` folder.

## Licenses inside the copy

The upstream project has an MIT license, with separately licensed files that retain their own terms. These include Apache-2.0 drivers and an asset-generation script; GPL oscillator, LilyGO pin-configuration and LilyGO display-header files; gifdec's public-domain declaration and LVGL's MIT notice; and the Stardos-derived display font under the SIL Open Font License.

[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) records the exact file-level declarations, preserved attributions, GIF provenance, and NOTICE review. Full Apache-2.0, GPLv3 and LVGL MIT texts are supplied in [LICENSES/](LICENSES/); the font notice and OFL text remain in [STARDOS_STENCIL_LICENSE.txt](STARDOS_STENCIL_LICENSE.txt). Include these documents when redistributing the firmware source. Files for other boards are still distributed as source even when they are not compiled for PhilosophyPod.

The license inventory and texts sit outside `xiaozhi-esp32/`; adding them does not change the firmware files or the patch below.

## History

| Date | Based on | Notes |
|---|---|---|
| 2026-03-31 | Commit `8afebe5`, 31 commits after v2.2.4 | First PhilosophyPod version, built with ESP-IDF 5.5.2 |
| 2026-09-29 | Release v2.5.0 | Changes carried over onto v2.5.0, which takes in 154 upstream commits. Built with ESP-IDF 6.0.3 and flashed to the device |
| 2026-09-29 | Release v2.5.0 | Built-in WiFi default removed; deepest-level node colour changed to violet; device token accepted during USB setup. Flashed to the device |
| 2026-09-30 | Release v2.5.0 | License notice added to the header of `stencil_font_20.c`, pointing at `STARDOS_STENCIL_LICENSE.txt`. Comment only; no rebuild needed |
| 2026-10-01 | Release v2.5.0 | Device renamed to PhilosophyPod, including the parent folder, public build preset, patch filename and branding comments. Runtime code and build settings are unchanged; firmware was not rebuilt or flashed |

## What was changed

Fifteen upstream files were modified and five files were added. `philosophypod-firmware-changes.patch`, next to this file, holds the exact changes to the modified files: applying it to a clean checkout of v2.5.0 reproduces them.

### Modified files

```
 main/CMakeLists.txt                                |    2 +
 main/application.cc                                |   87 +-
 main/application.h                                 |    2 +-
 main/audio/audio_codec.cc                          |   34 +
 main/audio/audio_codec.h                           |   13 +-
 main/audio/codecs/box_audio_codec.cc               |    1 -
 main/boards/common/backlight.cc                    |    2 +-
 main/boards/common/board.h                         |    1 +
 .../esp32-s3-touch-lcd-3.49/custom_lcd_display.cc  | 1161 +++++++++++++++++++-
 .../esp32-s3-touch-lcd-3.49/custom_lcd_display.h   |   97 +-
 .../waveshare-s3-touch-lcd-3.49.cc                 |   57 +-
 main/display/display.h                             |    8 +
 main/main.cc                                       |  137 +++
 main/protocols/protocol.cc                         |    5 +
 main/protocols/protocol.h                          |    1 +
 15 files changed, 1582 insertions(+), 26 deletions(-)
```

### Added

| Path in `xiaozhi-esp32/` | What it is |
|---|---|
| `main/boards/waveshare/esp32-s3-touch-lcd-3.49/assets/splash.mvid` | The boot animation |
| `main/boards/waveshare/esp32-s3-touch-lcd-3.49/stencil_font_20.c` | Display font for the turn counter, generated from Stardos Stencil (SIL Open Font License; see Credits) |
| `scripts/make_splash_mvid.py` | Packs a video into the `.mvid` format |
| `sdkconfig.philosophypod` | Build settings for this device: board, language, console on USB, echo cancellation off |
| `sdkconfig.board.example` | Template for the server address setting |

The added files are not in the patch, since the patch only covers files that exist upstream.

### Changes since the first version

- `main/CMakeLists.txt`: upstream renamed its font settings; the boot animation's asset folder is set alongside the new names. The USB serial component is declared as a requirement, which ESP-IDF 6 demands.
- `main/display/display.h`: the PhilosophyPod display functions sit alongside the functions upstream added.
- `main/application.cc`: upstream skips its "ready" step after a failed activation. Connecting to the server, which replaces that step here, is placed inside the same check.
- `custom_lcd_display.cc`: includes `material_symbols.h` in place of `font_awesome.h`, which upstream removed.
- `custom_lcd_display.cc`: the colour for nodes at depth 3 or more is violet. It was the same green used for resolved nodes, which made unresolved deep nodes look resolved.
- `main/main.cc`: setup over USB accepts a `token`, which the device saves and presents when it connects to the server.
- `main/boards/common/wifi_board.cc`: restored to the upstream version. The earlier PhilosophyPod version had a default WiFi network written into it; the device is now given its WiFi details over USB with `provision.py`.

## Component versions

The vendor-local `dependencies.lock` remains ignored upstream. A validated public copy is now maintained at [`locks/firmware/dependencies.lock`](../locks/firmware/dependencies.lock), outside the vendor tree, with component hashes and a [build record and reproduction instructions](../locks/firmware/README.md). Restore that lock before a reproduction build and verify that the build did not change its resolution. This export does not modify the firmware source or private board configuration and does not claim a new build or flash.

The versions below are the ones the device firmware was built and tested with, on ESP-IDF 6.0.3, resolved from `main/idf_component.yml` on 2026-09-29. Intentional component changes require reviewing and updating the public lock, build record and this provenance document together.

| Component | Version |
|---|---|
| `78/esp-ml307` | 3.7.4 |
| `78/esp-wifi-connect` | 3.3.1 |
| `78/esp_lcd_nv3023` | 1.0.1 |
| `78/uart-eth-modem` | 0.6.5 |
| `78/uart-uhci` | 0.3.3 |
| `78/xiaozhi-fonts` | 2.0.0 |
| `cube32esp/xpowerslib` | 0.3.3 |
| `esphome/esp-hub75` | 0.3.6 |
| `espressif/adc_battery_estimation` | 0.2.2 |
| `espressif/bmi270_sensor` | 0.1.2 |
| `espressif/bq27220` | 0.1.2 |
| `espressif/button` | 4.2.1 |
| `espressif/cjson` | 1.7.19~2 |
| `espressif/cmake_utilities` | 0.5.0 |
| `espressif/dl_fft` | 0.8.0 |
| `espressif/esp-dsp` | 1.8.0 |
| `espressif/esp-sr` | 2.4.7 |
| `espressif/esp32-camera` | 2.1.8 |
| `espressif/esp_audio_codec` | 2.5.0 |
| `espressif/esp_audio_effects` | 1.3.0~1 |
| `espressif/esp_cam_sensor` | 2.6.0 |
| `espressif/esp_codec_dev` | 1.6.2 |
| `espressif/esp_image_effects` | 1.2.0 |
| `espressif/esp_io_expander` | 1.2.1 |
| `espressif/esp_io_expander_tca9554` | 2.0.3 |
| `espressif/esp_io_expander_tca95xx_16bit` | 2.0.2 |
| `espressif/esp_jpeg` | 1.3.1 |
| `espressif/esp_lcd_axs15231b` | 2.1.1 |
| `espressif/esp_lcd_co5300` | 2.2.0 |
| `espressif/esp_lcd_gc9a01` | 2.0.4 |
| `espressif/esp_lcd_ili9341` | 2.1.0 |
| `espressif/esp_lcd_panel_io_additions` | 1.0.1~1 |
| `espressif/esp_lcd_spd2010` | 2.0.0~1 |
| `espressif/esp_lcd_st7701` | 2.0.2~2 |
| `espressif/esp_lcd_st77916` | 2.0.2 |
| `espressif/esp_lcd_st77922` | 2.0.2 |
| `espressif/esp_lcd_st7796` | 1.4.0 |
| `espressif/esp_lcd_touch` | 1.2.1 |
| `espressif/esp_lcd_touch_cst816s` | 1.1.2 |
| `espressif/esp_lcd_touch_ft5x06` | 1.1.1 |
| `espressif/esp_lcd_touch_gt1151` | 1.1.1 |
| `espressif/esp_lcd_touch_gt911` | 1.2.1 |
| `espressif/esp_lcd_touch_st7123` | 1.0.2 |
| `espressif/esp_lvgl_port` | 2.9.0 |
| `espressif/esp_mmap_assets` | 1.4.0 |
| `espressif/esp_new_jpeg` | 1.0.2 |
| `espressif/esp_sccb_intf` | 0.0.9 |
| `espressif/esp_video` | 2.5.0 |
| `espressif/freetype` | 2.14.3~1 |
| `espressif/gmf_fft` | 1.0.0 |
| `espressif/i2c_bus` | 1.5.2 |
| `espressif/iot_eth` | 1.1.0 |
| `espressif/iot_usbh_cdc` | 3.1.0 |
| `espressif/iot_usbh_rndis` | 0.3.1 |
| `espressif/knob` | 1.1.0 |
| `espressif/led_strip` | 3.0.3 |
| `espressif/mqtt` | 1.1.0 |
| `espressif/usb` | 1.5.0 |
| `espressif/usb_host_uvc` | 2.5.2 |
| `espressif2022/esp_emote_assets` | 0.1.2 |
| `espressif2022/esp_emote_expression` | 1.0.2 |
| `espressif2022/esp_emote_gfx` | 3.0.5 |
| `espressif2022/image_player` | 1.1.1 |
| `laride/heatshrink` | 0.4.1 |
| `lvgl/lvgl` | 9.5.0 |
| `m5stack/m5ioe1` | 1.0.9 |
| `m5stack/m5pm1` | 1.0.7 |
| `tny-robotics/sh1106-esp-idf` | 1.0.2 |
| `txp666/otto-emoji-gif-component` | 1.3.0 |
| `waveshare/custom_io_expander_ch32v003` | 2.0.0 |
| `waveshare/esp_lcd_sh8601` | 1.0.2 |
| `waveshare/esp_lcd_touch_cst9217` | 1.0.4 |
| `wvirgil123/sscma_client` | 1.0.4 |

## Rebuilding from upstream

```
git clone https://github.com/78/xiaozhi-esp32.git
cd xiaozhi-esp32
git checkout v2.5.0
git apply ../philosophypod-firmware-changes.patch
```

Then copy the five added files into place.

## Credits

- **xiaozhi-esp32** by Shenzhen Xinzhi Future Technology Co., Ltd. and contributors, MIT license.
- **Stardos Stencil** typeface, copyright 2011 Vernon Adams, SIL Open Font License 1.1. `stencil_font_20.c` is a bitmap rendering of its digits and the letters of "TURNS", and is distributed under the same license. The copyright notice and license text are in `STARDOS_STENCIL_LICENSE.txt`, next to this file.
- **Boot animation, videos and images** by Philipp Koralus.
- Components downloaded when the firmware is built carry their own licenses, found in each component's folder under `managed_components/` after a build.
