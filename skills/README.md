# Inquiry shard skills

Instructions for building inquiry shards for Inquiry Chat. They are plain Markdown and written for any AI agent or assistant, whatever its maker.

| Skill | Use it to | Needs | Produces |
|---|---|---|---|
| [`generate-inquiry-shard`](generate-inquiry-shard/SKILL.md) | Make a complete shard in one go, ready to chat with | A source text and, optionally, a central question and a title | Everything the two skills below produce, checked |
| [`ics-from-text`](ics-from-text/SKILL.md) | Build a shard from a text | A source text and, optionally, a central question, a title and a source line | `Shards/<shard-name>/<shard-name>.json` |
| [`node-contexts`](node-contexts/SKILL.md) | Write the context document for each question in a shard | The shard's JSON file and the source text | `Shards/<shard-name>/contexts/<NODE_ID>.md`, one per question |

`generate-inquiry-shard` is the one to ask for in most cases: say "generate an inquiry shard from X". It runs `ics-from-text`, then `node-contexts`, then checks the result with `generate-inquiry-shard/check_shard.py`. It contains no format rules of its own, so the rules stay in the two skills it runs.

To do the steps by hand, run `ics-from-text` first, then `node-contexts` on its output.

## Checking a shard

```
python3 skills/generate-inquiry-shard/check_shard.py "Shards/<folder>/<shard>.json"
```

Prints `READY` or `NOT READY` with a line per problem. It checks the file format and that every question has its context document. It needs only Python 3.

## How to use them

**With an agent that supports skills.** Each skill is a folder holding a `SKILL.md` with `name` and `description` in its front matter, the layout used by the Agent Skills format. Point the agent at this `skills/` folder, or copy the three skill folders to wherever that agent looks for skills.

**With an agent that reads project instructions.** `AGENTS.md` in the project folder tells the agent these skills exist and when to read them.

**With any chat assistant.** Paste the contents of the `SKILL.md` as the first message, followed by the inputs it asks for. If the assistant cannot write files, it replies with the content and the path to save it to.

## Keeping copies in step

This folder is the master copy. Identical copies are kept for Claude Code at:

- `.claude/skills/ics-from-text/SKILL.md`
- `.claude/skills/node-contexts/SKILL.md`
- `.claude/skills/generate-inquiry-shard/SKILL.md` and `check_shard.py`

After editing a skill here, copy it over the matching files above.

The shard format these skills produce is described in section 3 of `CONVERSATION_LOGIC.md`.
