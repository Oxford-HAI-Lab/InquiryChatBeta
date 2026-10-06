"""
Inquiry Chat

A chat application that guides users toward erotetic equilibrium with respect
to an inquiry complex shard. Features progress tracking, gamification, and
session persistence.
"""

from __future__ import annotations

import asyncio
import json
import re
import os
import time
import uuid
import hmac
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
# The env file wins over the shell, except that a real key from the shell
# (the launcher's Keychain lookup or prompt) beats an empty or placeholder
# OPENAI_API_KEY line left over from env.example.
_shell_openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
load_dotenv(Path(__file__).parent / "env", override=True)
if os.environ.get("OPENAI_API_KEY", "").strip() in ("", "your-key-here") and _shell_openai_key not in ("", "your-key-here"):
    os.environ["OPENAI_API_KEY"] = _shell_openai_key

import httpx
import openai
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ic_engine import (
    ICShard,
    build_chat_system_prompt,
    inquiry_complete,
    welcome_message,
    closing_mode_info,
    evaluate_equilibrium,
    load_shard,
)

from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(app):
    await _resolve_tts_provider()
    yield


app = FastAPI(title="Inquiry Chat", lifespan=_lifespan)

# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------
# By default the server listens only on this computer. It listens on the
# network when ALLOW_NETWORK_ACCESS is switched on in the env file, or when a
# DEVICE_TOKEN is set, so that a voice device that holds the token can reach
# it. In the second case, browsers on the network are still refused.
ALLOW_NETWORK_ACCESS = os.environ.get("ALLOW_NETWORK_ACCESS", "").strip().lower() in ("1", "true", "yes", "on")
# Secret the voice device must present to connect. Given to the device over
# USB by PhilosophyPod/provision.py; never sent over the network by the
# server. Empty = no check, and the device endpoints are then reachable from
# the network only if ALLOW_NETWORK_ACCESS is on.
DEVICE_TOKEN = os.environ.get("DEVICE_TOKEN", "").strip()
LISTEN_HOST = "0.0.0.0" if (ALLOW_NETWORK_ACCESS or DEVICE_TOKEN) else "127.0.0.1"
_LOCAL_CLIENTS = {"127.0.0.1", "::1"}
# Host names a browser may use for the local-only server. A web page on
# another site can point a name of its own at 127.0.0.1 (DNS rebinding) and
# then call the API as if it were local; the Host header gives that away.
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
_BROWSER_CSRF_TOKEN = secrets.token_urlsafe(32)
_SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS"}


def _origin_tuple(value: str) -> tuple[str, str, int] | None:
    """Compare complete origins, including the port; reject opaque origins."""
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment):
            return None
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        return parsed.scheme, parsed.hostname.lower(), port
    except ValueError:
        return None


def _is_local(client_host: str | None) -> bool:
    return (client_host or "") in _LOCAL_CLIENTS


def _host_name(host_header: str) -> str:
    """The host part of a Host header, without the port."""
    host = host_header.strip().lower()
    if host.startswith("["):
        return host[: host.index("]") + 1] if "]" in host else host
    return host.split(":")[0]


@app.middleware("http")
async def _local_only(request: Request, call_next):
    client = request.client.host if request.client else ""
    device_path = request.url.path.startswith("/xiaozhi/")
    if not ALLOW_NETWORK_ACCESS and not (DEVICE_TOKEN and device_path):
        if not _is_local(client):
            print(f"[ACCESS] Refused {request.method} {request.url.path} from {client}")
            return JSONResponse(
                status_code=403,
                content={"detail": "Inquiry Chat only accepts connections from the computer it runs on. "
                                   "Set ALLOW_NETWORK_ACCESS=1 in the env file to change this."},
            )
        host = _host_name(request.headers.get("host", ""))
        if host not in _LOCAL_HOSTS:
            print(f"[ACCESS] Refused {request.method} {request.url.path}: Host header {host!r}")
            return JSONResponse(
                status_code=403,
                content={"detail": "Open Inquiry Chat as http://localhost:8000 or http://127.0.0.1:8000."},
            )
    if request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        expected_origin = _origin_tuple(f"{request.url.scheme}://{request.headers.get('host', '')}")
        if origin is not None and (_origin_tuple(origin) is None or _origin_tuple(origin) != expected_origin):
            return JSONResponse(status_code=403, content={"detail": "Cross-origin API requests are not allowed."})
        if request.method not in _SAFE_HTTP_METHODS:
            supplied = request.headers.get("x-inquiry-csrf", "")
            if not hmac.compare_digest(supplied.encode(), _BROWSER_CSRF_TOKEN.encode()):
                return JSONResponse(status_code=403, content={"detail": "Reload Inquiry Chat before making this request."})
            if request.method in {"POST", "PUT", "PATCH"} and request.url.path != "/api/stt":
                content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type != "application/json":
                    return JSONResponse(status_code=415, content={"detail": "This endpoint requires application/json."})
    return await call_next(request)


@app.get("/api/csrf")
async def browser_csrf():
    """Same-origin bootstrap for browser and deliberate native API clients."""
    return JSONResponse({"token": _BROWSER_CSRF_TOKEN}, headers={"Cache-Control": "no-store"})


def _device_token_ok(ws) -> bool:
    """True if no token is required, or the device presented the right one."""
    if not DEVICE_TOKEN:
        return True
    import hmac
    given = ws.headers.get("authorization", "")
    if given.lower().startswith("bearer "):
        given = given[7:]
    return hmac.compare_digest(given.strip().encode(), DEVICE_TOKEN.encode())


def _device_ws_refusal(ws) -> str | None:
    """Why a voice-device connection must be refused, or None to accept it.

    Web pages cannot be voice devices: a browser always sends an Origin header
    on a WebSocket, the device firmware never does, and a page open in the
    owner's browser must not be able to reach the conversation this way."""
    if "origin" in ws.headers:
        return "connection came from a web page, not a voice device"
    client = ws.client.host if ws.client else ""
    if not _is_local(client) and not ALLOW_NETWORK_ACCESS and not DEVICE_TOKEN:
        return "the server is not open to the network and no DEVICE_TOKEN is set"
    if not _device_token_ok(ws):
        return "missing or wrong token. Set the device up over USB to give it the token"
    if not _HAS_OPUS:
        return "Opus audio is unavailable. Install requirements-device.txt and the system Opus library"
    return None
# Every file the server needs is found from its own location, so it can be
# started from any working directory.
PROJECT_ROOT = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "static")), name="static")

SESSIONS_DIR = PROJECT_ROOT / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

API_KEY = os.environ.get("OPENAI_API_KEY", "")
CHAT_MODEL = os.environ.get("OPENAI_CHAT_MODEL", "gpt-5.6-sol")
TRANSCRIBE_MODEL = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "gpt-transcribe")
# Largest audio upload accepted for transcription (OpenAI's own limit).
MAX_AUDIO_BYTES = 25 * 1024 * 1024
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
# Default: the voice made for Inquiry Chat. It is a custom voice, so an
# ElevenLabs account can only use it if the voice has been shared with it;
# other accounts set ELEVENLABS_VOICE_ID to a voice of their own.
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "yHfgpRM0HDTqWxFXMMUf")
# OpenAI voice, used when ElevenLabs is not configured or its voice is not
# available to the account. Voices: alloy, ash, ballad, coral, echo, sage,
# shimmer, verse, marin, cedar.
OPENAI_TTS_MODEL = os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_TTS_VOICE = os.environ.get("OPENAI_TTS_VOICE", "ash")
# "auto": ElevenLabs when its key is set and the voice can be used, else
# OpenAI. "elevenlabs" or "openai" force one.
TTS_PROVIDER_SETTING = os.environ.get("TTS_PROVIDER", "auto").strip().lower() or "auto"

# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _valid_session_id(session_id: str) -> bool:
    return bool(_SESSION_ID_RE.match(session_id or ""))


def save_session(session_id: str, data: dict) -> None:
    if not _valid_session_id(session_id):
        raise ValueError("invalid session id")
    with open(SESSIONS_DIR / f"{session_id}.json", "w") as f:
        json.dump(data, f, indent=2)


def load_session(session_id: str) -> dict | None:
    if not _valid_session_id(session_id):
        return None
    path = SESSIONS_DIR / f"{session_id}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


# A node is drawn as resolved (green) from this display score up. The voice
# device uses the same value in its firmware.
NODE_RESOLVED_DISPLAY = 0.85
# How many nodes are marked as "next in line". The session's frontier lists
# every unresolved node in priority order, which early in a chat is nearly
# all of them; the displays mark only the first few.
NEXT_UP_MARKS = 2


def _next_up(shard: ICShard, frontier: list) -> list[str]:
    """The first few unresolved nodes of the frontier, in priority order."""
    return [
        nid for nid in frontier
        if nid in shard.nodes
        and shard.nodes[nid].disposition not in ("settled", "rejected_understood")
    ][:NEXT_UP_MARKS]


def _nodes_info(shard: ICShard, frontier: list) -> list[dict]:
    """Per-node data for the web app's shard map. `display_score`, `resolved`
    and `next_up` follow the same rules as the voice device's display."""
    next_up = _next_up(shard, frontier)
    info = []
    for node in shard.nodes.values():
        display_score = shard._equilibrium_contribution(node)
        info.append({
            "id": node.id,
            "text": node.text,
            "parent": node.parent,
            "engagement_score": node.engagement_score,
            "engaged": node.engaged,
            "disposition": node.disposition,
            "raise_count": node.raise_count,
            "display_score": display_score,
            "resolved": display_score >= NODE_RESOLVED_DISPLAY,
            "next_up": node.id in next_up,
        })
    return info


def _percent(score: float) -> int:
    """A score as a whole percentage, rounded half up as the web page does."""
    return int(score * 100 + 0.5)


def _current_shard_info(data: dict) -> tuple[float, str]:
    """(equilibrium score, shard title) for the session list. The score is
    recomputed under the current formula from the session's saved node scores
    and dispositions, and the title is read from the shard. Falls back to the
    saved values if the shard can't be loaded."""
    try:
        shard = load_shard(data["shard_dir"])
    except Exception:
        return data.get("equilibrium_score", 0), data.get("shard_name", "")
    for nid, score in data.get("node_scores", {}).items():
        if nid in shard.nodes:
            shard.nodes[nid].engagement_score = score
    for nid, disp in data.get("node_dispositions", {}).items():
        if nid in shard.nodes:
            shard.nodes[nid].disposition = disp
    if "node_dispositions" not in data:
        _backfill_dispositions(shard, data.get("conversation", []))
    return shard.equilibrium_score(), shard.title


