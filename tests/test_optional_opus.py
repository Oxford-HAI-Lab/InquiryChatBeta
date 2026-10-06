"""Missing optional Python/native Opus must not prevent ordinary web startup."""

import builtins
from contextlib import ExitStack
import importlib.util
import json
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from support import ROOT, isolated_app


class OptionalOpusTests(unittest.IsolatedAsyncioTestCase):
    def load_bridge_without_opus(self):
        real_import = builtins.__import__
        def without_opus(name, *args, **kwargs):
            if name == "opuslib":
                raise Exception("Could not find Opus library")
            return real_import(name, *args, **kwargs)
        spec = importlib.util.spec_from_file_location("_inquiry_test_bridge", ROOT / "PhilosophyPod" / "bridge_server.py")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {}, clear=True), patch("builtins.__import__", side_effect=without_opus):
            spec.loader.exec_module(module)
        return module

    async def test_web_import_and_homepage_survive_missing_python_or_native_opus(self):
        real_import = builtins.__import__
        for failure in (ModuleNotFoundError("opuslib"), OSError("native library unavailable"), Exception("Could not find Opus library")):
            def without_opus(name, *args, **kwargs):
                if name == "opuslib":
                    raise failure
                return real_import(name, *args, **kwargs)
            with ExitStack() as stack:
                directory = stack.enter_context(tempfile.TemporaryDirectory())
                stack.enter_context(patch("builtins.__import__", side_effect=without_opus))
                module = stack.enter_context(isolated_app(directory))
                self.assertFalse(module._HAS_OPUS)
                self.assertIsNone(module._opus_decoder)
                stack.enter_context(patch.object(module, "_resolve_tts_provider", AsyncMock(return_value="openai")))
                async with module.app.router.lifespan_context(module.app):
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=module.app, client=("127.0.0.1", 50000)),
                        base_url="http://localhost:8000",
                    ) as client:
                        response = await client.get("/")
                self.assertEqual(response.status_code, 200)
                self.assertIn("Inquiry Chat", response.text)
                native = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
                self.assertIn("Opus", module._device_ws_refusal(native))

    async def test_bridge_exits_clearly_before_starting_without_native_opus(self):
        module = self.load_bridge_without_opus()
        self.assertFalse(module.HAS_OPUS)
        with self.assertRaisesRegex(RuntimeError, "requirements-device.txt"):
            await module.main()
        with self.assertRaisesRegex(RuntimeError, "Opus"):
            module.pcm_to_opus_frames(b"synthetic")

    async def test_native_bridge_bootstraps_authorization_for_all_paid_paths(self):
        module = self.load_bridge_without_opus()
        paths = []
        def respond(request):
            paths.append(request.url.path)
            if request.url.path == "/api/csrf":
                return httpx.Response(200, json={"token": "synthetic-csrf"})
            self.assertEqual(request.headers.get("X-Inquiry-CSRF"), "synthetic-csrf")
            if request.url.path == "/api/stt":
                self.assertEqual(request.headers["Content-Type"], "audio/wav")
                return httpx.Response(200, json={"text": "Synthetic transcript"})
            if request.url.path == "/api/tts":
                return httpx.Response(200, content=b"synthetic mp3")
            self.assertEqual(request.url.path, "/api/chat/synthetic-session")
            phases = [
                {"phase": "reply", "assistant_message": "Synthetic reply"},
                {"phase": "eval", "equilibrium_score": 1},
                {"phase": "closing", "assistant_message": "Synthetic closing"},
            ]
            return httpx.Response(200, content="".join(json.dumps(p) + "\n" for p in phases))
        original_client = httpx.AsyncClient
        with patch.object(module.httpx, "AsyncClient", side_effect=lambda **kwargs: original_client(transport=httpx.MockTransport(respond))), \
                patch.object(module, "mp3_to_pcm", return_value=b"synthetic pcm"):
            self.assertEqual(await module.send_stt(b"synthetic wav"), "Synthetic transcript")
            merged, closing = await module.send_chat("synthetic-session", "Synthetic thought")
            self.assertEqual(merged["assistant_message"], "Synthetic reply")
            self.assertEqual(await closing, "Synthetic closing")
            self.assertEqual(await module.fetch_tts_pcm("Synthetic speech"), b"synthetic pcm")
        self.assertEqual(paths, ["/api/csrf", "/api/stt", "/api/csrf", "/api/chat/synthetic-session", "/api/csrf", "/api/tts"])


if __name__ == "__main__":
    unittest.main()
