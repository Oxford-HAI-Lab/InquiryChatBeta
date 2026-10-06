// ── State ────────────────────────────────────────────────────────
let sessionId = null;
let sending = false;
let previousEqScore = 0;
let celebrationShown = false;
let currentCentralQuestion = "";
// Follow-up closing message for the turn that reaches 100% equilibrium.
// message: undefined = still being generated, null = none coming, string = ready.
let closingState = null;
let ttsEnabled = false;
let ttsProviderLabel = "";
let ttsAutoPlay = false;
let sttActive = false;
let sttWanted = true;  // voice input on by default; follows the mic button after that
let recognition = null;
let sttFinalTranscript = "";
let sttGeneration = 0;
let currentAudio = null;
let ttsEmotions = false;
let messageCount = 0;
let sendHoldStart = 0;
let sendHoldTimer = null;
let sendDetailLevel = 1.0;

// ── DOM refs ─────────────────────────────────────────────────────
const $app = document.getElementById("app");

// ── API helpers ──────────────────────────────────────────────────
let csrfTokenRequest = null;
async function csrfHeaders() {
  if (!csrfTokenRequest) {
    csrfTokenRequest = fetch("/api/csrf", { cache: "no-store" }).then(async res => {
      if (!res.ok) throw new Error("Could not authorize this page. Reload Inquiry Chat.");
      return (await res.json()).token;
    }).catch(error => {
      csrfTokenRequest = null;
      throw error;
    });
  }
  return { "X-Inquiry-CSRF": await csrfTokenRequest };
}

async function api(method, path, body) {
  const opts = { method, headers: ["GET", "HEAD", "OPTIONS"].includes(method) ? {} : await csrfHeaders() };
  if (body) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`/api${path}`, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
}

// Fresh screens start at the top; clear anchors left by older frontend versions.
function resetWorkspaceLocation() {
  if (["#conversation-panel", "#inquiry-panel"].includes(window.location.hash)) {
    window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search);
  }
  window.scrollTo(0, 0);
}

// ── Landing screen ───────────────────────────────────────────────
async function showLanding() {
  document.body.classList.remove("chat-active");
  const [sessions, shards] = await Promise.all([
    api("GET", "/sessions"),
    api("GET", "/shards"),
  ]);

  let sessionsHtml = "";
  let continueHtml = "";
  if (sessions.length > 0) {
    const latest = sessions[0]; // sessions are sorted by most recent
    continueHtml = `
      <button class="continue-btn" onclick="continueConversation('${latest.id}')">
        <span class="continue-btn-icon">&#9654;</span>
        <span class="continue-btn-text">
          <span class="continue-btn-label">Continue</span>
          <span class="continue-btn-meta">${escapeHtml(latest.shard_name)} &mdash; ${latest.turn_count} turns &middot; ${Math.round(latest.equilibrium_score * 100)}% equilibrium</span>
        </span>
        <span class="continue-btn-badges">
          <span class="continue-btn-badge" title="Auto-enables voice input">&#127908;</span>
          <span class="continue-btn-badge" title="Auto-enables voice output">&#128264;</span>
        </span>
      </button>`;
    sessionsHtml = `
      <div class="saved-sessions">
        <h3>Resume</h3>
        ${sessions.map(s => `
          <div class="session-item">
            <div class="session-info" onclick="resumeSession('${s.id}')">
              <div class="session-name">${escapeHtml(s.shard_name)} &mdash; Level ${s.level}</div>
              <div class="session-meta">${s.turn_count} turns &middot; ${s.updated_at}</div>
            </div>
            <div class="session-eq" onclick="resumeSession('${s.id}')">${Math.round(s.equilibrium_score * 100)}%</div>
            <button class="session-delete-btn" onclick="deleteSession(event, '${s.id}')" title="Delete session">&times;</button>
          </div>
        `).join("")}
      </div>`;
  }

  let shardsHtml = "";
  if (shards.length > 0) {
    shardsHtml = shards.map(s => `
      <div class="shard-card" data-dir="${escapeAttr(s.dir)}" data-question="${escapeAttr(s.central_question)}" onclick="selectShard(this)">
        <div class="shard-card-header">
          <div class="shard-card-name">${escapeHtml(s.title || s.name)}</div>
          <div class="shard-card-stats">${s.node_count} nodes</div>
        </div>
        <div class="shard-card-question">${escapeHtml(s.central_question)}</div>
      </div>
    `).join("");
  } else {
    shardsHtml = `<div class="no-shards">No shards found. Place a shard JSON in the project root or Shards/ directory.</div>`;
  }

  $app.innerHTML = `
    <div class="landing">
      <div class="landing-card">
        <h1>Inquiry Chat</h1>
        <p class="subtitle">
          Traverse the question space around a central issue and seek erotetic
          equilibrium &mdash; judgment that is robust to further questions in a
          given inquiry shard.
          <a href="https://link.springer.com/content/pdf/10.1007/s11299-025-00326-z.pdf" target="_blank" rel="noopener">Koralus (2025)</a>
        </p>

        ${continueHtml}

        <label>Select inquiry shard</label>
        <div class="shard-list" id="shard-list">
          ${shardsHtml}
        </div>

        <div class="selected-shard-info" id="selected-shard-info" style="display:none">
          <label>Selected Shard</label>
          <div class="selected-shard-display" id="selected-shard-display"></div>
          <label>Central Question (optional override)</label>
          <input type="text" id="central-q" placeholder="Leave blank to use shard's default" />
          <input type="hidden" id="shard-dir" value="" />
          <button class="landing-btn" onclick="startNew()">Begin Inquiry</button>
        </div>

        ${sessionsHtml}
      </div>
    </div>`;
  resetWorkspaceLocation();
}

