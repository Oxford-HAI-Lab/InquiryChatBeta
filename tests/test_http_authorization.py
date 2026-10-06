"""Exercise the actual HTTP boundary without personal data or paid services."""

from contextlib import ExitStack
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from support import isolated_app


class FakeSpeech:
    async def iter_bytes(self, size):
        yield b"synthetic audio"


class FakeSpeechContext:
    async def __aexit__(self, *args):
        return None


class HTTPAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.module = self.stack.enter_context(isolated_app(directory))
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.module.app, client=("127.0.0.1", 50000)),
            base_url="http://localhost:8000",
        )
        self.addAsyncCleanup(self.client.aclose)
        self.speech = self.stack.enter_context(patch.object(
            self.module, "_open_openai_speech",
            AsyncMock(return_value=(FakeSpeechContext(), FakeSpeech())),
        ))
        self.stack.enter_context(patch.object(self.module, "_resolve_tts_provider", AsyncMock(return_value="openai")))
        bootstrap = await self.client.get("/api/csrf")
        self.assertEqual(bootstrap.status_code, 200)
        self.assertEqual(bootstrap.headers["cache-control"], "no-store")
        self.headers = {"X-Inquiry-CSRF": bootstrap.json()["token"]}

    async def test_same_origin_authorized_json_and_native_client_work(self):
        for origin in (None, "http://localhost:8000"):
            headers = dict(self.headers)
            if origin:
                headers["Origin"] = origin
            response = await self.client.post("/api/tts", json={"text": "Synthetic"}, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"synthetic audio")
        self.assertEqual(self.speech.await_count, 2)

    async def test_cross_origin_and_opaque_requests_cannot_bootstrap_or_spend(self):
        for origin in ("https://external.example", "http://localhost:8766", "null"):
            response = await self.client.get("/api/csrf", headers={"Origin": origin})
            self.assertEqual(response.status_code, 403)
            response = await self.client.post(
                "/api/tts", headers={**self.headers, "Origin": origin, "Content-Type": "text/plain"},
                content='{"text":"Synthetic"}',
            )
            self.assertEqual(response.status_code, 403)
        self.speech.assert_not_awaited()

    async def test_originless_and_same_origin_requests_require_deliberate_token(self):
        for headers in ({}, {"Origin": "http://localhost:8000"}, {"X-Inquiry-CSRF": "wrong"}):
            response = await self.client.post("/api/tts", json={"text": "Synthetic"}, headers=headers)
            self.assertEqual(response.status_code, 403)
        self.speech.assert_not_awaited()

    async def test_plain_text_json_is_rejected_even_with_valid_token(self):
        response = await self.client.post(
            "/api/tts", content='{"text":"Synthetic"}',
            headers={**self.headers, "Content-Type": "text/plain;charset=UTF-8"},
        )
        self.assertEqual(response.status_code, 415)
        self.speech.assert_not_awaited()

    async def test_delete_requires_token_but_no_json_body(self):
        response = await self.client.delete("/api/sessions/nonexistent")
        self.assertEqual(response.status_code, 403)
        response = await self.client.delete("/api/sessions/nonexistent", headers=self.headers)
        self.assertEqual(response.status_code, 200)

    async def test_host_guard_is_preserved(self):
        response = await self.client.get("/api/csrf", headers={"Host": "external.example"})
        self.assertEqual(response.status_code, 403)

    async def test_network_mode_does_not_disable_origin_or_token_checks(self):
        self.module.ALLOW_NETWORK_ACCESS = True
        response = await self.client.post("/api/tts", json={"text": "Synthetic"})
        self.assertEqual(response.status_code, 403)
        response = await self.client.post(
            "/api/tts", json={"text": "Synthetic"},
            headers={**self.headers, "Origin": "http://external.example"},
        )
        self.assertEqual(response.status_code, 403)
        self.speech.assert_not_awaited()

    async def test_multipart_and_raw_audio_are_compatible_with_patched_parser(self):
        transcribe = AsyncMock(return_value=SimpleNamespace(text="Synthetic transcript"))
        provider = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=transcribe)))
        with patch.object(self.module.openai, "AsyncOpenAI", return_value=provider):
            response = await self.client.post(
                "/api/stt", files={"file": ("sample.wav", b"synthetic wav", "audio/wav")}, headers=self.headers,
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {"text": "Synthetic transcript"})
            self.assertEqual(transcribe.call_args.kwargs["file"].getvalue(), b"synthetic wav")
            response = await self.client.post(
                "/api/stt", content=b"synthetic raw wav", headers={**self.headers, "Content-Type": "audio/wav"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(transcribe.call_args.kwargs["file"].getvalue(), b"synthetic raw wav")

    async def test_malformed_multipart_fails_without_provider_call(self):
        provider = AsyncMock()
        with patch.object(self.module.openai, "AsyncOpenAI", provider):
            response = await self.client.post(
                "/api/stt", content=b"invalid", headers={**self.headers, "Content-Type": "multipart/form-data"},
            )
        self.assertEqual(response.status_code, 400)
        provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
