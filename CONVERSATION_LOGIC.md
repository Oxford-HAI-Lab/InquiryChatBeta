# Inquiry Chat — Conversation Logic & Prompt Architecture

Last checked against the code: 2026-09-30.

Prompts are described here, not reproduced in full. The live wording is in the functions named in each section; read it there, since a copy in this file would go stale.

## Contents

1. Overview
2. Files and setup
3. Inquiry shards
4. Sessions
5. The welcome message
6. Per-turn sequence (web chat)
7. Chat call: system prompt
8. Chat call: per-turn steering reminder
9. Evaluation call
10. Dispositions
11. Equilibrium score
12. End-of-inquiry stages
13. Gamification
14. Rewind
15. Voice
16. Voice device path
17. API endpoints

---

## 1. Overview

Inquiry Chat guides a user through the question space around a central question, using an **inquiry shard**: a directed graph of questions that the user's answer should be robust to. Progress is measured as movement toward **erotetic equilibrium** with the shard.

Each turn makes two LLM calls, both to the model named by `CHAT_MODEL` (default `gpt-5.6-sol`):

```
                         ┌─────────────────────┐
                         │    Inquiry shard    │
                         │  (JSON + contexts)  │
                         └──────────┬──────────┘
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
         ┌──────────────────┐            ┌──────────────────────┐
         │  CHAT CALL       │            │  EVALUATION CALL     │
         │  system prompt   │            │  evaluator prompt    │
         │  + history       │            │  + full conversation │
         │  + steering      │            │                      │
         └────────┬─────────┘            └──────────┬───────────┘
                  ▼                                 ▼
         ┌──────────────────┐            ┌──────────────────────┐
         │  Reply           │            │  Per-node scores     │
         │  (sent at once)  │            │  + dispositions      │
         └──────────────────┘            │  + frontier, summary │
                                         └──────────┬───────────┘
                                                    ▼
                                         ┌──────────────────────┐
                                         │  Equilibrium score   │
                                         │  Gamification        │
                                         │  Closing stage       │
                                         └──────────────────────┘
```

The reply is sent to the browser as soon as it is ready. The evaluation runs in the background and its results follow as a second message, so the user never waits for scoring before reading or hearing the reply.

---

## 2. Files and setup

| Path | Role |
|---|---|
| `app.py` | Web server (FastAPI): endpoints, turn handling, gamification, voice, device path |
| `ic_engine.py` | Shard loading, scoring, evaluation prompt, chat system prompt, closing stages, welcome message |
| `static/index.html`, `static/app.js`, `static/style.css` | The browser interface |
| `Shards/` | Inquiry shards, one folder per source work. A folder can hold several shards, which share its `contexts/` folder |
| `sessions/` | Saved chats, one JSON file each |
| `env` | API keys and optional settings. A visible file. It holds secrets and is excluded from git by `.gitignore`; leave it out when sharing the folder any other way |
| `.venv/` | The Python environment the launcher activates (hidden folder) |
| `requirements.txt`, `requirements-device.txt` | Web packages and optional device packages, respectively |
| `Launch_Inquiry_Chat.command` | If a voice device is plugged in by USB, offers to set it up for the current network, which takes up to a minute, and creates the device token the first time. Then starts the server, waits until it answers, and opens the browser |
| `skills/` | Skills usable by any AI agent: `generate-inquiry-shard` (a complete shard in one go), `ics-from-text` (the shard file), `node-contexts` (the context documents), plus the checker `check_shard.py`. The master copy. See "Building shards" in section 3 |
| `AGENTS.md` | Short guide for AI agents working in this folder: where the skills are and what not to touch |
| `PhilosophyPod/` | The optional voice device: firmware (`xiaozhi-esp32/`, based on upstream release v2.5.0 and built with ESP-IDF 6), bridge server (`bridge_server.py`), USB setup tool (`provision.py`) and its own `README.md`. Not used by the web app. See section 16 |
| `LICENSE` | MIT license, copyright 2026 Philipp Koralus |
| `README.md` | Introduction for new users: what the app is, setup, running, making shards |
| `env.example` | Template for `env`, with the key values blank |
| `.gitignore` | Files git must not upload: `env`, `sessions/`, `.venv/`, caches, backups, personal settings and the device's server address file |
| `CITATION.cff` | How to cite the project: Koralus (2025), *Mind & Society* 24(2) |
| `.claude/skills/` | Copies of the skills for Claude Code, kept identical to `skills/` |

### Running

1. Copy `env.example` to `env` and put the API keys in it (see Settings below).
2. Double-click `Launch_Inquiry_Chat.command`. It activates `.venv`, loads `env`, starts the server on port 8000 and opens `http://localhost:8000` once the server answers.
3. To rebuild the Python environment from scratch: create a virtual environment named `.venv` and install `requirements.txt` into it. For a voice device, install `requirements-device.txt` instead (it includes the web packages), plus native Opus and `ffmpeg` on the system. Missing device codecs do not prevent the web app from starting.

Changes to `app.py` or `ic_engine.py` take effect when the server is restarted. Changes under `static/` and to shard files take effect on the next page load.

### Settings (`env`)

