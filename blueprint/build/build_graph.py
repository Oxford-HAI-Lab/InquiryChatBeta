#!/usr/bin/env python3
"""Write projects/inquirychat/graphs/inquirychat.json, the Inquiry Chat port.

Run with the original's Python (it imports ic_engine to copy the prompt prose):
    .venv/bin/python3 blueprint/build/build_graph.py [API_BASE NAME [MODEL]]
The Go node `shard` carries every shard the original lists (Shards/ and the repo root),
with their full context documents. With SHARD=<path> in the environment it carries that
one shard and starts a session on it when fired (blueprint/shard/ holds a trimmed copy of
the Mill shard that fits a window of 8,192 tokens).
Template texts come from the original's functions, called with sentinel values;
the script asserts each sentinel lands once, so a change upstream fails here.
Steering and follow-up texts are inline in app.py, so they are copied and
checked as substrings of app.py.
"""
import json
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
BP = HERE.parent
REPO = BP.parent
sys.path.insert(0, str(REPO))
# graph.py, the graph builder, comes with the engine checkout (the same default as bin/serve).
ENGINE = os.environ.get("BLUEPRINT_ENGINE") or str(REPO.parent / "blueprint-beta")
if not os.path.isfile(os.path.join(ENGINE, "skills/blueprint/scripts/graph.py")):
    sys.exit("set BLUEPRINT_ENGINE to your blueprint-beta checkout: no skills/blueprint/scripts/graph.py under " + ENGINE)
sys.path.insert(0, os.path.join(ENGINE, "skills/blueprint/scripts"))
import ic_engine as ic  # noqa: E402
from graph import Graph, branch, custom, database, go, model, panel, template  # noqa: E402

# `build_graph.py [API_BASE NAME [MODEL]]`: the same graph for another model server, saved under NAME.
API_BASE, NAME, MODEL_NAME = (sys.argv[1:] + [None] * 3)[:3] if len(sys.argv) > 2 else (None, None, None)
API_BASE, NAME = API_BASE or "http://localhost:1235/v1", NAME or "inquirychat"
MODEL = dict(model=MODEL_NAME or "bonsai2-27b", api_base=API_BASE, max_tokens=2048)
APP = (REPO / "app.py").read_text()


def once(text, old, new):
    assert text.count(old) == 1, (old[:60], text.count(old))
    return text.replace(old, new)


APP_JOINED = re.sub(r'"\s*\n\s*(\+\s*)?"', "", APP)  # adjacent string literals joined


def from_app(s):
    """A literal copied from app.py; assert it is still there verbatim."""
    assert s in APP_JOINED or s.replace('"', '\\"') in APP_JOINED, s[:60]
    return s


# --- prose from the original -------------------------------------------------
C = "\x01CENTRAL\x01"
fake = ic.ICShard(central_question=C)
TAIL = ("Current inquiry complex status:\n\n\n"
        "The most productive questions to explore next (YOU MUST steer toward these):\n\n")
sp = ic.build_chat_system_prompt(fake, [])
assert sp.endswith(TAIL)
SYSTEM = once(sp[:-len(TAIL)], C, "{central}") + (
    "Current inquiry complex status:\n{status}\n\n"
    "The most productive questions to explore next (YOU MUST steer toward these):\n{frontier}\n{stage}")
CLOSING_BLOCK = ic._closing_mode_block()
GRACEFUL_BLOCK = ic._graceful_completion_block()
COMPLETE_BLOCK = once(ic._inquiry_complete_block(fake), "Candidates:\n\n\nThen end", "Candidates:\n{candidates}\n\nThen end")

U = "\x02CONV\x02"
ep = ic.build_evaluation_prompt(fake, [{"role": "user", "content": U}])
FORMAT_AT = ep.index("Respond ONLY with valid JSON in this format:\n") + len("Respond ONLY with valid JSON in this format:\n")
EVAL_FORMAT = ep[FORMAT_AT:]
EVAL = ep[:FORMAT_AT] + "{format}"
EVAL = once(EVAL, '"' + C + '"', '"{central}"')
EVAL = once(EVAL, "Nodes:\n\n\nRecent conversation:", "Nodes:\n{nodes}\n\nRecent conversation:")
EVAL = once(EVAL, "User: " + U + "\n\n", "{conv}")

