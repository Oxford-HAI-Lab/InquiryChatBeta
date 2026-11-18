# write_code of the Database node `session`. Runs with `state` (a dict kept
# while the graph is installed) and `input` (one tagged message). The first line
# of `input` names the op: LIBRARY, SHARD, LIST, START, RESUME, DELETE, USER, REPLY,
# PHASE, EVAL, CLOSING, FAILED or REWIND. Each op
# updates the state and leaves the next record to emit in state['out'] (read_code
# emits it). Every rule below mirrors a named function of the original; the
# comments give the name.
#
# A turn runs in the original's phases, one Model call per epoch: reply, then
# evaluation, then (on the turn that completes) the follow-up closing. A phase
# that has a successor ends with a STEP record naming it (`next`), which the
# relay node sends back as a new epoch (`@@OP PHASE`). A PHASE that is not the
# one pending for the current turn is stale (the user moved on, or the phase
# before it failed) and is answered IDLE.
import json
import time

op, _, body = input.partition("\n")
op = op.replace("@@OP", "").strip()
S = state
# The engine recovers from a failed epoch (a Model call that errors or passes the 600 s
# limit) by reinstalling the graph, which empties this node. READY, STEP, DONE and LIST
# records, and those that start a Model call, carry a checkpoint that the relay node keeps; an op that finds the state empty is held
# (LOST) until the relay hands the checkpoint back (RESTORE), then runs as if nothing had
# happened. So a failed evaluation leaves the state as the reply phase saved it.
if op == "RESTORE":
    held = S.pop("held", None)
    if body.strip() and held:
        S.clear()
        S.update(json.loads(body))
        S["restores"] = S.get("restores", 0) + 1
        op, _, body = held.partition("\n")
        op = op.replace("@@OP", "").strip()
    else:
        op = "NO CHECKPOINT"
elif op not in ("SHARD", "LIBRARY") and "library" not in S:
    S["held"] = input
    op = "LOST"

# The library holds every shard; the current session's keys sit at the top level, the others
# in `saved` (as the original keeps one file per session). A session refers to its shard by
# `dir`; the shard itself is rebuilt from the library and is left out of saved copies and
# checkpoints.
OWN = ("library", "saved", "cur", "out", "held", "restores", "shard", "node", "text")


def load_shard():
    shard = dict(S["library"][S["dir"]], central=S["central"])
    S.update({"shard": shard, "node": {n["id"]: n for n in shard["nodes"]},
              "text": {n["id"]: n["text"] for n in shard["nodes"]}})


if op not in ("LOST", "NO CHECKPOINT") and S.get("dir") and "shard" not in S:
    load_shard()

RESOLVED = ("settled", "rejected_understood")
RANK = {"active": 0, "dismissed": 1, "settled": 2, "rejected_understood": 2}


def nodes():
    return S["shard"]["nodes"]


def text(nid):
    return S["text"][nid]


def weights():  # ICShard._node_weights
    return {n["id"]: 1.0 + sum(e["weight"] for e in S["shard"]["edges"] if e["to"] == n["id"]) for n in nodes()}


def contribution(nid):  # ICShard._equilibrium_contribution
    if S["disp"][nid] in RESOLVED and S["scores"][nid] >= 0.75:
        return 1.0
    return S["scores"][nid]


def equilibrium():  # ICShard.equilibrium_score
    w = weights()
    total = sum(w.values())
    return sum(w[n] * contribution(n) for n in w) / total if total else 0.0


def closing_info(was_active):  # closing_mode_info
    eq = equilibrium()
    active = (0.80 <= eq < 1.0) if was_active else (0.85 <= eq < 1.0)
    return active


def graceful():  # _graceful_completion_active
    return equilibrium() >= 0.90 and all(S["disp"][n["id"]] in RESOLVED for n in nodes())


def complete():  # inquiry_complete
    return equilibrium() >= 1.0 - 1e-9


def key_terms(nid):  # the keyword rule used for raise counts and steering
    return [t for t in text(nid).lower().split() if len(t) > 4][:3]


def field(name, value):
    return "@@F %s\n%s\n@@E %s\n" % (name, value, name)


