#!/usr/bin/env python3
"""Set up a PhilosophyPod over USB without logging its credentials.

Interactive defaults use macOS WiFi helpers when available. Explicit --ssid,
--host and --serial-port also work on platforms supported by pyserial. --port
is the server's TCP port (8000 by default, 8002 for the optional bridge).

PHILOSOPHYPOD_WIFI_PASSWORD supplies the WiFi password without a command-line
argument; an interactive password prompt is hidden. Environment variables may
still be visible to other processes running as the same user. DEVICE_TOKEN, if
set, is included in the USB payload. This tool never opens the project's env file.
"""

import argparse
import getpass
import ipaddress
import json
import os
import re
import subprocess
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None


SERVER_PORT = 8000
PASSWORD_ENV = "PHILOSOPHYPOD_WIFI_PASSWORD"
TOKEN_ENV = "DEVICE_TOKEN"
# Native USB Serial/JTAG used by the documented ESP32-S3 firmware. A USB ID is
# a selection hint, not authentication; require the firmware handshake as well.
NATIVE_USB_IDS = {(0x303A, 0x1001)}


def build_payload(ssid: str, password: str, ota_url: str) -> str:
    fields = {"ssid": ssid, "password": password, "ota_url": ota_url}
    token = os.environ.get(TOKEN_ENV, "").strip()
    if token:
        fields["token"] = token
    payload = json.dumps(fields, ensure_ascii=False)
    # The 512-byte firmware buffer needs room to read the newline and terminate.
    if len(payload.encode("utf-8")) > 510:
        raise ValueError("Setup values exceed the firmware's 510-byte USB payload limit.")
    return payload


def _mac_output(command: list[str]) -> tuple[str, str]:
    if sys.platform != "darwin":
        return "", ""
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return "", ""
    return result.stdout, result.stderr


def get_wifi_ssid() -> str | None:
    output, _ = _mac_output(["networksetup", "-getairportnetwork", "en0"])
    match = re.search(r"Current Wi-Fi Network:\s*(.+)", output)
    return match.group(1).strip() if match else None


def get_wifi_password(ssid: str) -> str | None:
    _, output = _mac_output([
        "security", "find-generic-password", "-ga", ssid,
        "-D", "AirPort network password",
    ])
    match = re.search(r'password:\s*"(.+)"', output)
    return match.group(1) if match else None


def get_local_ip() -> str | None:
    output, _ = _mac_output(["ipconfig", "getifaddr", "en0"])
    return output.strip() or None


def server_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Server port must be an integer from 1 to 65535.") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("Server port must be from 1 to 65535.")
    return port


def ota_url(host: str, port: int) -> str:
    """Accept a bare LAN hostname or IP, never credentials or a URL path."""
    host = host.strip()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if (not host or len(host) > 253 or not re.fullmatch(r"[A-Za-z0-9.-]+", host)
                or any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
                       for label in host.rstrip(".").split("."))):
            raise ValueError("Server host must be a bare LAN hostname or IP address, without a scheme, path or port.")
        address = None
    formatted = f"[{host}]" if address and address.version == 6 else host
    return f"http://{formatted}:{port}/xiaozhi/ota/"


def available_ports():
    if serial is None or list_ports is None:
        raise RuntimeError("USB setup requires pyserial. From the project root run: "
                           "python -m pip install -r requirements-device.txt")
    try:
        return sorted(list_ports.comports(), key=lambda info: info.device)
    except (OSError, serial.SerialException) as exc:
        raise RuntimeError("Could not list USB serial ports. Check USB permissions and reconnect the device.") from exc


def port_summary(info) -> str:
    identity = (f"{info.vid:04x}:{info.pid:04x}"
                if info.vid is not None and info.pid is not None else "unknown USB ID")
    # Do not output serial numbers or untrusted terminal control sequences.
    description = "".join(c for c in (info.description or "serial device") if c.isprintable())
    return f"{info.device} — {description} [{identity}]"


def find_serial_port(serial_port: str | None = None) -> str | None:
    ports = available_ports()
    if serial_port:
        return next((info.device for info in ports if info.device == serial_port), None)
    compatible = [info for info in ports if (info.vid, info.pid) in NATIVE_USB_IDS]
    if len(compatible) > 1:
        choices = "\n  ".join(port_summary(info) for info in compatible)
        raise RuntimeError("Multiple compatible devices are connected; no device was selected. "
                           "Rerun with --serial-port PORT after checking --list-ports:\n  " + choices)
    if compatible:
        return compatible[0].device
    return None


def wait_for_serial_port(serial_port: str | None = None, timeout: float = 120) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        port = find_serial_port(serial_port)
        if port:
            time.sleep(0.3)
            return port
        time.sleep(0.5)
    target = f"serial port {serial_port}" if serial_port else "a compatible ESP32 USB Serial/JTAG device"
    raise RuntimeError(f"Timed out waiting for {target}. Check the data cable and USB permissions. "
                       "Use --list-ports, then --serial-port PORT for a device with a different USB ID.")