wq = "\x03Q\x03?"
WELCOME = ic.welcome_message(ic.ICShard(central_question=wq, source_brief="\x04O\x04"), "")
WELCOME = once(once(WELCOME, "\x04O\x04", "{origin}"), '**"' + wq + '"**', '**"{central}"**{end}')

STEER_COMPLETE = from_app(
    "REMINDER — The inquiry has reached full equilibrium. Follow the INQUIRY COMPLETE "
    "instructions: close the conversation with a summary and pointers for further "
    "thought (or, if you already did, reply briefly). Do NOT probe, do NOT introduce "
    "new challenges, and do NOT end with a question.")
STEER_FRESH = from_app(
    "REMINDER — Do NOT repeat questions you already asked. "
    "Your NEXT response must introduce a NEW angle the user has NOT yet addressed: ") + "{targets}" + from_app(
    ". If the user says you're repeating yourself, acknowledge it and move to a genuinely different topic.") + "{off}"
STEER_REVISIT = from_app(
    "REMINDER — You already raised these topics recently but the user hasn't fully grappled with them. "
    "Do NOT re-ask the same question. Instead, find a NEW concrete example or scenario that forces "
    "the user to confront a specific tension in their stated position: ") + "{targets}{off}"
STEER_NONE = from_app(
    "REMINDER — Do NOT wrap up or ask what the user wants to explore. "
    "Continue probing their position with concrete challenges.") + "{off}"
OFF = from_app(" OFF LIMITS — Do NOT raise these topics again, the user has already engaged with or "
               "understood and rejected them: ") + "{names}."
# Holding the send button asks for a longer reply (app._chat_turn, detail_level above 1.5).
DETAIL = re.search(r'detail_instruction = \(\s*"([^"]*)"\s*\)', APP_JOINED).group(1).replace("\\n", "\n")
assert DETAIL.startswith("\n\nRESPONSE STYLE OVERRIDE") and not set("\\{}") & set(DETAIL)
EARLIER = from_app("[Earlier we discussed these topics (do NOT re-ask these unless deepening significantly): ")
EARLIER = "Assistant: " + EARLIER + "{topics}]\n\n"
FOLLOWUP = from_app(
    "The inquiry reached full equilibrium with the user's last message. Write the closing "
    "now, as a follow-up message that will appear directly after your previous message. "
    "Skip part 1 of the closing: you have already responded to the user. Open by marking "
    "that the inquiry has reached equilibrium, then give the summary and the pointers for "
    "further thought. If your previous message ended with a question, do not repeat it or "
    "press for an answer; you may note in one clause that it can stand as something to "
    "keep thinking about. Do NOT ask a question.")
for t in (SYSTEM, CLOSING_BLOCK, GRACEFUL_BLOCK, COMPLETE_BLOCK, EVAL, WELCOME):
    stripped = t
    for name in ("central", "status", "frontier", "stage", "candidates", "nodes", "conv", "format",
                 "origin", "end"):
        stripped = stripped.replace("{%s}" % name, "")
    assert "{" not in stripped and "}" not in stripped, "literal brace in a Template"

# --- the shard payload ---------------------------------------------------------
def payload(path):
    shard = json.loads(path.read_text())
    for n in shard["nodes"]:
        p = path.parent / "contexts" / f"{n['id']}.md"
        n.update({"parent": n.get("parent"), "notes": n.get("notes", ""), "context": p.read_text() if p.is_file() else ""})
    shard["edges"] = [{"from": e["from"], "to": e["to"], "weight": e.get("weight", 0.5), "comment": e.get("comment", "")}
                      for e in shard["edges"]]
    shard.update(eval_format=EVAL_FORMAT, dir=str(path.relative_to(REPO)), title=shard.get("title") or path.stem)
    return shard


