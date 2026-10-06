# PhilosophyPod

A handheld voice device for Inquiry Chat. You speak to it, and it speaks back, continuing your most recent Inquiry Chat conversation. Its screen shows your progress toward erotetic equilibrium.

It runs on a Waveshare ESP32-S3-Touch-LCD-3.49 board, using a modified copy of the open-source [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) firmware.

This page assumes Inquiry Chat itself is set up and running; see `../README.md`. Settings named here (`DEVICE_TOKEN`, `ALLOW_NETWORK_ACCESS`) live in the `env` file described in `../env.example`, and section 16 of `../CONVERSATION_LOGIC.md` describes how the device and the server talk.

## How it fits together

The device talks to Inquiry Chat over your WiFi network. There are two routes. The built-in route is the usual one and needs no extra server.

```
Built-in route (usual)
[Device] --Opus audio over WebSocket--> [Inquiry Chat, port 8000]
 listens, speaks, displays               transcribes, replies, speaks

Bridge route (optional)
[Device] --Opus audio over WebSocket--> [Bridge server] --HTTP--> [Inquiry Chat]
                                         ports 8001, 8002          port 8000
```

| Part | Where | Role |
|---|---|---|
| Device firmware | `xiaozhi-esp32/` | Records and plays audio, shows the display |
| Setup tool | `provision.py` | Gives the device its WiFi details, server address and token over USB |
| Inquiry Chat | The parent folder | Does the transcription, the conversation and the speech |
| Bridge server | `bridge_server.py` | Optional. Sits between the device and Inquiry Chat |

Which route a device uses depends on the server address it has been given: port 8000 for the built-in route, port 8002 for the bridge. The two routes differ slightly; see "Differences between the two routes".

## What the device does

- Plays a boot animation, then asks the server to resume: it repeats the last thing the assistant said, or speaks a welcome if the conversation is new.
- Tap to speak. Your words are transcribed and sent to the conversation, and the reply is spoken and shown on screen.
- Shows the equilibrium score as a bar, and changes its display when the conversation enters closing mode.
- Draws the shard's questions as nodes on a rotating capsule: coloured by depth in the graph (red, cyan, amber, violet), brighter as you engage with them, green once resolved, and pulsing when they are next in line.

## Setup

### 1. Install ESP-IDF 6.0.1 or later

The firmware was built and tested with ESP-IDF 6.0.3. Earlier major versions will not build it.

```bash
mkdir -p ~/esp && cd ~/esp
git clone -b v6.0.3 --depth 1 --recursive --shallow-submodules https://github.com/espressif/esp-idf.git esp-idf-v6.0.3
cd esp-idf-v6.0.3 && ./install.sh esp32s3
source ~/esp/esp-idf-v6.0.3/export.sh
```

The download and its tools take several gigabytes.

### 2. Set the default server address

Copy `xiaozhi-esp32/sdkconfig.board.example` to `xiaozhi-esp32/sdkconfig.board`, then edit the copy and set the address of the computer running Inquiry Chat, as seen on your local network:

```
CONFIG_OTA_URL="http://YOUR_COMPUTER_IP:8000/xiaozhi/ota/"
```

Use port 8000 for Inquiry Chat's built-in route, or 8002 for the bridge.

This address is only the default built into the firmware. Setting the device up over USB (step 4) saves an address on the device, and the device then uses the saved one. So an approximate value here is fine.

### 3. Build and flash

With the device connected by USB:

```bash
source ~/esp/esp-idf-v6.0.3/export.sh
cd xiaozhi-esp32
idf.py -B build/philosophypod -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.esp32s3;sdkconfig.philosophypod;sdkconfig.board" set-target esp32s3
idf.py -B build/philosophypod build
idf.py -B build/philosophypod flash monitor
```

The first command applies the device's settings: `sdkconfig.philosophypod` holds the ones every PhilosophyPod build needs (board, language, console on USB, echo cancellation off), and `sdkconfig.board` holds your server address from step 2. Run it again after changing either file; it discards the previous configuration.

These commands use a separate `build/philosophypod/` directory so cached absolute paths from before the folder rename are not reused. Existing binaries in `build/` and saved flash sets in `local-firmware/` remain available for local use; keep them.

The first build downloads about 60 components and takes several minutes.

### 4. Set the device up over USB

`provision.py` sends the device its WiFi name, WiFi password, the server's address and the device token, and the device saves them. The device and the computer must be on the same network. Run the setup again whenever the computer's address changes, for example on a different network.

