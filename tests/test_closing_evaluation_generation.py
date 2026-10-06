"""Closing must use completed evaluation results from its own generation."""

import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from support import isolated_app


def completion(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class ClosingEvaluationGenerationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory(prefix="inquiry-closing-test-"))
        self.app = self.stack.enter_context(isolated_app(directory))
        self.stack.enter_context(patch.object(
            self.app.openai, "AsyncOpenAI", side_effect=AssertionError("Unexpected provider call"),
        ))
        self.shard_file = Path(directory) / "synthetic.json"
        self.shard_file.write_text(json.dumps({
            "central": "Is this complete?",
            "nodes": [{"id": "CENTRAL", "text": "Is this complete?", "parent": None}],
            "edges": [],
        }))
        self.session_id = "synthetic-closing"
        self.original_conversation = [{"role": "user", "content": "done"}]
        self.seed()

    def seed(self):
        self.app.save_session(self.session_id, {
            "session_id": self.session_id, "shard_dir": str(self.shard_file),
            "conversation": self.original_conversation, "conversation_revision": 4,
            "evaluation_generation": 1, "evaluated_generation": 1,
            "node_scores": {"CENTRAL": 0.9}, "node_dispositions": {"CENTRAL": "settled"},
            "node_raise_counts": {}, "frontier": [], "xp": 0, "level": 1,
            "achievements": [],
        })

    def read(self):
        return self.app.load_session(self.session_id)

    @staticmethod
    async def lower_score(shard, *_args):
        shard.nodes["CENTRAL"].engagement_score = 0.2
        shard.nodes["CENTRAL"].disposition = "active"
        return {"frontier": ["CENTRAL"], "summary": "Synthetic replacement evaluation"}

    async def test_pending_newer_evaluation_cannot_supply_old_scores_to_closing(self):
        # Reproduce the previous failure: generation 2 starts, closing adopts
        # that generation with generation 1's complete scores, then generation
        # 2 lowers the score before the stale closing tries to append.
        for expected_generation in (None, 1):
            with self.subTest(expected_generation=expected_generation):
                self.seed()
                eval_entered, eval_release = asyncio.Event(), asyncio.Event()
                closing_release = asyncio.Event()

                async def evaluate(shard, *args):
                    eval_entered.set()
                    await eval_release.wait()
                    return await self.lower_score(shard, *args)

                async def create(**_kwargs):
                    await closing_release.wait()
                    return completion("outdated closing")

                provider = AsyncMock(side_effect=create)
                client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=provider)))
                with patch.object(self.app, "evaluate_equilibrium", evaluate), \
                        patch.object(self.app.openai, "AsyncOpenAI", return_value=client):
                    evaluation = asyncio.create_task(self.app._eval_and_merge(self.session_id, False, 4))
                    await asyncio.wait_for(eval_entered.wait(), 2)
                    closing = asyncio.create_task(self.app._generate_closing(
                        self.session_id, 4, expected_generation,
                    ))
                    await asyncio.sleep(0)
                    eval_release.set()
                    await asyncio.wait_for(evaluation, 2)
                    closing_release.set()
                    self.assertIsNone(await asyncio.wait_for(closing, 2))
                provider.assert_not_awaited()
                data = self.read()
                self.assertEqual(data["conversation"], self.original_conversation)
                self.assertEqual(data["conversation_revision"], 4)
                self.assertEqual(data["equilibrium_score"], 0.2)
                self.assertEqual(data["evaluation_generation"], 2)
                self.assertEqual(data["evaluated_generation"], 2)

    async def test_newer_evaluation_started_during_closing_invalidates_its_commit(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def create(**_kwargs):
            entered.set()
            await release.wait()
            return completion("outdated closing")

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(self.app, "evaluate_equilibrium", self.lower_score), \
                patch.object(self.app.openai, "AsyncOpenAI", return_value=client):
            closing = asyncio.create_task(self.app._generate_closing(self.session_id, 4, 1))
            await asyncio.wait_for(entered.wait(), 2)
            evaluation = await self.app._eval_and_merge(self.session_id, False, 4)
            self.assertEqual(evaluation["evaluation_generation"], 2)
            release.set()
            self.assertIsNone(await asyncio.wait_for(closing, 2))
        self.assertEqual(self.read()["conversation"], self.original_conversation)
        self.assertEqual(self.read()["conversation_revision"], 4)
        self.assertEqual(self.read()["equilibrium_score"], 0.2)

    async def test_old_generation_cannot_close_from_newer_completed_scores(self):
        evaluate = AsyncMock(return_value={"frontier": [], "summary": "Still complete"})
        with patch.object(self.app, "evaluate_equilibrium", evaluate):
            result = await self.app._eval_and_merge(self.session_id, False, 4)
        self.assertEqual(result["evaluation_generation"], 2)
        with patch.object(self.app.openai, "AsyncOpenAI") as provider:
            self.assertIsNone(await self.app._generate_closing(self.session_id, 4, 1))
        provider.assert_not_called()
        self.assertEqual(self.read()["conversation"], self.original_conversation)

    async def test_matching_completed_generation_can_close(self):
        provider = AsyncMock(return_value=completion("current closing"))
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=provider)))
        with patch.object(self.app.openai, "AsyncOpenAI", return_value=client):
            self.assertEqual(await self.app._generate_closing(self.session_id, 4, 1), "current closing")
        provider.assert_awaited_once()
        data = self.read()
        self.assertEqual(data["conversation"][-1], {"role": "assistant", "content": "current closing"})
        self.assertEqual(data["conversation_revision"], 5)


if __name__ == "__main__":
    unittest.main()
