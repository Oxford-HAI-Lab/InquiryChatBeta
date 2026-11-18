// Stands in for the original's server (app.py) inside the Blueprint panel. The original
// front end (static/app.js, inlined after this script unchanged) calls fetch("/api/...");
// this script answers each call from the graph: it emits ops on the panel's outputs and
// resolves the call when the Database's record comes back on the `state` input.
//
//   user  the message text of a chat turn; after a hold on the send button it
//         has a first line "@@DETAIL <level>"
//   op    "@@OP START|RESUME|DELETE|LIST|REWIND\n<json>"
//
// Records on `state`: a turn record ({phase, final, ...}), a session view (READY's map:
// {session_id, conversation, nodes, ...}) or the shard and session list ({shards, sessions}).
// The welcome text arrives on `welcome`.
(() => {
  const host = globalThis.blueprint;
  const json = (body, status = 200) => new Response(JSON.stringify(body), {status, headers: {"Content-Type": "application/json"}});
  const op = (name, body) => host && host.emit("op", `@@OP ${name}\n${JSON.stringify(body)}`);

  // The sandbox allows no dialogs: alert and confirm are drawn in the page. confirm cannot
  // wait, so it answers false and asks; OK clicks the button that asked again, and the
  // repeated question is then answered true.
  let granted = null;
  function dialog(text, withCancel, onOk) {
    const box = document.createElement("div");
    box.style.cssText = "position:fixed;inset:0;z-index:10000;display:flex;align-items:flex-start;justify-content:center;background:rgba(0,0,0,.25);font:14px system-ui,sans-serif";
    box.innerHTML = `<div style="margin-top:40px;width:420px;padding:20px;background:#fff;border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.25)"><p style="margin:0 0 18px;white-space:pre-wrap"></p><div style="display:flex;justify-content:flex-end;gap:8px">${withCancel ? "<button>Cancel</button>" : ""}<button>OK</button></div></div>`;
    box.querySelector("p").textContent = text;
    const buttons = box.querySelectorAll("button");
    buttons.forEach(b => b.style.cssText = "padding:5px 16px;border-radius:6px;border:1px solid #aab3c0;background:#fff");
    buttons[buttons.length - 1].addEventListener("click", () => { box.remove(); if (onOk) onOk(); });
    if (withCancel) buttons[0].addEventListener("click", () => box.remove());
    document.body.appendChild(box);
  }
  window.alert = text => dialog(String(text), false);
  window.confirm = text => {
    if (granted === text) { granted = null; return true; }
    const asker = window.event && window.event.currentTarget;
    dialog(String(text), true, () => { granted = text; if (asker && asker.click) asker.click(); });
    return false;
  };

  // The panel sits on the editor's canvas: it takes keyboard focus only while it has it,
  // so the editor's keys are never typed into the chat box.
  const focus = HTMLElement.prototype.focus;
  HTMLElement.prototype.focus = function (...args) { if (document.hasFocus()) focus.apply(this, args); };

  // Waiting calls, each resolved by the next record of its kind.
  // cached: a list just received, for the calls showLanding makes at once (both read it).
  let lists = [], views = [], turn = null, welcome = null, view = null, cached = null;
  const keep = l => { cached = l; setTimeout(() => { cached = null; }); };
  const newId = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, "0")).join("");

  function list() {
    if (cached) return Promise.resolve(cached);
    if (!lists.length) op("LIST", {});
    return new Promise(resolve => lists.push(resolve));
  }
  function session(name, body) {  // START or RESUME; resolves with the view and the welcome
    op(name, body);
    return new Promise(resolve => views.push(resolve));
  }
  let shown = null;  // the view the next GET /api/sessions/<id> answers with
  function viewReady() {
    if (!view || welcome === null) return;
    const v = {...view, welcome_message: welcome, welcome_speech: null};
    view = welcome = null;
    shown = v;
    if (views.length) return views.shift()(v);
    // Not asked for: the Go node fired with a single shard (a SHARD= build) and started a session.
    sessionId = v.session_id;
    showChat();
  }

  // One chat turn: the original's NDJSON lines, from the turn records.
  function evalLine(r) {
    return {phase: "eval", equilibrium_score: r.equilibrium_score, node_scores: r.after.scores, nodes: r.nodes,
            frontier: r.after.frontier, eval_summary: r.summary, xp: r.xp, level: r.level,
            new_achievements: r.new_achievements || [], closing_pending: r.just_completed};
  }
  function onRecord(r) {
    if (!turn) return;
    if (turn.rewind) {
      if (!r.final) return;
      const t = turn; turn = null;
      if (r.eval_failed) return t.done(new Response("Internal Server Error", {status: 500}));
      return t.done(json({conversation: r.conversation, equilibrium_score: r.equilibrium_score, node_scores: r.after.scores,
                          nodes: r.nodes, frontier: r.after.frontier, eval_summary: r.summary, xp: r.xp, level: r.level}));
    }
    if (r.phase === "reply") turn.line({phase: "reply", assistant_message: r.reply});
    if (r.phase === "eval" && !r.eval_failed) turn.line(evalLine(r));
    if (r.phase === "closing") turn.line({phase: "closing", assistant_message: r.closing});
    if (r.final) { turn.close(); turn = null; }
  }
  function chat(message, detail) {
    let control;
    const body = new ReadableStream({start(c) { control = c; }});
    const enc = new TextEncoder();
    turn = {line: x => control.enqueue(enc.encode(JSON.stringify(x) + "\n")), close: () => control.close()};
    host.emit("user", detail > 1.5 ? `@@DETAIL ${detail}\n${message}` : message);
    return new Response(body, {headers: {"Content-Type": "application/x-ndjson"}});
  }

  if (host) {
    host.on("input", ({port, value}) => {
      if (port === "welcome") { welcome = String(value); return viewReady(); }
      if (port !== "state") return;
      const r = JSON.parse(String(value));
      if (r.shards) {
        if (lists.length) lists.splice(0).forEach(resolve => resolve(r));
        else if (document.querySelector(".landing")) { keep(r); showLanding(); }  // the Go node fired
      } else if (r.session_id) { view = r; viewReady(); }
      else if ("phase" in r) onRecord(r);
    });
  }

  window.fetch = async (url, opts = {}) => {
    const method = opts.method || "GET";
    const path = String(url).replace(/^\/api/, "");
    const body = opts.body ? JSON.parse(opts.body) : {};
    let m;
    if (path === "/csrf") return json({token: "panel"});
    if (path === "/tts/enabled") return json({enabled: false, provider: "openai", note: "the port has no voice"});
    if (path === "/shards") return json((await list()).shards);
    if (path === "/sessions" && method === "GET") return json((await list()).sessions);
    if (path === "/sessions/new") {
      const v = await session("START", {dir: body.shard_dir, central: body.central_question || "", id: newId()});
      return json({session_id: v.session_id, central_question: v.central_question});
    }
    if ((m = path.match(/^\/sessions\/(\w+)$/))) {
      if (method === "DELETE") { op("DELETE", {id: m[1]}); keep(await new Promise(resolve => lists.push(resolve))); return json({ok: true}); }
      if (shown && shown.session_id === m[1]) { const v = shown; shown = null; return json(v); }
      const v = await session("RESUME", {id: m[1]});
      shown = null;
      return json(v);
    }
    if ((m = path.match(/^\/chat\/(\w+)\/rewind$/))) {
      op("REWIND", {index: body.message_index});
      return new Promise(done => { turn = {rewind: true, done}; });
    }
    if ((m = path.match(/^\/chat\/(\w+)$/))) return chat(body.message, body.detail_level);
    return json({detail: "Not Found"}, 404);
  };
})();