**Automatically.** On macOS, `Launch_Inquiry_Chat.command` in the parent folder notices a device plugged in by USB and offers to set it up before starting the server. It suggests the current WiFi network and can look up its password in your Keychain, if you agree.

**By hand.** With the device plugged in:

```sh
python -m pip install -r ../requirements-device.txt
python provision.py --list-ports
python provision.py
```

Use the virtual environment's Python (on Windows, `..\.venv\Scripts\python.exe`
when running from this folder). The list command shows port names, descriptions
and USB IDs; it does not read or transmit credentials. Automatic selection accepts
one Espressif native USB Serial/JTAG device (`303a:1001`). If several match, setup
stops before opening a port. Choose the intended device explicitly with
`--serial-port PORT`, using the exact name shown by `--list-ports`. This also lets
you select a device using a different USB adapter. USB IDs help select a device;
they are not cryptographic authentication.

On macOS, missing values can be suggested from the current WiFi network and
computer address. Keychain lookup is optional and happens only after you agree.
On Linux or Windows, enter the missing values or provide them explicitly:

```sh
python provision.py --ssid "Your WiFi" --host 192.0.2.10 --serial-port PORT
```

Replace `192.0.2.10` with the computer's actual LAN address and `PORT` with the
listed USB port, such as `/dev/cu.usbmodem1101`, `/dev/ttyACM0` or `COM3`.
`--ssid` skips the SSID prompt in ordinary foreground mode. The WiFi password
prompt is hidden; alternatively set `PHILOSOPHYPOD_WIFI_PASSWORD` in the process
environment. Avoid `--pw` because command-line arguments are visible to other
processes. Environment variables can also be inspected by sufficiently privileged
or same-user processes; the tool does not log passwords or tokens.

`--bg` never prompts: it requires `--ssid` and a password, and also `--host` when
the macOS address lookup is unavailable. Missing values and ambiguous devices
produce an error instead of falling back to interactive prompts. These paths
have automated tests with fake USB devices; physical USB/reset behavior on Linux
and Windows has not been verified.

Close `idf.py monitor` or any other serial monitor before setup. The tool restarts
the selected device and waits for its PhilosophyPod handshake before sending any
credentials. If the handshake times out, check the port and firmware, press RESET,
and retry. Device output is not copied into the terminal because it could contain
credentials. A missing confirmation means the device may have received the values;
check it before retrying with the same selected port.

By default the device is pointed at Inquiry Chat's built-in route on port 8000.
To use the bridge, add `--port 8002` in either foreground or background mode.
`--port` is the server TCP port (1–65535); `--serial-port` selects the USB device.

How it works: for a few seconds after starting, the firmware announces `PROVISION_AVAILABLE` on its USB serial connection. The tool answers `PROVISION` followed by one line of JSON with `ssid`, `password`, `ota_url` and, if one is set, `token`.

### The device token

The server can require a secret from the device before letting it connect, so that other devices on the network cannot join your conversations.

- The launcher creates the token the first time it sets up a device, gives it to the device over USB, and saves it in the `env` file as `DEVICE_TOKEN`.
- The server never sends the token over the network. USB is the only way it reaches a device.
- From then on the server refuses any device that does not present it. The Terminal shows "Refused a device" when that happens.
- To set up a second device, or one that has lost its settings, plug it in and start Inquiry Chat; it is given the same token.
- Setting the token also makes the server listen on the network, for the device. Browsers on the network are still refused unless `ALLOW_NETWORK_ACCESS=1` is set.
- To run without a token, remove the `DEVICE_TOKEN` line from `env` and set `ALLOW_NETWORK_ACCESS=1`, or the server listens on this computer only and no device can reach it. Any device on the network can then connect.

To set the device up by hand with a token, pass it in the environment: `DEVICE_TOKEN=... python provision.py`. The bridge server checks the same `DEVICE_TOKEN` if it is set in its environment.

### Without USB

A device with no saved WiFi details creates a WiFi hotspot named "Xiaozhi-XXXX" on boot. Connect to it from a phone or laptop, open the page it presents, and enter your WiFi details. This sets WiFi only: the device then uses the default server address from step 2 and has no token, so the server will refuse it if a token is set.

### 5. Start the server

From the parent folder: double-click `Launch_Inquiry_Chat.command`, or run `python app.py`.

Only if you use the bridge route, also start the bridge, from this folder, in a second terminal:

```bash
pip install -r ../requirements-device.txt
python bridge_server.py
```

The bridge needs `ffmpeg` and the Opus audio library installed on the computer. It expects Inquiry Chat at `http://127.0.0.1:8000`; this is set by `INQUIRY_CHAT_URL` near the top of `bridge_server.py`.