def list_sessions() -> list[dict]:
    sessions = []
    for path in SESSIONS_DIR.glob("*.json"):
        try:
            with open(path) as f:
                data = json.load(f)
            eq_score, shard_title = _current_shard_info(data)
            sessions.append({
                "id": data["session_id"],
                "central_question": data.get("central_question", ""),
                "shard_name": shard_title,
                "equilibrium_score": eq_score,
                "xp": data.get("xp", 0),
                "level": data.get("level", 1),
                "turn_count": len(data.get("conversation", [])) // 2,
                "updated_at": data.get("updated_at", ""),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return sessions


# ---------------------------------------------------------------------------
# Background-eval infrastructure
# ---------------------------------------------------------------------------
# A chat turn is split into two phases so the user (web or ESP32) doesn't
# wait for equilibrium re-evaluation before seeing/hearing the reply:
#   Phase 1 — generate reply, save conversation + raise_counts to disk.
#   Phase 2 — re-run evaluate_equilibrium in the background, merge the
#             eval-derived fields (scores, dispositions, frontier, xp,
#             level, closing-mode) back into the session.
# Complete turns share a separate lock across web and device entry points.
# Disk-state locks stay short except during a rewind. Every conversation
# change advances a persisted revision; slow evaluation and closing results
# are accepted only for the revision they actually used.

_session_locks: dict[str, asyncio.Lock] = {}
_turn_locks: dict[str, asyncio.Lock] = {}
_background_tasks: set[asyncio.Task] = set()


def _session_lock(session_id: str) -> asyncio.Lock:
    if session_id not in _session_locks:
        _session_locks[session_id] = asyncio.Lock()
    return _session_locks[session_id]


def _turn_lock(session_id: str) -> asyncio.Lock:
    """Serialize generation and saving, including browser/device overlap.

    These locks coordinate one server process. Run one worker per sessions
    directory; independent workers would need a shared locking service.
    Always acquire this before _session_lock when both are needed.
    """
    if session_id not in _turn_locks:
        _turn_locks[session_id] = asyncio.Lock()
    return _turn_locks[session_id]


def _conversation_revision(data: dict) -> int:
    # Sessions written before revisions were introduced start at zero.
    return data.get("conversation_revision", 0)


def _advance_conversation(data: dict) -> int:
    revision = _conversation_revision(data) + 1
    data["conversation_revision"] = revision
    return revision


def _spawn_bg(coro) -> asyncio.Task:
    """Fire-and-forget a coroutine while keeping a strong reference so the
    asyncio runtime can't GC the task mid-flight."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def _eval_and_merge(
    session_id: str, was_closing: bool, expected_revision: int | None = None,
) -> dict | None:
    """Phase 2 of a chat turn. Reloads session, re-runs evaluate_equilibrium
    against the current on-disk conversation, then writes only the
    eval-derived fields back. The slow LLM call happens outside the lock so
    concurrent endpoints (TTS streaming on the ESP32 WebSocket, other HTTP
    handlers) aren't blocked."""
    async with _session_lock(session_id):
        data = load_session(session_id)
        if not data:
            return None
        revision = _conversation_revision(data)
        if expected_revision is not None and revision != expected_revision:
            return None
        # If two evaluations start for the same conversation, only the most
        # recently requested one may merge, regardless of completion order.
        generation = data.get("evaluation_generation", 0) + 1
        data["evaluation_generation"] = generation
        save_session(session_id, data)
        shard = load_shard(data["shard_dir"])
        for nid, score in data.get("node_scores", {}).items():
            if nid in shard.nodes:
                shard.nodes[nid].engagement_score = score
                shard.nodes[nid].engaged = score >= 0.4
        for nid, disp in data.get("node_dispositions", {}).items():
            if nid in shard.nodes:
                shard.nodes[nid].disposition = disp
        for nid, count in data.get("node_raise_counts", {}).items():
            if nid in shard.nodes:
                shard.nodes[nid].raise_count = count
        conversation_snapshot = list(data.get("conversation", []))

    eval_result = await evaluate_equilibrium(shard, conversation_snapshot, API_KEY)

    async with _session_lock(session_id):
        data = load_session(session_id)
        if not data:
            return None
        if (_conversation_revision(data) != revision
                or data.get("evaluation_generation", 0) != generation):
            return None
        # Only this exact conversation and evaluation request may contribute
        # scores. A rewind, newer turn or deletion invalidates pending work.
        data["evaluated_generation"] = generation
        data["node_scores"] = {nid: n.engagement_score for nid, n in shard.nodes.items()}
        data["node_dispositions"] = {nid: n.disposition for nid, n in shard.nodes.items()}
        data["equilibrium_score"] = shard.equilibrium_score()
        data["frontier"] = eval_result.get("frontier", [])
        gamification = compute_gamification(data, shard)
        data["xp"] = gamification["xp"]
        data["level"] = gamification["level"]
        data["achievements"] = gamification["all_achievements"]
        cmode = closing_mode_info(shard, was_active=was_closing)
        data["closing_mode_active"] = cmode["active"]
        data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        save_session(session_id, data)

    nodes_info = _nodes_info(shard, data.get("frontier", []))

    return {
        "conversation_revision": revision,
        "evaluation_generation": generation,
        "equilibrium_score": data["equilibrium_score"],
        "node_scores": data["node_scores"],
        "nodes": nodes_info,
        "frontier": data["frontier"],
        "eval_summary": eval_result.get("summary", ""),
        "xp": gamification["xp"],
        "level": gamification["level"],
        "new_achievements": gamification["new_achievements"],
        "closing_mode": cmode,
    }


async def _generate_closing(
    session_id: str, expected_revision: int | None = None,
    expected_generation: int | None = None,
) -> str | None:
    async with _turn_lock(session_id):
        return await _generate_closing_locked(session_id, expected_revision, expected_generation)


async def _generate_closing_locked(
    session_id: str, expected_revision: int | None, expected_generation: int | None,
) -> str | None:
    """Follow-up closing message, generated right after the eval that brought
    the session to 100% equilibrium. Sent as its own assistant message so the
    reply path isn't slowed down. Returns None if the session isn't complete
    or the conversation has moved on in the meantime."""
    async with _session_lock(session_id):
        data = load_session(session_id)
        if not data:
            return None
        revision = _conversation_revision(data)
        generation = data.get("evaluation_generation", 0)
        if expected_revision is not None and revision != expected_revision:
            return None
        if expected_generation is not None and generation != expected_generation:
            return None
        if data.get("evaluated_generation", 0) != generation:
            return None  # A newer evaluation has started but has not merged.
        shard = load_shard(data["shard_dir"])
        for nid, score in data.get("node_scores", {}).items():
            if nid in shard.nodes:
                shard.nodes[nid].engagement_score = score
                shard.nodes[nid].engaged = score >= 0.4
        for nid, disp in data.get("node_dispositions", {}).items():
            if nid in shard.nodes:
                shard.nodes[nid].disposition = disp
        conversation = list(data.get("conversation", []))
    if not inquiry_complete(shard):
        return None

    system_prompt = build_chat_system_prompt(shard, [], closing_mode_was_active=True)
    followup_instruction = {
        "role": "system",
        "content": (
            "The inquiry reached full equilibrium with the user's last message. Write the closing "
            "now, as a follow-up message that will appear directly after your previous message. "
            "Skip part 1 of the closing: you have already responded to the user. Open by marking "
            "that the inquiry has reached equilibrium, then give the summary and the pointers for "
            "further thought. If your previous message ended with a question, do not repeat it or "
            "press for an answer; you may note in one clause that it can stand as something to "
            "keep thinking about. Do NOT ask a question."
        ),
    }
    messages = [{"role": "system", "content": system_prompt}] + conversation[-20:] + [followup_instruction]
    client = openai.AsyncOpenAI(api_key=API_KEY)
    response = await client.chat.completions.create(
        model=CHAT_MODEL, reasoning_effort="none",
        max_completion_tokens=500,
        messages=messages,
    )
    closing_message = (response.choices[0].message.content or "").strip()
    if not closing_message:
        return None

    async with _session_lock(session_id):
        data = load_session(session_id)
        if not data:
            return None
        if (_conversation_revision(data) != revision
                or data.get("evaluation_generation", 0) != generation):
            return None
        data["conversation"] = conversation + [{"role": "assistant", "content": closing_message}]
        _advance_conversation(data)
        data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        save_session(session_id, data)
    return closing_message


# Respellings applied to spoken text only (never to what is displayed), for
# words the TTS voice mispronounces. Keys are matched as whole words, ignoring
# case; a trailing "s" is carried over.
# A respelling ending in a comma keeps the word as written and adds a short
# pause after it when another word follows. "shard" was being read as "sherd"
# mid-phrase.
SPEECH_RESPELLINGS = {
    "shard": "shard,",
}

# The voice model generates differently on every request, so the same text
# can be pronounced differently from one time to the next. A fixed seed asks
# ElevenLabs to repeat the same rendering for the same text (best effort).
TTS_SEED = int(os.environ.get("ELEVENLABS_SEED", "20260929"))

# How the OpenAI voice should sound in general. The expressive step adds a
# per-reply instruction to this.
OPENAI_TTS_BASE_INSTRUCTIONS = (
    "You are a thoughtful, warm Socratic interlocutor in an unhurried "
    "conversation. Natural conversational pacing, clear diction, genuine "
    "interest in the other person's thinking, no theatrical exaggeration."
)

# Which voice service is in use: "elevenlabs" or "openai", decided once at
# startup by _resolve_tts_provider() and switched to OpenAI if an ElevenLabs
# request later fails.
_tts_provider: str | None = None
_tts_provider_note = ""
_tts_resolve_lock = asyncio.Lock()


async def _resolve_tts_provider() -> str:
    global _tts_provider, _tts_provider_note
    if _tts_provider:
        return _tts_provider
    async with _tts_resolve_lock:
        if _tts_provider:
            return _tts_provider
        if TTS_PROVIDER_SETTING == "openai":
            provider, note = "openai", "TTS_PROVIDER=openai"
        elif TTS_PROVIDER_SETTING == "elevenlabs":
            provider, note = "elevenlabs", "TTS_PROVIDER=elevenlabs"
        elif not ELEVENLABS_API_KEY:
            provider, note = "openai", "no ELEVENLABS_API_KEY"
        else:
            try:
                async with httpx.AsyncClient() as client:
                    r = await client.get(
                        f"https://api.elevenlabs.io/v1/voices/{ELEVENLABS_VOICE_ID}",
                        headers={"xi-api-key": ELEVENLABS_API_KEY}, timeout=10.0,
                    )
                if r.status_code == 200:
                    provider, note = "elevenlabs", f"ElevenLabs voice {ELEVENLABS_VOICE_ID}"
                elif r.status_code in (401, 403) and "missing_permissions" in r.text:
                    # A key limited to text-to-speech cannot list voices, so
                    # this says nothing about the voice. Try ElevenLabs.
                    provider = "elevenlabs"
                    note = ("the ElevenLabs key cannot check voices (no voices_read permission); "
                            "will switch to OpenAI if a request fails")
                elif r.status_code == 401:
                    provider, note = "openai", "ElevenLabs rejected the API key (HTTP 401)"
                else:
                    provider = "openai"
                    note = (f"ElevenLabs voice {ELEVENLABS_VOICE_ID} is not available to this "
                            f"account (HTTP {r.status_code}); set ELEVENLABS_VOICE_ID to a voice of your own")
            except Exception as e:
                provider = "elevenlabs"
                note = f"could not check the ElevenLabs voice ({type(e).__name__}); will switch to OpenAI if it fails"
        _tts_provider, _tts_provider_note = provider, note
        label = "ElevenLabs" if provider == "elevenlabs" else f"OpenAI voice {OPENAI_TTS_VOICE} ({OPENAI_TTS_MODEL})"
        print(f"[TTS] Using {label}: {note}")
        return provider


def _switch_tts_to_openai(reason: str) -> bool:
    """After an ElevenLabs failure, use the OpenAI voice from now on."""
    global _tts_provider, _tts_provider_note
    if TTS_PROVIDER_SETTING == "elevenlabs" or _tts_provider == "openai":
        return False
    _tts_provider, _tts_provider_note = "openai", reason
    print(f"[TTS] Switching to OpenAI voice {OPENAI_TTS_VOICE}: {reason}")
    return True


def _openai_tts_instructions(extra: str | None) -> str | None:
    if OPENAI_TTS_MODEL.startswith("tts-1"):
        return None  # these models do not take instructions
    extra = (extra or "").strip()
    return f"{OPENAI_TTS_BASE_INSTRUCTIONS} {extra}".strip()


_SPEECH_TAG_RE = re.compile(r"</?[A-Za-z_]+>")


async def _open_openai_speech(text: str, response_format: str, instructions: str | None):
    """Start an OpenAI speech request. Returns (context manager, response);
    raises HTTPException if the request is refused, before any audio."""
    # Text tagged for ElevenLabs before a switch to OpenAI would have its
    # tags read aloud; the OpenAI voice takes instructions instead.
    text = _SPEECH_TAG_RE.sub("", text)
    client = openai.AsyncOpenAI(api_key=API_KEY)
    kwargs = dict(model=OPENAI_TTS_MODEL, voice=OPENAI_TTS_VOICE,
                  input=_speech_text(text[:4096]), response_format=response_format)
    instr = _openai_tts_instructions(instructions)
    if instr:
        kwargs["instructions"] = instr
    cm = client.audio.speech.with_streaming_response.create(**kwargs)
    try:
        resp = await cm.__aenter__()
    except openai.APIStatusError as e:
        raise HTTPException(status_code=502, detail=f"OpenAI speech failed: HTTP {e.status_code}")
    except openai.OpenAIError as e:
        raise HTTPException(status_code=502, detail=f"OpenAI speech failed: {type(e).__name__}")
    return cm, resp


async def _open_elevenlabs_speech(text: str, output_format: str, seed: int):
    """Start an ElevenLabs request. Returns (client, response) with the body
    still streaming, or None if ElevenLabs refused it (after switching the
    provider to OpenAI)."""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}/stream"
    headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}
    payload = {
        "text": _speech_text(text[:5000]),
        "model_id": "eleven_v3",
        "seed": seed,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        "optimize_streaming_latency": 3,
    }
    client = httpx.AsyncClient(timeout=30.0)
    try:
        # ElevenLabs reads output_format from the URL only; in the body it is
        # ignored and MP3 comes back whatever was asked for.
        req = client.build_request("POST", url, params={"output_format": output_format},
                                   json=payload, headers=headers)
        resp = await client.send(req, stream=True)
    except Exception as e:
        await client.aclose()
        _switch_tts_to_openai(f"ElevenLabs request failed ({type(e).__name__})")
        return None
    if resp.status_code != 200:
        await resp.aclose()
        await client.aclose()
        _switch_tts_to_openai(f"ElevenLabs refused the request (HTTP {resp.status_code})")
        return None
    return client, resp