| Name | Required | Default | Purpose |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | none | Chat, evaluation, emotion tagging, server-side transcription. The launcher falls back to the macOS Keychain item `openai-api-key` |
| `ELEVENLABS_API_KEY` | No | none | Voice output with ElevenLabs. Without it, the OpenAI voice speaks instead |
| `ELEVENLABS_VOICE_ID` | No | `yHfgpRM0HDTqWxFXMMUf` | Which ElevenLabs voice to use. The default is a custom voice made for Inquiry Chat by Philipp Koralus. An account that the voice has not been shared with falls back to the OpenAI voice, or sets a voice of its own here |
| `OPENAI_TTS_VOICE` | No | `ash` | The OpenAI voice, used when ElevenLabs is not set up or its voice is not available. One of alloy, ash, ballad, coral, echo, sage, shimmer, verse, marin, cedar |
| `OPENAI_TTS_MODEL` | No | `gpt-4o-mini-tts` | Model for the OpenAI voice. Must accept `instructions` for expressive mode to have an effect; `tts-1` and `tts-1-hd` do not |
| `TTS_PROVIDER` | No | `auto` | `auto` uses ElevenLabs when its key is set and the voice can be used, otherwise OpenAI. `elevenlabs` or `openai` forces one |
| `OPENAI_CHAT_MODEL` | No | `gpt-5.6-sol` | Model for chat, evaluation and emotion tagging |
| `OPENAI_TRANSCRIBE_MODEL` | No | `gpt-transcribe` | Model for server-side transcription |
| `ELEVENLABS_SEED` | No | `20260929` | Fixed seed sent with every ElevenLabs request |
| `ALLOW_NETWORK_ACCESS` | No | off | Set to `1` to let other computers on the network open the web app. See "Access" below |
| `DEVICE_TOKEN` | No | none | Secret a voice device must present to connect. Created by the launcher when it first sets up a device. Setting it makes the server listen on the network, for the device. See "Access" below |

All chat-model calls pass `reasoning_effort="none"` and limit output with `max_completion_tokens`.

### Access

**File:** `app.py` -> `LISTEN_HOST`, `_local_only()`, `_device_ws_refusal()`, `_device_token_ok()`

By default the server listens on this computer only (`127.0.0.1`). It listens on all network interfaces when `ALLOW_NETWORK_ACCESS=1` is set, or when `DEVICE_TOKEN` is set, since the voice device reaches it over the network. The Terminal says which at startup. Three rules then limit who can use it:

| Who | Rule |
|---|---|
| Browsers and other HTTP clients | Accepted only from the computer the server runs on, and only when the request's Host header is `localhost`, `127.0.0.1` or `[::1]`, so that a web page elsewhere cannot reach the API by pointing a name of its own at this computer (DNS rebinding). Others get a 403 response and a line in the Terminal. `ALLOW_NETWORK_ACCESS=1` lifts both checks |
| Voice device setup address (`/xiaozhi/ota/...`) | Open to the network when `DEVICE_TOKEN` is set. It returns only the address to connect to, never the token |
| Voice device connection (`/xiaozhi/ws`) | Refused if the connection carries an `Origin` header, which every browser sends and the device firmware never does, so a web page cannot join the conversation. Refused from the network unless `DEVICE_TOKEN` or `ALLOW_NETWORK_ACCESS` is set. If `DEVICE_TOKEN` is set, the device must present it |

The token reaches a device only over USB, through `PhilosophyPod/provision.py`. The bridge server, which runs on the same computer, reaches the web endpoints as a local client and is not affected by the first rule. The bridge applies the same listening rule to itself: it is reachable from the network only when `DEVICE_TOKEN` or `ALLOW_NETWORK_ACCESS` is set in its environment, and it refuses connections that carry an `Origin` header.

Every `/api/` request with an `Origin` must match the server origin exactly, including its port. Mutations and paid requests also require `X-Inquiry-CSRF`, obtained from `GET /api/csrf`; that response is not cached, and the token changes on server restart. JSON endpoints require `Content-Type: application/json`; transcription keeps its multipart and raw-audio formats. The frontend and bridge supply the token automatically. Native API clients first fetch it, then include it with each unsafe request. Device OTA/WebSocket protocols keep their existing token rules. Network mode does not disable these browser request protections and still assumes a trusted, single-user network; CSRF protection is not user authentication.

---

## 3. Inquiry shards

### File format

A shard is one JSON file. Its node context documents live in a `contexts/` folder next to it, one `<NODE_ID>.md` per node.

```json
{
  "title": "Mill: The Harm Principle",
  "source": "John Stuart Mill, On Liberty (1859), mainly Chapters 1, 4 and 5 ...",
  "source_brief": "John Stuart Mill's On Liberty, focusing on the harm principle",
  "central": "When, if ever, is society justified in interfering with an individual's liberty?",
  "nodes": [
    {"id": "CENTRAL", "text": "...", "parent": null, "notes": "..."},
    {"id": "HARMPRINCIPLE", "text": "...", "parent": "CENTRAL", "notes": "..."}
  ],
  "edges": [
    {"from": "CENTRAL", "to": "HARMPRINCIPLE", "weight": 0.95}
  ]
}
```