### 6. Use

Once on WiFi, the device contacts the server and works in the most recently updated Inquiry Chat conversation. It cannot choose a shard itself, so start a conversation in the web app. With the built-in route the order doesn't matter: the device checks for the latest conversation on every turn, and says so aloud if there is none yet.

## Differences between the two routes

| | Through the bridge | Built into Inquiry Chat |
|---|---|---|
| Servers to run | Two | One |
| Ports | 8001 and 8002 | 8000 |
| Conversation handling | Uses the web chat's turn logic, including the per-turn steering reminder | A simpler version without the steering reminder |
| Welcome for a new conversation | The bridge's own wording: "Welcome to your inquiry on: ..." | Inquiry Chat's welcome message, with emphasis on the central question |
| If the device disconnects mid-turn | The reply is lost | The reply is queued and spoken on reconnect |
| Nodes on the rotating shard display | Not sent, so the display stays empty | Sent on connect and after every turn |
| Closing message at 100% | Spoken straight after the reply | Spoken as the next reply |
| Device token | Checked, if `DEVICE_TOKEN` is set where the bridge runs. Without it the bridge listens on this computer only unless `ALLOW_NETWORK_ACCESS=1` is also set | Checked, if `DEVICE_TOKEN` is set in `env`. Without it the server listens on this computer only unless `ALLOW_NETWORK_ACCESS=1` is also set |

## Reaching 100%

On the turn that brings a conversation to 100%, Inquiry Chat sends two messages: the normal reply, then a closing message with a summary and pointers for further thought. Through the bridge, the device speaks the reply first and the closing straight after, in one speaking turn. The closing is prepared while the reply is being spoken. If the closing cannot be generated, the device speaks the reply alone.

Through the built-in route, the closing comes as the assistant's next reply instead, after you speak again.

## Troubleshooting

| Symptom | What to do |
|---|---|
| Flashing or setup reports "No serial data received", or times out | Put the device in flashing mode: hold **BOOT**, press and release **RESET**, release **BOOT**. Then try again |
| The launcher does not mention the device | The computer does not see it on USB. Use a cable that carries data; some only charge |
| Terminal shows "Refused a device" | The device has no token or the wrong one. Set it up over USB again |
| Device shows a cloud error, Terminal shows nothing from it | The device cannot reach the server: the computer's address has changed, the server is not running, or the two are on different networks. Set the device up over USB again |
| Device stays on "Thinking" | Restart the device. If it recurs, check the Terminal for an error from the chat or speech service |
| The rotating display has no nodes | The bridge route does not send them. Use the built-in route |

## The firmware

`xiaozhi-esp32/` is a copy of upstream release v2.5.0, included as plain files, with local changes to 15 files, mainly:

- a custom display for this board: the equilibrium bar, closing-mode visuals, status captions, a "thinking" animation and the rotating shard display
- a boot animation, played from `main/boards/waveshare/esp32-s3-touch-lcd-3.49/assets/splash.mvid`
- handling for the `resume`, `equilibrium`, `closing_mode` and `ic_state` messages
- setup over USB at boot, in `main/main.cc`

The boot animation is made with `xiaozhi-esp32/scripts/make_splash_mvid.py`, which packs a video into the `.mvid` format.

The upstream firmware retains its [MIT license](xiaozhi-esp32/LICENSE), copyright Shenzhen Xinzhi Future Technology Co., Ltd. and others, with separately licensed files retaining their own terms. [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) lists those files, attributions and supplied license texts; keep these with redistributed source. [UPSTREAM.md](UPSTREAM.md) records the exact upstream version this copy came from, every firmware change, and credits.

Building the firmware downloads about 60 components and produces over 1 GB of files in `xiaozhi-esp32/build/` and `xiaozhi-esp32/managed_components/`. Keep successful builds locally for flashing your own devices. `local-firmware/` holds a separate local archive of the flash binaries and their flashing instructions, so they can be retained even when the build directory is regenerated. All three directories are ignored by Git and excluded from the public release; preparing a release should not delete these local files.

## Folder contents

| Path | Contents |
|---|---|
| `bridge_server.py` | The bridge server |
| `provision.py` | Sets up the device over USB: WiFi details, server address and device token |
| `xiaozhi-esp32/` | The device firmware. Most of its size is build output and downloaded components |
| `local-firmware/` | Local flash archives for personal use; excluded from Git and public releases |
| `UPSTREAM.md` | Where the firmware came from, what was changed, and credits |
| `philosophypod-firmware-changes.patch` | The exact changes made to the upstream firmware files |