def render(messages):  # the role rendering of build_evaluation_prompt
    return "".join("%s: %s\n\n" % ("User" if m["role"] == "user" else "Assistant", m["content"]) for m in messages)


def status_lines(with_raises=True):  # build_chat_system_prompt, node status
    out = []
    for n in nodes():
        nid = n["id"]
        sc = S["scores"][nid]
        st = "%s (%.1f)" % ("[engaged]" if sc >= 0.4 else "[not yet]", sc)
        d = " [%s]" % S["disp"][nid] if S["disp"][nid] != "active" else ""
        r = " [raised %dx]" % S["raises"][nid] if with_raises and S["raises"][nid] > 0 else ""
        out.append("  %s: %s %s%s%s" % (nid, n["text"], st, d, r))
    return "\n".join(out)


def frontier_context(frontier, raises):  # build_chat_system_prompt, frontier context
    frontier = [f for f in frontier if f in S["text"] and S["disp"][f] not in RESOLVED]
    ctx = ""
    for nid in frontier:
        n = S["node"][nid]
        doc = n["context"] if n["context"] else n["notes"]
        note = ""
        if S["disp"][nid] == "dismissed" and raises[nid] > 0:
            note = (" [DISMISSED %dx — user has brushed this off without engaging the core tension. "
                    "You MUST try a completely different angle, concrete example, or thought experiment. "
                    "Do NOT rephrase the same abstract question.]" % raises[nid])
        ctx += "\n--- %s: %s [PRIORITY]%s ---\n%s\n" % (nid, n["text"], note, doc)
    for n in nodes():
        nid = n["id"]
        if nid not in frontier and S["scores"][nid] < 0.7 and S["disp"][nid] not in RESOLVED:
            doc = n["context"] if n["context"] else n["notes"]
            ctx += "\n--- %s: %s [unengaged, score=%.1f] ---\n%s\n" % (nid, n["text"], S["scores"][nid], doc)
    return ctx


def candidates():  # _inquiry_complete_block, candidate pointers
    ranked = sorted((n for n in nodes() if n["text"] != S["shard"]["central"]), key=lambda n: S["scores"][n["id"]])
    cands = ranked[:3] + [n for n in ranked[3:] if S["disp"][n["id"]] == "rejected_understood"][:2]
    return "\n".join(
        '- "%s" (%s, engagement %.2f)\n  Notes: %s' % (
            n["text"], "rejected with understanding" if S["disp"][n["id"]] == "rejected_understood" else "settled",
            S["scores"][n["id"]], n["notes"][:200])
        for n in cands)


def stage_tag(was_active):  # which block build_chat_system_prompt appends
    if complete():
        return "complete"
    if graceful():
        return "graceful"
    if closing_info(was_active):
        return "closing"
    return "none"


def snapshot():
    return {"scores": dict(S["scores"]), "dispositions": dict(S["disp"]), "raise_counts": dict(S["raises"]),
            "frontier": list(S["frontier"]), "closing_mode_active": S["closing_active"]}


def nodes_info():  # app._nodes_info and _next_up
    nxt = [f for f in S["frontier"] if f in S["text"] and S["disp"][f] not in RESOLVED][:2]
    return [{"id": n["id"], "text": n["text"], "parent": n["parent"], "engagement_score": S["scores"][n["id"]],
             "disposition": S["disp"][n["id"]], "raise_count": S["raises"][n["id"]],
             "display_score": contribution(n["id"]), "resolved": contribution(n["id"]) >= 0.85,
             "next_up": n["id"] in nxt} for n in nodes()]


ACHIEVEMENTS = [  # app.ACHIEVEMENTS
    {"id": "first_question", "name": "First Inquiry", "desc": "Begin your philosophical journey", "threshold": 1},
    {"id": "five_nodes", "name": "Questioner", "desc": "Engage with 5 questions in the inquiry complex", "threshold": 5},
    {"id": "ten_nodes", "name": "Deep Thinker", "desc": "Engage with 10 questions", "threshold": 10},
    {"id": "all_nodes", "name": "Philosopher", "desc": "Engage with every question in the complex", "threshold": None},
    {"id": "half_equilibrium", "name": "Seeking Balance", "desc": "Reach 50% erotetic equilibrium", "threshold": 0.5},
    {"id": "high_equilibrium", "name": "Approaching Wisdom", "desc": "Reach 75% equilibrium", "threshold": 0.75},
    {"id": "full_equilibrium", "name": "Erotetic Equilibrium", "desc": "Achieve full equilibrium with the inquiry complex", "threshold": 0.95},
    {"id": "deep_engagement", "name": "Depth Charge", "desc": "Score 0.9+ engagement on any single node", "threshold": 0.9},
    {"id": "cross_link", "name": "Web Weaver", "desc": "Engage with nodes connected by a cross-edge", "threshold": 2},
]