def _speech_text(text: str) -> str:
    """Prepare text for TTS: drop markdown emphasis markers and apply
    SPEECH_RESPELLINGS."""
    text = re.sub(r"\*{1,3}", "", text)
    for word, respelling in SPEECH_RESPELLINGS.items():
        pause = respelling.endswith(",")
        base = respelling.rstrip(",")

        def _swap(m, base=base, pause=pause):
            out = base + m.group(2)
            if m.group(1)[0].isupper():
                out = out[0].upper() + out[1:]
            return out + "," if pause else out

        # With a pause, only where a word follows directly; existing
        # punctuation after the word already gives the break.
        follows = r"(?=\s+[\w\[])" if pause else ""
        text = re.sub(rf"\b({re.escape(word)})(s?)\b{follows}", _swap, text, flags=re.IGNORECASE)
    return text


# ---------------------------------------------------------------------------
# Gamification
# ---------------------------------------------------------------------------

ACHIEVEMENTS = [
    {"id": "first_question", "name": "First Inquiry", "desc": "Begin your philosophical journey", "threshold": 1},
    {"id": "five_nodes", "name": "Questioner", "desc": "Engage with 5 questions in the inquiry complex", "threshold": 5},
    {"id": "ten_nodes", "name": "Deep Thinker", "desc": "Engage with 10 questions", "threshold": 10},
    {"id": "all_nodes", "name": "Philosopher", "desc": "Engage with every question in the complex", "threshold": None},  # every node in the shard
    {"id": "half_equilibrium", "name": "Seeking Balance", "desc": "Reach 50% erotetic equilibrium", "threshold": 0.5},
    {"id": "high_equilibrium", "name": "Approaching Wisdom", "desc": "Reach 75% equilibrium", "threshold": 0.75},
    {"id": "full_equilibrium", "name": "Erotetic Equilibrium", "desc": "Achieve full equilibrium with the inquiry complex", "threshold": 0.95},
    {"id": "deep_engagement", "name": "Depth Charge", "desc": "Score 0.9+ engagement on any single node", "threshold": 0.9},
    {"id": "cross_link", "name": "Web Weaver", "desc": "Engage with nodes connected by a cross-edge", "threshold": 2},
]


def compute_gamification(session_data: dict, shard: ICShard) -> dict:
    """Compute XP, level, and newly unlocked achievements."""
    scores = session_data.get("node_scores", {})
    prev_achievements = set(session_data.get("achievements", []))

    engaged_count = sum(1 for s in scores.values() if s >= 0.4)
    eq_score = shard.equilibrium_score()
    max_single = max(scores.values()) if scores else 0

    # XP: base points per engagement level
    xp = int(sum(s * 100 for s in scores.values()))

    # Level: 1-10 based on equilibrium
    level = max(1, min(10, int(eq_score * 10) + 1))

    # Check achievements
    new_achievements = []
    earned = set(prev_achievements)

    for ach in ACHIEVEMENTS:
        if ach["id"] in earned:
            continue
        unlocked = False
        if ach["id"] == "first_question" and engaged_count >= ach["threshold"]:
            unlocked = True
        elif ach["id"] in ("five_nodes", "ten_nodes") and engaged_count >= ach["threshold"]:
            unlocked = True
        elif ach["id"] == "all_nodes" and engaged_count >= len(shard.nodes):
            unlocked = True
        elif ach["id"] == "half_equilibrium" and eq_score >= ach["threshold"]:
            unlocked = True
        elif ach["id"] == "high_equilibrium" and eq_score >= ach["threshold"]:
            unlocked = True
        elif ach["id"] == "full_equilibrium" and eq_score >= ach["threshold"]:
            unlocked = True
        elif ach["id"] == "deep_engagement" and max_single >= ach["threshold"]:
            unlocked = True
        elif ach["id"] == "cross_link":
            # Check if user engaged both ends of any cross-edge
            cross_edges = [e for e in shard.edges if e.comment]
            cross_engaged = sum(
                1 for e in cross_edges
                if scores.get(e.from_id, 0) >= 0.4 and scores.get(e.to_id, 0) >= 0.4
            )
            if cross_engaged >= ach["threshold"]:
                unlocked = True

        if unlocked:
            earned.add(ach["id"])
            new_achievements.append(ach)

    return {
        "xp": xp,
        "level": level,
        "new_achievements": new_achievements,
        "all_achievements": list(earned),
    }


# ---------------------------------------------------------------------------
# Legacy session backfill
# ---------------------------------------------------------------------------