def listed():  # app.get_shards: every shard file under Shards/ and in the repo root
    for p in sorted((REPO / "Shards").rglob("*.json")) + sorted(REPO.glob("*.json")):
        if any(x.startswith(".") for x in p.relative_to(REPO).parts[:-1]):
            continue
        try:
            d = json.loads(p.read_text())
        except ValueError:
            continue
        if isinstance(d, dict) and all(k in d for k in ("central", "nodes", "edges")):
            yield p


if os.environ.get("SHARD"):
    SHARD_PAYLOAD = "@@OP SHARD\n" + json.dumps(payload(REPO / os.environ["SHARD"]))
else:
    SHARD_PAYLOAD = "@@OP LIBRARY\n" + json.dumps({"shards": [payload(p) for p in listed()]})

# --- the graph -------------------------------------------------------------------
# The panel window: wide enough for the original's desktop layout (its narrow layout starts
# at 900 px).
PANEL_W, PANEL_H = 1280, 800
g = Graph()
faults = []          # (node, port) arms that should never fire; all join Phi `faults`


def T(name, text, x, y):
    return g.node("function", name, template(text), x, y)


def B(name, pattern, x, y):
    return g.node("control", name, branch(pattern), x, y)


def extract(src, src_port, field, sink, sink_port, x, y):
    """A Branch that emits one field of a record; its Fail arm is a fault."""
    b = B("field " + field, r"(?<=@@F %s\n)[\s\S]*?(?=\n@@E %s\n)" % (field, field), x, y)
    g.wire(src, b, src_port, "")
    g.wire(b, sink, "Match", sink_port)
    faults.append((b, "Fail"))
    return b


def chain(src, src_port, routes, x, y):
    """Branch chain: routes is [(name, pattern, on_match)]; on_match(node) wires the Match arm.
    The last route's Fail arm is a fault."""
    for i, (name, pattern, on_match) in enumerate(routes):
        b = B(name, pattern, x + 200 * i, y + 60 * i)
        g.wire(src, b, src_port, "")
        on_match(b)
        src, src_port = b, "Fail"
    faults.append((src, "Fail"))


shard_go = g.node("io", "shard", go(SHARD_PAYLOAD), 0, 0)
chat = g.node("io", "chat", panel("panels/chat", [("state", "text"), ("welcome", "text")],
                                  [("user", "text"), ("op", "text")], PANEL_W, PANEL_H), -600, 300)
tag_user = T("tag user", "@@OP USER\n{message}", 0, 300)
into = g.node("phi", "into session", 4, 200, 150)
session = g.node("io", "session", database((HERE / "session_read.py").read_text(),
                                           (HERE / "session_write.py").read_text()), 400, 150)
g.wire(chat, tag_user, "user", "message")
g.wire(shard_go, into, "", "0")
g.wire(into, session)

# interlocutor turn
system = T("system prompt", SYSTEM, 1600, -400)
interlocutor = g.node("function", "interlocutor", model(**MODEL), 2000, -400)
turn = T("turn prompt", "{after}{earlier}{history}System: {steer}{detail}\n\nUser: {latest}", 1800, -200)
after = B("after system prompt", r"\A", 1800, -300)
tag_reply = T("tag reply", "@@OP REPLY\n{reply}", 2200, -400)
stage = g.node("phi", "stage block", 4, 1400, -500)
steer = g.node("phi", "steering reminder", 4, 1600, -100)
earlier = g.node("phi", "earlier topics", 2, 1600, 0)
off = g.node("phi", "off limits", 2, 1400, 0)
g.wire(system, interlocutor, "", "system")
g.wire(system, after)
g.wire(after, turn, "Match", "after")
faults.append((after, "Fail"))
g.wire(turn, interlocutor)
g.wire(interlocutor, tag_reply, "", "reply")
g.wire(stage, system, "", "stage")
g.wire(steer, turn, "", "steer")
g.wire(earlier, turn, "", "earlier")