def gamification():  # app.compute_gamification; sets xp, level and achievements, returns the new ones
    scores = S["scores"]
    engaged = sum(1 for s in scores.values() if s >= 0.4)
    eq = equilibrium()
    top = max(scores.values()) if scores else 0
    cross = sum(1 for e in S["shard"]["edges"] if e.get("comment")
                and scores.get(e["from"], 0) >= 0.4 and scores.get(e["to"], 0) >= 0.4)
    reached = {"first_question": engaged >= 1, "five_nodes": engaged >= 5, "ten_nodes": engaged >= 10,
               "all_nodes": engaged >= len(nodes()), "half_equilibrium": eq >= 0.5, "high_equilibrium": eq >= 0.75,
               "full_equilibrium": eq >= 0.95, "deep_engagement": top >= 0.9, "cross_link": cross >= 2}
    new = [a for a in ACHIEVEMENTS if a["id"] not in S["achievements"] and reached[a["id"]]]
    S["achievements"] = S["achievements"] + [a["id"] for a in new]
    S["xp"] = int(sum(s * 100 for s in scores.values()))
    S["level"] = max(1, min(10, int(eq * 10) + 1))
    return new


def session_row(s, eq):  # app.list_sessions, one row
    return {"id": s["cur"], "central_question": s["central"], "shard_name": S["library"][s["dir"]]["title"],
            "equilibrium_score": eq, "xp": s["xp"], "level": s["level"],
            "turn_count": len(s["conv"]) // 2, "updated_at": s["updated_at"]}


def drop_current():
    for k in [k for k in S if k not in OWN or k == "cur"]:
        del S[k]
    for k in ("shard", "node", "text"):
        S.pop(k, None)


def save_current():
    if S.get("cur"):
        S["eq"] = equilibrium()
        S.setdefault("saved", {})[S["cur"]] = {k: v for k, v in S.items() if k not in OWN or k == "cur"}
        drop_current()


def library_record():  # app.get_shards and app.get_sessions in one record
    shards = sorted(({"dir": d, "name": d.rsplit("/", 1)[-1][:-5], "title": s["title"], "source": s.get("source", ""),
                      "central_question": s["central"], "node_count": len(s["nodes"]), "edge_count": len(s["edges"]),
                      "has_contexts": any(n["context"] for n in s["nodes"])} for d, s in S["library"].items()),
                    key=lambda s: s["title"].lower())
    rows = [session_row(s, s["eq"]) for s in S.get("saved", {}).values()]
    if S.get("cur"):
        rows.append(session_row(S, equilibrium()))
    rows = sorted(rows, key=lambda r: r["updated_at"], reverse=True)
    return "@@KIND LIST\n" + json.dumps({"shards": shards, "sessions": rows})


def start(dir_, central, sid):  # app.new_session
    save_current()
    S.update({"cur": sid, "dir": dir_, "central": central or S["library"][dir_]["central"]})
    load_shard()
    S.update({"conv": [], "turn": 0, "scores": {n["id"]: 0.0 for n in nodes()},
              "disp": {n["id"]: "active" for n in nodes()}, "raises": {n["id"]: 0 for n in nodes()},
              "frontier": [n["id"] for n in nodes()][:2], "closing_active": False, "pending": None,
              "xp": 0, "level": 1, "achievements": [], "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S")})


