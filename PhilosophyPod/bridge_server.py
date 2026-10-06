"""
PhilosophyPod Bridge Server

Bridges the xiaozhi-esp32 WebSocket protocol to Inquiry Chat.
Runs alongside Inquiry Chat (which serves on port 8000).

Flow:
  1. Device boots → hits /xiaozhi/ota for config
  2. Device connects via WebSocket
  3. User speaks → device sends OPUS audio frames
  4. Bridge decodes OPUS → WAV → Inquiry Chat /api/stt
  5. Transcribed text → Inquiry Chat /api/chat/{session_id}
  6. Response text → Inquiry Chat /api/tts (MP3, converted with ffmpeg)
  7. Bridge encodes PCM → OPUS → streams back to device

Usage:
    pip install -r ../requirements-device.txt
    python bridge_server.py
"""

import asyncio
import json
import io
import wave
import os
import subprocess
import time
import uuid

import httpx
from websockets.asyncio.server import serve

# ── Config ───────────────────────────────────────────────────────────────────

BRIDGE_PORT = 8001
INQUIRY_CHAT_URL = "http://127.0.0.1:8000"
DEVICE_SAMPLE_RATE = 16000      # Device sends 16kHz OPUS
SERVER_SAMPLE_RATE = 24000      # We tell device we reply at 24kHz
OPUS_FRAME_DURATION_MS = 60     # 60ms per OPUS frame
SESSION_ID = None               # Auto-detect most recent
DEVICE_TOKEN = os.environ.get("DEVICE_TOKEN", "").strip()  # empty = no check
ALLOW_NETWORK_ACCESS = os.environ.get("ALLOW_NETWORK_ACCESS", "").strip().lower() in ("1", "true", "yes", "on")
# The bridge is reachable from the network only when a device token is set,
# or when ALLOW_NETWORK_ACCESS is switched on. Otherwise it listens on this
# computer only, which no device can reach: a safe default, not a useful one.
BRIDGE_HOST = "0.0.0.0" if (DEVICE_TOKEN or ALLOW_NETWORK_ACCESS) else "127.0.0.1"

# ── OPUS codec ───────────────────────────────────────────────────────────────

try:
    import opuslib
    opus_decoder = opuslib.Decoder(DEVICE_SAMPLE_RATE, 1)
    opus_encoder = opuslib.Encoder(SERVER_SAMPLE_RATE, 1, opuslib.APPLICATION_VOIP)
    HAS_OPUS = True
    print("[BRIDGE] OPUS codec loaded")
except Exception as exc:
    HAS_OPUS = False
    opus_decoder = None
    opus_encoder = None
    OPUS_SETUP_ERROR = (f"Opus audio is unavailable ({type(exc).__name__}). "
                        "Install requirements-device.txt and the system Opus library before starting the bridge.")
    print(f"[BRIDGE] {OPUS_SETUP_ERROR}")

# ── Inquiry Chat API helpers ─────────────────────────────────────────────────

async def inquiry_api_headers(client: httpx.AsyncClient) -> dict[str, str]:
    """Authorize each operation with the running server, including after restart."""
    response = await client.get(f"{INQUIRY_CHAT_URL}/api/csrf", timeout=10)
    response.raise_for_status()
    return {"X-Inquiry-CSRF": response.json()["token"]}

async def get_most_recent_session():
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{INQUIRY_CHAT_URL}/api/sessions", timeout=10)
        sessions = r.json()
        if not sessions:
            return None
        return sessions[0]  # sorted by updated_at desc

async def send_stt(wav_bytes: bytes) -> str:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{INQUIRY_CHAT_URL}/api/stt",
            content=wav_bytes,
            headers={"Content-Type": "audio/wav", **await inquiry_api_headers(client)},
            timeout=30,
        )
        return r.json().get("text", "")