def call_arm(b):
    for i, (f, sink, port) in enumerate([("central", system, "central"), ("status", system, "status"),
                                         ("frontier", system, "frontier"), ("history", turn, "history"),
                                         ("latest", turn, "latest")]):
        extract(b, "Match", f, sink, port, 1000, -700 + 60 * i)

    def complete(bb):
        blk = T("complete block", COMPLETE_BLOCK, 1300, -650)
        extract(bb, "Match", "candidates", blk, "candidates", 1200, -650)
        g.wire(blk, stage, "", "0")

    def const(text, slot, name):
        def wire(bb):
            t = T(name, "{e}" + text, 1300, -600 + 40 * slot)
            g.wire(bb, t, "Match", "e")
            g.wire(t, stage, "", str(slot))
        return wire

    head = r"\A@@KIND CALL "
    chain(b, "Match", [
        ("stage: complete?", head + r"STAGE=complete [\s\S]*", complete),
        ("stage: graceful?", r"\A(?=@@KIND CALL STAGE=graceful )", const(GRACEFUL_BLOCK, 1, "graceful block")),
        ("stage: closing?", r"\A(?=@@KIND CALL STAGE=closing )", const(CLOSING_BLOCK, 2, "closing block")),
        ("stage: none?", r"\A(?=@@KIND CALL STAGE=none )", lambda bb: g.wire(bb, stage, "Match", "3")),
    ], 1000, -500)

    def steer_targets(text, slot, name):
        def wire(bb):
            t = T(name, text, 1500, -150 + 40 * slot)
            extract(bb, "Match", "targets", t, "targets", 1400, -150 + 40 * slot)
            g.wire(off, t, "", "off")
            g.wire(t, steer, "", str(slot))
        return wire

    def steer_none(bb):
        t = T("steer: none", "{e}" + STEER_NONE, 1500, 0)
        g.wire(bb, t, "Match", "e")
        g.wire(off, t, "", "off")
        g.wire(t, steer, "", "3")

    def steer_complete(bb):
        t = T("steer: complete", "{e}" + STEER_COMPLETE, 1500, -200)
        g.wire(bb, t, "Match", "e")
        g.wire(t, steer, "", "0")

    line = r"\A@@KIND CALL [^\n]*"
    chain(b, "Match", [
        ("steer: complete?", r"\A(?=@@KIND CALL [^\n]*STEER=complete)", steer_complete),
        ("steer: fresh?", line + r"STEER=fresh[\s\S]*", steer_targets(STEER_FRESH, 1, "steer: fresh")),
        ("steer: revisit?", line + r"STEER=revisit[\s\S]*", steer_targets(STEER_REVISIT, 2, "steer: revisit")),
        ("steer: none?", r"\A(?=@@KIND CALL [^\n]*STEER=none)", steer_none),
    ], 1000, -200)

    def off_yes(bb):
        t = T("off limits sentence", OFF, 1300, 0)
        extract(bb, "Match", "offnames", t, "names", 1200, 0)
        g.wire(t, off, "", "0")

    chain(b, "Match", [
        ("off limits?", line + r"OFF=yes[\s\S]*", off_yes),
        ("no off limits?", r"\A(?=@@KIND CALL [^\n]*OFF=no)", lambda bb: g.wire(bb, off, "Match", "1")),
    ], 1000, 50)

    def earlier_yes(bb):
        t = T("earlier topics line", EARLIER, 1300, 100)
        extract(bb, "Match", "topics", t, "topics", 1200, 100)
        g.wire(t, earlier, "", "0")

    chain(b, "Match", [
        ("earlier topics?", line + r"EARLIER=yes[\s\S]*", earlier_yes),
        ("no earlier topics?", r"\A(?=@@KIND CALL [^\n]*EARLIER=no)", lambda bb: g.wire(bb, earlier, "Match", "1")),
    ], 1000, 150)


