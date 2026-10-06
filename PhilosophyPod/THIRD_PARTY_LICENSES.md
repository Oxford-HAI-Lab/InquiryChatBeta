# Third-party licenses and notices

This inventory accompanies the source snapshot described in [UPSTREAM.md](UPSTREAM.md):
xiaozhi-esp32 v2.5.0 with the documented PhilosophyPod changes. Paths in the file
inventory are relative to `xiaozhi-esp32/`. Original copyright notices and license
headers remain in place; this document does not replace them or relicense the code.

## Scope and included license texts

| Material | Applicable notice or license text |
|---|---|
| Upstream xiaozhi-esp32 source, except separately licensed material below | [Upstream MIT license](xiaozhi-esp32/LICENSE), copyright 2025 Shenzhen Xinzhi Future Technology Co., Ltd. and Project Contributors |
| Inquiry Chat's original PhilosophyPod code, documented modifications and boot animation, except the Stardos-derived font | [Repository MIT license](../LICENSE), copyright 2026 Philipp Koralus |
| Files marked Apache-2.0 | [Apache License 2.0](LICENSES/Apache-2.0.txt); their individual Espressif copyright notices are retained |
| Files marked GPL 3.0 | [GNU GPL version 3](LICENSES/GPL-3.0.txt) |
| Oscillator files marked only “GPL license” | [GNU GPL version 3](LICENSES/GPL-3.0.txt) supplied for this distribution; the unspecified-version declarations and author notices are retained |
| Bitmap font generated from Stardos Stencil | [SIL Open Font License 1.1 and font copyright notice](STARDOS_STENCIL_LICENSE.txt) |
| GIF decoder and LVGL-derived GIF integration | [Existing gifdec public-domain notice](xiaozhi-esp32/main/display/lvgl_display/gif/LICENSE.txt), [LVGL MIT notice](LICENSES/LVGL-MIT.txt), and upstream MIT notice for xiaozhi adaptations; see the separate mapping below |

`GPL-unspecified` in the inventory is a documentation label, not an SPDX identifier.
Those six headers say “GPL license” without a version. The supplied GPLv3 text
includes the version-choice rule in section 14; this inventory does not turn the
original unversioned declaration into a GPLv3-only restriction. The five LilyGO
headers say “GPL 3.0”; no “or later” wording has been added.

These files are part of the source distribution even when their boards are not
selected in a PhilosophyPod build. Include the applicable license texts and
notices when redistributing them. A distribution containing `xiaozhi-esp32/`
must also carry this inventory, `LICENSES/`, `STARDOS_STENCIL_LICENSE.txt`, and the
repository MIT license for the local additions. If distributing a compiled board
variant, assess the licenses of the code and downloaded components actually
included in that binary as well.

## Explicit file-level declarations

The following table records the declarations in the supplied source, including
its existing attribution wording. In particular, the two LilyGO `.cc` display
drivers are Apache-2.0 while their `.h` files declare GPL 3.0. They must not be
collapsed into a single MIT or Apache-only component entry.