function escapeHtml(str) {
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// For values placed inside a double-quoted HTML attribute.
function escapeAttr(str) {
  return escapeHtml(str).replace(/"/g, "&quot;");
}

function selectShard(card) {
  const dir = card.dataset.dir;
  const centralQuestion = card.dataset.question;
  document.getElementById("shard-dir").value = dir;
  document.getElementById("central-q").placeholder = centralQuestion;
  document.getElementById("selected-shard-display").textContent = centralQuestion;
  document.getElementById("selected-shard-info").style.display = "block";

  // Highlight selected card
  document.querySelectorAll(".shard-card").forEach(el => el.classList.remove("selected"));
  card.classList.add("selected");
}

async function startNew() {
  const shardDir = document.getElementById("shard-dir").value.trim();
  if (!shardDir) {
    alert("Please select an inquiry complex shard first.");
    return;
  }
  const centralQ = document.getElementById("central-q").value.trim();
  try {
    const res = await api("POST", "/sessions/new", {
      shard_dir: shardDir,
      central_question: centralQ || undefined,
    });
    sessionId = res.session_id;
    // Auto-enable TTS so the welcome message is read aloud
    if (ttsEnabled) ttsAutoPlay = true;
    await showChat();
  } catch (e) {
    alert(e.message);
  }
}

async function resumeSession(id) {
  sessionId = id;
  await showChat();
}

async function continueConversation(id) {
  sessionId = id;
  // Auto-enable TTS and STT
  if (ttsEnabled) {
    ttsAutoPlay = true;
    ttsEmotions = true;
  }
  sttWanted = true;
  await showChat();  // starts STT once the chat DOM is rendered
  updateSpeakerBtn();
  updateEmotionBtn();
}

// ── Chat screen ──────────────────────────────────────────────────
async function showChat() {
  document.body.classList.add("chat-active");
  const data = await api("GET", `/sessions/${sessionId}`);
  previousEqScore = data.equilibrium_score || 0;
  celebrationShown = previousEqScore >= 0.999;
  currentCentralQuestion = data.central_question || "";

  $app.innerHTML = `
    <div class="app">
      <header class="app-header">
        <h1 class="app-brand">Inquiry Chat</h1>
        <div class="header-actions">
          <span class="save-indicator" id="save-indicator" role="status">auto-saved</span>
          <button class="save-exit-btn" onclick="saveAndExit()" title="Save session and return to menu">Exit</button>
        </div>
      </header>

      <aside class="sidebar" aria-labelledby="inquiry-panel">
        <div class="sidebar-header">
          <h2 id="inquiry-panel">Inquiry map</h2>
        </div>

        <div class="progress-section">
          <div class="progress-heading">
            <div class="eq-label">Erotetic equilibrium</div>
            <div class="eq-score-big" id="eq-big">${Math.round(data.equilibrium_score * 100)}%</div>
          </div>
          <div class="eq-bar-container">
            <div class="eq-bar pulsing" id="eq-bar" style="width: ${Math.round(data.equilibrium_score * 100)}%"></div>
            <span class="eq-percentage sr-only" id="eq-pct" aria-hidden="true">${Math.round(data.equilibrium_score * 100)}%</span>
          </div>
          <div class="eq-summary" id="eq-summary"></div>
        </div>

        <div class="stats-row">
          <div class="stat-card">
            <div class="stat-value" id="xp-value">${data.xp || 0}</div>
            <div class="stat-label">XP</div>
          </div>
          <div class="stat-card">
            <div class="stat-value" id="level-value">${data.level || 1}</div>
            <div class="stat-label">Level</div>
          </div>
          <div class="stat-card">
            <div class="stat-value" id="engaged-count">${(data.nodes || []).filter(n => n.resolved).length}</div>
            <div class="stat-label">Resolved</div>
          </div>
        </div>

        <div class="node-map-section">
          <div id="node-map" aria-label="Question progress"></div>
        </div>
        <details class="map-key">
          <summary>Reading the map</summary>
          <div class="map-key-items">
            <span><i class="node-dot engaged" aria-hidden="true"></i>Resolved</span>
            <span><i class="node-dot partial" aria-hidden="true"></i>In progress</span>
            <span><i class="node-dot" aria-hidden="true"></i>Not started</span>
            <span><i class="node-dot frontier" aria-hidden="true"></i>Next in line</span>
          </div>
          <p>A brighter gold dot means more progress. A purple ring marks a question next in line, independently of its progress.</p>
        </details>
        <details class="session-details">
          <summary>Session details</summary>
          <div class="session-id-row">Session: <span class="session-id-text">${escapeHtml(sessionId)}</span></div>
        </details>
      </aside>

      <main class="chat-area" aria-labelledby="conversation-panel">
        <div class="chat-header">
          <div class="shard-name">${escapeHtml(data.shard_name || "Inquiry")}</div>
          <h2 class="chat-question" id="conversation-panel">${escapeHtml(data.central_question)}</h2>
        </div>
        <div class="chat-messages" id="messages"></div>
        <div class="chat-input-area">
          <div class="composer">
          <div class="chat-controls-row" role="group" aria-label="Voice controls">
            <button class="icon-btn mic-btn" id="mic-btn" onclick="toggleMic()" title="Voice input (speech-to-text)" aria-pressed="false" aria-describedby="voice-privacy-note">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
            </button>
            <button class="icon-btn speaker-btn" id="speaker-btn" onclick="toggleAutoTTS()" title="Toggle auto-read responses aloud">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>
            </button>
            <button class="icon-btn emotion-btn" id="emotion-btn" onclick="toggleEmotions()" title="Expressive TTS: OFF">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>
            </button>
          </div>
          <div class="chat-input-row">
            <textarea class="chat-input" id="chat-input"
              placeholder="Share your thoughts on this question..."
              rows="1"
              aria-label="Your thoughts on this question"
              autocomplete="off"
              onkeydown="handleKey(event)"></textarea>
            <button class="send-btn" id="send-btn" aria-label="Send message" title="Send message. Hold for up to two seconds for a more detailed response.">
              <svg class="send-ring" width="48" height="48" viewBox="0 0 48 48">
                <circle class="send-ring-bg" cx="24" cy="24" r="21" fill="none" stroke="rgba(255,255,255,0.15)" stroke-width="3"/>
                <circle class="send-ring-fill" id="send-ring-fill" cx="24" cy="24" r="21" fill="none" stroke="var(--accent-glow, #7c6ef0)" stroke-width="3" stroke-dasharray="131.95" stroke-dashoffset="131.95" stroke-linecap="round" transform="rotate(-90 24 24)"/>
              </svg>
              <svg class="send-arrow" width="20" height="20" viewBox="0 0 24 24" fill="white"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
            </button>
          </div>
          </div>
          <p class="voice-privacy-note" id="voice-privacy-note">Voice input may send audio to your browser's speech service before you send a message. Turn the microphone off to stop listening.</p>
        </div>
      </main>
    </div>`;
  resetWorkspaceLocation();

  renderNodeMap(data.nodes || [], data.frontier || []);
  renderConversation(data.conversation || []);

  // Auto-resize textarea
  const input = document.getElementById("chat-input");
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  });

  // If no conversation yet, show a welcome message
  if (!data.conversation || data.conversation.length === 0) {
    appendMessage("assistant",
      data.welcome_message ||
        `Our central question is: **"${data.central_question}"** Share your initial thoughts to begin.`,
      true, true, data.welcome_speech || null, false
    );
  }

  updateSpeakerBtn();
  updateEmotionBtn();
  setupSendButton();
  document.getElementById("chat-input").focus();
  if (sttWanted) startSTT();
}