| Field | Used for |
|---|---|
| `title` | Display name in the shard menu and session list. Falls back to the file name |
| `source` | One line saying what the shard was generated from. Loaded and returned by the API; not displayed |
| `source_brief` | Short phrase completing "derived from …" in the welcome message. Falls back to the first sentence of `source` |
| `central` | The central question |
| `nodes[].id`, `text`, `parent`, `notes` | The question graph. `notes` (first 200 characters) goes to the evaluator; it also stands in for a missing context document. The `CENTRAL` node's `text` must equal `central` |
| `edges[].from`, `to`, `weight` | Destabilization relations. `weight` defaults to 0.5 |
| `edges[]._comment` | Present on cross-edges only (edges that do not mirror a node's `parent`), starting `Cross-edge:`. The app identifies cross-edges by this field, for the `cross_link` achievement |

### Context documents

Each node can have a context document at `contexts/<NODE_ID>.md`, next to the shard file: a source-faithful summary with quotes, typically 1000–2000 words. The chat reads each document **in full** (section 7).

Shards in the same folder share one `contexts/` folder. A node ID that appears in two sibling shards uses the same document in both.

### Building shards

Shards and context documents are produced by an AI agent following the skills in `skills/`, not by the app. The skills are plain Markdown and not tied to any one agent; `skills/README.md` explains how to use them.

| Skill | Version | Produces |
|---|---|---|
| `generate-inquiry-shard` | 1.0.0 | A complete shard in one go: runs the two skills below in turn, then checks the result with `check_shard.py` |
| `ics-from-text` | 2.2.1 | The shard JSON file, in the format above, from a source text and a central question |
| `node-contexts` | 1.4.1 | The `contexts/<NODE_ID>.md` files, from the shard file and the source text. Adds `source` and `source_brief` to the shard if they are missing |

To check that a shard is ready for the app, run `python3 skills/generate-inquiry-shard/check_shard.py "<path to the shard .json>"`. It checks the file format and that every question has a context document.

The skills state the format rules the app depends on: field order, `_comment` on cross-edges, `CENTRAL` text matching `central`, and the essential point of each note within its first 200 characters.

### Current shards

| Title | File | Questions |
|---|---|---|
| Mill: Freedom of Thought and Individuality | `Shards/mill-on-liberty/mill_thought_individuality.json` | 8 |
| Mill: The Harm Principle | `Shards/mill-on-liberty/mill_harm_principle.json` | 10 |

Question counts include the central question. The two Mill shards share `Shards/mill-on-liberty/contexts/`; each covers a different part of the source.

### Discovery

**File:** `app.py` -> `get_shards()`

The shard menu lists every JSON file under `Shards/` (and the project folder) that has `central`, `nodes` and `edges`. Shards are identified by file path, so one folder can hold several. Hidden folders and `sessions`, `static`, `node_modules` and `__pycache__` are skipped. The list is sorted by title. A JSON file that cannot be read, or that has only some of the three required fields, is reported in the Terminal.

### Loading

**File:** `ic_engine.py` -> `load_shard(shard_dir)`. `POST /api/sessions/new` accepts only a `shard_dir` inside the project folder, as listed by `GET /api/shards`.

Accepts the path of a shard's JSON file. For sessions saved before shards were identified by file, it also accepts a folder and uses the first JSON file found in it.

Before reading any context, the runtime and checker validate every node ID as a nonempty ASCII letter/digit/underscore/hyphen string and resolve all context paths. Context files must stay inside the shard's own `contexts/` directory; directory redirection and escaping file symlinks are rejected. The shared checks live beside the portable checker in `skills/generate-inquiry-shard/_shard_paths.py`.

---

## 4. Sessions

**Directory:** `sessions/`, one file per chat, named `<session_id>.json`.

```json
{
  "session_id": "a1b2c3d4",
  "shard_dir": "Shards/mill-on-liberty/mill_harm_principle.json",
  "shard_name": "Mill: The Harm Principle",
  "central_question": "When, if ever, is society justified...?",
  "conversation": [{"role": "user", "content": "..."}],
  "conversation_revision": 1,
  "evaluation_generation": 1,
  "evaluated_generation": 1,
  "node_scores": {"CENTRAL": 0.5, "HARMPRINCIPLE": 0.7},
  "node_dispositions": {"CENTRAL": "settled", "HARMPRINCIPLE": "active"},
  "node_raise_counts": {"CENTRAL": 1, "HARMPRINCIPLE": 3},
  "equilibrium_score": 0.35,
  "frontier": ["WHATHARM", "TYRANNY"],
  "xp": 340,
  "level": 4,
  "achievements": ["first_question"],
  "closing_mode_active": false,
  "updated_at": "2026-09-29T16:30:00"
}
```

- Sessions save when a reply lands (conversation and raise counts), when an evaluation starts (its request generation), and when a current evaluation finishes (scores, dispositions, frontier, gamification, closing flag). Evaluation never writes conversation or raise counts.
- A per-session turn lock orders generation and saving across browser turns, live voice turns, buffered voice turns after a disconnect, rewind and closing. A separate state lock protects snapshots and writes, so background evaluation and speech playback can continue independently.
- `conversation_revision` increases on each turn, rewind and closing. Legacy sessions start at revision zero. Evaluation must match both the conversation revision and latest `evaluation_generation` before merging; `evaluated_generation` records the last accepted evaluation. Closing must use that completed evaluation and the same conversation revision. Deletion prevents pending work from recreating the session.
- Run exactly one server process/worker per session directory, as `python app.py` does. Process-local locks do not coordinate multiple Uvicorn workers or separate app instances sharing these files.
- `central_question` may differ from the shard's if the user typed an override when starting the chat.
- A conversation can contain two assistant messages in a row: the reply and the follow-up closing (section 12).
- The equilibrium score is recomputed from the saved node data whenever a session is opened or listed, so sessions saved under older rules show current values. In the session list, the shard title is also read afresh from the shard file; an opened session returns the saved `shard_name`.
- Sessions saved before dispositions existed have them estimated from the conversation (`_backfill_dispositions`).

---

## 5. The welcome message

**File:** `ic_engine.py` -> `welcome_message(shard, central_question, markdown, speech)`

Shown when a chat with no messages is opened, and spoken if voice output is on. It is not stored in the conversation.

> Welcome to an inquiry shard derived from *[source_brief]*. Our central question is: **"[central question]"** Share your initial thoughts to begin.

The session endpoint returns two versions:

| Field | Content |
|---|---|
| `welcome_message` | Display text, with the question in bold |
| `welcome_speech` | Text for the voice: plain, with delivery directions in square brackets and ellipses for pauses, so the central question is set apart and emphasised |

The spoken version is marked as already directed, so expressive-mode emotion tagging is skipped for it.

---

## 6. Per-turn sequence (web chat)

**File:** `app.py` -> `chat()`, `_chat_turn()`, `_eval_and_merge()`, `_generate_closing()`

The response to `POST /api/chat/{session_id}` is a stream of JSON lines.

```
1. Acquire the turn lock, load session and shard; restore scores and counts.
   Note whether the inquiry was already complete (100%) before this turn.
2. Append the user message.
3. ── CHAT CALL ──────────────────────────────────────────
   a. Build the system prompt (section 7).
   b. Trim history: if longer than 20 messages, keep the last 20 and
      prepend a one-line summary of earlier topics.
   c. Build the steering reminder (section 8) and insert it just before
      the user's latest message.
   d. Call the model. Output limit: 300 tokens x detail level (1 to 4).
4. Increase raise_count for each frontier node the reply touched.
5. Save conversation and raise counts; advance revision, release turn lock.
6. SEND LINE 1:  {"phase": "reply", "assistant_message": ...}
7. ── EVALUATION CALL (background) ───────────────────────
   a. Evaluate the full conversation (section 9).
   b. Apply score damping and update dispositions.
   c. Recompute equilibrium score, gamification, closing-mode flag.
   d. Save only if the conversation revision and evaluation request are current.
8. SEND LINE 2:  {"phase": "eval", ...scores, nodes, frontier, summary,
                  xp, level, new_achievements, closing_mode,
                  closing_pending}
9. Only if this turn brought the score to 100%:
   a. Generate the follow-up closing message (section 12).
   b. Save it as a second assistant message.
   c. SEND LINE 3:  {"phase": "closing", "assistant_message": ...}
```

The evaluation runs as a background task shielded from cancellation, so it can finish and save even if the browser disconnects. Results for an obsolete revision or evaluation request are discarded. The closing is only started once the evaluation result has been sent, so if the browser has disconnected by then, no follow-up closing is generated and the fallback in section 12 applies on the next turn. A closing that has started is shielded in the same way and participates in turn ordering.

If the evaluation call itself fails, the error is printed in the Terminal, no eval line is sent, and scores stay as they were.

**Detail level.** Holding the send button raises the detail level from 1 to 4. Above 1.5 it lifts the reply length limit for that turn and asks for a longer reply with concrete examples.

---

## 7. Chat call: system prompt

**File:** `ic_engine.py` -> `build_chat_system_prompt(shard, frontier, closing_mode_was_active)`

Rebuilt every turn. Sent as the `system` message.

### Structure

| Part | Content |
|---|---|
| Opening | "You are a conversational partner exploring the question: …" and the instruction to follow the Socratic method |
| Style rules | Turn length (1–3 sentences typical, 4–5 at most), pacing (one point per exchange), opening, questions as the primary instrument, affirmation before redirection, analogies, uncertainty, periodic summaries, contradictions, impasse, never breaking character |
| Steering | The model chooses the next question from the frontier. It must not ask what the user wants to explore, declare the view settled, signal winding down, or mention the inquiry complex, nodes or scores |
| Repetition avoidance | Settled and rejected-with-understanding nodes are off limits. Dismissed nodes may be retried only from a new angle; after three dismissals the model asks the user to explain the point in their own words |
| Node status | One line per node: id, question, engaged or not, score, disposition, times raised |
| Frontier context | Full context documents for the questions to explore next and for other unresolved questions |
| Stage block | At most one of: closing mode, graceful closing, inquiry complete (section 12) |

### Frontier context

- Nodes already settled or rejected with understanding are removed from the frontier first.
- Each frontier node gets its **full context document**, marked `[PRIORITY]`.
- Every other node scoring below 0.7, unless settled or rejected with understanding, also gets its full context document.
- Nodes that are settled or rejected with understanding contribute no context. Neither do nodes scoring 0.7 or more, unless they are on the frontier.
- If a node has no context document, its `notes` are used.
- A dismissed frontier node carries a note that a completely different angle is required.

On the first turn of a session, the frontier is the first two nodes in the shard file.

### Prompt size

Because documents are included in full, the system prompt is largest on the first turn and shrinks as nodes are resolved, down to about 10,000 characters once every node is resolved. First-turn sizes, measured 2026-09-30:

| Shard | Nodes | First-turn prompt | Approx. tokens |
|---|---|---|---|
| Mill: Freedom of Thought and Individuality | 8 | 81,086 characters | 20,000 |
| Mill: The Harm Principle | 10 | 97,553 | 24,000 |

Token figures are estimates at four characters per token. This prompt is sent on every turn, so cost and response time scale with it.

---

## 8. Chat call: per-turn steering reminder

**File:** `app.py` -> `chat()`

A second `system` message, inserted just before the user's latest message. Web chat only. Its content depends on the frontier:

| Situation | Reminder |
|---|---|
| Frontier nodes not discussed in the last 20 messages | Introduce a new angle from up to three of them; do not repeat earlier questions |
| Frontier nodes discussed recently | Do not re-ask; find a new concrete example that forces the tension, for up to two of them |
| Nothing on the frontier | Do not wrap up; continue probing |
| Inquiry complete (100%) | Replaces all of the above: follow the inquiry-complete instructions, do not probe, do not end with a question |

Settled and rejected-with-understanding nodes are listed as off limits. Dismissed nodes carry the same retry rules as in the system prompt. "Discussed recently" is judged by keyword overlap between the node's question and the recent messages.

---

## 9. Evaluation call

**File:** `ic_engine.py` -> `build_evaluation_prompt()`, `evaluate_equilibrium()`

Sent as a single `user` message, with an output limit of 1500 tokens. The evaluator sees the **full conversation**, not a trimmed one.

### Inputs

- The central question
- For each node: id, engaged or not, disposition, times raised, question text, first 200 characters of notes
- The whole conversation

### Output

```json
{
  "scores": {"NODE_ID": 0.0},
  "dispositions": {"NODE_ID": "active"},
  "frontier": ["NODE_ID_1", "NODE_ID_2"],
  "summary": "One sentence on the user's current equilibrium state"
}
```

`frontier` lists **all** nodes scoring below 0.7, ordered by how productive they would be to explore next. Nodes are not excluded for being disagreed with, only for being settled or rejected with understanding.

### Scoring rubric

| Score | Meaning |
|---|---|
| 0.0 | Not engaged at all |
| 0.1–0.3 | Briefly mentioned or tangentially touched |
| 0.4–0.6 | Partially engaged |
| 0.7–0.9 | Substantially engaged, clear position with awareness of tensions |
| 1.0 | Deeply engaged, robust and nuanced |

A node counts as **engaged** at 0.4 or above.

### Score damping

For a node whose disposition before the turn was settled or rejected with understanding, a lower new score can reduce the stored score by at most **0.10** per turn (`DOWNGRADE_CAP`). Increases apply at once. This absorbs single-turn evaluator noise while letting sustained regression show over a few turns. Nodes that are active or dismissed move freely.

### If the evaluator's reply cannot be parsed

Scores are left as they were, and the frontier falls back to the two unengaged nodes with the greatest total outgoing edge weight (`most_destabilizing_unengaged`).

---

## 10. Dispositions

Each node has a disposition, separate from its score. A user can reject an argument while fully understanding it.

| Disposition | Meaning |
|---|---|
| `active` | Not yet raised, or no clear response |
| `dismissed` | Brushed off without showing understanding of why the point might challenge their view |
| `settled` | Substantively engaged, clear position taken, conversation moved on |
| `rejected_understood` | Rejected, but with demonstrated understanding of the argument's force |

The evaluator is told to be conservative with `rejected_understood`: could the user explain to a third party why someone might find the argument compelling?

**Dispositions never move backwards.** The order is `active` < `dismissed` < `settled` / `rejected_understood`. A later evaluation cannot lower a node's rank.

---

## 11. Equilibrium score

**File:** `ic_engine.py` -> `ICShard.equilibrium_score()`

```
node_weight(N)  = 1.0 + sum(weight of each incoming edge to N)
contribution(N) = 1.0                  if disposition(N) is settled or rejected_understood
                                       and engagement_score(N) >= 0.75
                = engagement_score(N)  otherwise
equilibrium     = sum(node_weight(N) * contribution(N)) / sum(node_weight(N))
```

- A resolved node counts as fully in equilibrium, because equilibrium is about the judgment being stable under that node's question, not about depth of engagement. The evaluator reserves 1.0 for unusually deep engagement, so without this rule a fully resolved inquiry would stop in the low 90s.
- The 0.75 floor (`RESOLVED_SCORE_THRESHOLD`) matters because dispositions never move backwards: a resolved node whose score later falls below the floor goes back to contributing its raw score.
- Nodes with more incoming edges count more heavily.

---

### How nodes are displayed

**File:** `app.py` -> `_nodes_info()`, `_next_up()`; `static/app.js` -> `renderNodeMap()`

The web app's shard map and the voice device's rotating display follow the same rules, computed on the server.

| State | Rule | Web app | Device |
|---|---|---|---|
| Resolved | Display score of 0.85 or more. The display score is the node's contribution to the equilibrium score, so a settled or rejected-with-understanding node scoring at least 0.75 counts as 1.0 | Green dot | Green |
| In progress | Display score above 0 | Gold dot, brighter with score | Depth colour (red, cyan, amber or violet), brighter with score |
| Not started | Score of 0 | Empty dot | Dim |
| Next in line | The first two unresolved nodes of the frontier (`NEXT_UP_MARKS`) | Pulsing purple ring | Pulsing |

The percentage beside each node in the web app is the display score, so a resolved node shows 100%. The "Resolved" figure in the sidebar counts resolved nodes. Achievements still use the engaged threshold of 0.4 (section 13).

---

## 12. End-of-inquiry stages

Three stages, each replacing the one before. At most one block is added to the system prompt.

| Stage | Active when | Effect on the assistant |
|---|---|---|
| Closing mode | Score reaches 85%; stays on down to 80%; off at 100% | Lays out each remaining issue directly in 2–4 sentences, then one direct question. Up to 6–7 sentences per turn |
| Graceful closing | Score at least 90% and every node settled or rejected with understanding | May state its own view, summarise, and accept a natural end. Asks a further question only for a specific tension not yet raised |
| Inquiry complete | Score at 100% | Delivers a closing with pointers for further thought, then stops probing |

### Closing mode

**File:** `ic_engine.py` -> `closing_mode_info()`, `_closing_mode_block()`

The 85% / 80% band prevents the mode switching on and off when evaluator noise moves the score around the threshold. The previous turn's state is stored in the session as `closing_mode_active`. Closing mode overrides the turn-length and pacing rules but keeps the rules against declaring the view settled or signalling a wind-down.

### Graceful closing

**File:** `ic_engine.py` -> `_graceful_completion_active()`, `_graceful_completion_block()`

Replaces the closing-mode block. It suspends the rules about being puzzled, never having answers and never winding down. It names withholding a view as the failure to avoid at this stage.

### Inquiry complete

**File:** `ic_engine.py` -> `inquiry_complete()`, `_inquiry_complete_block()`; `app.py` -> `_generate_closing()`

**Web chat: follow-up closing.** Because scoring runs after the reply, the reply on the turn that reaches 100% is an ordinary one. When the evaluation then reports 100%, and the session was not already complete before the turn:

1. The eval line carries `closing_pending: true`, and the browser shows the celebration overlay.
2. The server generates a closing (output limit 500 tokens) and sends it as a third line.
3. The browser adds it to the chat when the overlay is dismissed, after any reply still being read aloud has finished.

The closing states that the inquiry has reached equilibrium, summarises where the user landed in their own terms, and offers 2–3 pointers for further thought. It asks no question. Pointer candidates are the three nodes with the lowest engagement scores plus up to two nodes rejected with understanding; the central question is excluded.

Closing checks the conversation revision and originating evaluation generation before starting and before saving. A replacement history of the same length cannot pass these checks. New turns and rewinds wait for a closing already being generated; a closing queued after a newer turn or rewind is discarded. A deleted session is never restored by pending closing work.

**Fallback: closing as the next reply.** If no closing was delivered (generation failed, the browser disconnected before it started, or a voice device path), the inquiry-complete block in the system prompt makes the next reply the closing. On later turns the assistant does not repeat the closing or reopen the inquiry, but engages directly if the user asks to go deeper.

### Celebration overlay

**File:** `static/app.js` -> `showCelebration()`

Shown once per chat when the score reaches 100%. A progress ring, confetti, the central question, four figures (questions resolved, turns, level, XP), a short explanation, and a button that reads "Read your closing reflections" once the closing has arrived. The user can leave early; the chat then shows the thinking indicator until the closing arrives. Animation is skipped when the system's reduced-motion setting is on.

---

## 13. Gamification

**File:** `app.py` -> `compute_gamification()`

```
XP    = sum(engagement_score * 100) across all nodes   (raw scores)
Level = floor(equilibrium_score * 10) + 1              (limited to 1–10)
```

XP uses raw engagement scores, so it is not affected by the resolved-node rule. Level uses the equilibrium score, so it is.

| ID | Name | Unlock condition |
|---|---|---|
| `first_question` | First Inquiry | 1 node engaged (score at least 0.4) |
| `five_nodes` | Questioner | 5 nodes engaged |
| `ten_nodes` | Deep Thinker | 10 nodes engaged |
| `all_nodes` | Philosopher | Every node in the shard engaged |
| `half_equilibrium` | Seeking Balance | Equilibrium score at least 50% |
| `high_equilibrium` | Approaching Wisdom | Equilibrium score at least 75% |
| `full_equilibrium` | Erotetic Equilibrium | Equilibrium score at least 95% |
| `deep_engagement` | Depth Charge | Any node scoring 0.9 or more |
| `cross_link` | Web Weaver | Both ends engaged on at least 2 cross-edges |

The `full_equilibrium` achievement unlocks at 95%, while the celebration and the closing happen at 100%.

---

## 14. Rewind

**Endpoint:** `POST /api/chat/{session_id}/rewind`

Truncates the conversation to a chosen message, resets every node's score, disposition and raise count, and re-runs the evaluation on what remains. The closing-mode flag is reset so that it re-establishes from the new score.

Rewind holds the turn and state locks while computing its replacement state, and advances the persisted revision and evaluation generation. Older background evaluations are discarded even if they finish after rewind releases those locks.

---

## 15. Voice

### Defaults

Voice input, voice output (auto-read) and expressive mode are all **on by default**. Voice output needs only `OPENAI_API_KEY`; with `ELEVENLABS_API_KEY` and a usable voice it uses ElevenLabs instead. A choice made with the buttons holds until the page is reloaded, except that the Continue button on the home screen switches all three on. Leaving a chat stops the microphone and any speech.

### Voice output

**Endpoint:** `POST /api/tts`, streamed as MP3. **Files:** `app.py` -> `_resolve_tts_provider()`, `_open_elevenlabs_speech()`, `_open_openai_speech()`.

Two voice services can speak, chosen once at startup and reported in the Terminal (`[TTS] Using ...`) and by `GET /api/tts/enabled`:

| Service | When | Model |
|---|---|---|
| ElevenLabs | `ELEVENLABS_API_KEY` is set and `GET /v1/voices/{ELEVENLABS_VOICE_ID}` answers 200, so the account can use the voice | `eleven_v3`, with `TTS_SEED` |
| OpenAI | Otherwise, or after an ElevenLabs request fails (the switch is permanent until restart) | `OPENAI_TTS_MODEL` with `OPENAI_TTS_VOICE`; `OPENAI_TTS_BASE_INSTRUCTIONS` describes the manner of speaking |

`TTS_PROVIDER` overrides the choice. If the check is inconclusive, because the ElevenLabs key is limited to text-to-speech and cannot list voices, or because there is no network, ElevenLabs is tried first and OpenAI takes over on the first failed request; any ElevenLabs emotion tags already in that reply are stripped before it is spoken. Both services are opened before the response starts, so a refused request is an HTTP error to the browser rather than a truncated stream.

| Step | What happens |
|---|---|
| Expressive mode | If on, the reply is first sent to `POST /api/tts/emotionalize` with the recent conversation as context. With ElevenLabs it comes back wrapped in v3 emotion tags. With the OpenAI voice, which takes no inline tags, it comes back unchanged with a delivery instruction (emotion, tone, pacing, at most 60 words) that `/api/tts` appends to the base instructions. Skipped for the welcome message |
| Spoken-text preparation | `_speech_text()` removes markdown emphasis markers and applies `SPEECH_RESPELLINGS`. Affects spoken text only, never what is displayed |
| Seed | Every ElevenLabs request carries `TTS_SEED`, asking for the same rendering of the same text each time (best effort). OpenAI has no seed |
| Length | Text over 5000 characters (ElevenLabs) or 4096 (OpenAI) is cut |
| Raw audio | An `output_format` of `pcm_...` returns 16-bit mono PCM: at the requested rate from ElevenLabs, always 24 kHz from OpenAI |

**Pronunciation of "shard".** The voice tended to say "sherd". `SPEECH_RESPELLINGS` currently maps `shard` to `shard,`: the word is kept and a comma is added after it when another word follows, which adds a slight pause. The voice model varies between requests, so this is not fully reliable.

### Voice input

The browser invokes `SpeechRecognition` and places transcripts continuously in the input box. This does not call Inquiry Chat's `/api/stt` endpoint, but it does **not** imply local processing: browsers such as Chrome can send microphone audio to their speech-recognition provider, including speech the user never submits to the chat. The app does not set `processLocally` or guarantee offline recognition. [MDN documents the browser-managed service](https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition).

The microphone is enabled by default, subject to browser permission. Sending a message aborts recognition while the reply is pending; it restarts only if it was enabled, the user has not switched it off, and the same chat input remains open. Turning the microphone off or leaving the chat aborts the current recognition instance. Instance and generation guards reject late start, result, error and end callbacks, so they cannot restart capture or populate another chat. Stopping recognition cannot undo audio already transmitted. The microphone button and composer explain this behavior; users can also revoke the site's microphone permission. Reload and Continue retain the default/enabling behavior described above.

Recognition support and service behavior depend on the browser; Chrome and Edge support the API, while Safari support varies and can depend on macOS Dictation. Recognition errors are written to the browser console; an error switches voice input off until the user enables it again.

`POST /api/stt` offers server-side transcription with `TRANSCRIBE_MODEL`. The browser interface does not use it; the device path does its own transcription with the same model.

---

## 16. Voice device path

The voice device is PhilosophyPod, an ESP32 handheld whose firmware and setup instructions are in `PhilosophyPod/`. It can reach the chat by two routes:

| Route | How it works | Ports |
|---|---|---|
| Built in | The device connects straight to `app.py`. Described in the rest of this section | 8000 |
| Bridge | The device connects to `PhilosophyPod/bridge_server.py`, which calls the web endpoints `/api/stt`, `/api/chat/{id}` and `/api/tts` | 8001 and 8002, plus 8000 for the chat |

Which route is used depends on the server address the device contacts on boot. An address saved on the device (set by `PhilosophyPod/provision.py`, which the launcher can run) takes priority; otherwise the firmware's built-in default applies (`CONFIG_OTA_URL`), which in the template `sdkconfig.board.example` points to port 8000, the built-in route.

Because the bridge calls the web chat endpoint, a turn through the bridge follows section 6, steering reminder included, and not the simpler device logic below. Three things differ from the browser: the bridge speaks its own welcome wording for a new conversation; on the turn that reaches 100% the device speaks the reply and then the closing in one speaking turn, with no celebration screen in between; and the bridge does not send the node map, so the device's rotating display stays empty on this route.

### Built-in route

**Endpoints:** WebSocket `/xiaozhi/ws`, and `/xiaozhi/ota/...` for device setup. Requires the optional packages in `requirements-device.txt`, native Opus and `ffmpeg`. A missing codec produces a device setup error while web chat remains available.

A hardware voice client first calls `/xiaozhi/ota/...`, which tells it the WebSocket address to use and handles activation. It then connects to `/xiaozhi/ws`, presenting the device token if it has one; the server refuses it if `DEVICE_TOKEN` is set and the token is missing or wrong (section 2, "Access"). It works in the most recently updated session, looked up afresh on every turn, so a conversation started in the browser after the device connected is picked up. If there is no session at all, the device says so aloud and asks the user to start one in the browser. Each utterance goes through transcription, the chat call and text-to-speech, with audio streamed back as Opus frames. Evaluation runs in the background as in the web chat.

**Node map.** The device draws the shard as nodes on a rotating capsule. The server sends the map as an `ic_state` message: one entry per node with its depth in the graph (`d`), position (`p`, `t`), score (`s`) and whether it is next in line (`f`). Only the first two unresolved nodes of the frontier are marked, since the full frontier lists every unresolved node and early in a chat that is nearly all of them. It is sent when the device connects, after each evaluation, and when the device moves to a different conversation. A resolved node is sent with score 1.0, as it counts in the equilibrium score; the device draws nodes scoring 0.85 or more in green and makes frontier nodes pulse. The device shows at most 32 nodes. The firmware colours unresolved nodes by depth: red, cyan, amber, then violet for depth 3 and deeper. Green is used only for resolved nodes. Positions are computed in `_compute_ic_state()`.

If the device disconnects while a turn is being processed, the turn is still completed and saved, and the reply is queued to be spoken when the device next connects.

Live and post-disconnect device turns both use `_device_chat_turn()`, which shares the browser's per-session turn lock and revision checks. Transcription and audio playback happen outside that lock. The firmware and its message formats are unchanged.

Differences from the web chat:

| Aspect | Device path |
|---|---|
| History sent to the model | System prompt plus the last 20 messages, with no earlier-topics summary |
| Steering reminder | Not used |
| Reply length | Fixed at 300 tokens |
| Closing at 100% | Delivered as the next reply (the fallback in section 12), not as a follow-up message |
| On resume | When the device asks to resume, it speaks, in order of preference: a queued reply that was not delivered before a disconnect, the last assistant message, or the welcome message if the chat is empty |

Spoken-text preparation and the fixed seed apply here too.

---

## 17. API endpoints

| Method and path | Purpose |
|---|---|
| `GET /` | The web page |
| `GET /api/csrf` | Noncached authorization token for browser and native API clients; send as `X-Inquiry-CSRF` on unsafe requests |
| `GET /api/shards` | Shard list: path, name, title, source, central question, node and edge counts, whether context documents exist |
| `GET /api/sessions` | Session list, newest first |
| `POST /api/sessions/new` | Start a session on a shard, with an optional central question |
| `GET /api/sessions/{id}` | Full session, plus nodes, edges, recomputed score and welcome message |
| `DELETE /api/sessions/{id}` | Delete a session |
| `POST /api/chat/{id}` | One turn; streamed reply, evaluation and optional closing |
| `POST /api/chat/{id}/rewind` | Rewind to an earlier message |
| `GET /api/tts/enabled` | Whether voice output is available, and which voice service is in use |
| `POST /api/tts` | Text to speech, from ElevenLabs or the OpenAI voice |
| `POST /api/tts/emotionalize` | Decide how a reply is spoken: emotion tags (ElevenLabs) or a delivery instruction (OpenAI voice) |
| `POST /api/stt` | Server-side transcription |
| `WS /xiaozhi/ws` | Voice device connection. Refuses web pages and, from the network, requires the device token if one is set (section 2, "Access") |
| `GET` or `POST /xiaozhi/ota/{path}` | Voice device setup: returns the WebSocket address and handles activation. Open to the network |
| `GET /static/...` | The browser interface's files |