| File | Declaration | Retained attribution |
|---|---|---|
| `main/boards/espressif/esp-vocat/touch.h` | `Apache-2.0` | 2023 Espressif Systems (Shanghai) CO LTD |
| `main/boards/espressif/esp32-s3-lcd-ev-board-2/esp_lcd_gc9503.c` | `Apache-2.0` | 2023 Espressif Systems (Shanghai) CO LTD |
| `main/boards/espressif/esp32-s3-lcd-ev-board-2/esp_lcd_gc9503.h` | `Apache-2.0` | 2023 Espressif Systems (Shanghai) CO LTD |
| `main/boards/espressif/esp32-s3-lcd-ev-board/esp_io_expander_tca9554.c` | `Apache-2.0` | 2023-2024 Espressif Systems (Shanghai) CO LTD |
| `main/boards/espressif/esp32-s3-lcd-ev-board/esp_io_expander_tca9554.h` | `Apache-2.0` | 2022 Espressif Systems (Shanghai) CO LTD |
| `main/boards/espressif/esp32-s3-lcd-ev-board/esp_lcd_gc9503.c` | `Apache-2.0` | 2023 Espressif Systems (Shanghai) CO LTD |
| `main/boards/espressif/esp32-s3-lcd-ev-board/esp_lcd_gc9503.h` | `Apache-2.0` | 2023 Espressif Systems (Shanghai) CO LTD |
| `main/boards/espressif/esp32-s31-korvo-1/bsp_adc_calibration.h` | `Apache-2.0` | 2026 Espressif Systems (Shanghai) CO LTD |
| `main/boards/espressif/esp32-s31-korvo-1/esp32_s31_adc_calibration.c` | `Apache-2.0` | 2026 Espressif Systems (Shanghai) CO LTD |
| `main/boards/jiuchuan-s3/esp_lcd_panel_gc9301.c` | `Apache-2.0` | 2021-2024 Espressif Systems (Shanghai) CO LTD; 2024 Your Name |
| `main/boards/jiuchuan-s3/esp_lcd_panel_gc9301.h` | `Apache-2.0` | 2021-2023 Espressif Systems (Shanghai) CO LTD |
| `main/boards/kevin/yuying-313lcd/esp_lcd_gc9503.c` | `Apache-2.0` | 2023 Espressif Systems (Shanghai) CO LTD |
| `main/boards/kevin/yuying-313lcd/esp_lcd_gc9503.h` | `Apache-2.0` | 2023 Espressif Systems (Shanghai) CO LTD |
| `main/boards/lceda-course-examples/eda-robot-pro/oscillator.cc` | `GPL-unspecified` | (c) Juan Gonzalez-Gomez (Obijuan), Dec 2011; (c) txp666 for esp32, 202503 |
| `main/boards/lceda-course-examples/eda-robot-pro/oscillator.h` | `GPL-unspecified` | (c) Juan Gonzalez-Gomez (Obijuan), Dec 2011; (c) txp666 for esp32, 202503 |
| `main/boards/lceda-course-examples/eda-super-bear/oscillator.cc` | `GPL-unspecified` | (c) Juan Gonzalez-Gomez (Obijuan), Dec 2011; (c) txp666 for esp32, 202503 |
| `main/boards/lceda-course-examples/eda-super-bear/oscillator.h` | `GPL-unspecified` | (c) Juan Gonzalez-Gomez (Obijuan), Dec 2011; (c) txp666 for esp32, 202503 |
| `main/boards/lilygo/t-cameraplus-s3/pin_config.h` | `GPL-3.0` | Author: LILYGO_L |
| `main/boards/lilygo/t-circle-s3/pin_config.h` | `GPL-3.0` | Author: LILYGO_L |
| `main/boards/lilygo/t-display-p4/hi8561_driver.cc` | `Apache-2.0` | 2023-2024 Espressif Systems (Shanghai) CO LTD |
| `main/boards/lilygo/t-display-p4/hi8561_driver.h` | `GPL-3.0` | Author: LILYGO_L |
| `main/boards/lilygo/t-display-p4/rm69a10_driver.cc` | `Apache-2.0` | 2023-2024 Espressif Systems (Shanghai) CO LTD |
| `main/boards/lilygo/t-display-p4/rm69a10_driver.h` | `GPL-3.0` | Author: LILYGO_L |
| `main/boards/lilygo/t-display-s3-pro-mvsrlora/pin_config.h` | `GPL-3.0` | No author named in header |
| `main/boards/m5stack/tab5/esp_lcd_st7121.c` | `Apache-2.0` | 2024 Espressif Systems (Shanghai) CO LTD |
| `main/boards/m5stack/tab5/esp_lcd_st7121.h` | `Apache-2.0` | 2024-2025 Espressif Systems (Shanghai) CO LTD |
| `main/boards/m5stack/tab5/esp_lcd_st7123.c` | `Apache-2.0` | 2024 Espressif Systems (Shanghai) CO LTD |
| `main/boards/m5stack/tab5/esp_lcd_st7123.h` | `Apache-2.0` | 2025 Espressif Systems (Shanghai) CO LTD |
| `main/boards/otto-robot/oscillator.cc` | `GPL-unspecified` | (c) Juan Gonzalez-Gomez (Obijuan), Dec 2011; (c) txp666 for esp32, 202503 |
| `main/boards/otto-robot/oscillator.h` | `GPL-unspecified` | (c) Juan Gonzalez-Gomez (Obijuan), Dec 2011; (c) txp666 for esp32, 202503 |
| `main/boards/waveshare/esp32-s3-audio-board/esp_lcd_jd9853.c` | `Apache-2.0` | 2022-2023 Espressif Systems (Shanghai) CO LTD |
| `main/boards/waveshare/esp32-s3-audio-board/esp_lcd_jd9853.h` | `Apache-2.0` | 2022-2023 Espressif Systems (Shanghai) CO LTD |
| `main/boards/waveshare/esp32-s3-touch-lcd-3.49/stencil_font_20.c` | `OFL-1.1` | Copyright 2011 vernon adams; reserved font names retained |
| `main/boards/wk-esp32s3-dev/esp_lcd_ili9486.c` | `Apache-2.0` | 2022-2023 Espressif Systems (Shanghai) CO LTD |
| `main/boards/wk-esp32s3-dev/esp_lcd_ili9486.h` | `Apache-2.0` | 2022-2023 Espressif Systems (Shanghai) CO LTD |
| `main/boards/wk-esp32s3-dev/esp_lcd_nv3030b.c` | `Apache-2.0` | 2023 Espressif Systems (Shanghai) CO LTD |
| `main/boards/wk-esp32s3-dev/esp_lcd_nv3030b.h` | `Apache-2.0` | 2022-2023 Espressif Systems (Shanghai) CO LTD |
| `scripts/spiffs_assets/spiffs_assets_gen.py` | `Apache-2.0` | 2024-2025 Espressif Systems (Shanghai) CO LTD |