// ── Render helpers ───────────────────────────────────────────────
function renderNodeMap(nodes, frontier) {
  const container = document.getElementById("node-map");
  if (!container) return;

  // Sort: CENTRAL first, then by parent grouping
  const sorted = [...nodes].sort((a, b) => {
    if (a.id === "CENTRAL") return -1;
    if (b.id === "CENTRAL") return 1;
    if (a.parent === null && b.parent !== null) return -1;
    if (a.parent !== null && b.parent === null) return 1;
    return a.id.localeCompare(b.id);
  });

  // Same rules as the voice device's display: green once resolved, gold and
  // brighter with score while in progress, pulsing for the next two in line.
  container.innerHTML = sorted.map(node => {
    const score = node.display_score ?? node.engagement_score;
    const resolved = node.resolved ?? score >= 0.85;
    const nextUp = node.next_up ?? false;
    const state = resolved ? "engaged" : (score > 0 ? "partial" : "");
    const cls = [state, nextUp ? "frontier" : ""].join(" ").trim();
    const dotStyle = state === "partial" ? `opacity: ${(0.4 + 0.6 * score).toFixed(2)};` : "";
    const indent = node.parent && node.parent !== "CENTRAL" ? "padding-left: 20px;" : "";
    const scoreText = score > 0 ? Math.round(score * 100) + "%" : "";

    return `
      <div class="node-item ${cls}" style="${indent}" title="${escapeAttr(node.text)}">
        <div class="node-dot ${cls}" style="${dotStyle}"></div>
        <div class="node-text">${escapeHtml(truncate(node.text, 45))}</div>
        <div class="node-score">${scoreText}</div>
      </div>`;
  }).join("");
}

function renderConversation(messages) {
  const container = document.getElementById("messages");
  if (!container) return;
  container.innerHTML = "";
  messageCount = 0;
  for (const msg of messages) {
    appendMessage(msg.role, msg.content, false);
  }
  scrollToBottom();
}

// speechText: optional version of the message for text-to-speech, already
// carrying its own delivery directions (so emotion tagging is skipped).
// `saved` is false for the welcome message, which is shown in the browser
// only and is not part of the saved conversation: it gets no rewind button
// and does not count toward the message indices the server uses.
function appendMessage(role, content, animate = true, autoSpeak = false, speechText = null, saved = true) {
  const container = document.getElementById("messages");
  if (!container) return;

  const msgIndex = saved ? messageCount++ : null;
  const div = document.createElement("div");
  div.className = `message ${role}`;
  if (!animate) div.style.animation = "none";

  const playBtn = (role === "assistant" && ttsEnabled)
    ? `<button class="msg-play-btn" onclick="playTTS(this)" ${speechText ? 'data-directed="1" ' : ''}data-text="${(speechText || content).replace(/"/g, '&quot;').replace(/</g, '&lt;')}" title="Read aloud"><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg></button>`
    : "";

  const rewindBtn = msgIndex === null ? "" : `<button class="msg-rewind-btn" onclick="rewindTo(${msgIndex})" title="Restart conversation from here"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg></button>`;

  div.innerHTML = `<div class="message-bubble">${formatMarkdown(content)}${playBtn}${rewindBtn}</div>`;
  container.appendChild(div);
  scrollToBottom();

  if (autoSpeak && role === "assistant" && ttsEnabled && ttsAutoPlay) {
    const btn = div.querySelector(".msg-play-btn");
    if (btn) playTTS(btn);
  }
}

function showThinking() {
  const container = document.getElementById("messages");
  const div = document.createElement("div");
  div.className = "message assistant";
  div.id = "thinking-msg";
  div.innerHTML = `
    <div class="message-bubble">
      <div class="thinking">
        <div class="thinking-dot"></div>
        <div class="thinking-dot"></div>
        <div class="thinking-dot"></div>
      </div>
    </div>`;
  container.appendChild(div);
  scrollToBottom();
}

function removeThinking() {
  const el = document.getElementById("thinking-msg");
  if (el) el.remove();
}

function scrollToBottom() {
  const container = document.getElementById("messages");
  if (container) {
    requestAnimationFrame(() => {
      container.scrollTop = container.scrollHeight;
    });
  }
}