def ready_record():  # the welcome fields, and app.get_session for the panel
    shard = S["shard"]
    origin = (shard.get("source_brief") or "").strip()
    if not origin and shard.get("source", "").strip():
        origin = shard["source"].strip().split(". ")[0]
    q = shard["central"].strip()
    view = {"session_id": S["cur"], "shard_name": shard["title"], "central_question": q, "conversation": S["conv"],
            "equilibrium_score": equilibrium(), "xp": S["xp"], "level": S["level"], "frontier": S["frontier"],
            "nodes": nodes_info()}
    S["out"] = ("@@KIND READY\n" + field("origin", origin.rstrip(".")) + field("central", q)
                + field("end", "" if q[-1] in "?.!" else ".") + field("map", json.dumps(view)))


def done_record(phase):
    S["pending"] = None
    S["out"] = "@@KIND DONE\n" + json.dumps(dict(S["turn_record"], phase=phase, final=True))


def step_record(phase, nxt):
    S["pending"] = [nxt, S["turn"]]
    S["out"] = ("@@KIND STEP\n" + field("next", "%s %d" % (nxt, S["turn"]))
                + field("record", json.dumps(dict(S["turn_record"], phase=phase, final=False))))


def eval_request():  # build_evaluation_prompt inputs (raise counts restored, as _eval_and_merge does)
    lines = []
    for n in nodes():
        nid = n["id"]
        st = "PREVIOUSLY_ENGAGED" if S["scores"][nid] >= 0.4 else "NOT_YET_ENGAGED"
        d = " [disposition: %s]" % S["disp"][nid] if S["disp"][nid] != "active" else ""
        if S["raises"][nid] > 0:
            d += " [raised %d time(s)]" % S["raises"][nid]
        lines.append('  - %s [%s]%s: "%s"\n    Notes: %s' % (nid, st, d, n["text"], n["notes"][:200]))
    return ("@@KIND EVAL\n" + field("central", S["shard"]["central"]) + field("nodes", "\n".join(lines))
            + field("conv", render(S["conv"])) + field("format", S["shard"]["eval_format"]))


def close_request():  # app._generate_closing: frontier [], closing_mode_was_active True, no raise counts
    return ("@@KIND CLOSE\n" + field("central", S["shard"]["central"]) + field("status", status_lines(False))
            + field("frontier", frontier_context([], S["raises"])) + field("candidates", candidates())
            + field("history", render(S["conv"][-20:])))


if op == "LOST":
    S["out"] = "@@KIND LOST\n"

elif op == "SHARD":  # one shard: a fresh library holding it, and a session on it at once
    shard = json.loads(body)
    S.clear()
    S["library"] = {shard["dir"]: shard}
    start(shard["dir"], "", "session")
    ready_record()

elif op == "LIBRARY":  # every shard; the sessions are kept, as the original keeps its files
    S["library"] = {s["dir"]: s for s in json.loads(body)["shards"]}
    S["out"] = library_record()

elif op == "LIST":
    S["out"] = library_record()

elif op == "START":
    b = json.loads(body)
    start(b["dir"], b.get("central", ""), b["id"])
    ready_record()

elif op == "RESUME":
    b = json.loads(body)
    save_current()
    S.update(S["saved"].pop(b["id"]))
    load_shard()
    ready_record()

elif op == "DELETE":
    sid = json.loads(body)["id"]
    S.get("saved", {}).pop(sid, None)
    if S.get("cur") == sid:
        drop_current()
    S["out"] = library_record()