# evaluation
evaluation = T("evaluation prompt", EVAL, 1600, 400)
evaluator = g.node("function", "evaluator", model(**MODEL), 2000, 400)
tag_eval = T("tag eval", "@@OP EVAL\n{raw}", 2200, 400)
g.wire(evaluation, evaluator)
g.wire(evaluator, tag_eval, "", "raw")


def eval_arm(b):
    for i, f in enumerate(["central", "nodes", "conv", "format"]):
        extract(b, "Match", f, evaluation, f, 1200, 350 + 50 * i)


# follow-up closing
close_system = T("closing system prompt", SYSTEM, 1600, 700)
close_block = T("closing: complete block", COMPLETE_BLOCK, 1400, 650)
closer = g.node("function", "closing", model(**MODEL), 2000, 700)
close_prompt = T("closing prompt", "{after}{history}System: " + FOLLOWUP, 1800, 800)
close_after = B("after closing system prompt", r"\A", 1800, 750)
tag_closing = T("tag closing", "@@OP CLOSING\n{closing}", 2200, 700)
g.wire(close_block, close_system, "", "stage")
g.wire(close_system, closer, "", "system")
g.wire(close_system, close_after)
g.wire(close_after, close_prompt, "Match", "after")
faults.append((close_after, "Fail"))
g.wire(close_prompt, closer)
g.wire(closer, tag_closing, "", "closing")


def close_arm(b):
    for i, (f, sink, port) in enumerate([("central", close_system, "central"), ("status", close_system, "status"),
                                         ("frontier", close_system, "frontier"),
                                         ("candidates", close_block, "candidates"),
                                         ("history", close_prompt, "history")]):
        extract(b, "Match", f, sink, port, 1200, 650 + 50 * i)


# end of turn, welcome, exit
state_in = g.node("phi", "to panel state", 4, -200, 600)
exit_ = g.node("phi", "exit", 6, 600, 1000)
welcome = T("welcome", WELCOME, 1000, 1000)
g.wire(state_in, chat, "", "state")
g.wire(welcome, chat, "", "welcome")
g.wire(welcome, exit_, "", "1")


def done_arm(b):
    g.wire(b, state_in, "Match", "0")
    g.wire(b, exit_, "Match", "0")


def ready_arm(b):
    for i, f in enumerate(["origin", "central", "end"]):
        extract(b, "Match", f, welcome, f, 900, 950 + 40 * i)
    extract(b, "Match", "map", state_in, "1", 900, 1100)


# The user's ops, the Model nodes' results and every Database record pass the relay node
# (custom/relay/run.py). It emits a STEP record's `next` field as a new epoch (`@@OP PHASE`), so each Model call has
# an epoch of its own; it keeps the checkpoint and answers LOST with RESTORE; and it sends
# an op again (up to ten times) if the epoch carrying it failed before the Database answered,
# so a Model's answer is not lost when the Database's container fails to start in time.
relay = g.node("io", "relay", custom("relay"), 500, 0)
into_relay = g.node("phi", "into relay", 6, 300, 0)
g.wire(session, into_relay, "", "0")
g.wire(tag_user, into_relay, "", "1")
g.wire(chat, into_relay, "op", "2")  # the panel's own ops: start, resume, delete, list, rewind
for i, tag in enumerate((tag_reply, tag_eval, tag_closing)):
    g.wire(tag, into_relay, "", str(3 + i))
g.wire(into_relay, relay)
tag_phase = T("tag phase", "@@OP PHASE\n{x}", 200, 1300)
g.wire(tag_phase, into, "", "2")


def list_arm(b):  # the shards and sessions, for the panel's landing page
    g.wire(b, state_in, "Match", "3")
    g.wire(b, exit_, "Match", "5")


def restore_arm(b):
    g.wire(b, into, "Match", "3")


def step_arm(b):  # the turn record so far goes to the panel and the exit
    g.wire(extract(b, "Match", "record", state_in, "2", 900, 1300), exit_, "Match", "3")