function truncate(str, len) {
  return str.length > len ? str.slice(0, len) + "\u2026" : str;
}

function formatMarkdown(text) {
  // Very basic markdown: bold, italic, paragraphs
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/\n\n/g, "</p><p>")
    .replace(/\n/g, "<br>")
    .replace(/^/, "<p>")
    .replace(/$/, "</p>");
}

// ── Sending messages ─────────────────────────────────────────────
function handleKey(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendDetailLevel = 1.0;
    sendMessage();
  }
}

function setupSendButton() {
  const btn = document.getElementById("send-btn");
  if (!btn) return;
  const ring = document.getElementById("send-ring-fill");
  const circumference = 2 * Math.PI * 21; // ~131.95

  function startHold(e) {
    if (btn.disabled) return;
    e.preventDefault();
    sendHoldStart = Date.now();
    sendDetailLevel = 1.0;

    sendHoldTimer = requestAnimationFrame(function tick() {
      const elapsed = Date.now() - sendHoldStart;
      const progress = Math.min(elapsed / 2000, 1); // 0-1 over 2 seconds
      sendDetailLevel = 1.0 + progress * 3.0; // 1x to 4x
      // Update ring: full offset = hidden, 0 = fully drawn
      ring.style.strokeDashoffset = circumference * (1 - progress);
      // Neon glow intensifies
      ring.style.stroke = `hsl(255, ${60 + progress * 40}%, ${55 + progress * 25}%)`;
      ring.style.filter = `drop-shadow(0 0 ${3 + progress * 8}px hsl(255, 80%, ${60 + progress * 20}%))`;
      if (progress < 1) {
        sendHoldTimer = requestAnimationFrame(tick);
      }
    });
  }

  function endHold(e) {
    e.preventDefault();
    if (sendHoldTimer) {
      cancelAnimationFrame(sendHoldTimer);
      sendHoldTimer = null;
    }
    // Reset ring visual
    ring.style.strokeDashoffset = circumference;
    ring.style.filter = "none";
    ring.style.stroke = "var(--accent-glow, #7c6ef0)";
    // Only send if we had a hold start (prevents duplicate sends)
    if (sendHoldStart > 0) {
      sendHoldStart = 0;
      sendMessage();
    }
  }

  function cancelHold() {
    if (sendHoldTimer) {
      cancelAnimationFrame(sendHoldTimer);
      sendHoldTimer = null;
    }
    sendHoldStart = 0;
    sendDetailLevel = 1.0;
    ring.style.strokeDashoffset = circumference;
    ring.style.filter = "none";
    ring.style.stroke = "var(--accent-glow, #7c6ef0)";
  }

  btn.addEventListener("mousedown", startHold);
  btn.addEventListener("mouseup", endHold);
  btn.addEventListener("mouseleave", cancelHold);
  btn.addEventListener("touchstart", startHold, { passive: false });
  btn.addEventListener("touchend", endHold);
  btn.addEventListener("touchcancel", cancelHold);
}