elif op == "USER":  # app._chat_turn, steps 1 to 3
    detail = 1.0  # app: detail_level, from a hold on the send button; the panel sends it as a first line
    if body.startswith("@@DETAIL "):
        head, _, body = body.partition("\n")
        try:
            detail = max(1.0, min(4.0, float(head[9:])))
        except ValueError:
            pass
    S["turn"] += 1
    S["pending"] = None  # a phase still pending from the last turn is dropped, as the original drops a failed eval
    S["was_complete"] = complete()
    was_closing = S["closing_active"]
    S["turn_record"] = {"turn": S["turn"], "user": body, "before": snapshot()}
    conv = S["conv"] + [{"role": "user", "content": body}]
    S["conv"] = conv
    frontier = list(S["frontier"])
    stage = stage_tag(was_closing)
    # history trim (3b)
    earlier = ""
    if len(conv) > 20:
        topics = []
        for m in conv[:-20]:
            low = m["content"].lower()
            for n in nodes():
                terms = n["text"].lower().split()[:4]
                if any(t in low for t in terms if len(t) > 4) and "%s: %s" % (n["id"], n["text"]) not in topics:
                    topics.append("%s: %s" % (n["id"], n["text"]))
        earlier = "; ".join(topics[:10])
        trimmed = conv[-20:]
    else:
        trimmed = conv
    # steering reminder (3c)
    recent = " ".join(m["content"].lower() for m in conv[-20:])
    fresh, revisit, off = [], [], []
    for nid in frontier:
        if nid not in S["text"]:
            continue
        if S["disp"][nid] in RESOLVED:
            off.append(nid)
            continue
        hits = sum(1 for t in key_terms(nid) if t in recent)
        (revisit if hits >= 2 else fresh).append(nid)
    parts = []
    if fresh:
        steer = "fresh"
        for nid in fresh[:3]:
            p = '"%s" (node %s, score %.1f)' % (text(nid), nid, S["scores"][nid])
            if S["disp"][nid] == "dismissed" and S["raises"][nid] >= 3:
                p += (" [DISMISSED %dx — do NOT argue this point again. Instead, ask the user to explain in "
                      "their own words why someone might find this point compelling or challenging]" % S["raises"][nid])
            elif S["disp"][nid] == "dismissed":
                p += " [PREVIOUSLY DISMISSED %dx — must use a completely different angle]" % S["raises"][nid]
            parts.append(p)
    elif revisit:
        steer = "revisit"
        for nid in revisit[:2]:
            p = '"%s" (score %.1f — needs deeper engagement)' % (text(nid), S["scores"][nid])
            if S["disp"][nid] == "dismissed" and S["raises"][nid] >= 3:
                p += (" [DISMISSED %dx — do NOT argue this point again. Instead, ask the user to explain in "
                      "their own words why someone might find this point compelling]" % S["raises"][nid])
            elif S["disp"][nid] == "dismissed":
                p += " [DISMISSED %dx — try a vivid concrete scenario, NOT the same abstract question]" % S["raises"][nid]
            parts.append(p)
    else:
        steer = "none"
    if complete():
        steer = "complete"
    S["turn_record"]["stage_at_reply"] = stage
    S["turn_record"]["steer"] = steer
    S["out"] = ("@@KIND CALL STAGE=%s STEER=%s EARLIER=%s OFF=%s DETAIL=%s\n" % (
        stage, steer, "yes" if earlier else "no", "yes" if off else "no",
        "yes" if detail > 1.5 and steer != "complete" else "no")  # the complete reminder replaces the override
        + field("central", S["shard"]["central"]) + field("status", status_lines())
        + field("frontier", frontier_context(frontier, S["raises"])) + field("candidates", candidates())
        + field("targets", " | ".join(parts)) + field("offnames", ", ".join("%s (%s)" % (n, text(n)[:50]) for n in off))
        + field("topics", earlier) + field("history", render(trimmed[:-1])) + field("latest", body))