def idle_arm(b):
    g.wire(b, exit_, "Match", "4")


chain(relay, "", [
    ("relayed phase?", r"\A(?:EVAL|CLOSE) \d+\Z", lambda bb: g.wire(bb, tag_phase, "Match", "x")),
    ("user op?", r"\A@@OP (?!RESTORE\n)[A-Z]+\n[\s\S]*", lambda b: g.wire(b, into, "Match", "1")),
    ("restore?", r"\A@@OP RESTORE\n[\s\S]*", restore_arm),
    ("kind: call?", r"\A@@KIND CALL [\s\S]*", call_arm),
    ("kind: step?", r"(?<=\A@@KIND STEP\n)[\s\S]*", step_arm),
    ("kind: idle?", r"\A@@KIND IDLE[\s\S]*", idle_arm),
    ("kind: eval?", r"\A@@KIND EVAL\n[\s\S]*", eval_arm),
    ("kind: close?", r"\A@@KIND CLOSE\n[\s\S]*", close_arm),
    ("kind: done?", r"(?<=\A@@KIND DONE\n)[\s\S]*", done_arm),
    ("kind: ready?", r"\A@@KIND READY\n[\s\S]*", ready_arm),
    ("kind: list?", r"(?<=\A@@KIND LIST\n)[\s\S]*", list_arm),
], 600, 150)

# The detail override joins the reminder in the turn prompt. Built after the routing chain, so
# the node numbers in the layout table below stay as they are.
detail = g.node("phi", "detail", 2, 1700, 100)
g.wire(detail, turn, "", "detail")


def detail_yes(bb):
    t = T("detail override", "{e}" + DETAIL, 1500, 100)
    g.wire(bb, t, "Match", "e")
    g.wire(t, detail, "", "0")


chain(next(n["id"] for n in g.nodes if n["node"]["data"].get("name") == "kind: call?"), "Match", [
    ("detail?", r"\A(?=@@KIND CALL [^\n]*DETAIL=yes)", detail_yes),
    ("no detail?", r"\A(?=@@KIND CALL [^\n]*DETAIL=no)", lambda bb: g.wire(bb, detail, "Match", "1")),
], 1300, 100)

fault_phi = g.node("phi", "faults", len(faults), 400, 1100)
for i, (node, port) in enumerate(faults):
    g.wire(node, fault_phi, port, str(i))
fault = T("fault", "@@FAULT\n{x}", 500, 1100)
g.wire(fault_phi, fault, "", "x")
g.wire(fault, exit_, "", "2")

for n in g.nodes:  # draw the wired `system` sinks on the canvas (lint: wire.dangling_endpoint otherwise)
    if n["id"] in (interlocutor, closer):
        n["node"]["exposed_optional"] = [{"direction": "sink", "branch": None, "name": "system"}]

