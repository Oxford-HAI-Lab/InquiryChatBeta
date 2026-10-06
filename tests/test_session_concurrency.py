"""Controlled races through the real turn/evaluation code, with fake providers."""

import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from support import isolated_app


def request(**body):
    return SimpleNamespace(json=AsyncMock(return_value=body))


def completion(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class ControlledChat:
    def __init__(self):
        self.calls = []
        self.entered = {label: asyncio.Event() for label in ("FIRST", "SECOND")}
        self.release = {label: asyncio.Event() for label in self.entered}
        self.client = SimpleNamespace(chat=SimpleNamespace(completions=self))

    async def create(self, **kwargs):
        messages = kwargs["messages"]
        label = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        self.calls.append(messages)
        self.entered[label].set()
        await self.release[label].wait()
        return completion("reply " + label)


class SessionConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory(prefix="inquiry-turn-test-"))
        self.app = self.stack.enter_context(isolated_app(directory))
        self.stack.enter_context(patch.object(
            self.app.openai, "AsyncOpenAI", side_effect=AssertionError("Unexpected provider call"),
        ))
        self.shard_file = Path(directory) / "shard" / "synthetic.json"
        self.shard_file.parent.mkdir()
        self.shard_file.write_text(json.dumps({
            "central": "What is justified?", "title": "Synthetic inquiry",
            "nodes": [{"id": "CENTRAL", "text": "What is justified?", "parent": None}],
            "edges": [],
        }))
        self.session_id = "synthetic-session"
        self.seed()
        self.stack.enter_context(patch.object(self.app, "evaluate_equilibrium", self.evaluate))

    async def asyncTearDown(self):
        tasks = list(self.app._background_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def seed(self, conversation=None, revision=None, score=0.0):
        data = {
            "session_id": self.session_id, "shard_dir": str(self.shard_file),
            "conversation": conversation or [], "node_scores": {"CENTRAL": score},
            "node_dispositions": {"CENTRAL": "settled" if score >= 0.75 else "active"},
            "node_raise_counts": {"CENTRAL": 0}, "frontier": ["CENTRAL"],
            "xp": 0, "level": 1, "achievements": [],
        }
        if revision is not None:
            data["conversation_revision"] = revision
        self.app.save_session(self.session_id, data)
        return data

    @staticmethod
    async def evaluate(shard, conversation, api_key):
        return {"frontier": ["CENTRAL"], "summary": "Synthetic evaluation"}

    def read(self):
        return self.app.load_session(self.session_id)

    async def drain(self):
        if self.app._background_tasks:
            await asyncio.gather(*list(self.app._background_tasks))

    async def start_turn(self, kind, label, client):
        if kind == "web":
            return await self.app.chat(self.session_id, request(message=label))
        return await self.app._device_chat_turn(self.session_id, label, client)

    async def assert_overlap(self, first_kind, second_kind):
        chat = ControlledChat()
        with patch.object(self.app.openai, "AsyncOpenAI", return_value=chat.client):
            first = asyncio.create_task(self.start_turn(first_kind, "FIRST", chat.client))
            await asyncio.wait_for(chat.entered["FIRST"].wait(), 2)
            second = asyncio.create_task(self.start_turn(second_kind, "SECOND", chat.client))
            # Try to complete SECOND first. It must not even use a stale prompt.
            chat.release["SECOND"].set()
            await asyncio.sleep(0)
            self.assertFalse(chat.entered["SECOND"].is_set())
            chat.release["FIRST"].set()
            await asyncio.wait_for(asyncio.gather(first, second), 2)
        await self.drain()
        self.assertEqual([m["content"] for m in self.read()["conversation"]],
                         ["FIRST", "reply FIRST", "SECOND", "reply SECOND"])
        self.assertIn({"role": "assistant", "content": "reply FIRST"}, chat.calls[1])
        self.assertEqual(self.read()["conversation_revision"], 2)

    async def test_two_web_turns_preserve_both_replies(self):
        await self.assert_overlap("web", "web")

    async def test_web_then_device_preserves_both_replies(self):
        await self.assert_overlap("web", "device")

    async def test_device_then_web_preserves_both_replies(self):
        await self.assert_overlap("device", "web")

    async def test_two_device_turns_preserve_both_replies(self):
        await self.assert_overlap("device", "device")

    async def test_different_sessions_do_not_block_each_other(self):
        other_id = "independent-session"
        other = dict(self.read(), session_id=other_id)
        self.app.save_session(other_id, other)
        async with self.app._turn_lock(self.session_id):
            fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
                create=AsyncMock(return_value=completion("independent reply")),
            )))
            await asyncio.wait_for(self.app._device_chat_turn(other_id, "hello", fake), 2)
        self.assertEqual(len(self.app.load_session(other_id)["conversation"]), 2)

    async def test_failed_turn_releases_lock_without_saving(self):
        with patch.object(self.app.openai, "AsyncOpenAI", side_effect=RuntimeError("synthetic failure")):
            with self.assertRaises(RuntimeError):
                await self.app.chat(self.session_id, request(message="FIRST"))
        self.assertFalse(self.app._turn_lock(self.session_id).locked())
        self.assertEqual(self.read()["conversation"], [])
        await self.assert_overlap("web", "device")

    async def test_cancelled_turn_releases_lock_without_saving(self):
        chat = ControlledChat()
        task = asyncio.create_task(self.app._device_chat_turn(self.session_id, "FIRST", chat.client))
        await asyncio.wait_for(chat.entered["FIRST"].wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.app._turn_lock(self.session_id).locked())
        self.assertEqual(self.read()["conversation"], [])

    async def test_delete_during_turn_never_recreates_session(self):
        chat = ControlledChat()
        with patch.object(self.app.openai, "AsyncOpenAI", return_value=chat.client):
            task = asyncio.create_task(self.app.chat(self.session_id, request(message="FIRST")))
            await asyncio.wait_for(chat.entered["FIRST"].wait(), 2)
            await self.app.delete_session(self.session_id)
            chat.release["FIRST"].set()
            with self.assertRaises(self.app.HTTPException) as error:
                await task
        self.assertEqual(error.exception.status_code, 404)
        self.assertIsNone(self.read())

    async def test_stale_evaluation_after_rewind_is_discarded(self):
        self.seed([{"role": "user", "content": "old"}, {"role": "assistant", "content": "reply"}], revision=3)
        entered, release = asyncio.Event(), asyncio.Event()

        async def evaluate(shard, conversation, api_key):
            if len(conversation) == 2:
                entered.set()
                await release.wait()
                shard.nodes["CENTRAL"].engagement_score = 0.9
                shard.nodes["CENTRAL"].disposition = "settled"
            else:
                shard.nodes["CENTRAL"].engagement_score = 0.2
            return {"frontier": ["CENTRAL"], "summary": "synthetic"}

        with patch.object(self.app, "evaluate_equilibrium", evaluate):
            old = asyncio.create_task(self.app._eval_and_merge(self.session_id, False, 3))
            await asyncio.wait_for(entered.wait(), 2)
            await self.app.rewind_chat(self.session_id, request(message_index=0))
            release.set()
            self.assertIsNone(await old)
        self.assertEqual(self.read()["node_scores"], {"CENTRAL": 0.2})
        self.assertEqual(self.read()["node_dispositions"], {"CENTRAL": "active"})
        self.assertEqual(len(self.read()["conversation"]), 1)
        self.assertEqual(self.read()["conversation_revision"], 4)

    async def test_only_latest_evaluation_request_merges_in_either_finish_order(self):
        for newest_finishes_first in (False, True):
            with self.subTest(newest_finishes_first=newest_finishes_first):
                self.seed(revision=2)
                entered = [asyncio.Event(), asyncio.Event()]
                release = [asyncio.Event(), asyncio.Event()]
                calls = []

                async def evaluate(shard, conversation, api_key):
                    index = len(calls)
                    calls.append(index)
                    entered[index].set()
                    await release[index].wait()
                    shard.nodes["CENTRAL"].engagement_score = (0.9, 0.3)[index]
                    return {"frontier": [], "summary": "synthetic"}

                with patch.object(self.app, "evaluate_equilibrium", evaluate):
                    old = asyncio.create_task(self.app._eval_and_merge(self.session_id, False, 2))
                    await asyncio.wait_for(entered[0].wait(), 2)
                    new = asyncio.create_task(self.app._eval_and_merge(self.session_id, False, 2))
                    await asyncio.wait_for(entered[1].wait(), 2)
                    first, second = (1, 0) if newest_finishes_first else (0, 1)
                    release[first].set()
                    await (new if first else old)
                    release[second].set()
                    self.assertIsNone(await old)
                    self.assertIsNotNone(await new)
                self.assertEqual(self.read()["node_scores"], {"CENTRAL": 0.3})

    async def test_evaluation_for_old_revision_does_not_start_provider(self):
        self.seed(revision=4)
        with patch.object(self.app, "evaluate_equilibrium", new_callable=AsyncMock) as evaluate:
            self.assertIsNone(await self.app._eval_and_merge(self.session_id, False, 3))
            evaluate.assert_not_awaited()

    async def test_evaluation_finishing_after_new_turn_does_not_change_its_scores(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def evaluate(shard, conversation, api_key):
            if not conversation:
                entered.set()
                await release.wait()
                shard.nodes["CENTRAL"].engagement_score = 0.9
            else:
                shard.nodes["CENTRAL"].engagement_score = 0.2
            return {"frontier": [], "summary": "synthetic"}

        fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=AsyncMock(return_value=completion("new reply")),
        )))
        with patch.object(self.app, "evaluate_equilibrium", evaluate):
            old = asyncio.create_task(self.app._eval_and_merge(self.session_id, False, 0))
            await asyncio.wait_for(entered.wait(), 2)
            _, new = await self.app._device_chat_turn(self.session_id, "new", fake)
            await new
            release.set()
            self.assertIsNone(await old)
        self.assertEqual(self.read()["node_scores"], {"CENTRAL": 0.2})
        self.assertEqual(len(self.read()["conversation"]), 2)

    async def test_delete_invalidates_pending_evaluation(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def evaluate(*args):
            entered.set()
            await release.wait()
            return {"frontier": [], "summary": "synthetic"}

        with patch.object(self.app, "evaluate_equilibrium", evaluate):
            task = asyncio.create_task(self.app._eval_and_merge(self.session_id, False))
            await asyncio.wait_for(entered.wait(), 2)
            await self.app.delete_session(self.session_id)
            release.set()
            self.assertIsNone(await task)
        self.assertIsNone(self.read())

    async def test_closing_cannot_restore_replacement_history_of_equal_length(self):
        self.seed([{"role": "user", "content": "old"}], revision=5, score=0.9)
        entered, release = asyncio.Event(), asyncio.Event()

        async def create(**kwargs):
            entered.set()
            await release.wait()
            return completion("obsolete closing")

        fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(self.app.openai, "AsyncOpenAI", return_value=fake):
            task = asyncio.create_task(self.app._generate_closing(self.session_id, 5))
            await asyncio.wait_for(entered.wait(), 2)
            # Exercise the persisted revision guard independently of turn locks.
            async with self.app._session_lock(self.session_id):
                data = self.read()
                data["conversation"] = [{"role": "user", "content": "replacement"}]
                self.app._advance_conversation(data)
                self.app.save_session(self.session_id, data)
            release.set()
            self.assertIsNone(await task)
        self.assertEqual(self.read()["conversation"], [{"role": "user", "content": "replacement"}])

    async def test_closing_queued_before_rewind_and_new_turn_is_discarded(self):
        original = [{"role": "user", "content": "old"}, {"role": "assistant", "content": "old reply"},
                    {"role": "user", "content": "old two"}, {"role": "assistant", "content": "reply two"}]
        self.seed(original, revision=6, score=0.9)
        await self.app.rewind_chat(self.session_id, request(message_index=1))
        fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=AsyncMock(return_value=completion("replacement reply")),
        )))
        _, evaluation = await self.app._device_chat_turn(self.session_id, "replacement", fake)
        await evaluation
        self.assertEqual(len(self.read()["conversation"]), len(original))
        self.assertIsNone(await self.app._generate_closing(self.session_id, 6))
        self.assertEqual(self.read()["conversation"][-1]["content"], "replacement reply")

    async def test_closing_appends_once_and_advances_revision(self):
        self.seed([{"role": "user", "content": "done"}], revision=4, score=0.9)
        fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=AsyncMock(return_value=completion("valid closing")),
        )))
        with patch.object(self.app.openai, "AsyncOpenAI", return_value=fake):
            self.assertEqual(await self.app._generate_closing(self.session_id, 4), "valid closing")
            self.assertIsNone(await self.app._generate_closing(self.session_id, 4))
        self.assertEqual(self.read()["conversation_revision"], 5)
        self.assertEqual(len(self.read()["conversation"]), 2)

    async def test_real_stream_delivers_reply_evaluation_and_current_closing(self):
        async def complete(shard, conversation, api_key):
            shard.nodes["CENTRAL"].engagement_score = 0.9
            shard.nodes["CENTRAL"].disposition = "settled"
            return {"frontier": [], "summary": "Complete"}

        create = AsyncMock(side_effect=[completion("reply"), completion("closing")])
        fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(self.app, "evaluate_equilibrium", complete), \
                patch.object(self.app.openai, "AsyncOpenAI", return_value=fake):
            response = await self.app.chat(self.session_id, request(message="question"))
            lines = [json.loads(line) async for line in response.body_iterator]
        self.assertEqual([line["phase"] for line in lines], ["reply", "eval", "closing"])
        self.assertTrue(lines[1]["closing_pending"])
        self.assertEqual(lines[2]["assistant_message"], "closing")
        self.assertEqual([m["content"] for m in self.read()["conversation"]], ["question", "reply", "closing"])
        self.assertEqual(self.read()["conversation_revision"], 2)

    async def test_stream_disconnect_does_not_cancel_current_evaluation(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def evaluate(shard, conversation, api_key):
            entered.set()
            await release.wait()
            shard.nodes["CENTRAL"].engagement_score = 0.5
            return {"frontier": [], "summary": "Synthetic"}

        fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=AsyncMock(return_value=completion("reply")),
        )))
        with patch.object(self.app, "evaluate_equilibrium", evaluate), \
                patch.object(self.app.openai, "AsyncOpenAI", return_value=fake):
            response = await self.app.chat(self.session_id, request(message="question"))
            first = json.loads(await response.body_iterator.__anext__())
            self.assertEqual(first["phase"], "reply")
            waiting = asyncio.create_task(response.body_iterator.__anext__())
            await asyncio.wait_for(entered.wait(), 2)
            waiting.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiting
            release.set()
            await self.drain()
        self.assertEqual(self.read()["node_scores"], {"CENTRAL": 0.5})
        self.assertEqual(len(self.read()["conversation"]), 2)


if __name__ == "__main__":
    unittest.main()