elif op == "REPLY":  # app._chat_turn, steps 3 (reply) and 4 (raise counts)
    S["conv"].append({"role": "assistant", "content": body})
    low = body.lower()
    raised = []
    for nid in S["frontier"]:
        if nid in S["text"] and sum(1 for t in key_terms(nid) if t in low) >= 1:
            S["raises"][nid] += 1
            raised.append(nid)
    S["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    S["turn_record"]["reply"] = body
    S["turn_record"]["raised"] = raised
    # The state as saved before the evaluation runs; it stands if the evaluation fails.
    S["turn_record"].update({"after": snapshot(), "equilibrium_score": equilibrium(), "nodes": nodes_info(),
                             "just_completed": False})
    step_record("reply", "EVAL")

elif op == "PHASE":  # the relay brings the next phase of the turn as its own epoch
    kind, _, turn = body.strip().partition(" ")
    if S.get("pending") != [kind, int(turn or -1)]:
        S["out"] = "@@KIND IDLE\nstale phase " + body.strip()
    elif kind == "EVAL":
        S["out"] = eval_request()
    else:
        S["out"] = close_request()

elif op == "EVAL":  # evaluate_equilibrium (parse, damping, dispositions) and _eval_and_merge
    raw = body.strip()
    a, b = raw.find("{"), raw.rfind("}")
    if a != -1 and b > a:
        raw = raw[a:b + 1]
    rec = S["turn_record"]
    rec["eval_raw"] = body
    try:
        result = json.loads(raw)
        parsed = True
    except ValueError:
        parsed = False
        unengaged = [n for n in nodes() if S["scores"][n["id"]] < 0.4]  # most_destabilizing_unengaged
        unengaged.sort(key=lambda n: -sum(e["weight"] for e in S["shard"]["edges"] if e["from"] == n["id"]))
        result = {"scores": dict(S["scores"]), "frontier": [n["id"] for n in unengaged[:2]],
                  "summary": "Evaluation in progress."}
    rec["eval_parsed"] = parsed
    try:
        new_scores, new_disp = dict(S["scores"]), dict(S["disp"])
        for nid, score in result.get("scores", {}).items():
            if nid in S["text"]:
                prev = new_scores[nid]
                ns = float(score)
                if new_disp[nid] in RESOLVED and ns < prev:
                    ns = max(ns, prev - 0.10)
                new_scores[nid] = ns
        for nid, d in result.get("dispositions", {}).items():
            if nid in S["text"] and d in RANK and RANK[d] >= RANK.get(new_disp[nid], 0):
                new_disp[nid] = d
        S["scores"], S["disp"] = new_scores, new_disp
        S["frontier"] = result.get("frontier", [])
        was_closing = S["closing_active"]
        S["closing_active"] = closing_info(was_closing)
        rec["eval_failed"] = False
        rec["summary"] = result.get("summary", "")
        rec["new_achievements"] = gamification()
        S["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception as exc:  # the original's eval task raises; no eval line, state unchanged
        rec["eval_failed"] = True
        rec["summary"] = ""
        rec["eval_error"] = repr(exc)
    eq = equilibrium()
    rec.update({"after": snapshot(), "equilibrium_score": eq, "nodes": nodes_info(), "xp": S["xp"], "level": S["level"],
                "just_completed": (not rec["eval_failed"]) and (not S["was_complete"]) and eq >= 1.0 - 1e-9})
    if rec.get("rewind"):  # app._rewind_locked: no closing, the closing-mode latch starts afresh
        S["closing_active"] = closing_info(False)
        rec.update(just_completed=False, conversation=S["conv"])
        done_record("rewind")
    elif rec["just_completed"]:
        rec["closing"] = None
        step_record("eval", "CLOSE")
    else:
        done_record("eval")

elif op == "FAILED":  # the relay reports that a phase's epoch failed: the turn ends as the original's does
    kind, _, turn = body.strip().partition(" ")
    if S.get("pending") != [kind, int(turn or -1)]:
        S["out"] = "@@KIND IDLE\nstale failure " + body.strip()
    elif kind == "EVAL":  # no eval line; the reply's state stands
        S["turn_record"].update(eval_failed=True, summary="")
        done_record("eval")
    else:  # a closing line with no message
        S["turn_record"]["closing"] = None
        done_record("closing")

elif op == "REWIND":  # app._rewind_locked: truncate, reset every score, evaluate afresh
    S["turn"] += 1
    S["conv"] = S["conv"][:json.loads(body)["index"] + 1]
    S.update({"scores": {n["id"]: 0.0 for n in nodes()}, "disp": {n["id"]: "active" for n in nodes()},
              "raises": {n["id"]: 0 for n in nodes()}, "closing_active": False, "was_complete": False,
              "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    S["turn_record"] = {"turn": S["turn"], "rewind": True, "before": snapshot()}
    step_record("rewind", "EVAL")

elif op == "CLOSING":
    S["conv"].append({"role": "assistant", "content": body.strip()})
    S["turn_record"]["closing"] = body.strip()
    S["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    done_record("closing")

else:
    S["out"] = "@@KIND FAULT\nunknown op " + op

if S["out"].startswith(("@@KIND READY", "@@KIND STEP", "@@KIND DONE", "@@KIND LIST", "@@KIND CALL",
                         "@@KIND EVAL", "@@KIND CLOSE")):
    S["out"] += "\n@@F checkpoint\n%s\n@@E checkpoint\n" % json.dumps(
        {k: v for k, v in S.items() if k not in ("out", "shard", "node", "text")})