async function sendMessage() {
  if (sending) return;
  const input = document.getElementById("chat-input");
  const message = input.value.trim();
  if (!message) return;

  // Stop STT to prevent pending results from repopulating the input
  const wasSTTActive = sttActive || recognition !== null;
  const microphoneSessionId = sessionId;
  stopSTT();

  sending = true;
  input.value = "";
  input.style.height = "auto";
  document.getElementById("send-btn").disabled = true;

  appendMessage("user", message);
  showThinking();

  try {
    // The /chat endpoint now streams NDJSON in two phases:
    //   { "phase": "reply", "assistant_message": "..." }   ← arrives ASAP, triggers TTS
    //   { "phase": "eval", ...scores, nodes, frontier... } ← arrives once eval finishes
    //   { "phase": "closing", "assistant_message": "..." } ← only on the turn that reaches 100%
    // This removes the ~2-5s eval delay from the reply path.
    const res = await fetch(`/api/chat/${sessionId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...await csrfHeaders() },
      body: JSON.stringify({ message, detail_level: sendDetailLevel }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Request failed" }));
      throw new Error(err.detail || "Request failed");
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let replyHandled = false;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        let payload;
        try {
          payload = JSON.parse(line);
        } catch (err) {
          console.warn("Bad NDJSON line:", line, err);
          continue;
        }
        if (payload.phase === "reply") {
          removeThinking();
          appendMessage("assistant", payload.assistant_message, true, true);
          replyHandled = true;
        } else if (payload.phase === "eval") {
          updateProgress(payload);
          if (payload.new_achievements && payload.new_achievements.length > 0) {
            for (let i = 0; i < payload.new_achievements.length; i++) {
              setTimeout(() => showAchievement(payload.new_achievements[i]), i * 1500);
            }
          }
          flashSaveIndicator();
          if (payload.equilibrium_score >= 0.999 && !celebrationShown) {
            celebrationShown = true;
            showCelebration(payload);
          }
        } else if (payload.phase === "closing") {
          deliverClosing(payload.assistant_message);
        }
      }
    }

    if (!replyHandled) {
      removeThinking();
      appendMessage("assistant", "*Error: empty response from server.*");
    }
    // Stream ended without the promised closing: stop waiting for it
    if (closingState && closingState.message === undefined) deliverClosing(null);
  } catch (e) {
    if (closingState && closingState.message === undefined) deliverClosing(null);
    removeThinking();
    appendMessage("assistant", `*Error: ${e.message}*`);
  }

  sending = false;
  document.getElementById("send-btn").disabled = false;
  document.getElementById("chat-input").focus();

  // Restart STT if it was active before sending
  if (wasSTTActive && sttWanted && sessionId === microphoneSessionId
      && document.getElementById("chat-input") === input) {
    startSTT();
  }
}

// ── Rewind ───────────────────────────────────────────────────────
async function rewindTo(msgIndex) {
  if (sending) return;
  if (!confirm("Restart the conversation from this point? Messages after this will be removed.")) return;

  sending = true;
  try {
    const res = await api("POST", `/chat/${sessionId}/rewind`, { message_index: msgIndex });
    // Re-render conversation from the truncated history
    messageCount = 0;
    renderConversation(res.conversation || []);
    updateProgress(res);
    flashSaveIndicator();
  } catch (e) {
    alert("Rewind failed: " + e.message);
  }
  sending = false;
}

// ── Progress updates ─────────────────────────────────────────────
function updateProgress(res) {
  const pct = Math.round(res.equilibrium_score * 100);

  // Animate progress bar
  const bar = document.getElementById("eq-bar");
  const pctEl = document.getElementById("eq-pct");
  const bigEl = document.getElementById("eq-big");
  const summaryEl = document.getElementById("eq-summary");

  if (bar) bar.style.width = pct + "%";
  if (pctEl) pctEl.textContent = pct + "%";
  if (bigEl) {
    // Animate number counting up
    const prev = previousEqScore;
    animateNumber(bigEl, Math.round(prev * 100), pct, 1000);
    previousEqScore = res.equilibrium_score;
  }
  if (summaryEl) summaryEl.textContent = res.eval_summary || "";

  // XP with bounce
  const xpEl = document.getElementById("xp-value");
  if (xpEl) {
    animateNumber(xpEl, parseInt(xpEl.textContent) || 0, res.xp, 800);
  }

  const levelEl = document.getElementById("level-value");
  if (levelEl) levelEl.textContent = res.level;

  const engagedEl = document.getElementById("engaged-count");
  if (engagedEl) {
    const count = (res.nodes || []).filter(n => n.resolved).length;
    engagedEl.textContent = count;
  }

  // Update node map
  renderNodeMap(res.nodes || [], res.frontier || []);

  // Show score change float if significant
  if (res.equilibrium_score - previousEqScore > 0.02) {
    showScoreChange(res.equilibrium_score - previousEqScore);
  }
}

function animateNumber(el, from, to, duration) {
  const start = performance.now();
  const diff = to - from;
  function step(now) {
    const t = Math.min((now - start) / duration, 1);
    const ease = 1 - Math.pow(1 - t, 3); // ease-out cubic
    el.textContent = Math.round(from + diff * ease) + "%";
    if (t < 1) requestAnimationFrame(step);
  }
  // Fix: only add % for the big display
  function stepRaw(now) {
    const t = Math.min((now - start) / duration, 1);
    const ease = 1 - Math.pow(1 - t, 3);
    el.textContent = Math.round(from + diff * ease);
    if (t < 1) requestAnimationFrame(stepRaw);
  }
  if (el.id === "eq-big") {
    requestAnimationFrame(step);
  } else {
    requestAnimationFrame(stepRaw);
  }
}

function showScoreChange(delta) {
  const big = document.getElementById("eq-big");
  if (!big) return;
  const float = document.createElement("div");
  float.className = "score-change";
  float.textContent = `+${Math.round(delta * 100)}%`;
  float.style.left = big.offsetLeft + big.offsetWidth / 2 + "px";
  float.style.top = big.offsetTop + "px";
  big.parentElement.style.position = "relative";
  big.parentElement.appendChild(float);
  setTimeout(() => float.remove(), 1500);
}

// ── Achievements ─────────────────────────────────────────────────
function showAchievement(ach) {
  const toast = document.createElement("div");
  toast.className = "achievement-toast";
  toast.innerHTML = `
    <div class="ach-label">Achievement Unlocked</div>
    <div class="ach-title">${ach.name}</div>
    <div class="ach-desc">${ach.desc}</div>`;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

// ── Celebration ──────────────────────────────────────────────────
// Shown when equilibrium reaches 100%. When a follow-up closing message is
// on its way (res.closing_pending), the overlay stays up while it is
// generated and hands over to it when dismissed.
function showCelebration(res) {
  const nodes = res.nodes || [];
  const turns = document.querySelectorAll("#messages .message.user").length;
  const closingPending = !!res.closing_pending;
  closingState = { message: closingPending ? undefined : null, overlayOpen: true };

  const overlay = document.createElement("div");
  overlay.className = "celebration-overlay";
  overlay.id = "celebration-overlay";
  const RING_R = 54;
  const RING_C = 2 * Math.PI * RING_R;
  overlay.innerHTML = `
    <canvas class="celebration-confetti"></canvas>
    <div class="celebration-card" role="dialog" aria-modal="true" aria-labelledby="celebration-title">
      <div class="celebration-ring">
        <svg viewBox="0 0 120 120" aria-hidden="true">
          <circle class="ring-track" cx="60" cy="60" r="${RING_R}"></circle>
          <circle class="ring-fill" cx="60" cy="60" r="${RING_R}"
            stroke-dasharray="${RING_C}" stroke-dashoffset="${RING_C}"></circle>
        </svg>
        <div class="ring-number" id="celebration-number">0%</div>
      </div>
      <h2 id="celebration-title">Erotetic Equilibrium Reached</h2>
      <p class="celebration-question" id="celebration-question"></p>
      <div class="celebration-stats">
        <div class="celebration-stat"><span class="stat-value">${nodes.length}/${nodes.length}</span><span class="stat-label">questions resolved</span></div>
        <div class="celebration-stat"><span class="stat-value">${turns}</span><span class="stat-label">turns</span></div>
        <div class="celebration-stat"><span class="stat-value">${res.level ?? ""}</span><span class="stat-label">level</span></div>
        <div class="celebration-stat"><span class="stat-value">${res.xp ?? ""}</span><span class="stat-label">XP</span></div>
      </div>
      <p class="celebration-text">Your view has now been tested against every question in this
      inquiry complex, and it holds. Raising any of them again would not unsettle it. That is what
      it means for a judgment to be in equilibrium: not that it can never be revised, but that it
      has earned its stability.</p>
      <div class="celebration-status" id="celebration-status"></div>
      <button class="celebration-close" id="celebration-close" onclick="closeCelebration()"></button>
    </div>`;
  document.body.appendChild(overlay);
  document.getElementById("celebration-question").textContent =
    currentCentralQuestion ? `“${currentCentralQuestion}”` : "";
  updateCelebrationStatus();

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const numberEl = document.getElementById("celebration-number");
  if (reduceMotion) {
    overlay.querySelector(".ring-fill").style.strokeDashoffset = "0";
    numberEl.textContent = "100%";
  } else {
    // Ring sweeps from the previous score up to 100
    requestAnimationFrame(() => {
      overlay.querySelector(".ring-fill").style.strokeDashoffset = "0";
    });
    const start = performance.now();
    const step = (now) => {
      const t = Math.min((now - start) / 1800, 1);
      numberEl.textContent = Math.round(100 * (1 - Math.pow(1 - t, 3))) + "%";
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
    setTimeout(() => runConfetti(overlay.querySelector(".celebration-confetti")), 1500);
  }
  document.getElementById("celebration-close").focus({ preventScroll: true });
}

function updateCelebrationStatus() {
  const statusEl = document.getElementById("celebration-status");
  const btn = document.getElementById("celebration-close");
  if (!statusEl || !btn || !closingState) return;
  if (closingState.message === undefined) {
    statusEl.innerHTML = `Preparing your closing reflections<span class="celebration-dots"><span>.</span><span>.</span><span>.</span></span>`;
    btn.textContent = "Back to the conversation";
    btn.classList.add("secondary");
  } else if (closingState.message) {
    statusEl.textContent = "Your closing reflections are ready.";
    btn.textContent = "Read your closing reflections";
    btn.classList.remove("secondary");
  } else {
    statusEl.textContent = "";
    btn.textContent = "Back to the conversation";
    btn.classList.remove("secondary");
  }
}

function closeCelebration() {
  const overlay = document.getElementById("celebration-overlay");
  if (overlay) overlay.remove();
  if (!closingState) return;
  closingState.overlayOpen = false;
  if (closingState.message === undefined) {
    showThinking();  // closing still being generated
  } else {
    appendClosing();
  }
}

function deliverClosing(message) {
  if (!closingState) closingState = { overlayOpen: false };
  closingState.message = message || null;
  if (closingState.overlayOpen) {
    updateCelebrationStatus();
  } else {
    appendClosing();
  }
}

async function appendClosing() {
  const message = closingState && closingState.message;
  closingState = null;
  removeThinking();
  if (!message) return;
  // Let the previous reply finish being read aloud before the closing starts
  if (ttsEnabled && ttsAutoPlay) {
    const deadline = Date.now() + 60000;
    while ((currentAudio || ttsAbortController) && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 300));
    }
  }
  appendMessage("assistant", message, true, true);
}

function runConfetti(canvas) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.width = window.innerWidth * dpr;
  const h = canvas.height = window.innerHeight * dpr;
  const colors = ["#fdcb6e", "#6c5ce7", "#00b894", "#e4e4e7", "#a29bfe"];
  const pieces = [];
  for (let i = 0; i < 140; i++) {
    const angle = Math.random() * Math.PI * 2;
    const speed = (4 + Math.random() * 9) * dpr;
    pieces.push({
      x: w / 2, y: h * 0.42,
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed - 5 * dpr,
      size: (4 + Math.random() * 5) * dpr,
      rot: Math.random() * Math.PI,
      vr: (Math.random() - 0.5) * 0.3,
      color: colors[i % colors.length],
    });
  }
  const start = performance.now();
  const DURATION = 4500;
  function frame(now) {
    if (!canvas.isConnected) return;
    const t = now - start;
    ctx.clearRect(0, 0, w, h);
    ctx.globalAlpha = Math.max(0, 1 - Math.max(0, t - 3000) / 1500);
    for (const p of pieces) {
      p.vy += 0.18 * dpr;
      p.vx *= 0.99;
      p.x += p.vx; p.y += p.vy; p.rot += p.vr;
      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rot);
      ctx.fillStyle = p.color;
      ctx.fillRect(-p.size / 2, -p.size / 4, p.size, p.size / 2);
      ctx.restore();
    }
    if (t < DURATION) requestAnimationFrame(frame);
    else ctx.clearRect(0, 0, w, h);
  }
  requestAnimationFrame(frame);
}

// ── Session management ───────────────────────────────────────────
async function deleteSession(event, id) {
  event.stopPropagation();
  if (!confirm("Delete this session? This cannot be undone.")) return;
  await api("DELETE", `/sessions/${id}`);
  showLanding();
}

// ── Save & Exit ──────────────────────────────────────────────────
function saveAndExit() {
  // Session is already auto-saved after every turn, so just go back
  stopSTT();
  stopTTS();
  sessionId = null;
  showLanding();
}

function flashSaveIndicator() {
  const el = document.getElementById("save-indicator");
  if (!el) return;
  el.textContent = "saved!";
  el.classList.add("flash");
  setTimeout(() => {
    el.textContent = "auto-saved";
    el.classList.remove("flash");
  }, 2000);
}

// ── Text-to-Speech ───────────────────────────────────────────────
// The server speaks with ElevenLabs or, when that is not available, the
// OpenAI voice; /api/tts/enabled says which. Audio plays progressively as
// MP3 chunks arrive from /api/tts via the MediaSource API, so playback
// starts on the first chunk (~200-500ms), not after the whole file.
// Falls back to blob download for browsers without audio/mpeg MSE support.

const playIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>';
const pauseIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>';
let ttsCancelled = false;
let ttsAbortController = null;

function ttsStreamingSupported() {
  return typeof window.MediaSource !== "undefined"
      && window.MediaSource.isTypeSupported("audio/mpeg");
}

function stopTTS() {
  ttsCancelled = true;
  if (ttsAbortController) {
    try { ttsAbortController.abort(); } catch (e) {}
    ttsAbortController = null;
  }
  if (currentAudio) {
    try { currentAudio.pause(); } catch (e) {}
    currentAudio = null;
  }
  document.querySelectorAll(".msg-play-btn.playing").forEach(b => {
    b.classList.remove("playing");
    b.innerHTML = playIcon;
  });
}

function getRecentMessages(count) {
  const msgs = [];
  const bubbles = document.querySelectorAll("#messages .message");
  const start = Math.max(0, bubbles.length - count);
  for (let i = start; i < bubbles.length; i++) {
    const el = bubbles[i];
    const role = el.classList.contains("user") ? "user" : "assistant";
    const bubble = el.querySelector(".message-bubble");
    if (bubble) {
      const clone = bubble.cloneNode(true);
      clone.querySelectorAll("button").forEach(b => b.remove());
      msgs.push({ role, content: clone.textContent.trim() });
    }
  }
  return msgs;
}

async function emotionalizeText(text) {
  const recent = getRecentMessages(10);
  const resp = await fetch("/api/tts/emotionalize", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...await csrfHeaders() },
    body: JSON.stringify({ text, recent_messages: recent }),
    signal: ttsAbortController ? ttsAbortController.signal : undefined,
  });
  if (!resp.ok) throw new Error("Emotionalize failed");
  const data = await resp.json();
  // ElevenLabs: the text comes back with emotion tags. OpenAI voice: the
  // text is unchanged and a delivery instruction comes with it.
  return { text: data.tagged_text || text, instructions: data.instructions || "" };
}

// Primary path: stream MP3 chunks into a MediaSource SourceBuffer so the
// audio element can begin playing before the network stream finishes.
function streamTTSMSE(text, instructions) {
  return new Promise((resolve, reject) => {
    const mediaSource = new MediaSource();
    const audio = new Audio();
    currentAudio = audio;
    const objectUrl = URL.createObjectURL(mediaSource);
    audio.src = objectUrl;

    const pending = [];
    let sourceBuffer = null;
    let streamComplete = false;
    let settled = false;
    let playStarted = false;

    function finish(err) {
      if (settled) return;
      settled = true;
      try { URL.revokeObjectURL(objectUrl); } catch (e) {}
      if (err && !ttsCancelled) reject(err); else resolve();
    }

    function pump() {
      if (settled || !sourceBuffer || sourceBuffer.updating) return;
      if (pending.length > 0) {
        try {
          sourceBuffer.appendBuffer(pending.shift());
        } catch (e) {
          finish(e);
        }
      } else if (streamComplete && mediaSource.readyState === "open") {
        try { mediaSource.endOfStream(); } catch (e) {}
      }
    }

    audio.onended = () => finish();
    audio.onerror = () => finish(new Error("audio playback error"));

    mediaSource.addEventListener("sourceopen", async () => {
      try {
        sourceBuffer = mediaSource.addSourceBuffer("audio/mpeg");
        sourceBuffer.addEventListener("updateend", () => {
          // Kick off playback as soon as the first chunk is buffered;
          // subsequent updateends just drain the pending queue.
          if (!playStarted) {
            playStarted = true;
            const p = audio.play();
            if (p) p.catch(() => {/* will retry on canplay */});
          }
          pump();
        });

        const resp = await fetch("/api/tts", {
          method: "POST",
          headers: { "Content-Type": "application/json", ...await csrfHeaders() },
          body: JSON.stringify({ text, instructions }),
          signal: ttsAbortController.signal,
        });
        if (!resp.ok) throw new Error("TTS request failed: " + resp.status);

        const reader = resp.body.getReader();
        while (true) {
          const { done: readerDone, value } = await reader.read();
          if (readerDone) {
            streamComplete = true;
            pump();
            break;
          }
          pending.push(value);
          pump();
        }
      } catch (e) {
        if (e.name === "AbortError" || ttsCancelled) finish();
        else finish(e);
      }
    });
  });
}

// Fallback: download the whole MP3 then play. Used when the browser
// doesn't support MediaSource for audio/mpeg.
async function playTTSBlob(text, instructions) {
  const resp = await fetch("/api/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...await csrfHeaders() },
    body: JSON.stringify({ text, instructions }),
    signal: ttsAbortController.signal,
  });
  if (!resp.ok) throw new Error("TTS request failed: " + resp.status);
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  currentAudio = audio;
  await new Promise((resolve, reject) => {
    audio.onended = () => { URL.revokeObjectURL(url); resolve(); };
    audio.onerror = (e) => { URL.revokeObjectURL(url); reject(e); };
    const p = audio.play();
    if (p) p.catch(reject);
  });
}

async function playTTS(btn) {
  const text = btn.dataset.text;
  if (!text) return;

  // Clicking the playing button stops playback
  if (currentAudio) {
    const wasPlayingBtn = btn.classList.contains("playing");
    stopTTS();
    if (wasPlayingBtn) return;
  }

  ttsCancelled = false;
  ttsAbortController = new AbortController();
  btn.classList.add("playing");
  btn.innerHTML = pauseIcon;

  try {
    let speechText = text;
    let instructions = "";
    if (ttsEmotions && !btn.dataset.directed) {
      // Delivery is decided for the whole reply at once: ElevenLabs v3 tags
      // must wrap a single coherent text, and the OpenAI voice takes one
      // instruction per request.
      const directed = await emotionalizeText(text);
      speechText = directed.text;
      instructions = directed.instructions;
      if (ttsCancelled) return;
    }
    if (ttsStreamingSupported()) {
      await streamTTSMSE(speechText, instructions);
    } else {
      await playTTSBlob(speechText, instructions);
    }
  } catch (e) {
    if (!ttsCancelled && e.name !== "AbortError") {
      console.error("TTS error:", e);
    }
  } finally {
    if (!ttsCancelled) {
      btn.classList.remove("playing");
      btn.innerHTML = playIcon;
      currentAudio = null;
      ttsAbortController = null;
    }
  }
}

function toggleAutoTTS() {
  if (!ttsEnabled) {
    alert("Voice output is not available. Check OPENAI_API_KEY in the env file.");
    return;
  }
  ttsAutoPlay = !ttsAutoPlay;
  updateSpeakerBtn();
}

function updateSpeakerBtn() {
  const btn = document.getElementById("speaker-btn");
  if (!btn) return;
  if (!ttsEnabled) {
    btn.style.opacity = "0.3";
    btn.title = "Voice output not available (check OPENAI_API_KEY in the env file)";
  } else if (ttsAutoPlay) {
    btn.classList.add("active");
    btn.title = `Auto-read responses: ON (click to disable). Voice: ${ttsProviderLabel}`;
  } else {
    btn.classList.remove("active");
    btn.title = `Auto-read responses: OFF (click to enable). Voice: ${ttsProviderLabel}`;
  }
}

function toggleEmotions() {
  if (!ttsEnabled) {
    alert("Voice output is not available. Check OPENAI_API_KEY in the env file.");
    return;
  }
  ttsEmotions = !ttsEmotions;
  updateEmotionBtn();
}

function updateEmotionBtn() {
  const btn = document.getElementById("emotion-btn");
  if (!btn) return;
  if (!ttsEnabled) {
    btn.style.opacity = "0.3";
    btn.title = "TTS not configured";
  } else if (ttsEmotions) {
    btn.classList.add("active");
    btn.title = "Expressive TTS: ON (click to disable)";
  } else {
    btn.classList.remove("active");
    btn.title = "Expressive TTS: OFF (click to enable)";
  }
}

// ── Speech-to-Text (Web Speech API) ─────────────────────────────
function toggleMic() {
  if (sttWanted) {
    sttWanted = false;
    stopSTT();
  } else {
    sttWanted = true;
    startSTT();
  }
}

function updateMicBtn() {
  const btn = document.getElementById("mic-btn");
  if (!btn) return;
  btn.classList.toggle("active", sttActive);
  btn.setAttribute("aria-pressed", String(sttWanted));
  btn.title = !sttWanted ? "Voice input: OFF (click to enable)"
    : sttActive ? "Voice input: ON — listening (click to turn off)"
    : recognition ? "Voice input: starting (click to turn off)"
    : "Voice input: paused (click to turn off)";
}

function startSTT() {
  if (recognition || !sttWanted || !sessionId) return;
  const input = document.getElementById("chat-input");
  const micBtn = document.getElementById("mic-btn");
  if (!input || !micBtn) return;  // Never capture outside a rendered chat.
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    // Only interrupt with a message when the user asked for the mic themselves
    if (window.event && window.event.type === "click" && window.event.target.closest("#mic-btn")) {
      alert("Speech recognition is not supported in this browser. Please use Chrome or Edge.");
    }
    sttWanted = false;
    updateMicBtn();
    return;
  }

  const instance = new SpeechRecognition();
  recognition = instance;
  instance.continuous = true;
  instance.interimResults = true;
  instance.lang = "en-US";

  sttFinalTranscript = "";
  const myGeneration = ++sttGeneration;
  const isCurrent = () => recognition === instance && myGeneration === sttGeneration
    && sttWanted && document.getElementById("chat-input") === input;
  updateMicBtn();

  instance.onstart = () => {
    if (!isCurrent()) {
      // A late start after Off/Exit must not begin capturing again.
      try { instance.abort(); } catch (e) {}
      return;
    }
    sttActive = true;
    updateMicBtn();
    input.placeholder = "Listening...";
  };

  instance.onresult = (event) => {
    if (!isCurrent() || !sttActive) return;
    let interim = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const transcript = event.results[i][0].transcript;
      if (event.results[i].isFinal) {
        sttFinalTranscript += transcript;
      } else {
        interim += transcript;
      }
    }
    input.value = sttFinalTranscript + interim;
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  };

  instance.onerror = (event) => {
    if (!isCurrent()) return;
    if (event.error !== "no-speech") {
      console.error("STT error:", event.error);
    }
    sttWanted = false;
    stopSTT();
  };

  instance.onend = () => {
    // Restart only this still-authorized instance after ordinary silence.
    if (isCurrent() && sttActive) {
      sttActive = false;
      updateMicBtn();
      try { instance.start(); } catch (e) { sttWanted = false; stopSTT(); }
    }
  };

  try {
    instance.start();
  } catch (e) {
    console.error("STT start error:", e);
    sttWanted = false;
    stopSTT();
  }
}

function stopSTT() {
  sttActive = false;
  sttFinalTranscript = "";
  ++sttGeneration;
  const instance = recognition;
  recognition = null;
  updateMicBtn();
  const input = document.getElementById("chat-input");
  if (input) input.placeholder = "Share your thoughts on this question...";
  if (instance) {
    // Abort stops listening without requesting a final transcription.
    try { instance.abort(); } catch (e) {}
  }
}

// ── Init ─────────────────────────────────────────────────────────
(async () => {
  try {
    const ttsStatus = await api("GET", "/tts/enabled");
    ttsEnabled = ttsStatus.enabled;
    ttsProviderLabel = ttsStatus.provider === "openai" ? "OpenAI" : "ElevenLabs";
    // Voice output and expressive delivery are on by default
    ttsAutoPlay = ttsEnabled;
    ttsEmotions = ttsEnabled;
    console.log("[ICChat] Voice output:", ttsEnabled ? ttsProviderLabel : "off", "-", ttsStatus.note || "");
  } catch (e) {
    ttsEnabled = false;
    console.warn("[ICChat] TTS check failed:", e.message, e);
  }
  showLanding();
})();