def _read_marker(ser, marker: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        # Do not print arbitrary firmware output: it could contain credentials.
        if line == marker:
            return True
    return False


def send_to_device(payload: str, quiet: bool = False, serial_port: str | None = None) -> bool:
    """Select one device, wait for its handshake, send credentials, and close it."""
    tag = "[provision] " if quiet else "  "
    existing = find_serial_port(serial_port)
    already_connected = bool(existing)
    if existing is None:
        print(f"{tag}Waiting for the selected USB device..." if serial_port
              else f"{tag}Waiting for a compatible ESP32 USB Serial/JTAG device...")
        existing = wait_for_serial_port(serial_port)
    print(f"{tag}Using {existing}. Close any serial monitor before setup.")

    ser = serial.Serial()
    ser.port = existing
    ser.baudrate = 115200
    ser.timeout = 0.5
    ser.dtr = False
    ser.rts = False
    try:
        ser.open()
        ser.reset_input_buffer()
        if already_connected:
            print(f"{tag}Restarting the device; press RESET if it does not restart.")
            ser.rts = True
            time.sleep(0.2)
            ser.rts = False
        if not _read_marker(ser, "PROVISION_AVAILABLE", 30):
            raise RuntimeError("No PhilosophyPod provisioning handshake received. Check the chosen port, "
                               "close the serial monitor, and press RESET before retrying. No credentials were sent.")
        ser.write(b"PROVISION\n")
        ser.flush()
        time.sleep(0.1)
        ser.write((payload + "\n").encode("utf-8"))
        ser.flush()
        if not _read_marker(ser, "PROVISION_OK", 10):
            raise RuntimeError("The device did not confirm setup. It may have received the values; "
                               "check it before retrying with the same selected port.")
    except (OSError, serial.SerialException) as exc:
        raise RuntimeError(f"USB communication failed on {existing}. Close any serial monitor, "
                           "check port permissions, reconnect the cable, then retry.") from exc
    finally:
        ser.close()
    print(f"{tag}Done. The device is rebooting onto the new network.")
    return True


def provision_interactive(ssid: str | None = None, password: str | None = None,
                          host: str | None = None, port: int = SERVER_PORT,
                          serial_port: str | None = None) -> bool:
    print("=== PhilosophyPod USB setup ===\n")
    if ssid is None:
        suggested = get_wifi_ssid()
        ssid = (input(f"  WiFi SSID [{suggested}]: ").strip() or suggested) if suggested else input("  WiFi SSID: ").strip()
    if not ssid:
        raise ValueError("No WiFi SSID provided.")
    if password is None:
        if sys.platform == "darwin":
            use_keychain = input("  Look up the WiFi password in your Keychain? [y/N]: ").strip().lower()
            if use_keychain in ("y", "yes"):
                password = get_wifi_password(ssid)
                if not password:
                    print("  No password found in Keychain.")
        if not password:
            password = getpass.getpass("  WiFi password: ")
    if not password:
        raise ValueError("No WiFi password provided.")
    if host is None:
        suggested = get_local_ip()
        host = (input(f"  Server LAN address [{suggested}]: ").strip() or suggested) if suggested else input("  Server LAN address: ").strip()
    url = ota_url(host, port)
    print(f"  Server: {url}")
    print(f"  Device token: {'will be sent' if os.environ.get(TOKEN_ENV, '').strip() else 'not set'}")
    return send_to_device(build_payload(ssid, password, url), serial_port=serial_port)


def provision_background(ssid: str, password: str, host: str | None = None,
                         port: int = SERVER_PORT, serial_port: str | None = None) -> bool:
    host = host or get_local_ip()
    if not host:
        raise ValueError("Could not determine the server's LAN address. Pass --host ADDRESS (required outside macOS).")
    url = ota_url(host, port)
    print(f"[provision] Server: {url}; token={'yes' if os.environ.get(TOKEN_ENV, '').strip() else 'not set'}")
    return send_to_device(build_payload(ssid, password, url), quiet=True, serial_port=serial_port)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set up PhilosophyPod over USB")
    parser.add_argument("--ssid", help="WiFi SSID; skips this prompt in foreground mode")
    parser.add_argument("--pw", help="WiFi password (visible in process arguments); prefer the hidden prompt or " + PASSWORD_ENV)
    parser.add_argument("--host", help="Computer's LAN IP or hostname, without a scheme or port")
    parser.add_argument("--port", type=server_port, default=SERVER_PORT,
                        help="Server TCP port: 8000 (default), or 8002 for the bridge; not the USB port")
    parser.add_argument("--serial-port", help="Exact USB serial port from --list-ports (for example /dev/cu.usbmodem... or COM3)")
    parser.add_argument("--list-ports", action="store_true", help="List serial ports without reading or sending credentials")
    parser.add_argument("--bg", action="store_true", help="Never prompt; require SSID and password, and fail if device selection is ambiguous")
    args = parser.parse_args(argv)
    try:
        if args.list_ports:
            ports = available_ports()
            for info in ports:
                print(port_summary(info))
            if not ports:
                print("No serial ports found. Use a data-capable USB cable and check USB permissions.")
            return 0
        password = args.pw if args.pw is not None else os.environ.get(PASSWORD_ENV)
        if args.bg and (not args.ssid or not password):
            parser.error("--bg requires --ssid and a password in " + PASSWORD_ENV + " (or --pw); no interactive fallback")
        if args.pw is not None:
            print("Warning: --pw is visible in process arguments. Prefer the hidden prompt or password environment variable.", file=sys.stderr)
        if args.bg:
            success = provision_background(args.ssid, password, args.host, args.port, args.serial_port)
        else:
            success = provision_interactive(args.ssid, password, args.host, args.port, args.serial_port)
        return 0 if success else 1
    except KeyboardInterrupt:
        print("\nSetup cancelled.")
        return 1
    except (RuntimeError, ValueError, EOFError) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