def _backfill_dispositions(shard: ICShard, conversation: list[dict]) -> None:
    """For sessions created before disposition tracking was added, estimate
    dispositions and raise counts from the existing conversation history."""

    # Count how many times the assistant raised each node's topic
    for node in shard.nodes.values():
        key_terms = [t for t in node.text.lower().split() if len(t) > 4][:3]
        if not key_terms:
            continue
        for msg in conversation:
            if msg["role"] != "assistant":
                continue
            msg_lower = msg["content"].lower()
            if sum(1 for t in key_terms if t in msg_lower) >= 1:
                node.raise_count += 1

    # Detect dismissals: look for user complaints about repetition and
    # short affirmative-only responses to nodes that have been raised
    # multiple times but still have low scores
    user_complaints = set()
    for i, msg in enumerate(conversation):
        if msg["role"] != "user":
            continue
        lower = msg["content"].lower()
        if any(phrase in lower for phrase in [
            "already ask", "already said", "repeating", "same question",
            "keep pushing", "you keep", "didn't you already",
        ]):
            # Find which node the preceding assistant message was about
            if i > 0 and conversation[i - 1]["role"] == "assistant":
                asst_lower = conversation[i - 1]["content"].lower()
                for node in shard.nodes.values():
                    key_terms = [t for t in node.text.lower().split() if len(t) > 4][:3]
                    if key_terms and sum(1 for t in key_terms if t in asst_lower) >= 1:
                        user_complaints.add(node.id)

    # Mark dispositions
    for node in shard.nodes.values():
        if node.engagement_score >= 0.7:
            node.disposition = "settled"
        elif node.id in user_complaints or (node.raise_count >= 3 and node.engagement_score < 0.5):
            node.disposition = "dismissed"
        # Leave the rest as "active" — let the evaluator refine on next turn


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    with open(PROJECT_ROOT / "static" / "index.html") as f:
        content = f.read()
    return HTMLResponse(content, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


# Browsers ask for these at the site root whether or not the page links them.
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(PROJECT_ROOT / "static" / "favicon.ico")


@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
async def apple_touch_icon():
    return FileResponse(PROJECT_ROOT / "static" / "apple-touch-icon.png")


@app.get("/api/shards")
async def get_shards():
    """Discover available inquiry complex shards: every JSON file under
    Shards/, plus any in the project folder itself. Each file is listed by
    its path relative to the project folder, so a folder holding several
    shard files shows all of them."""
    shards = []
    shards_dir = PROJECT_ROOT / "Shards"
    candidates = list(shards_dir.rglob("*.json")) if shards_dir.exists() else []
    candidates += list(PROJECT_ROOT.glob("*.json"))
    seen = set()
    for json_file in candidates:
        if any(p.startswith(".") for p in json_file.relative_to(PROJECT_ROOT).parts[:-1]):
            continue
        key = json_file.resolve()
        if key in seen:
            continue
        seen.add(key)
        try:
            with open(json_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            print(f"[SHARDS] Skipping {json_file}: cannot be read as JSON ({e})")
            continue
        if not isinstance(data, dict):
            continue
        missing = [k for k in ("central", "nodes", "edges") if k not in data]
        if missing:
            # Only worth a warning if it looks like a shard at all
            if len(missing) < 3:
                print(f"[SHARDS] Skipping {json_file}: missing {', '.join(missing)}")
            continue
        contexts_dir = json_file.parent / "contexts"
        has_contexts = contexts_dir.exists() and any(contexts_dir.iterdir())
        shards.append({
            "dir": str(json_file.relative_to(PROJECT_ROOT)),
            "name": json_file.stem,
            "title": data.get("title") or json_file.stem,
            "source": data.get("source", ""),
            "central_question": data["central"],
            "node_count": len(data["nodes"]),
            "edge_count": len(data["edges"]),
            "has_contexts": has_contexts,
        })
    shards.sort(key=lambda s: s["title"].lower())
    return shards


@app.get("/api/sessions")
async def get_sessions():
    return list_sessions()


@app.post("/api/sessions/new")
async def new_session(request: Request):
    body = await request.json()
    shard_dir = str(body.get("shard_dir", "") or "")
    central_question = str(body.get("central_question", "") or "")

    # Only shard files inside the project folder, as listed by /api/shards.
    # The path arrives from the browser and must not be able to name any
    # other file on this computer.
    root = PROJECT_ROOT
    try:
        resolved = (root / shard_dir).resolve()
        inside = resolved.is_relative_to(root)
    except (OSError, ValueError):
        inside = False
    if not shard_dir or not inside or not resolved.exists():
        raise HTTPException(status_code=400, detail="Choose a shard from the list")
    try:
        shard = load_shard(str(resolved.relative_to(root)))
    except Exception as e:
        print(f"[SHARDS] Cannot load {shard_dir}: {type(e).__name__}: {e}")
        raise HTTPException(status_code=400, detail="That shard cannot be loaded; see the Terminal")

    if central_question:
        shard.central_question = central_question

    session_id = uuid.uuid4().hex
    session_data = {
        "session_id": session_id,
        "shard_dir": shard_dir,
        "shard_name": shard.title,
        "central_question": shard.central_question,
        "conversation": [],
        "conversation_revision": 0,
        "node_scores": {nid: 0.0 for nid in shard.nodes},
        "node_dispositions": {nid: "active" for nid in shard.nodes},
        "node_raise_counts": {nid: 0 for nid in shard.nodes},
        "equilibrium_score": 0.0,
        "frontier": list(shard.nodes.keys())[:2],
        "xp": 0,
        "level": 1,
        "achievements": [],
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    save_session(session_id, session_data)

    return {"session_id": session_id, "central_question": shard.central_question}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    data = load_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")

    # Also load shard to get node details
    shard = load_shard(data["shard_dir"])
    # Restore engagement scores and dispositions
    for nid, score in data.get("node_scores", {}).items():
        if nid in shard.nodes:
            shard.nodes[nid].engagement_score = score
            shard.nodes[nid].engaged = score >= 0.4
    for nid, disp in data.get("node_dispositions", {}).items():
        if nid in shard.nodes:
            shard.nodes[nid].disposition = disp
    for nid, count in data.get("node_raise_counts", {}).items():
        if nid in shard.nodes:
            shard.nodes[nid].raise_count = count

    # Backfill for legacy sessions
    if "node_dispositions" not in data:
        _backfill_dispositions(shard, data.get("conversation", []))

    nodes_info = _nodes_info(shard, data.get("frontier", []))

    edges_info = [{"from": e.from_id, "to": e.to_id, "weight": e.weight, "comment": e.comment} for e in shard.edges]

    return {
        **data,
        # Recomputed so sessions saved under an older scoring formula show
        # the current one.
        "equilibrium_score": shard.equilibrium_score(),
        "welcome_message": welcome_message(shard, data.get("central_question", "")),
        "welcome_speech": welcome_message(shard, data.get("central_question", ""), speech=True),
        "nodes": nodes_info,
        "edges": edges_info,
    }


@app.post("/api/chat/{session_id}")
async def chat(session_id: str, request: Request):
    async with _turn_lock(session_id):
        return await _chat_turn(session_id, request)


async def _chat_turn(session_id: str, request: Request):
    """Streamed NDJSON response. First line is the assistant reply (so the
    client can render text and start TTS without waiting for equilibrium
    evaluation); second line is the eval result (scores, dispositions,
    frontier, gamification, closing-mode). See _eval_and_merge for the
    background-eval design. If that eval brings the session to 100%
    equilibrium, a third line carries the follow-up closing message."""
    body = await request.json()
    user_message = body.get("message", "").strip()
    detail_level = max(1.0, min(4.0, float(body.get("detail_level", 1.0))))
    if not user_message:
        raise HTTPException(status_code=400, detail="Empty message")

    if not API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not set")

    # Snapshot session + shard state under the session lock so we don't race
    # with a previous turn's still-running eval merge.
    async with _session_lock(session_id):
        data = load_session(session_id)
        if not data:
            raise HTTPException(status_code=404, detail="Session not found")
        shard = load_shard(data["shard_dir"])
        for nid, score in data.get("node_scores", {}).items():
            if nid in shard.nodes:
                shard.nodes[nid].engagement_score = score
                shard.nodes[nid].engaged = score >= 0.4
        for nid, disp in data.get("node_dispositions", {}).items():
            if nid in shard.nodes:
                shard.nodes[nid].disposition = disp
        for nid, count in data.get("node_raise_counts", {}).items():
            if nid in shard.nodes:
                shard.nodes[nid].raise_count = count
        if "node_dispositions" not in data:
            _backfill_dispositions(shard, data.get("conversation", []))
        was_closing = data.get("closing_mode_active", False)
        revision = _conversation_revision(data)
        conversation = list(data.get("conversation", []))
        frontier_ids = list(data.get("frontier", []))
    was_complete = inquiry_complete(shard)

    # Add user message to local conversation (will be saved after reply lands)
    conversation.append({"role": "user", "content": user_message})

    # Closing-mode hysteresis uses the previous turn's closing_mode_active
    # state (prevents threshold-edge flicker around eq=0.85).
    system_prompt = build_chat_system_prompt(
        shard, frontier_ids, closing_mode_was_active=was_closing,
    )

    # Trim history to last 20 turns for the prompt, summarising older topics
    if len(conversation) > 20:
        early = conversation[:-20]
        topics_discussed = set()
        for m in early:
            content_lower = m["content"].lower()
            for nid, node in shard.nodes.items():
                key_terms = node.text.lower().split()[:4]
                if any(term in content_lower for term in key_terms if len(term) > 4):
                    topics_discussed.add(f"{nid}: {node.text}")
        topics_summary = "; ".join(list(topics_discussed)[:10])
        trimmed = [{"role": "assistant", "content": f"[Earlier we discussed these topics (do NOT re-ask these unless deepening significantly): {topics_summary}]"}] + conversation[-20:]
    else:
        trimmed = conversation

    # Build steering reminder from frontier state
    recent_text = " ".join(m["content"].lower() for m in conversation[-20:])
    fresh_questions = []
    revisit_questions = []
    off_limits_nodes = []
    for nid in frontier_ids:
        if nid in shard.nodes:
            node = shard.nodes[nid]
            if node.disposition in ("rejected_understood", "settled"):
                off_limits_nodes.append(nid)
                continue
            key_terms = [t for t in node.text.lower().split() if len(t) > 4][:3]
            recently_discussed = sum(1 for t in key_terms if t in recent_text) >= 2
            if recently_discussed:
                revisit_questions.append((nid, node.text, node.engagement_score, node.disposition, node.raise_count))
            else:
                fresh_questions.append((nid, node.text, node.engagement_score, node.disposition, node.raise_count))

    off_limits_reminder = ""
    if off_limits_nodes:
        off_limits_names = [f"{nid} ({shard.nodes[nid].text[:50]})" for nid in off_limits_nodes if nid in shard.nodes]
        off_limits_reminder = (
            " OFF LIMITS — Do NOT raise these topics again, the user has already engaged with or "
            "understood and rejected them: " + ", ".join(off_limits_names) + "."
        )

    if fresh_questions:
        target_parts = []
        for nid, text, score, disp, raises in fresh_questions[:3]:
            part = f'"{text}" (node {nid}, score {score:.1f})'
            if disp == "dismissed" and raises >= 3:
                part += (
                    f" [DISMISSED {raises}x — do NOT argue this point again. Instead, "
                    f"ask the user to explain in their own words why someone might "
                    f"find this point compelling or challenging]"
                )
            elif disp == "dismissed":
                part += f" [PREVIOUSLY DISMISSED {raises}x — must use a completely different angle]"
            target_parts.append(part)
        steering_instruction = (
            "REMINDER — Do NOT repeat questions you already asked. "
            "Your NEXT response must introduce a NEW angle the user has NOT yet addressed: "
            + " | ".join(target_parts)
            + ". If the user says you're repeating yourself, acknowledge it and move to a genuinely different topic."
            + off_limits_reminder
        )
    elif revisit_questions:
        target_parts = []
        for nid, text, score, disp, raises in revisit_questions[:2]:
            part = f'"{text}" (score {score:.1f} — needs deeper engagement)'
            if disp == "dismissed" and raises >= 3:
                part += (
                    f" [DISMISSED {raises}x — do NOT argue this point again. Instead, "
                    f"ask the user to explain in their own words why someone might "
                    f"find this point compelling]"
                )
            elif disp == "dismissed":
                part += f" [DISMISSED {raises}x — try a vivid concrete scenario, NOT the same abstract question]"
            target_parts.append(part)
        steering_instruction = (
            "REMINDER — You already raised these topics recently but the user hasn't fully grappled with them. "
            "Do NOT re-ask the same question. Instead, find a NEW concrete example or scenario that forces "
            "the user to confront a specific tension in their stated position: "
            + " | ".join(target_parts)
            + off_limits_reminder
        )
    else:
        steering_instruction = (
            "REMINDER — Do NOT wrap up or ask what the user wants to explore. "
            "Continue probing their position with concrete challenges."
            + off_limits_reminder
        )

    if detail_level > 1.5:
        intensity = min((detail_level - 1.0) / 3.0, 1.0)
        detail_instruction = (
            "\n\nRESPONSE STYLE OVERRIDE: The user has requested a more detailed response. "
            "For THIS turn only, override the usual 1–3 sentence limit. Instead:\n"
            "- Give a LONGER, more substantive response (aim for a full paragraph or more)\n"
            "- Use VIVID, CONCRETE real-world examples — historical events, famous cases, "
            "everyday scenarios the user can picture\n"
            "- Paint a scene: instead of 'there could be tyranny', describe what it actually "
            "looks like when a majority enforces conformity on a dissenter\n"
            "- Draw on the context material to bring the philosophical point to life with "
            "specifics — names, dates, real dilemmas — not just abstractions\n"
            "- Still end with a question, but let the buildup do real work first\n"
            "- Do NOT use this extra space to repeat points already made — use it to "
            "deepen and illustrate"
        )
        steering_instruction += detail_instruction

    if inquiry_complete(shard):
        # At 100% the probing reminders above would contradict the closing.
        steering_instruction = (
            "REMINDER — The inquiry has reached full equilibrium. Follow the INQUIRY COMPLETE "
            "instructions: close the conversation with a summary and pointers for further "
            "thought (or, if you already did, reply briefly). Do NOT probe, do NOT introduce "
            "new challenges, and do NOT end with a question."
        )

    steering_reminder = {"role": "system", "content": steering_instruction}
    messages = [{"role": "system", "content": system_prompt}] + trimmed[:-1] + [steering_reminder] + trimmed[-1:]

    max_tokens = int(300 * detail_level)
    client = openai.AsyncOpenAI(api_key=API_KEY)
    response = await client.chat.completions.create(
        model=CHAT_MODEL, reasoning_effort="none",
        max_completion_tokens=max_tokens,
        messages=messages,
    )
    assistant_message = (response.choices[0].message.content or "").strip()
    if not assistant_message:
        # A content-filter or length stop can return no text. Nothing has
        # been saved yet, so the user can simply send again.
        raise HTTPException(status_code=502, detail="The model returned no reply. Please try again.")
    conversation.append({"role": "assistant", "content": assistant_message})

    # Increment raise counts for frontier nodes the assistant's reply touched
    for nid in frontier_ids:
        if nid in shard.nodes:
            node = shard.nodes[nid]
            key_terms = [t for t in node.text.lower().split() if len(t) > 4][:3]
            assistant_lower = assistant_message.lower()
            if sum(1 for t in key_terms if t in assistant_lower) >= 1:
                shard.nodes[nid].raise_count += 1

    # Phase 1 save: conversation + raise_counts + updated_at. Eval-derived
    # fields are left alone; phase 2 will fill them in.
    async with _session_lock(session_id):
        data = load_session(session_id)
        if not data:
            raise HTTPException(status_code=404, detail="Session not found")
        if _conversation_revision(data) != revision:
            raise HTTPException(status_code=409, detail="The conversation changed. Please reload and try again.")
        data["conversation"] = conversation
        revision = _advance_conversation(data)
        data["node_raise_counts"] = {nid: n.raise_count for nid, n in shard.nodes.items()}
        data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        save_session(session_id, data)

    # Phase 2: kick off eval in the background. Spawned (not awaited inline)
    # so it survives client disconnects via asyncio.shield below.
    eval_task = _spawn_bg(_eval_and_merge(session_id, was_closing, revision))

    async def stream_response():
        # Phase 1: reply text — sent immediately so the client can render
        # and start TTS without waiting for equilibrium evaluation.
        yield json.dumps({
            "phase": "reply",
            "assistant_message": assistant_message,
        }) + "\n"

        # Phase 2: eval results. Shielded so the task keeps running to
        # completion (and saves to disk) even if the client disconnects
        # between phase 1 and phase 2.
        try:
            eval_data = await asyncio.shield(eval_task)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[CHAT] Eval task failed: {e}")
            eval_data = None
        if not eval_data:
            return

        # Phase 3 (only on the turn that reaches 100%): follow-up closing.
        # closing_pending tells the client to hold the celebration open
        # while the closing is generated.
        just_completed = (not was_complete) and eval_data["equilibrium_score"] >= 1.0 - 1e-9
        yield json.dumps({"phase": "eval", **eval_data, "closing_pending": just_completed}) + "\n"
        if not just_completed:
            return

        closing_task = _spawn_bg(_generate_closing(
            session_id, eval_data["conversation_revision"], eval_data["evaluation_generation"],
        ))
        try:
            closing_message = await asyncio.shield(closing_task)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[CHAT] Closing generation failed: {e}")
            closing_message = None
        yield json.dumps({"phase": "closing", "assistant_message": closing_message}) + "\n"

    return StreamingResponse(
        stream_response(),
        media_type="application/x-ndjson",
    )


@app.post("/api/chat/{session_id}/rewind")
async def rewind_chat(session_id: str, request: Request):
    """Truncate conversation to a given message index and re-evaluate equilibrium."""
    body = await request.json()
    msg_index = body.get("message_index")
    if not isinstance(msg_index, int) or isinstance(msg_index, bool) or msg_index < 0:
        raise HTTPException(status_code=400, detail="Invalid message_index")

    # Rewind is ordered with complete turns. Its new revision also prevents
    # an older evaluation from merging after these locks are released.
    async with _turn_lock(session_id):
        async with _session_lock(session_id):
            return await _rewind_locked(session_id, msg_index)


async def _rewind_locked(session_id: str, msg_index: int):
    data = load_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")

    conversation = data.get("conversation", [])
    if msg_index >= len(conversation):
        raise HTTPException(status_code=400, detail="message_index out of range")

    # Truncate conversation to include messages up to and including msg_index
    data["conversation"] = conversation[:msg_index + 1]
    _advance_conversation(data)
    # The rewind itself computes the replacement evaluation under the lock.
    data["evaluation_generation"] = data.get("evaluation_generation", 0) + 1

    # Re-evaluate equilibrium on the truncated conversation
    shard = load_shard(data["shard_dir"])
    # Reset all engagement scores and dispositions before re-evaluation
    for node in shard.nodes.values():
        node.engagement_score = 0.0
        node.engaged = False
        node.disposition = "active"
        node.raise_count = 0

    if data["conversation"]:
        eval_result = await evaluate_equilibrium(shard, data["conversation"], API_KEY)
    else:
        eval_result = {"scores": {nid: 0.0 for nid in shard.nodes}, "frontier": list(shard.nodes.keys())[:3], "summary": "Conversation rewound."}

    data["node_scores"] = {nid: n.engagement_score for nid, n in shard.nodes.items()}
    data["node_dispositions"] = {nid: n.disposition for nid, n in shard.nodes.items()}
    data["node_raise_counts"] = {nid: n.raise_count for nid, n in shard.nodes.items()}
    data["evaluated_generation"] = data["evaluation_generation"]
    data["equilibrium_score"] = shard.equilibrium_score()
    data["frontier"] = eval_result.get("frontier", [])
    gamification = compute_gamification(data, shard)
    data["xp"] = gamification["xp"]
    data["level"] = gamification["level"]
    data["achievements"] = gamification["all_achievements"]
    # Reset closing-mode latch on rewind so hysteresis re-establishes from
    # the new post-rewind equilibrium rather than carrying pre-rewind state.
    data["closing_mode_active"] = False
    cmode = closing_mode_info(shard, was_active=False)
    data["closing_mode_active"] = cmode["active"]
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    save_session(session_id, data)

    # Build node info for frontend
    nodes_info = _nodes_info(shard, data.get("frontier", []))

    return {
        "conversation": data["conversation"],
        "equilibrium_score": data["equilibrium_score"],
        "node_scores": data["node_scores"],
        "nodes": nodes_info,
        "frontier": data["frontier"],
        "eval_summary": eval_result.get("summary", ""),
        "xp": data["xp"],
        "level": data["level"],
        "closing_mode": cmode,
    }


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    if not _valid_session_id(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    # Pending turns/evaluations re-check existence under this same lock.
    # They must never recreate a deleted conversation from an old snapshot.
    async with _session_lock(session_id):
        path = SESSIONS_DIR / f"{session_id}.json"
        if path.exists():
            path.unlink()
        _pending_replies.pop(session_id, None)
    return {"ok": True}


@app.post("/api/tts/emotionalize")
async def emotionalize_text(request: Request):
    """Work out how the reply should be spoken, from the recent conversation.
    With ElevenLabs, the reply is returned with v3 emotion tags wrapped
    around its segments. With the OpenAI voice, which takes no inline tags,
    the reply is returned unchanged with a delivery instruction beside it."""
    if not API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not set")

    body = await request.json()
    text = body.get("text", "").strip()
    recent_messages = body.get("recent_messages", [])
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")

    # Build the context from recent messages
    context = ""
    for msg in recent_messages[-10:]:
        role = "User" if msg.get("role") == "user" else "Assistant"
        context += f"{role}: {msg.get('content', '')}\n\n"

    provider = await _resolve_tts_provider()
    client = openai.AsyncOpenAI(api_key=API_KEY)

    if provider == "openai":
        prompt = f"""You direct the delivery of a text-to-speech voice that speaks for a Socratic interlocutor.

Given the recent conversation and the reply to be spoken, write a short delivery
instruction, at most 60 words, for how the reply should be spoken: the overall
emotion and tone, the pacing, and any moment in the reply that calls for a change,
such as genuine curiosity for a question, warmth for an acknowledgement, gravity
for a hard point, or slight surprise at something unexpected the user said.
Do not quote or repeat the reply. Output only the instruction.

Recent conversation:
{context}

Reply to be spoken:
{text}"""
        response = await client.chat.completions.create(
            model=CHAT_MODEL, reasoning_effort="none",
            max_completion_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        instructions = (response.choices[0].message.content or "").strip()
        return {"tagged_text": text, "instructions": instructions, "provider": "openai"}

    prompt = f"""You are an emotion tagger for a text-to-speech system (ElevenLabs v3).

Analyze this assistant response in the context of the recent conversation, then insert
emotion/delivery tags into the text. ElevenLabs v3 supports these tag formats:

- <curiosity>text spoken with genuine curiosity</curiosity>
- <thoughtful>text spoken reflectively, with consideration</thoughtful>
- <warmth>text spoken with warmth and friendliness</warmth>
- <surprise>text expressing genuine surprise or intrigue</surprise>
- <concern>text expressing gentle concern or worry</concern>
- <encouragement>text spoken with encouragement</encouragement>
- <playful>text with a light, playful tone</playful>
- <serious>text with gravity and seriousness</serious>
- <empathy>text spoken with deep understanding</empathy>

Rules:
- Wrap segments of the text in the MOST appropriate emotion tag
- Every segment must be wrapped in exactly one tag — no bare text
- Do NOT change the words at all — only add tags around existing text
- Choose emotions that fit the conversational moment: if the user said something
  surprising, react with surprise; if probing a contradiction, use curiosity or
  seriousness; if acknowledging, use warmth or empathy
- Keep it natural — vary the emotions, don't use the same tag for everything
- Output ONLY the tagged text, nothing else

Recent conversation:
{context}

Text to tag:
{text}"""

    response = await client.chat.completions.create(
        model=CHAT_MODEL, reasoning_effort="none",
        max_completion_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    tagged_text = (response.choices[0].message.content or "").strip() or text
    return {"tagged_text": tagged_text, "instructions": "", "provider": "elevenlabs"}


@app.post("/api/stt")
async def speech_to_text(request: Request):
    """Transcribe audio with TRANSCRIBE_MODEL. Accepts raw WAV (Content-Type: audio/wav)
    or multipart form upload (field name: 'file')."""
    if not API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not set")

    content_type = request.headers.get("content-type", "")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio too large")

    if "audio/" in content_type:
        # Raw audio body (used by ESP32 client), read with a size cap
        audio_buf = bytearray()
        async for chunk in request.stream():
            audio_buf.extend(chunk)
            if len(audio_buf) > MAX_AUDIO_BYTES:
                raise HTTPException(status_code=413, detail="Audio too large")
        audio_bytes = bytes(audio_buf)
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Empty audio")
    elif "multipart" in content_type:
        async with request.form() as form:
            upload = form.get("file")
            if not upload:
                raise HTTPException(status_code=400, detail="No file field")
            audio_bytes = await upload.read()
            if len(audio_bytes) > MAX_AUDIO_BYTES:
                raise HTTPException(status_code=413, detail="Audio too large")
    else:
        raise HTTPException(status_code=400, detail="Send audio/wav or multipart form")

    client = openai.AsyncOpenAI(api_key=API_KEY)
    import io
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = "recording.wav"

    try:
        transcript = await client.audio.transcriptions.create(
            model=TRANSCRIBE_MODEL,
            file=audio_file,
            language="en",
        )
    except openai.APIStatusError as e:
        raise HTTPException(status_code=502, detail=f"Transcription failed: HTTP {e.status_code}")
    except openai.OpenAIError as e:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {type(e).__name__}")

    return {"text": transcript.text}


@app.post("/api/tts")
async def text_to_speech(request: Request):
    """Stream spoken audio for a text, from ElevenLabs or the OpenAI voice.
    Body: text, optional output_format (mp3 by default; a "pcm_..." value gives
    raw 16-bit PCM, at the requested rate from ElevenLabs and always 24 kHz
    from OpenAI), optional instructions (OpenAI voice only, from the
    expressive step), optional seed (ElevenLabs only)."""
    if not API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not set")

    body = await request.json()
    text = body.get("text", "").strip()
    output_format = str(body.get("output_format", "mp3_44100_128"))
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")
    try:
        seed = int(body.get("seed", TTS_SEED))
    except (TypeError, ValueError):
        seed = TTS_SEED

    if output_format.startswith("pcm_"):
        media_type = "audio/pcm"
    elif output_format.startswith("ulaw_"):
        media_type = "audio/basic"
    else:
        media_type = "audio/mpeg"
    response_headers = {"Content-Disposition": "inline"}

    provider = await _resolve_tts_provider()
    if provider == "elevenlabs":
        opened = await _open_elevenlabs_speech(text, output_format, seed)
        if opened:
            client, resp = opened

            async def stream_elevenlabs():
                try:
                    async for chunk in resp.aiter_bytes(chunk_size=4096):
                        yield chunk
                finally:
                    await resp.aclose()
                    await client.aclose()

            return StreamingResponse(stream_elevenlabs(), media_type=media_type, headers=response_headers)
        if TTS_PROVIDER_SETTING == "elevenlabs":
            raise HTTPException(status_code=502, detail="ElevenLabs TTS failed")

    # OpenAI voice
    fmt = "pcm" if output_format.startswith("pcm_") else "mp3"
    cm, resp = await _open_openai_speech(text, fmt, body.get("instructions"))

    async def stream_openai():
        try:
            async for chunk in resp.iter_bytes(4096):
                yield chunk
        finally:
            await cm.__aexit__(None, None, None)

    return StreamingResponse(stream_openai(), media_type="audio/pcm" if fmt == "pcm" else "audio/mpeg",
                             headers=response_headers)


@app.get("/api/tts/enabled")
async def tts_enabled():
    """Whether voice output is available, and which voice service is in use."""
    provider = await _resolve_tts_provider()
    return {"enabled": bool(API_KEY), "provider": provider, "note": _tts_provider_note}


# ---------------------------------------------------------------------------
# PhilosophyPod — xiaozhi ESP32 bridge (WebSocket + OTA on same port)
# ---------------------------------------------------------------------------

import wave
import io as _io
from fastapi.websockets import WebSocket as WSConnection
from starlette.websockets import WebSocketDisconnect

XIAOZHI_SAMPLE_RATE = 16000
XIAOZHI_SERVER_RATE = 24000
XIAOZHI_FRAME_MS = 60
_activated_devices = set()
_pending_replies = {}  # session_id → reply text to speak on next connection

try:
    import opuslib
    _opus_decoder = opuslib.Decoder(XIAOZHI_SAMPLE_RATE, 1)
    _HAS_OPUS = True
except Exception as exc:
    # opuslib also raises OSError or a plain Exception when its native
    # library cannot be loaded. Audio devices are optional for web chat.
    _HAS_OPUS = False
    _opus_decoder = None
    print(f"[XIAOZHI] Device audio unavailable ({type(exc).__name__}). "
          "Web chat is available. Install requirements-device.txt and the system Opus library for a device.")


def _pcm_to_wav(pcm: bytes, rate: int = XIAOZHI_SAMPLE_RATE) -> bytes:
    buf = _io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(rate); wf.writeframes(pcm)
    return buf.getvalue()


@app.api_route("/xiaozhi/ota/{path:path}", methods=["GET", "POST"])
async def xiaozhi_ota(request: Request, path: str = ""):
    device_id = request.headers.get("Device-Id", "unknown")
    # Send the device back to the same host and port it reached us on
    host_header = request.headers.get("Host", "127.0.0.1:8000").strip()
    host = _host_name(host_header)
    port = "8000"
    rest = host_header[len(host):]
    if rest.startswith(":") and rest[1:].isdigit():
        port = rest[1:]
    ws_url = f"ws://{host}:{port}/xiaozhi/ws"

    if "activate" in path:
        _activated_devices.add(device_id)
        print(f"[XIAOZHI] Device {device_id} activated")
        return {
            "websocket": {"url": ws_url, "version": 1},
            "server_time": {"timestamp": int(time.time() * 1000), "timezone_offset": 0},
        }

    config = {
        "websocket": {"url": ws_url, "version": 1},
        "server_time": {"timestamp": int(time.time() * 1000), "timezone_offset": 0},
    }
    if device_id not in _activated_devices:
        config["activation"] = {"code": "", "message": "Connected to PhilosophyPod", "challenge": "pv_challenge"}
    return config


import asyncio as _asyncio


async def _tts_pcm_chunks(text: str, log_tag: str):
    """Yield 16-bit mono PCM at XIAOZHI_SERVER_RATE from whichever voice
    service is in use, falling back to the OpenAI voice if ElevenLabs refuses."""
    provider = await _resolve_tts_provider()
    if provider == "elevenlabs":
        opened = await _open_elevenlabs_speech(text, f"pcm_{XIAOZHI_SERVER_RATE}", TTS_SEED)
        if opened:
            client, resp = opened
            try:
                async for chunk in resp.aiter_bytes(chunk_size=4096):
                    yield chunk
            finally:
                await resp.aclose()
                await client.aclose()
            return
        if TTS_PROVIDER_SETTING == "elevenlabs":
            print(f"[XIAOZHI] {log_tag}: ElevenLabs failed")
            return
    # OpenAI PCM is 24 kHz, which is XIAOZHI_SERVER_RATE
    try:
        cm, resp = await _open_openai_speech(text, "pcm", None)
    except HTTPException as e:
        print(f"[XIAOZHI] {log_tag}: {e.detail}")
        return
    try:
        async for chunk in resp.iter_bytes(4096):
            yield chunk
    finally:
        await cm.__aexit__(None, None, None)


async def _stream_tts_to_device(ws, text: str, log_tag: str = "TTS") -> int:
    """Stream speech to the device incrementally. PCM chunks from the voice
    service are encoded into OPUS frames and pushed over the WebSocket as
    soon as a full frame's worth of samples (2880 bytes at 24kHz/60ms) has
    arrived, so the first audio frame reaches the device in the service's
    time-to-first-chunk rather than after the whole file. Returns frame count.

    Pacing: bursts the first 30 frames (~1.8s of audio) to fill the
    device's jitter buffer, then sleeps ~55ms per frame to deliver at
    real-time."""
    enc = opuslib.Encoder(XIAOZHI_SERVER_RATE, 1, opuslib.APPLICATION_AUDIO)
    frame_samples = int(XIAOZHI_SERVER_RATE * XIAOZHI_FRAME_MS / 1000)
    frame_bytes = frame_samples * 2
    pcm_buf = bytearray()
    total_sent = 0
    total_bytes = 0
    first_frame_t = None
    start_t = time.monotonic()

    async for chunk in _tts_pcm_chunks(text, log_tag):
        if not chunk:
            continue
        pcm_buf.extend(chunk)
        total_bytes += len(chunk)
        while len(pcm_buf) >= frame_bytes:
            frame_pcm = bytes(pcm_buf[:frame_bytes])
            del pcm_buf[:frame_bytes]
            opus_frame = enc.encode(frame_pcm, frame_samples)
            await ws.send_bytes(opus_frame)
            total_sent += 1
            if first_frame_t is None:
                first_frame_t = time.monotonic() - start_t
            if total_sent > 30:
                await _asyncio.sleep(0.055)

    ttft = f"{first_frame_t*1000:.0f}ms" if first_frame_t is not None else "n/a"
    print(f"[XIAOZHI] {log_tag} streamed: {total_sent} frames, {total_bytes} bytes PCM, first-frame {ttft}")
    return total_sent


import math as _math


def _compute_ic_state(shard, node_scores: dict, frontier: list) -> dict:
    """Compute node layout (phi/theta) and pack into a compact message for the device."""
    nodes_list = list(shard.nodes.values())
    depth_rings = {0: 0.0, 1: _math.pi * 0.20, 2: _math.pi * 0.45, 3: _math.pi * 0.65}

    # BFS to compute depths
    depths = {}
    central_id = None
    for n in nodes_list:
        if n.parent is None:
            central_id = n.id
            depths[n.id] = 0
    if central_id:
        queue = [central_id]
        while queue:
            pid = queue.pop(0)
            for n in nodes_list:
                if n.parent == pid and n.id not in depths:
                    depths[n.id] = depths[pid] + 1
                    queue.append(n.id)
    for n in nodes_list:
        if n.id not in depths:
            depths[n.id] = 1

    # Assign theta (longitude), the same algorithm the device display uses
    theta = {}
    if central_id:
        theta[central_id] = 0
    depth_groups: dict[int, list] = {}
    for nid, d in depths.items():
        depth_groups.setdefault(d, []).append(nid)

    d1 = depth_groups.get(1, [])
    for i, nid in enumerate(d1):
        theta[nid] = 2 * _math.pi * i / max(len(d1), 1)

    children = {n.id: [] for n in nodes_list}
    for n in nodes_list:
        if n.parent and n.parent in children:
            children[n.parent].append(n.id)

    def assign_thetas(parent_id, depth):
        kids = [nid for nid in children.get(parent_id, []) if depths.get(nid) == depth]
        if not kids:
            return
        pt = theta.get(parent_id, 0)
        spread = _math.pi * 0.25
        for i, nid in enumerate(kids):
            offset = 0 if len(kids) == 1 else (i / (len(kids) - 1) - 0.5) * spread
            theta[nid] = pt + offset
        for nid in kids:
            assign_thetas(nid, depth + 1)

    for nid in d1:
        assign_thetas(nid, 2)

    result_nodes = []
    for n in nodes_list:
        d = depths.get(n.id, 1)
        result_nodes.append({
            "d": d,
            "p": round(depth_rings.get(d, _math.pi * 0.5), 3),
            "t": round(theta.get(n.id, 0), 3),
            "s": round(node_scores.get(n.id, 0), 2),
            "f": 1 if n.id in frontier else 0,
        })
    return {"type": "ic_state", "n": result_nodes}


def _ic_state_for_session(sess_data: dict) -> dict | None:
    """The node map message for the device's rotating shard display: one
    entry per node with its position, score and whether it is next in line.
    A resolved node is sent with score 1.0, matching how it counts toward
    the equilibrium score."""
    try:
        shard = load_shard(sess_data["shard_dir"])
    except Exception as e:
        print(f"[XIAOZHI] ic_state: cannot load shard: {e}")
        return None
    for nid, score in sess_data.get("node_scores", {}).items():
        if nid in shard.nodes:
            shard.nodes[nid].engagement_score = score
    for nid, disp in sess_data.get("node_dispositions", {}).items():
        if nid in shard.nodes:
            shard.nodes[nid].disposition = disp
    shown = {nid: shard._equilibrium_contribution(n) for nid, n in shard.nodes.items()}
    return _compute_ic_state(shard, shown, _next_up(shard, sess_data.get("frontier", [])))


async def _send_ic_state(ws, session_id: str | None, when: str) -> None:
    if not session_id:
        return
    try:
        sess_data = load_session(session_id)
        msg = _ic_state_for_session(sess_data) if sess_data else None
        if msg:
            await ws.send_json(msg)
            print(f"[XIAOZHI] Sent ic_state {when}: {len(msg['n'])} nodes")
    except Exception as e:
        print(f"[XIAOZHI] ic_state send failed: {e}")


NO_SESSION_MESSAGE = (
    "There is no conversation open yet. "
    "Open Inquiry Chat in your browser and choose an inquiry shard to begin."
)


def _latest_session_id() -> str | None:
    """The session the voice device should use: the most recently updated
    one. Looked up afresh for every turn, so a conversation started in the
    browser after the device connected is picked up."""
    sessions = list_sessions()
    return sessions[0]["id"] if sessions else None


async def _device_chat_turn(session_id: str, text: str, oai):
    """Generate and save one device turn, ordered with browser turns.

    Audio transcription/playback remain outside the turn lock. The live and
    disconnect fallback paths share this helper so neither can lose history.
    """
    async with _turn_lock(session_id):
        async with _session_lock(session_id):
            sess_data = load_session(session_id)
            if not sess_data:
                return None
            shard = load_shard(sess_data["shard_dir"])
            for nid, score in sess_data.get("node_scores", {}).items():
                if nid in shard.nodes:
                    shard.nodes[nid].engagement_score = score
                    shard.nodes[nid].engaged = score >= 0.4
            for nid, disp in sess_data.get("node_dispositions", {}).items():
                if nid in shard.nodes:
                    shard.nodes[nid].disposition = disp
            for nid, count in sess_data.get("node_raise_counts", {}).items():
                if nid in shard.nodes:
                    shard.nodes[nid].raise_count = count
            conversation = list(sess_data.get("conversation", []))
            frontier_ids = list(sess_data.get("frontier", []))
            was_closing = sess_data.get("closing_mode_active", False)
            revision = _conversation_revision(sess_data)

        conversation.append({"role": "user", "content": text})
        system_prompt = build_chat_system_prompt(
            shard, frontier_ids, closing_mode_was_active=was_closing,
        )
        messages = [{"role": "system", "content": system_prompt}] + conversation[-20:]

        response = await oai.chat.completions.create(
            model=CHAT_MODEL, reasoning_effort="none", max_completion_tokens=300, messages=messages,
        )
        reply = (response.choices[0].message.content or "").strip()
        if not reply:
            raise HTTPException(status_code=502, detail="The model returned no reply. Please try again.")
        conversation.append({"role": "assistant", "content": reply})

        # Increment raise_counts for frontier nodes the reply touched
        for nid in frontier_ids:
            if nid in shard.nodes:
                node = shard.nodes[nid]
                key_terms = [t for t in node.text.lower().split() if len(t) > 4][:3]
                if sum(1 for t in key_terms if t in reply.lower()) >= 1:
                    shard.nodes[nid].raise_count += 1

        # Phase 1 save — conversation + raise_counts only
        async with _session_lock(session_id):
            sess_data = load_session(session_id)
            if not sess_data:
                return None
            if _conversation_revision(sess_data) != revision:
                return None
            sess_data["conversation"] = conversation
            revision = _advance_conversation(sess_data)
            sess_data["node_raise_counts"] = {nid: n.raise_count for nid, n in shard.nodes.items()}
            sess_data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            save_session(session_id, sess_data)

        eval_task = _spawn_bg(_eval_and_merge(session_id, was_closing, revision))
        return reply, eval_task


async def _process_and_respond(ws, session_id: str, pcm_audio: bytes):
    """Background task: STT → Chat → (TTS || Eval), send response over open
    WebSocket. Eval runs in parallel with the TTS download/encode so the
    user hears the reply ~2-5s sooner. The equilibrium and closing_mode
    updates arrive after TTS finishes (a few seconds later than before) —
    the trade is acceptable because the device's display update is less
    latency-sensitive than the audio."""
    try:
        secs = len(pcm_audio) / (XIAOZHI_SAMPLE_RATE * 2)
        print(f"[XIAOZHI] Processing {secs:.1f}s of audio...")

        oai = openai.AsyncOpenAI(api_key=API_KEY)

        # 1. STT
        wav_data = _pcm_to_wav(pcm_audio)
        audio_file = _io.BytesIO(wav_data)
        audio_file.name = "recording.wav"
        transcript = await oai.audio.transcriptions.create(
            model=TRANSCRIBE_MODEL, file=audio_file, language="en"
        )
        text = transcript.text.strip()
        print(f"[XIAOZHI] STT: \"{text}\"")

        if not text or text == ".":
            await ws.send_json({"type": "tts", "state": "stop"})
            return

        await ws.send_json({"type": "stt", "text": text})

        # Without a session there is nothing to reply to. Say so aloud: a bare
        # "stop" leaves the device showing "Thinking", since it only leaves
        # that state once speech has started.
        if not session_id or not load_session(session_id):
            print("[XIAOZHI] No session to reply in — telling the user")
            await _speak_text(ws, NO_SESSION_MESSAGE)
            return

        # Web chat, live audio and disconnected audio all share turn ordering.
        turn = await _device_chat_turn(session_id, text, oai)
        if turn is None:
            await _speak_text(ws, NO_SESSION_MESSAGE)
            return
        reply, eval_task = turn
        print(f"[XIAOZHI] Reply: \"{reply[:80]}\"")

        await ws.send_json({"type": "llm", "text": "", "emotion": "neutral"})

        # 3. TTS — stream OPUS frames
        await ws.send_json({"type": "tts", "state": "start"})

        if _HAS_OPUS:
            await _stream_tts_to_device(ws, reply)

        await ws.send_json({"type": "tts", "state": "stop"})

        # 4. Eval results (usually finished by now since we ran it during TTS)
        try:
            eval_data = await eval_task
        except Exception as e:
            print(f"[XIAOZHI] Eval task failed: {e}")
            eval_data = None

        if eval_data:
            await ws.send_json({
                "type": "equilibrium",
                "score": _percent(eval_data["equilibrium_score"]),
            })
            await ws.send_json({
                "type": "closing_mode",
                "active": bool(eval_data["closing_mode"]["active"]),
                "remaining": int(eval_data["closing_mode"]["remaining"]),
            })
            print(f"[XIAOZHI] Eval: eq={eval_data['equilibrium_score']:.1%}, closing={eval_data['closing_mode']['active']}")

            # Node map for the device's rotating shard display
            await _send_ic_state(ws, session_id, "after eval")

        print(f"[XIAOZHI] Response complete")

    except Exception as e:
        print(f"[XIAOZHI] Pipeline error: {e}")
        import traceback; traceback.print_exc()
        try:
            await ws.send_json({"type": "tts", "state": "stop"})
        except:
            pass

async def _speak_text(ws, text: str):
    """Stream arbitrary text to the device as TTS audio.

    Used by the `resume` flow on auto-connect — no STT, no chat, just speak.
    """
    if not text:
        await ws.send_json({"type": "tts", "state": "stop"})
        return

    await ws.send_json({"type": "llm", "text": "", "emotion": "neutral"})
    await ws.send_json({"type": "tts", "state": "start"})

    try:
        if _HAS_OPUS:
            await _stream_tts_to_device(ws, text, log_tag="Resume TTS")
    except Exception as e:
        print(f"[XIAOZHI] Resume TTS error: {e}")
        import traceback; traceback.print_exc()
    finally:
        try:
            await ws.send_json({"type": "tts", "state": "stop"})
        except Exception:
            pass


@app.websocket("/xiaozhi/ws")
async def xiaozhi_ws(ws: WSConnection):
    refusal = _device_ws_refusal(ws)
    if refusal:
        client = ws.client.host if ws.client else "unknown"
        print(f"[XIAOZHI] Refused a device at {client}: {refusal}.")
        await ws.close(code=1008)
        return
    await ws.accept()
    print(f"[XIAOZHI] Device connected")

    sessions = list_sessions()
    session_id = sessions[0]["id"] if sessions else None
    if session_id:
        print(f"[XIAOZHI] Session: {session_id} — {sessions[0].get('central_question', '')[:60]}")

    audio_buffer = bytearray()
    listening = False

    try:
        while True:
            message = await ws.receive()

            msg_type_raw = message.get("type", "")
            if msg_type_raw == "websocket.disconnect":
                print(f"[XIAOZHI] Disconnect")
                break

            if "bytes" in message:
                if listening and _HAS_OPUS:
                    try:
                        # Device may encode at 24kHz internally even though we decode at 16kHz
                        # Try multiple frame sizes to find the right one
                        raw = message["bytes"]
                        decoded = False
                        for try_rate in [XIAOZHI_SAMPLE_RATE, 24000, 48000]:
                            try:
                                try_samples = int(try_rate * XIAOZHI_FRAME_MS / 1000)
                                dec = opuslib.Decoder(try_rate, 1)
                                pcm = dec.decode(raw, try_samples)
                                audio_buffer.extend(pcm)
                                decoded = True
                                if not hasattr(_opus_decoder, '_rate_logged'):
                                    print(f"[XIAOZHI] OPUS decode OK at {try_rate}Hz, {try_samples} samples")
                                    _opus_decoder._rate_logged = True
                                break
                            except Exception:
                                continue
                        if not decoded:
                            print(f"[XIAOZHI] OPUS decode failed for all rates, frame={len(raw)} bytes")
                    except Exception as e:
                        print(f"[XIAOZHI] OPUS error: {e}")
                continue

            if "text" in message:
                data = json.loads(message["text"])
                msg_type = data.get("type")

                # Follow the most recent conversation, which may have been
                # started in the browser after the device connected.
                session_changed = False
                if msg_type in ("hello", "listen", "resume"):
                    latest = _latest_session_id()
                    if latest != session_id:
                        print(f"[XIAOZHI] Session: {latest or 'none'}")
                        session_id = latest
                        session_changed = True
                # A different conversation means a different shard to draw
                if session_changed and msg_type != "hello":
                    s_new = load_session(session_id) if session_id else None
                    if s_new:
                        await ws.send_json({"type": "equilibrium",
                                            "score": _percent(_current_shard_info(s_new)[0])})
                    await _send_ic_state(ws, session_id, "on session change")

                if msg_type == "hello":
                    print(f"[XIAOZHI] Hello")
                    await ws.send_json({
                        "type": "hello",
                        "session_id": session_id or "none",
                        "transport": "websocket",
                        "audio_params": {
                            "format": "opus", "sample_rate": XIAOZHI_SERVER_RATE,
                            "channels": 1, "frame_duration": XIAOZHI_FRAME_MS,
                        },
                    })

                    # Send current equilibrium score on connect
                    if session_id:
                        s = load_session(session_id)
                        if s:
                            eq_pct = _percent(s.get("equilibrium_score", 0))
                            await ws.send_json({"type": "equilibrium", "score": eq_pct})
                            await _send_ic_state(ws, session_id, "on hello")

                elif msg_type == "listen":
                    state = data.get("state")
                    print(f"[XIAOZHI] Listen state={state}")

                    if state == "start":
                        listening = True
                        audio_buffer = bytearray()
                        print("[XIAOZHI] Listening...")

                    elif state in ("stop", "detect", "end"):
                        listening = False
                        secs = len(audio_buffer) / (XIAOZHI_SAMPLE_RATE * 2)
                        print(f"[XIAOZHI] Stopped listening ({secs:.1f}s)")
                        if len(audio_buffer) > 3200:
                            buf_copy = bytes(audio_buffer)
                            audio_buffer = bytearray()
                            _asyncio.create_task(_process_and_respond(ws, session_id, buf_copy))


                elif msg_type == "resume":
                    # Device just finished booting and wants to continue the
                    # conversation. Priority order:
                    #   1. Any reply that didn't finish streaming before
                    #      the previous disconnect (_pending_replies)
                    #   2. Last assistant message in the conversation
                    #   3. An opening that frames the session's central question
                    print(f"[XIAOZHI] Resume requested")
                    if not session_id:
                        print(f"[XIAOZHI] Resume: no active session — telling the user")
                        await _speak_text(ws, NO_SESSION_MESSAGE)
                        continue

                    resume_text = _pending_replies.pop(session_id, None)
                    if resume_text:
                        print(f"[XIAOZHI] Resume: replaying queued reply ({len(resume_text)} chars)")
                    else:
                        sess = load_session(session_id) or {}
                        conv = sess.get("conversation", []) or []
                        last_assistant = next(
                            (m.get("content", "").strip()
                             for m in reversed(conv)
                             if m.get("role") == "assistant" and (m.get("content") or "").strip()),
                            None,
                        )
                        if last_assistant:
                            resume_text = last_assistant
                            print(f"[XIAOZHI] Resume: repeating last assistant message ({len(resume_text)} chars)")
                        else:
                            cq = (sess.get("central_question") or "").strip()
                            try:
                                resume_text = welcome_message(
                                    load_shard(sess["shard_dir"]), cq, speech=True,
                                )
                                print(f"[XIAOZHI] Resume: opening for '{cq[:60]}'")
                            except Exception:
                                resume_text = "Welcome. Let's begin."
                                print(f"[XIAOZHI] Resume: generic opening")

                    await _speak_text(ws, resume_text)

                elif msg_type == "abort":
                    listening = False
                elif msg_type == "goodbye":
                    break

    except WebSocketDisconnect:
        print(f"[XIAOZHI] Device disconnected")
    except Exception as e:
        print(f"[XIAOZHI] Error: {e}")
        import traceback; traceback.print_exc()

    # Fallback: process buffered audio if we didn't get to it
    if len(audio_buffer) > 3200 and session_id:
        secs = len(audio_buffer) / (XIAOZHI_SAMPLE_RATE * 2)
        print(f"[XIAOZHI] Processing {secs:.1f}s of audio post-disconnect...")
        try:
            oai = openai.AsyncOpenAI(api_key=API_KEY)
            wav_data = _pcm_to_wav(bytes(audio_buffer))
            audio_file = _io.BytesIO(wav_data)
            audio_file.name = "recording.wav"
            transcript = await oai.audio.transcriptions.create(
                model=TRANSCRIBE_MODEL, file=audio_file, language="en"
            )
            text = transcript.text.strip()
            print(f"[XIAOZHI] STT: \"{text}\"")

            if text and text != ".":
                turn = await _device_chat_turn(session_id, text, oai)
                if turn is None:
                    return
                reply, _eval_task = turn

                _pending_replies[session_id] = reply
                print(f"[XIAOZHI] Reply queued: \"{reply[:80]}\"")
        except Exception as e2:
            print(f"[XIAOZHI] Post-disconnect error: {e2}")
            import traceback; traceback.print_exc()


if __name__ == "__main__":
    import uvicorn
    if LISTEN_HOST == "0.0.0.0":
        why = "ALLOW_NETWORK_ACCESS is on" if ALLOW_NETWORK_ACCESS else "a DEVICE_TOKEN is set, for the voice device"
        print(f"[ACCESS] Listening on the network because {why}.")
    else:
        print("[ACCESS] Listening on this computer only.")
    uvicorn.run(app, host=LISTEN_HOST, port=8000, ws_ping_interval=30, ws_ping_timeout=60)
