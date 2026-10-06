#!/bin/bash
cd "$(dirname "$0")"
if [ ! -f .venv/bin/activate ]; then
  echo "No .venv folder here. Follow the Setup section of README.md first."
  read -p "Press Enter to close."
  exit 1
fi
source .venv/bin/activate

# The server reads the env file itself. The launcher needs two of its values
# for the checks below, read with the same parser the server uses.
if [ -f env ]; then
  OPENAI_API_KEY="$(python -c "from dotenv import dotenv_values; print(dotenv_values('env').get('OPENAI_API_KEY') or '')")"
  DEVICE_TOKEN="$(python -c "from dotenv import dotenv_values; print(dotenv_values('env').get('DEVICE_TOKEN') or '')")"
  export OPENAI_API_KEY DEVICE_TOKEN
fi

if [ -z "$OPENAI_API_KEY" ] || [ "$OPENAI_API_KEY" = "your-key-here" ]; then
  export OPENAI_API_KEY="$(security find-generic-password -s "openai-api-key" -w 2>/dev/null || echo "")"
fi

if [ -z "$OPENAI_API_KEY" ]; then
  echo "============================================"
  echo "  OPENAI_API_KEY not found."
  echo ""
  echo "  Option 1: Set it now (one time):"
  echo "    export OPENAI_API_KEY=\"sk-...\""
  echo ""
  echo "  Option 2: Store it in Keychain (persistent):"
  echo "    security add-generic-password -s openai-api-key -a $USER -w \"sk-...\""
  echo "============================================"
  read -r -s -p "Paste your OpenAI API key (input hidden): " OPENAI_API_KEY
  echo ""
  export OPENAI_API_KEY
fi

# ---------------------------------------------------------------------------
# PhilosophyPod voice device (optional). Only when one is plugged in by USB:
# offer to send it the WiFi details and this computer's address.
# ---------------------------------------------------------------------------
if ls /dev/cu.usbmodem* >/dev/null 2>&1 && [ -f PhilosophyPod/provision.py ]; then
  echo ""
  echo "  A USB serial device is connected."
  read -p "  Set it up for this network now? [Y/n]: " SETUP_DEVICE
  SETUP_DEVICE="${SETUP_DEVICE:-y}"
  if [[ "$SETUP_DEVICE" =~ ^[Yy] ]]; then
    if ! python -c 'import serial, opuslib; opuslib.Decoder(16000, 1)' >/dev/null 2>&1 \
        || ! command -v ffmpeg >/dev/null 2>&1; then
      echo "  Optional voice-device dependencies are missing. From this project folder, run:"
      echo "    source .venv/bin/activate"
      echo "    python -m pip install -r requirements-device.txt"
      echo "    brew install opus ffmpeg"
      echo "  Then launch again to set up the device. The web app will start now."
      SETUP_DEVICE=n
    fi
  fi
  if [[ "$SETUP_DEVICE" =~ ^[Yy] ]]; then
    AUTO_SSID=$(networksetup -getairportnetwork en0 2>/dev/null | sed -n 's/Current Wi-Fi Network: //p')
    if [ -n "$AUTO_SSID" ]; then
      read -p "  WiFi name [$AUTO_SSID]: " WIFI_SSID
      WIFI_SSID="${WIFI_SSID:-$AUTO_SSID}"
    else
      read -p "  WiFi name: " WIFI_SSID
    fi
    if [ -z "$WIFI_SSID" ]; then
      echo "  No WiFi name given, skipping device setup."
    else
      WIFI_PW=""
      read -p "  Look up the WiFi password in your Keychain? [Y/n]: " USE_KEYCHAIN
      USE_KEYCHAIN="${USE_KEYCHAIN:-y}"
      if [[ "$USE_KEYCHAIN" =~ ^[Yy] ]]; then
        WIFI_PW=$(security find-generic-password -ga "$WIFI_SSID" -D "AirPort network password" 2>&1 | sed -n 's/password: "\(.*\)"/\1/p')
        [ -z "$WIFI_PW" ] && echo "  Not found in Keychain."
      fi
      if [ -z "$WIFI_PW" ]; then
        read -s -p "  WiFi password: " WIFI_PW
        echo ""
      fi
      if [ -n "$WIFI_PW" ]; then
        # The device needs a secret to connect. Make one the first time.
        NEW_TOKEN=""
        if [ -z "$DEVICE_TOKEN" ]; then
          NEW_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
          DEVICE_TOKEN="$NEW_TOKEN"
        fi
        echo "  Setting up the device. This takes up to a minute..."
        if PHILOSOPHYPOD_WIFI_PASSWORD="$WIFI_PW" DEVICE_TOKEN="$DEVICE_TOKEN" \
            python PhilosophyPod/provision.py --ssid "$WIFI_SSID" --bg; then
          export DEVICE_TOKEN
          if [ -n "$NEW_TOKEN" ]; then
            # Keep the secret for next time, once the device has it
            [ -f env ] && [ -n "$(tail -c1 env)" ] && echo "" >> env
            echo "DEVICE_TOKEN=$NEW_TOKEN" >> env
            echo "  A device token was created and saved in the env file."
          fi
        else
          echo ""
          echo "  The device could not be set up. Check the setup error above."
          echo "  To identify connected devices, run:"
          echo "    python PhilosophyPod/provision.py --list-ports"
          echo "  With more than one device connected, use --serial-port to choose one."
          echo "  Close any serial monitor before retrying; press RESET if boot times out."
          [ -n "$NEW_TOKEN" ] && unset DEVICE_TOKEN
        fi
        unset NEW_TOKEN
      else
        echo "  No password given, skipping device setup."
      fi
      unset WIFI_PW
    fi
  fi
fi

echo ""
echo "  Starting Inquiry Chat..."
echo "  Open http://localhost:8000 in your browser."
echo ""

# Open the browser once the server answers (gives up waiting after ~30s)
(
  for _ in $(seq 1 60); do
    curl -s -o /dev/null http://localhost:8000 && break
    sleep 0.5
  done
  open "http://localhost:8000"
) &
python app.py