# --- layout and function sets --------------------------------------------------
# Each function set lists its nodes as (id, name, column, row); this table places
# every node, so the x, y given above are overwritten. Columns, left to right: the
# chat panel (Pc), the session and relay loop (Ac, Bc, Cc), the record routing chain (Sc),
# then each phase of a turn as a band of rows: chain branches (1), field extractors
# (2), constant Templates (3), joining Phis (4), prompts (5), Model calls (6) and the
# ops back to the session (7), which run along the top. The reply band is on top,
# the evaluation below it, then the closing; the end of a turn sits by the panel.
# The editor shows the sets with key 4.
CW, RH = 460, 120
# One more row of space above each stacked set: its caption is drawn at the set's top
# left corner and would otherwise sit on the name labels of the set above.
GAPS = (2.5, 7.5, 13.9, 15.5, 17.4, 22.5)
Pc, Ac, Bc, Cc, Sc = -4.2, -3, -2, -1, 0
SETS = [
    ("Chat panel", "Shows the original app's pages (the shards and sessions, the conversation and the progress map), sends each message the user writes as a USER op, and sends its own ops: start, resume, delete, list and rewind.",
     [(chat, "chat", Pc, 24.3), (tag_user, "tag user", Ac, 22)]),
    ("Session store", "Holds the whole conversation state; firing the shard starts a fresh session, and every reply, score and closing comes back here as an op, by way of the relay.",
     [(shard_go, "shard", Ac, -1.5), (into, "into session", Bc, -1.5), (session, "session", Bc, 0)]),
    ("Phase relay", "Passes every op, Model result and record through the relay, which keeps each until the Database answers it, which starts the evaluation and the closing as epochs of their own and restores the session after a failed epoch.",
     [(into_relay, "into relay", Bc, 1.5), (relay, "relay", Cc, 1.5), (30, "relayed phase?", Sc, 1.5),
      (tag_phase, "tag phase", Cc, 0)]),
    ("Record routing", "Sends each session record down the arm for its kind: a reply call, a step, an evaluation, a closing, the end of a turn, the welcome or the list of shards and sessions.",
     [(31, "user op?", Sc, 2.5), (32, "restore?", Sc, 3.5), (33, "kind: call?", Sc, 5), (65, "kind: step?", Sc, 16),
      (67, "kind: idle?", Sc, 17), (68, "kind: eval?", Sc, 19.5), (73, "kind: close?", Sc, 24.5),
      (79, "kind: done?", Sc, 25.5), (80, "kind: ready?", Sc, 26.5),
      (85, "kind: list?", Sc, 27.5)]),
    ("System prompt", "Fills the interlocutor's system prompt with the central question, the status of each question and the frontier, before the turn prompt may go.",
     [(34, "field central", 2, 0), (35, "field status", 2, 1), (36, "field frontier", 2, 2), (system, "system prompt", 5, 2),
      (after, "after system prompt", 5, 5)]),
    ("Stage block", "Adds the block for the stage the inquiry has reached: complete, graceful closing, closing mode or none.",
     [(39, "stage: complete?", 1, 3), (42, "stage: graceful?", 1, 4), (44, "stage: closing?", 1, 5), (46, "stage: none?", 1, 6),
      (41, "field candidates", 2, 3), (40, "complete block", 3, 3), (43, "graceful block", 3, 4),
      (45, "closing block", 3, 5), (stage, "stage block", 4, 6)]),
    ("Steering reminder", "Picks the reminder that steers the next reply: toward fresh questions, back to ones not yet grappled with, onward, or to the close, and rules out the topics the user has settled.",
     [(57, "off limits?", 1, 7.5), (60, "no off limits?", 1, 8.5), (59, "field offnames", 2, 7.5),
      (58, "off limits sentence", 3, 7.5), (off, "off limits", 3.6, 8.6),
      (47, "steer: complete?", 1, 9.7), (49, "steer: fresh?", 1, 10.7), (52, "steer: revisit?", 1, 11.7),
      (55, "steer: none?", 1, 12.7), (51, "field targets", 2, 10.7), (54, "field targets", 2, 11.7),
      (48, "steer: complete", 3, 9.7), (50, "steer: fresh", 3, 10.7), (53, "steer: revisit", 3, 11.7),
      (56, "steer: none", 3, 12.7), (steer, "steering reminder", 4, 11.2)]),
    ("Earlier topics", "Reminds the interlocutor of topics trimmed from the history, so that it does not ask them again.",
     [(61, "earlier topics?", 1, 13.9), (64, "no earlier topics?", 1, 14.9), (63, "field topics", 2, 13.9),
      (62, "earlier topics line", 3, 13.9), (earlier, "earlier topics", 4, 14.9)]),
    ("Reply call", "Builds the turn prompt from the history, the reminder and the latest message (with the override for a longer reply when the user held the send button), and calls the interlocutor for its reply, which goes to the relay as a REPLY op.",
     [(37, "field history", 2, 15.5), (38, "field latest", 2, 16.5), (turn, "turn prompt", 5, 15.8),
      (interlocutor, "interlocutor", 6, 15.8), (tag_reply, "tag reply", 7, 15.8),
      (87, "detail?", 3, 15.5), (89, "no detail?", 3, 16.5), (88, "detail override", 4, 15.5), (detail, "detail", 4.5, 16.6)]),
    ("Evaluation call", "Asks the evaluator to score every question on the conversation so far.",
     [(69, "field central", 2, 18), (70, "field nodes", 2, 19), (71, "field conv", 2, 20), (72, "field format", 2, 21),
      (evaluation, "evaluation prompt", 5, 19.5), (evaluator, "evaluator", 6, 19.5), (tag_eval, "tag eval", 7, 19.5)]),
    ("Follow-up closing", "Writes the closing summary as a message of its own once every question is resolved.",
     [(74, "field central", 2, 22.5), (75, "field status", 2, 23.5), (76, "field frontier", 2, 24.5),
      (77, "field candidates", 2, 25.5), (78, "field history", 2, 26.5), (close_block, "closing: complete block", 3, 25.5),
      (close_system, "closing system prompt", 5, 23.5), (close_after, "after closing system prompt", 5, 25),
      (close_prompt, "closing prompt", 5, 26.5), (closer, "closing", 6, 25), (tag_closing, "tag closing", 7, 25)]),
    ("Welcome message", "Greets the user with the shard's origin and central question when a session starts.",
     [(81, "field origin", Cc, 25.5), (82, "field central", Cc, 26.5), (83, "field end", Cc, 27.5), (welcome, "welcome", Bc, 26.5)]),
    ("Progress and exit", "Carries each turn record and the progress map to the panel, and closes every epoch at the exit.",
     [(66, "field record", Cc, 16), (84, "field map", Cc, 23.8), (state_in, "to panel state", Ac, 23.5), (exit_, "exit", Bc, 21)]),
    ("Fault report", "Gathers every arm that should never fire and reports it at the exit.",
     [(fault_phi, "faults", 0.5, 17.4), (fault, "fault", Cc, 19)]),
]
phi_names = {into: "into session", stage: "stage block", steer: "steering reminder", earlier: "earlier topics",
             off: "off limits", detail: "detail", state_in: "to panel state", exit_: "exit", into_relay: "into relay", fault_phi: "faults"}