async def get_session_details(session_id: str) -> dict:
    """Fetch full session including conversation history."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{INQUIRY_CHAT_URL}/api/sessions/{session_id}", timeout=10)
        r.raise_for_status()
        return r.json()

async def send_chat(session_id: str, message: str) -> tuple[dict, asyncio.Future]:
    """Inquiry Chat's /api/chat streams NDJSON: phase='reply' (assistant_message),
    then phase='eval' (equilibrium_score, level, closing_mode, ...), then, only
    on the turn that reaches 100% equilibrium, phase='closing' (a second
    assistant_message).

    Returns (merged, closing). `merged` is the reply and eval lines merged into
    one dict, so callers keep their flat-response contract. `closing` is a
    future that resolves to the closing message, or None if there is none. It
    is returned as soon as the eval line arrives, so the reply can be spoken
    while the closing is still being generated."""
    merged: dict = {}
    ready = asyncio.Event()
    closing: asyncio.Future = asyncio.get_running_loop().create_future()
    error: list[Exception] = []

    async def read_stream():
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    f"{INQUIRY_CHAT_URL}/api/chat/{session_id}",
                    json={"message": message, "detail_level": 1.0},
                    headers=await inquiry_api_headers(client),
                    timeout=120,
                ) as r:
                    r.raise_for_status()
                    async for line in r.aiter_lines():
                        if not line.strip():
                            continue
                        payload = json.loads(line)
                        if payload.get("phase") == "closing":
                            if not closing.done():
                                closing.set_result(payload.get("assistant_message") or None)
                            continue
                        merged.update(payload)
                        if payload.get("phase") == "eval":
                            ready.set()
        except Exception as e:
            # Before the eval line: the turn failed. After it: only the
            # closing was lost, and the reply can still be spoken.
            if ready.is_set():
                print(f"[BRIDGE] Chat stream ended early, no closing: {e}")
            else:
                error.append(e)
        finally:
            if not closing.done():
                closing.set_result(None)
            ready.set()

    task = asyncio.create_task(read_stream())
    _stream_tasks.add(task)
    task.add_done_callback(_stream_tasks.discard)

    await ready.wait()
    if error:
        raise error[0]
    return merged, closing


# Strong references to running stream readers, so they are not garbage
# collected while a closing is still on its way.
_stream_tasks: set = set()

async def fetch_tts_pcm(text: str) -> bytes:
    """Fetch speech from Inquiry Chat as MP3 and
    decode to mono s16le PCM at SERVER_SAMPLE_RATE for Opus encoding."""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{INQUIRY_CHAT_URL}/api/tts",
            json={"text": text, "output_format": "mp3_44100_128"},
            headers=await inquiry_api_headers(client),
            timeout=30,
        )
        return await asyncio.to_thread(mp3_to_pcm, r.content, SERVER_SAMPLE_RATE)

# ── Audio helpers ────────────────────────────────────────────────────────────

def mp3_to_pcm(mp3_data: bytes, sample_rate: int) -> bytes:
    """Decode MP3 bytes to mono 16-bit little-endian PCM at the given sample rate via ffmpeg."""
    proc = subprocess.run(
        [
            "ffmpeg", "-loglevel", "error", "-nostdin",
            "-f", "mp3", "-i", "pipe:0",
            "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "pipe:1",
        ],
        input=mp3_data, capture_output=True, check=True,
    )
    return proc.stdout


def pcm_to_wav(pcm_data: bytes, sample_rate: int = DEVICE_SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()

def pcm_to_opus_frames(pcm_data: bytes, sample_rate: int = SERVER_SAMPLE_RATE) -> list[bytes]:
    """Split PCM into OPUS frames."""
    if not HAS_OPUS:
        raise RuntimeError(OPUS_SETUP_ERROR)
    frame_samples = int(sample_rate * OPUS_FRAME_DURATION_MS / 1000)
    frame_bytes = frame_samples * 2  # 16-bit mono
    frames = []
    for i in range(0, len(pcm_data) - frame_bytes + 1, frame_bytes):
        chunk = pcm_data[i:i + frame_bytes]
        encoded = opus_encoder.encode(chunk, frame_samples)
        frames.append(encoded)
    return frames

# ── WebSocket handler ────────────────────────────────────────────────────────

def device_token_ok(websocket) -> bool:
    """True if no token is required, or the device presented the right one.
    The token comes from the environment variable DEVICE_TOKEN and reaches the
    device over USB (provision.py); the bridge never sends it."""
    if not DEVICE_TOKEN:
        return True
    import hmac
    given = websocket.request.headers.get("Authorization", "") or ""
    if given.lower().startswith("bearer "):
        given = given[7:]
    return hmac.compare_digest(given.strip().encode(), DEVICE_TOKEN.encode())


async def handle_device(websocket):
    # A browser always sends an Origin header on a WebSocket; the device
    # firmware never does. Web pages must not be able to join the conversation.
    if "Origin" in websocket.request.headers:
        print("[BRIDGE] Refused a connection from a web page, not a voice device.")
        await websocket.close(code=1008, reason="not a device")
        return
    if not device_token_ok(websocket):
        print("[BRIDGE] Refused a device: missing or wrong token. "
              "Set the device up over USB to give it the token.")
        await websocket.close(code=1008, reason="token required")
        return
    if not HAS_OPUS:
        await websocket.close(code=1011, reason="Opus unavailable; see bridge setup instructions")
        return
    session_id = SESSION_ID
    session_info = None
    audio_buffer = bytearray()
    listening = False
    client_id = websocket.request.headers.get("Client-Id", "unknown")

    print(f"[BRIDGE] Device connected: {client_id}")

    # Find most recent session
    if not session_id:
        session_info = await get_most_recent_session()
        if session_info:
            session_id = session_info["id"]
            print(f"[BRIDGE] Using session: {session_id} — {session_info.get('central_question', '')}")
        else:
            print("[BRIDGE] WARNING: No sessions found in Inquiry Chat")

    async for message in websocket:
        if isinstance(message, str):
            # JSON control message
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "hello":
                print(f"[BRIDGE] Hello from device")
                # Respond with hello + session config
                hello_resp = {
                    "type": "hello",
                    "session_id": str(uuid.uuid4()),
                    "transport": "websocket",
                    "audio_params": {
                        "format": "opus",
                        "sample_rate": SERVER_SAMPLE_RATE,
                        "channels": 1,
                        "frame_duration": OPUS_FRAME_DURATION_MS,
                    },
                }
                await websocket.send(json.dumps(hello_resp))

            elif msg_type == "listen":
                state = data.get("state")
                mode = data.get("mode", "unknown")
                print(f"[BRIDGE] Listen state={state} mode={mode}")
                if state == "start":
                    listening = True
                    audio_buffer = bytearray()
                    print("[BRIDGE] Listening started")
                elif state in ("stop", "detect", "end"):
                    listening = False
                    pcm_secs = len(audio_buffer) / (DEVICE_SAMPLE_RATE * 2)
                    print(f"[BRIDGE] Listening stopped, {len(audio_buffer)} bytes ({pcm_secs:.1f}s)")

                    if len(audio_buffer) < 3200:
                        print("[BRIDGE] Audio too short, ignoring")
                        await websocket.send(json.dumps({"type": "tts", "state": "stop"}))
                        continue

                    # Process the voice interaction
                    try:
                        await process_voice(websocket, session_id, bytes(audio_buffer))
                    except Exception as e:
                        print(f"[BRIDGE] Voice pipeline error: {e}")
                        import traceback; traceback.print_exc()
                        await websocket.send(json.dumps({"type": "tts", "state": "stop"}))

            elif msg_type == "resume":
                # Device just connected and wants the conversation continued.
                # Repeat the last assistant message, or speak the opening if the
                # conversation hasn't started yet.
                print(f"[BRIDGE] Resume requested by device")
                try:
                    await handle_resume(websocket, session_id)
                except Exception as e:
                    print(f"[BRIDGE] Resume error: {e}")
                    import traceback; traceback.print_exc()
                    try:
                        await websocket.send(json.dumps({"type": "tts", "state": "stop"}))
                    except Exception:
                        pass

            elif msg_type == "abort":
                listening = False
                print("[BRIDGE] Aborted")

            elif msg_type == "goodbye":
                print("[BRIDGE] Goodbye")
                break

        elif isinstance(message, bytes):
            # Binary = OPUS audio frame from device
            if listening and HAS_OPUS:
                try:
                    frame_samples = int(DEVICE_SAMPLE_RATE * OPUS_FRAME_DURATION_MS / 1000)
                    pcm = opus_decoder.decode(message, frame_samples)
                    audio_buffer.extend(pcm)
                except Exception as e:
                    print(f"[BRIDGE] OPUS decode error: {e}")

    print(f"[BRIDGE] Device disconnected: {client_id}")


async def handle_resume(websocket, session_id: str):
    """Pick what to say on a fresh connection, then stream the TTS to the device.

    Rule: repeat the last assistant message if there is one; otherwise, speak an
    opening built from the session's central_question.
    """
    if not session_id:
        print("[BRIDGE] Resume: no active session — nothing to say")
        await websocket.send(json.dumps({"type": "tts", "state": "stop"}))
        return

    try:
        session = await get_session_details(session_id)
    except Exception as e:
        print(f"[BRIDGE] Resume: failed to fetch session: {e}")
        await websocket.send(json.dumps({"type": "tts", "state": "stop"}))
        return

    conversation = session.get("conversation", []) or []
    central_question = (session.get("central_question") or "").strip()

    last_assistant = None
    for msg in reversed(conversation):
        if msg.get("role") == "assistant":
            content = (msg.get("content") or "").strip()
            if content:
                last_assistant = content
                break

    if last_assistant:
        text = last_assistant
        print(f"[BRIDGE] Resume: repeating last assistant message ({len(text)} chars)")
    elif central_question:
        text = (
            f"Welcome to your inquiry on: {central_question} "
            f"Share your initial thoughts to begin."
        )
        print(f"[BRIDGE] Resume: speaking opening for '{central_question[:60]}'")
    else:
        text = "Welcome. Let's begin."
        print(f"[BRIDGE] Resume: generic opening")

    await websocket.send(json.dumps({"type": "llm", "text": "", "emotion": "neutral"}))
    await websocket.send(json.dumps({"type": "tts", "state": "start"}))

    pcm_response = await fetch_tts_pcm(text)
    print(f"[BRIDGE] Resume TTS: {len(pcm_response)} bytes PCM")
    opus_frames = pcm_to_opus_frames(pcm_response, SERVER_SAMPLE_RATE)
    for frame in opus_frames:
        await websocket.send(frame)
        await asyncio.sleep(OPUS_FRAME_DURATION_MS / 1000 * 0.9)

    await websocket.send(json.dumps({"type": "tts", "state": "stop"}))
    print("[BRIDGE] Resume playback complete")


async def process_voice(websocket, session_id: str, pcm_data: bytes):
    """Full voice interaction: STT → Chat → TTS → stream back."""
    try:
        # 1. STT
        await websocket.send(json.dumps({
            "type": "stt", "text": "...",
        }))

        wav_data = pcm_to_wav(pcm_data, DEVICE_SAMPLE_RATE)
        transcript = await send_stt(wav_data)
        print(f"[BRIDGE] STT: \"{transcript}\"")

        if not transcript or transcript.strip() in (".", ""):
            await websocket.send(json.dumps({"type": "tts", "state": "stop"}))
            return

        await websocket.send(json.dumps({
            "type": "stt", "text": transcript,
        }))

        # 2. Chat with Inquiry Chat
        if not session_id:
            await websocket.send(json.dumps({
                "type": "llm", "text": "No active session found.",
                "emotion": "neutral",
            }))
            await websocket.send(json.dumps({"type": "tts", "state": "stop"}))
            return

        chat_resp, closing_message = await send_chat(session_id, transcript)
        reply = chat_resp.get("assistant_message", "Sorry, I couldn't process that.")
        eq_score = chat_resp.get("equilibrium_score", 0)
        level = chat_resp.get("level", 1)
        closing = chat_resp.get("closing_mode", {}) or {}
        print(
            f"[BRIDGE] Chat reply: \"{reply[:80]}...\" "
            f"(eq={eq_score:.1%}, lvl={level}, closing={closing.get('active', False)})"
        )

        # Forward equilibrium + closing_mode to device UI before TTS starts
        await websocket.send(json.dumps({
            "type": "equilibrium",
            "score": int(round(float(eq_score) * 100)),
        }))
        await websocket.send(json.dumps({
            "type": "closing_mode",
            "active": bool(closing.get("active", False)),
            "remaining": int(closing.get("remaining", 0)),
        }))

        # Send LLM response text to device display
        await websocket.send(json.dumps({
            "type": "llm", "text": "",
            "emotion": "neutral",
        }))

        # 3. TTS
        await websocket.send(json.dumps({"type": "tts", "state": "start"}))

        # On the turn that reaches 100% equilibrium a closing message follows
        # the reply. Prepare its audio while the reply is being spoken.
        async def closing_audio():
            text = await closing_message
            if not text:
                return None
            print(f"[BRIDGE] Closing message: \"{text[:80]}...\"")
            return await fetch_tts_pcm(text)

        closing_task = asyncio.create_task(closing_audio())

        pcm_response = await fetch_tts_pcm(reply)
        print(f"[BRIDGE] TTS: {len(pcm_response)} bytes PCM")

        # Encode PCM to OPUS and stream to device
        opus_frames = pcm_to_opus_frames(pcm_response, SERVER_SAMPLE_RATE)
        for frame in opus_frames:
            await websocket.send(frame)
            await asyncio.sleep(OPUS_FRAME_DURATION_MS / 1000 * 0.9)  # pace the frames slightly

        # Then the closing, in the same speaking turn so the device does not
        # start listening in between.
        try:
            closing_pcm = await closing_task
        except Exception as e:
            print(f"[BRIDGE] Closing audio failed, skipping it: {e}")
            closing_pcm = None
        if closing_pcm:
            print(f"[BRIDGE] Closing TTS: {len(closing_pcm)} bytes PCM")
            await asyncio.sleep(0.6)  # a breath between reply and closing
            for frame in pcm_to_opus_frames(closing_pcm, SERVER_SAMPLE_RATE):
                await websocket.send(frame)
                await asyncio.sleep(OPUS_FRAME_DURATION_MS / 1000 * 0.9)

        await websocket.send(json.dumps({"type": "tts", "state": "stop"}))
        print("[BRIDGE] TTS playback complete")

    except Exception as e:
        print(f"[BRIDGE] Error in voice pipeline: {e}")
        import traceback; traceback.print_exc()
        try:
            await websocket.send(json.dumps({"type": "tts", "state": "stop"}))
        except:
            pass

# ── HTTP server for OTA endpoint ─────────────────────────────────────────────

from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

activated_devices = set()

class OTAHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self._handle()
    def do_GET(self):
        self._handle()
    def _handle(self):
        host = self.headers.get("Host", f"127.0.0.1:{BRIDGE_PORT}").split(":")[0]
        device_id = self.headers.get("Device-Id", "unknown")

        if "/xiaozhi/ota/activate" in self.path:
            # Accept activation — mark device as activated
            activated_devices.add(device_id)
            print(f"[OTA] Device {device_id} activated")
            body = json.dumps({
                "websocket": {
                    "url": f"ws://{host}:{BRIDGE_PORT}/xiaozhi/ws",
                    "version": 1,
                },
                "server_time": {
                    "timestamp": int(time.time() * 1000),
                    "timezone_offset": 0,
                },
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif "/xiaozhi/ota" in self.path:
            config = {
                "websocket": {
                    "url": f"ws://{host}:{BRIDGE_PORT}/xiaozhi/ws",
                    "version": 1,
                },
                "server_time": {
                    "timestamp": int(time.time() * 1000),
                    "timezone_offset": 0,
                },
            }
            # Only include challenge if device hasn't activated yet
            if device_id not in activated_devices:
                config["activation"] = {
                    "code": "",
                    "message": "Connected to PhilosophyPod",
                    "challenge": "philosophypod_challenge_token",
                }
            body = json.dumps(config).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()
    def log_message(self, format, *args):
        print(f"[OTA] {args[0]}")

def run_ota_server():
    server = HTTPServer((BRIDGE_HOST, BRIDGE_PORT + 1), OTAHandler)
    print(f"[OTA] HTTP server on port {BRIDGE_PORT + 1}")
    server.serve_forever()

# ── Main ─────────────────────────────────────────────────────────────────────

async def main():
    if not HAS_OPUS:
        raise RuntimeError(OPUS_SETUP_ERROR)
    print("=" * 60)
    print("  PhilosophyPod Bridge Server")
    print(f"  WebSocket: ws://{BRIDGE_HOST}:{BRIDGE_PORT}")
    print(f"  OTA HTTP:  http://{BRIDGE_HOST}:{BRIDGE_PORT + 1}/xiaozhi/ota")
    print(f"  Inquiry Chat: {INQUIRY_CHAT_URL}")
    if BRIDGE_HOST != "0.0.0.0":
        print("  Listening on this computer only: no device can reach the bridge.")
        print("  Set DEVICE_TOKEN (recommended) or ALLOW_NETWORK_ACCESS=1 to open it.")
    print("=" * 60)

    # Verify Inquiry Chat is running
    try:
        session = await get_most_recent_session()
        if session:
            print(f"[BRIDGE] Inquiry Chat OK — session: {session['id']} ({session.get('central_question', '')[:50]})")
        else:
            print("[BRIDGE] WARNING: Inquiry Chat has no sessions")
    except Exception as e:
        print(f"[BRIDGE] WARNING: Can't reach Inquiry Chat at {INQUIRY_CHAT_URL}: {e}")

    # Start OTA HTTP server in background thread
    ota_thread = threading.Thread(target=run_ota_server, daemon=True)
    ota_thread.start()

    # Start WebSocket server
    async with serve(handle_device, BRIDGE_HOST, BRIDGE_PORT,
                     subprotocols=["xiaozhi"],
                     max_size=1024 * 1024,
                     ping_interval=30):
        print(f"[BRIDGE] WebSocket server running on port {BRIDGE_PORT}")
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None