## GIF code and LVGL provenance

The [directory README](xiaozhi-esp32/main/display/lvgl_display/gif/README.md)
identifies this code as a port of LVGL's GIF implementation. The existing license
notice declares gifdec source and documentation public domain. LVGL-derived
integration and additions are accompanied by the LVGL MIT notice, without
removing that public-domain declaration or the xiaozhi MIT notice.

| File | Notices to retain |
|---|---|
| `main/display/lvgl_display/gif/gifdec.c` | gifdec public-domain notice; LVGL MIT notice and xiaozhi MIT notice for adaptations |
| `main/display/lvgl_display/gif/gifdec.h` | gifdec public-domain notice; LVGL MIT notice and xiaozhi MIT notice for adaptations |
| `main/display/lvgl_display/gif/gifdec_mve.h` | gifdec public-domain notice and LVGL MIT notice |
| `main/display/lvgl_display/gif/lvgl_gif.cc` | LVGL MIT notice and xiaozhi MIT notice |
| `main/display/lvgl_display/gif/lvgl_gif.h` | LVGL MIT notice and xiaozhi MIT notice |
| `main/display/lvgl_display/gif/README.md` | Existing provenance description and xiaozhi MIT notice |
| `main/display/lvgl_display/gif/LICENSE.txt` | Existing gifdec public-domain declaration, unchanged |

## NOTICE review

The publishable vendored snapshot was checked on 30 September 2026 for files
named `NOTICE` or `NOTICE.*`; none are present. The Apache-2.0 headers identify
Espressif copyright holders, and those notices remain intact in the files listed
above. Apache-2.0 section 4(d) concerns an upstream NOTICE file when one accompanies
the distributed work; this inventory does not claim an absent NOTICE exists or
replace any notice supplied with a future upstream update.

Downloaded `managed_components/`, build output and their licenses are excluded
from this source snapshot. Their own license and NOTICE files must be reviewed
and carried into any distribution that bundles those components or firmware
built from them. A firmware source update that introduces a NOTICE file requires
updating this inventory and retaining that notice.

## Authoritative sources and verification

The following files are unmodified copies fetched from their primary sources on
30 September 2026. The hashes cover the exact bytes, including whitespace.

| Local text | Primary source | SHA-256 |
|---|---|---|
| `LICENSES/Apache-2.0.txt` | [Apache Software Foundation](https://www.apache.org/licenses/LICENSE-2.0.txt) | `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` |
| `LICENSES/GPL-3.0.txt` | [Free Software Foundation](https://www.gnu.org/licenses/gpl-3.0.txt) | `3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986` |
| `LICENSES/LVGL-MIT.txt` | [LVGL v9.5.0](https://raw.githubusercontent.com/lvgl/lvgl/v9.5.0/LICENCE.txt) | `27a80bd36832ab42d35ad60c08b2b230a807a9bc0d58e94ec1531543dc49cbe8` |

GNU GPLv3 section 4 and Apache-2.0 section 4(a) require supplying their license
texts with source copies. Apache-2.0 sections 4(b)–(d), the MIT notices, and the
OFL set out the applicable attribution and redistribution requirements. The
source headers, retained notices and full license texts govern; this inventory
is a navigation aid.

Run `python3 -m unittest discover -s tests -p 'test_third_party_licenses.py' -v`
to check that explicit source-license declarations still match this inventory,
that referenced notices exist, that no new NOTICE file is overlooked, and that
the copied license texts retain their verified hashes. This check is not a
complete provenance or binary-license audit.
