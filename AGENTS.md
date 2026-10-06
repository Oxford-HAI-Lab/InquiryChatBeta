# Inquiry Chat: notes for AI agents

Inquiry Chat is a web app that guides a user through the questions around a central question, using an **inquiry shard**: a JSON graph of questions plus one context document per question.

## Building shards

Three skills in `skills/` cover shard building. Read the skill's `SKILL.md` in full before starting, and follow it exactly: the app depends on the format it specifies.

| When asked to | Read |
|---|---|
| Generate a complete shard from a source, ready to use | `skills/generate-inquiry-shard/SKILL.md` |
| Build only the shard's JSON file | `skills/ics-from-text/SKILL.md` |
| Generate node contexts or context files for a shard | `skills/node-contexts/SKILL.md` |

To check any shard: `python3 skills/generate-inquiry-shard/check_shard.py "<path to the shard .json>"`.

## Where things are

| Path | Contents |
|---|---|
| `README.md` | Introduction, setup and running |
| `CONVERSATION_LOGIC.md` | How the app works, the shard file format, settings |
| `Shards/` | Existing shards, useful as examples |
| `app.py`, `ic_engine.py`, `static/` | The app |
| `PhilosophyPod/` | The optional voice device, with its own `README.md`. `PhilosophyPod/xiaozhi-esp32/` is a modified copy of someone else's open-source firmware; do not reformat or reorganise it, and record any further change to it in `PhilosophyPod/UPSTREAM.md` |
| `LICENSE` | MIT license. Keep the copyright notice in copies of the software |

## Rules

- `env` holds API keys and the device token. Do not print, copy or share its contents, and do not remove it from `.gitignore`. `env.example` is the version that may be published.
- Do not edit files in `sessions/`; the app writes them.
- Keep locally built firmware and saved flash binaries for the owner's use. `PhilosophyPod/local-firmware/` and the firmware `build/` directory are excluded from Git and public releases; that exclusion is not permission to delete them during cleanup.
- The files under `.claude/` are copies of `skills/`. Edit the skill in `skills/` and copy it across.
