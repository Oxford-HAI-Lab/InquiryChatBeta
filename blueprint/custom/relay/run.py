#!/usr/bin/env python3
"""Custom node `relay`: the user's ops, the Model nodes' results and every record
of the Database node `session` pass here. It makes no decision about the
conversation; it carries values across what the Database cannot cross by itself.

- Model results. The Model nodes' answers (`@@OP REPLY|EVAL|CLOSING`) come here
  too, so they are kept on file like the user's ops and never asked for twice.
- Epochs. A STEP record names the next phase of the turn in its `next` field.
  That value is emitted on its own (`{"event": "emit"}`), which the engine
  queues as a new epoch, so each Model call has an epoch (and the engine's
  600 s epoch limit) of its own.
- Reinstalls. The engine recovers from a failed epoch by reinstalling the
  graph, which empties the Database. A record's `checkpoint` field is saved
  and removed from the record; a LOST record (the Database found itself empty)
  is answered with `@@OP RESTORE` and the saved checkpoint.
- The firing after a reinstall. The Database's first firing after a recovery
  aborts (its old session is still registered), which would drop the user's
  message. An op is kept on file until a Database record answers it; if this
  daemon starts (it is restarted on every reinstall) with an op still on file,
  the op is emitted again as a new epoch, up to ten times (a busy machine can
  make the Database's container miss its start time several times running).
- A failed phase. The phase named by the last `next` is kept on file until its
  Model's result comes (or a record that ends the turn). If this daemon starts
  with one still on file, its epoch failed. If the Database had not yet started
  the phase's Model, the phase is sent again like an op; if it had, the Model
  call errored or ran out of time, and that is reported to the Database as
  `@@OP FAILED`, so the turn ends as the original's does.

Every other value is passed through unchanged. Files live in `state/` beside
this script (gitignored).
"""
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).parent / "state"
HERE.mkdir(exist_ok=True)
SAVED, HELD, REPLAYED, TRIES = (HERE / f for f in ("checkpoint.json", "held-op.txt", "replayed-op.txt", "tries.txt"))
PHASE, STARTED = HERE / "pending-phase.txt", HERE / "phase-started.txt"


def say(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


if PHASE.exists() and not (STARTED.exists() or HELD.exists() or REPLAYED.exists()):
    HELD.write_text(PHASE.read_text())  # the phase never reached its Model: send it again
if HELD.exists():  # restarted with an unanswered op: send it again
    HELD.replace(REPLAYED)
    TRIES.write_text("0")
tries = int(TRIES.read_text()) if TRIES.exists() else 0
if REPLAYED.exists() and tries < 10:
    TRIES.write_text(str(tries + 1))
    say({"event": "emit", "output": REPLAYED.read_text()})
elif PHASE.exists():  # restarted with an unanswered phase: report it, as an op kept on file
    HELD.write_text("@@OP FAILED\n" + PHASE.read_text())
    PHASE.unlink()
    STARTED.unlink(missing_ok=True)
    say({"event": "emit", "output": HELD.read_text()})

for line in sys.stdin:
    try:
        request = json.loads(line)
    except ValueError:
        continue
    if "input" not in request:  # a face message, not a wire value
        continue
    text = request["input"]
    if text.startswith("@@OP "):  # a user op or a Model's result: it answers the phase
        HELD.write_text(text)
        for f in (PHASE, STARTED):
            f.unlink(missing_ok=True)
    elif text.startswith("@@KIND ") and not text.startswith("@@KIND LOST\n"):  # LOST: RESTORE answers
        for f in (HELD, REPLAYED):
            f.unlink(missing_ok=True)
        if text.startswith(("@@KIND CALL ", "@@KIND EVAL\n", "@@KIND CLOSE\n")):  # a Model starts
            STARTED.touch()
        else:
            for f in (PHASE, STARTED):
                f.unlink(missing_ok=True)
    if text.startswith("@@KIND LOST\n"):
        text = "@@OP RESTORE\n" + (SAVED.read_text() if SAVED.exists() else "")
    checkpoint = re.search(r"\n@@F checkpoint\n(.*)\n@@E checkpoint\n\Z", text)
    if checkpoint:
        SAVED.write_text(checkpoint.group(1))
        text = text[:checkpoint.start()]
    nxt = re.search(r"@@F next\n(.*?)\n@@E next\n", text)
    if nxt:
        PHASE.write_text(nxt.group(1))
        STARTED.unlink(missing_ok=True)
        say({"event": "emit", "output": nxt.group(1)})
    say({"ok": True, "output": text})
