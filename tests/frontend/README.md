# Frontend regression fixtures

Start the isolated preview server from the project root:

```sh
python3 tests/frontend/preview_server.py --port 8766
```

Open `http://127.0.0.1:8766/runner.html` to run the browser integration checks.
The page displays each result and keeps the real frontend visible in a frame.
Refresh to repeat. It tests production `static/app.js` and `static/style.css`.

For visual checks, open `http://127.0.0.1:8766/fixture?scene=chat`. The fixture
switcher offers mixed question states, landing, long content, unavailable voice,
and completion. Add `&toolbar=0` to hide the fixture switcher for screenshots.
The `scene=mill` preview uses a synthetic conversation about Mill’s harm
principle, with mixed node states. It is labeled as synthetic and contains no
real saved-session content.

To compare with a saved pre-edit JavaScript file, start the server with
`--baseline /absolute/path/to/app.js` and open `/runner.html?baseline=1`.
Both versions use the current stylesheet; this comparison checks behavior.

The server binds only to `127.0.0.1` and serves an explicit frontend allowlist.
It never imports `app.py`, opens `env`, reads saved sessions, or calls a model.
All API responses and changes live in each browser frame's memory. Microphone
and audio are doubles, so speech recognition and real playback quality require
a separate manual check in the live app. Streamed chat responses are mocked
NDJSON chunks that exercise the real parsing and rendering code.

These checks cover existing frontend contracts rather than backend scoring or
real provider behavior: node states and display scores, welcome/saved message
indices, shard selection and session navigation, voice toggles, send/hold/touch/keyboard events,
streamed reply and evaluation, errors, rewind, achievement, and closing states.

The 39-check suite also verifies the microphone privacy disclosure, cancellation
during startup and a pending reply, rejection of stale recognition callbacks,
and ordinary silence restart. These lifecycle checks use deterministic speech
doubles and do not record audio or contact a speech service.

It verifies the single-row header has no Conversation or
Inquiry map links. On narrow screens, ordinary page scrolling reaches the map
below the conversation and returns to the composer without replacing either
region or losing a draft. It checks desktop map scrolling with persistent
metrics, short screens, and Exit → Resume resetting the reading position. The
frontend's only additional navigation-related helper resets the scroll position
when entering a screen and clears obsolete workspace fragments; there is no
separate map page or section-selection handler.