nodes = {n["id"]: n["node"] for n in g.nodes}
placed = {}
for _, _, members in SETS:
    for nid, name, col, row in members:
        assert phi_names.get(nid, nodes[nid]["data"].get("name")) == name, (nid, name)
        assert nid not in placed, nid
        placed[nid] = (col, row)
        nodes[nid]["origin"] = {"x": float(col * CW), "y": float((row + sum(row >= g for g in GAPS)) * RH)}
assert set(placed) == set(nodes), set(nodes) - set(placed)
links = {(w["data"]["source_key"]["node"], w["sink_key"]["node"]) for w in g.wires}
for name, _, members in SETS:  # each set is one connected piece of the graph
    ids = {m[0] for m in members}
    seen, todo = set(), [members[0][0]]
    while todo:
        i = todo.pop()
        seen.add(i)
        todo += [b if a == i else a for a, b in links if i in (a, b) and {a, b} <= ids and (b if a == i else a) not in seen]
    assert seen == ids, (name, ids - seen)
# Set ids follow the drawing from left to right, the order the editor numbers them in.
order = sorted(SETS, key=lambda s: min(placed[m[0]] for m in s[2]))
functions = [{"id": i + 1, "name": name, "nodes": sorted(m[0] for m in members), "note": note}
             for i, (name, note, members) in enumerate(order)]

out = BP / ("projects/inquirychat/graphs/%s.json" % NAME)
doc = g.document(NAME)
doc["functions"] = functions
out.write_text(json.dumps(doc, indent=1))
print(out, len(g.nodes), "nodes", len(g.wires), "wires", file=sys.stderr)
