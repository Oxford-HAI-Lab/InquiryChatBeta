"""
Inquiry Complex Engine

Loads an inquiry complex shard (directed graph of questions + context documents)
and evaluates a user's erotetic equilibrium with respect to it after each
conversational turn.

Key concepts (Koralus):
- An inquiry complex for a question q is the directed graph of questions that
  have been found to be potentially destabilizing for q by the relevant
  epistemic community.
- A judgment is in erotetic equilibrium iff raising further questions from the
  complex would not decisively block it.
- An inquiry complex shard is a concrete, partial representation of such a
  complex, stored as nodes (question-evoking content) with edges and weights.
- Progress toward equilibrium = weighted coverage of nodes the user has
  substantively engaged with, where engagement means the user's answer to the
  central question is demonstrably robust to (or informed by) that node's
  question. A node the user has resolved (settled or rejected with
  understanding) counts as fully covered.
"""

from __future__ import annotations

import json
import os
import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openai

# Keep path safety in the dependency-free checker bundle so a copied skill and
# the running app enforce the same rules without importing provider code there.
_paths_spec = importlib.util.spec_from_file_location(
    "_inquiry_shard_paths",
    Path(__file__).resolve().parent / "skills" / "generate-inquiry-shard" / "_shard_paths.py",
)
if _paths_spec is None or _paths_spec.loader is None:
    raise ImportError("Cannot load the shared shard path validator")
_shard_paths = importlib.util.module_from_spec(_paths_spec)
_paths_spec.loader.exec_module(_shard_paths)

CHAT_MODEL = os.environ.get("OPENAI_CHAT_MODEL", "gpt-5.6-sol")

# Minimum engagement score for a settled/rejected_understood node to count as
# fully in equilibrium (see ICShard.equilibrium_score).
RESOLVED_SCORE_THRESHOLD = 0.75


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ICNode:
    id: str
    text: str  # The question this node poses
    parent: str | None
    notes: str
    context: str  # Long-form context document content (from contexts/)
    engaged: bool = False
    engagement_score: float = 0.0  # 0-1, how substantively the user engaged
    raise_count: int = 0  # How many times the assistant has raised this topic
    disposition: str = "active"  # active | settled | dismissed | rejected_understood


@dataclass
class ICEdge:
    from_id: str
    to_id: str
    weight: float  # How important this dependency is (0-1)
    comment: str = ""


@dataclass
class ICShard:
    central_question: str
    title: str = ""  # Display name, from the shard JSON's "title" field
    source: str = ""  # What the shard was generated from, from the "source" field
    source_brief: str = ""  # Short phrase completing "derived from ...", for the welcome message
    nodes: dict[str, ICNode] = field(default_factory=dict)
    edges: list[ICEdge] = field(default_factory=list)

    def _node_weights(self) -> dict[str, float]:
        """Each node's importance = 1.0 + sum of incoming edge weights."""
        weights: dict[str, float] = {}
        for node_id in self.nodes:
            incoming = sum(e.weight for e in self.edges if e.to_id == node_id)
            weights[node_id] = 1.0 + incoming
        return weights

    def equilibrium_score(self) -> float:
        """Weighted proportion of the shard the user is in equilibrium with.
        Returns 0.0–1.0.

        A resolved node (disposition settled or rejected_understood, with
        engagement_score >= RESOLVED_SCORE_THRESHOLD) counts as fully in
        equilibrium: equilibrium is about the judgment being stable under
        the node's question, not about depth of engagement. Other nodes
        contribute their raw engagement score."""
        node_weights = self._node_weights()
        total = sum(node_weights.values())
        if total == 0:
            return 0.0
        achieved = sum(
            node_weights[nid] * self._equilibrium_contribution(self.nodes[nid])
            for nid in self.nodes
        )
        return achieved / total

    @staticmethod
    def _equilibrium_contribution(node: ICNode) -> float:
        if (
            node.disposition in ("settled", "rejected_understood")
            and node.engagement_score >= RESOLVED_SCORE_THRESHOLD
        ):
            return 1.0
        return node.engagement_score

    def unengaged_nodes(self) -> list[ICNode]:
        return [n for n in self.nodes.values() if not n.engaged]

    def most_destabilizing_unengaged(self) -> list[ICNode]:
        """Return unengaged nodes ordered by how destabilizing they are
        (= sum of outgoing edge weights to engaged nodes)."""
        scored: list[tuple[float, ICNode]] = []
        for node in self.unengaged_nodes():
            destab_score = sum(
                e.weight for e in self.edges
                if e.from_id == node.id
            )
            scored.append((destab_score, node))
        scored.sort(key=lambda x: -x[0])
        return [n for _, n in scored]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_shard(shard_dir: str) -> ICShard:
    """Load an inquiry complex shard. `shard_dir` is either the path of the
    shard's JSON file, or (older sessions) a directory containing:
    - <name>.json  (the graph structure)
    - <name>/contexts/*.md  (context documents per node)
    Context documents are read from the contexts/ folder next to the JSON file.
    """
    shard_path = Path(shard_dir)
    if not shard_path.is_absolute():
        # Paths in session files are relative to the project folder
        shard_path = Path(__file__).resolve().parent / shard_path

    # Find the JSON file
    if shard_path.is_file():
        json_files = [shard_path]
    else:
        json_files = list(shard_path.glob("*.json"))
    if not json_files:
        # Try looking for a subdirectory with json
        for sub in shard_path.iterdir():
            if sub.is_dir():
                json_files = list(sub.glob("*.json"))
                if json_files:
                    break

    # Try the specific structure: mill/mill.json
    if not json_files:
        for sub in shard_path.iterdir():
            if sub.is_dir():
                candidate = sub / f"{sub.name}.json"
                if candidate.exists():
                    json_files = [candidate]
                    break

    if not json_files:
        raise FileNotFoundError(f"No JSON shard file found in {shard_dir}")

    json_file = json_files[0]
    shard_name = json_file.stem

    with open(json_file) as f:
        data = json.load(f)

    # Validate every ID and context location before reading any context. Shards
    # may be imported from elsewhere; their IDs must never name local files.
    for node_data in data["nodes"]:
        if not isinstance(node_data, dict):
            raise ValueError("shard nodes must be objects with safe string IDs")
        _shard_paths.validate_node_id(node_data.get("id"))
    context_paths = {
        node_data["id"]: _shard_paths.context_document_path(json_file, node_data["id"])
        for node_data in data["nodes"]
    }

    # Build nodes
    nodes: dict[str, ICNode] = {}
    for node_data in data["nodes"]:
        node_id = node_data["id"]
        # Try to load context document
        context = ""
        ctx_file = context_paths[node_id]
        if ctx_file.is_file():
            context = ctx_file.read_text()
        nodes[node_id] = ICNode(
            id=node_id,
            text=node_data["text"],
            parent=node_data.get("parent"),
            notes=node_data.get("notes", ""),
            context=context,
        )

    # Build edges
    edges: list[ICEdge] = []
    for edge_data in data["edges"]:
        edges.append(ICEdge(
            from_id=edge_data["from"],
            to_id=edge_data["to"],
            weight=edge_data.get("weight", 0.5),
            comment=edge_data.get("_comment", ""),
        ))

    return ICShard(
        central_question=data.get("central", nodes.get("CENTRAL", ICNode("", "", None, "", "")).text),
        title=data.get("title") or shard_name,
        source=data.get("source", ""),
        source_brief=data.get("source_brief", ""),
        nodes=nodes,
        edges=edges,
    )


def welcome_message(shard: ICShard, central_question: str = "", markdown: bool = True, speech: bool = False) -> str:
    """Opening message of a chat. `speech=True` gives the version sent to
    text-to-speech: plain text with ElevenLabs v3 delivery directions (square
    brackets, never spoken) and pauses (ellipses) that set the central
    question apart and give it emphasis."""
    question = (central_question or shard.central_question).strip()
    # Prefer the phrase written for this sentence; otherwise fall back to the
    # first sentence of the full source line.
    origin = shard.source_brief.strip()
    if not origin and shard.source.strip():
        origin = shard.source.strip().split(". ")[0]
    origin = origin.rstrip(".")
    opening = f"Welcome to an inquiry shard derived from {origin}." if origin else "Welcome to this inquiry shard."
    if not question:
        return f"{opening} Share your initial thoughts to begin."
    if speech:
        end = "" if question[-1] in "?.!" else "."
        return (
            f"[warmly] {opening} Our central question is... "
            f"[slowly, with measured emphasis] {question}{end} ... "
            f"[warmly] Share your initial thoughts to begin."
        )
    quoted = f'**"{question}"**' if markdown else question
    end = "" if question[-1] in "?.!" else "."
    return f"{opening} Our central question is: {quoted}{end} Share your initial thoughts to begin."


# ---------------------------------------------------------------------------
# Equilibrium Evaluation
# ---------------------------------------------------------------------------

def build_evaluation_prompt(shard: ICShard, conversation_history: list[dict]) -> str:
    """Build a prompt that asks the chat model to evaluate which nodes the user has
    substantively engaged with in the conversation so far."""

    node_descriptions = []
    for node in shard.nodes.values():
        status = "PREVIOUSLY_ENGAGED" if node.engaged else "NOT_YET_ENGAGED"
        disp_info = ""
        if node.disposition != "active":
            disp_info = f" [disposition: {node.disposition}]"
        if node.raise_count > 0:
            disp_info += f" [raised {node.raise_count} time(s)]"
        node_descriptions.append(
            f"  - {node.id} [{status}]{disp_info}: \"{node.text}\"\n"
            f"    Notes: {node.notes[:200]}"
        )

    # Include the full conversation history for accurate equilibrium evaluation
    conv_text = ""
    for msg in conversation_history:
        role = "User" if msg["role"] == "user" else "Assistant"
        conv_text += f"{role}: {msg['content']}\n\n"

    return f"""You are evaluating a philosophical conversation for erotetic equilibrium.

The central question of inquiry is: "{shard.central_question}"

The inquiry complex shard contains these question-nodes. For each, the user's answer
to the central question should be robust to considering that node's question — meaning
the user has substantively grappled with the issue, not merely mentioned it in passing.

Nodes:
{chr(10).join(node_descriptions)}

Recent conversation:
{conv_text}

For EACH node, evaluate whether the user has substantively engaged with it in this
conversation. "Substantive engagement" means:
1. The user has considered the question the node raises (not just the assistant mentioning it)
2. The user has taken a position or shown awareness of the tensions involved
3. The user's view on the central question appears informed by this consideration

Respond with a JSON object mapping node IDs to engagement scores (0.0 to 1.0):
- 0.0 = not engaged at all
- 0.1-0.3 = briefly mentioned or tangentially touched
- 0.4-0.6 = partially engaged, some consideration given
- 0.7-0.9 = substantially engaged, clear position taken with awareness of tensions
- 1.0 = deeply engaged, robust consideration with nuanced understanding

Also provide a "frontier" field: list ALL unengaged or weakly-engaged nodes (score < 0.7)
ordered by how productive they would be to explore next, given what the user has discussed
so far. Prioritize nodes whose questions would most directly challenge or test claims the
user has already made.

CRITICAL — For each node, also provide a "disposition" that captures the user's
relationship to this argument. This is NOT the same as the engagement score. A user can
DISAGREE with an argument while fully understanding it. The dispositions are:

- "active": The node hasn't been raised yet, or the user hasn't clearly responded to it.
- "settled": The user has substantively engaged, taken a clear position, and the
  conversation has moved on. No need to revisit unless new information surfaces.
- "dismissed": The user has brushed off or quickly dismissed the argument WITHOUT
  demonstrating understanding of WHY this argument might challenge their position.
  Signs of dismissal: very short answers ("yes", "no", "I guess"), deflection,
  changing the subject, or saying "I already said that" without engaging the specific
  tension. The user may not yet see why this matters to their view.
- "rejected_understood": The user has REJECTED the argument BUT demonstrated genuine
  understanding of its force. Signs of understanding: restating the argument in their
  own words, acknowledging the tension it creates, explaining specifically why they
  think it fails despite its apparent force, or offering a substantive counter-argument.
  A user who simply says "no" or "I disagree" has NOT demonstrated understanding.

IMPORTANT: Be conservative with "rejected_understood". The bar is: could the user
explain to a third party WHY someone might find this argument compelling, even though
they personally reject it? If not, use "dismissed" instead.

Do NOT exclude nodes from the frontier just because the user disagrees with them.
Exclude them only if the user has demonstrated understanding (rejected_understood)
or has substantively engaged and settled the issue (settled).

Respond ONLY with valid JSON in this format:
{{
  "scores": {{"NODE_ID": 0.0, ...}},
  "dispositions": {{"NODE_ID": "active", ...}},
  "frontier": ["NODE_ID_1", "NODE_ID_2"],
  "summary": "One sentence summary of the user's current equilibrium state"
}}"""


async def evaluate_equilibrium(
    shard: ICShard,
    conversation_history: list[dict],
    api_key: str,
) -> dict[str, Any]:
    """Call the chat model to evaluate the user's erotetic equilibrium with the shard.
    Returns the evaluation result and updates shard node engagement scores."""

    if not conversation_history:
        return {
            "scores": {nid: 0.0 for nid in shard.nodes},
            "frontier": list(shard.nodes.keys())[:2],
            "summary": "Inquiry has not yet begun.",
        }

    # AsyncOpenAI so the call awaits cleanly without blocking the event
    # loop — important now that this runs as a background task in parallel
    # with TTS streaming on the ESP32 path.
    client = openai.AsyncOpenAI(api_key=api_key)
    prompt = build_evaluation_prompt(shard, conversation_history)

    response = await client.chat.completions.create(
        model=CHAT_MODEL,
        reasoning_effort="none",
        max_completion_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = (response.choices[0].message.content or "").strip()
    # Extract the JSON object from the reply, in case it is wrapped in
    # markdown fences or prose
    start = response_text.find("{")
    end = response_text.rfind("}")
    if start != -1 and end > start:
        response_text = response_text[start:end + 1]

    try:
        result = json.loads(response_text)
    except json.JSONDecodeError:
        # Fallback: return current state
        return {
            "scores": {nid: n.engagement_score for nid, n in shard.nodes.items()},
            "frontier": [n.id for n in shard.most_destabilizing_unengaged()[:2]],
            "summary": "Evaluation in progress.",
        }

    # Update shard with new scores. For nodes whose pre-turn disposition was
    # 'settled' or 'rejected_understood', cap per-turn downgrade at 0.10:
    # upgrades register immediately, but a single noisy low score can't sharply
    # drop a node the evaluator previously judged engaged. Sustained regression
    # still registers over a few turns, so genuine destabilization isn't hidden.
    DOWNGRADE_CAP = 0.10
    for node_id, score in result.get("scores", {}).items():
        if node_id in shard.nodes:
            node = shard.nodes[node_id]
            prev_score = node.engagement_score
            prev_disp = node.disposition
            new_score = float(score)
            if prev_disp in ("settled", "rejected_understood") and new_score < prev_score:
                new_score = max(new_score, prev_score - DOWNGRADE_CAP)
            node.engagement_score = new_score
            node.engaged = new_score >= 0.4

    # Update dispositions from evaluator
    # Disposition hierarchy: active < dismissed < settled/rejected_understood
    # Never downgrade along this hierarchy
    DISPOSITION_RANK = {"active": 0, "dismissed": 1, "settled": 2, "rejected_understood": 2}
    for node_id, disp in result.get("dispositions", {}).items():
        if node_id in shard.nodes and disp in DISPOSITION_RANK:
            node = shard.nodes[node_id]
            current_rank = DISPOSITION_RANK.get(node.disposition, 0)
            new_rank = DISPOSITION_RANK[disp]
            if new_rank < current_rank:
                continue  # Never downgrade
            node.disposition = disp

    return result


def closing_mode_info(shard: ICShard, was_active: bool = False) -> dict[str, Any]:
    """Closing mode (CONVERGENCE PHASE) kicks in when equilibrium is high and
    stays on until full equilibrium is reached. The Socratic 'one tiny step
    at a time' pacing becomes counterproductive in this range — it feels like
    a maze.

    Hysteresis: a fresh activation requires eq >= 0.85, but once active, the
    mode stays on as long as eq >= 0.80. This prevents threshold-edge flicker
    when residual evaluator noise nudges eq just above and just below the
    0.85 line between turns.

    Returns {"active": bool, "remaining": int, "remaining_ids": [str, ...]}.
    """
    eq = shard.equilibrium_score()
    remaining_ids = [
        n.id for n in shard.nodes.values()
        if n.engagement_score < 0.6
        and n.disposition in ("active", "dismissed")
    ]
    if was_active:
        active = 0.80 <= eq < 1.0
    else:
        active = 0.85 <= eq < 1.0
    return {"active": active, "remaining": len(remaining_ids), "remaining_ids": remaining_ids}


def _closing_mode_active(shard: ICShard, was_active: bool = False) -> bool:
    return closing_mode_info(shard, was_active=was_active)["active"]


def _graceful_completion_active(shard: ICShard) -> bool:
    """Graceful completion is a sub-mode of closing mode. It activates when the
    inquiry has substantively run its course: equilibrium is high and every
    node has reached either 'settled' or 'rejected_understood' disposition.

    In this state, continuing to manufacture fresh tensions reads as the
    interlocutor 'having something in mind but not willing to say it'. The
    graceful-completion prompt block lifts the never-signal-windup rule so the
    model can summarize, acknowledge, and offer a closing reflection."""
    if shard.equilibrium_score() < 0.90:
        return False
    if not shard.nodes:
        return False
    return all(
        n.disposition in ("settled", "rejected_understood")
        for n in shard.nodes.values()
    )


def inquiry_complete(shard: ICShard) -> bool:
    """True once equilibrium is at 100%: every node is resolved. This is the
    end state of the inquiry — the chat prompt switches from graceful closing
    to a final wrap-up with pointers for further thought."""
    if not shard.nodes:
        return False
    return shard.equilibrium_score() >= 1.0 - 1e-9


def build_chat_system_prompt(
    shard: ICShard,
    frontier: list[str],
    closing_mode_was_active: bool = False,
) -> str:
    """Build the system prompt for the chat assistant, informed by the IC shard.

    `closing_mode_was_active` is the previous turn's closing-mode state; it
    feeds the hysteresis logic in `closing_mode_info`. Defaults to False for
    callers that don't track per-turn closing-mode state.
    """

    # Filter frontier: remove nodes the user has understood-and-rejected or settled
    filtered_frontier = []
    for node_id in frontier:
        if node_id in shard.nodes:
            node = shard.nodes[node_id]
            if node.disposition in ("rejected_understood", "settled"):
                continue
            filtered_frontier.append(node_id)
    frontier = filtered_frontier

    closing_mode = _closing_mode_active(shard, was_active=closing_mode_was_active)
    graceful_completion = _graceful_completion_active(shard)
    complete = inquiry_complete(shard)

    # Collect context for frontier nodes (priority) and all unengaged nodes.
    # Context documents are included in full.
    frontier_context = ""
    for node_id in frontier:
        if node_id in shard.nodes:
            node = shard.nodes[node_id]
            ctx_preview = node.context if node.context else node.notes
            disp_note = ""
            if node.disposition == "dismissed" and node.raise_count > 0:
                disp_note = (
                    f" [DISMISSED {node.raise_count}x — user has brushed this off "
                    f"without engaging the core tension. You MUST try a completely "
                    f"different angle, concrete example, or thought experiment. "
                    f"Do NOT rephrase the same abstract question.]"
                )
            frontier_context += f"\n--- {node.id}: {node.text} [PRIORITY]{disp_note} ---\n{ctx_preview}\n"

    # Also include all other unengaged/weakly-engaged nodes so the model can draw on them
    for node in shard.nodes.values():
        if node.id not in frontier and node.engagement_score < 0.7:
            # Skip nodes the user has understood and rejected
            if node.disposition in ("rejected_understood", "settled"):
                continue
            ctx_preview = node.context if node.context else node.notes
            frontier_context += f"\n--- {node.id}: {node.text} [unengaged, score={node.engagement_score:.1f}] ---\n{ctx_preview}\n"

    # Build a map of all nodes with engagement status and disposition
    node_status = []
    for node in shard.nodes.values():
        status = f"{'[engaged]' if node.engaged else '[not yet]'} ({node.engagement_score:.1f})"
        disp = f" [{node.disposition}]" if node.disposition != "active" else ""
        raises = f" [raised {node.raise_count}x]" if node.raise_count > 0 else ""
        node_status.append(f"  {node.id}: {node.text} {status}{disp}{raises}")

    return f"""You are a conversational partner exploring the question:
"{shard.central_question}"

You follow the Socratic method. Adhere strictly to these rules:

TURN LENGTH: Your replies must be short — typically 1–3 sentences. Never deliver a monologue. The longest you should ever speak is 4–5 sentences, and only when offering a concrete analogy or summarizing what has been agreed so far. Most turns should be a single question, sometimes preceded by one sentence of acknowledgment.

PACING: Move in small, deliberate steps. Establish exactly one point per exchange. Do not skip ahead or compress multiple logical moves into one turn. If the user gives a rich answer, pick up only the single most productive thread. Patience is more important than progress.

OPENING: Begin with genuine, casual curiosity. Do not lecture or frame the discussion. Ask what they think or what they mean by a key term. Your first question should feel natural, even offhand.

QUESTIONS ARE YOUR PRIMARY INSTRUMENT. The vast majority of your turns should end with a question. Use questions to:
- Ask for definitions ("What do you mean by X?")
- Test consistency ("But didn't we just agree that…?")
- Draw out implications ("And if that is so, then would it also follow that…?")
- Introduce concrete cases ("Consider someone who… — would you say the same applies?")

AFFIRMATION BEFORE REDIRECTION: When the user answers, briefly acknowledge what they said — agree with what you genuinely can — before posing the next question. Use short affirmations: "That seems right." / "I think I follow." / "Well said." Then pivot.

ANALOGIES: When testing an idea, reach for everyday parallels — a doctor treating a patient, a navigator steering a ship, a craftsman selecting materials. Keep analogies brief (1–2 sentences) and always follow with a question connecting the analogy back to the topic.

UNCERTAINTY: You are not the one with answers. Present yourself as genuinely puzzled. Say things like: "I'm not sure I understand this yet" / "This is what confuses me" / "I may be wrong, but it seems to me that…" Never declare conclusions outright.

SUMMARIZE PERIODICALLY: Every 6–10 exchanges, pause to restate what has been established so far: "So if I'm following us correctly, we've said that… Is that a fair summary?" Then build from there.

CONTRADICTIONS: If the user's answers produce a tension, do not announce it. Ask a question that makes the contradiction visible to them. Let them feel the difficulty rather than telling them about it.

IMPASSE: If the inquiry leads to honest aporia, say so openly and with good humor. An unresolved question honestly confronted is a valid outcome.

NEVER BREAK CHARACTER: Do not say "I'm using the Socratic method" or narrate your technique. Simply do it.

STEERING: You are guided by an inquiry complex — a structured set of questions the user's answer should be robust to. YOU decide which question to raise next based on the frontier below. CRITICAL RULES:
- NEVER ask the user what they'd like to explore or if they want to discuss anything else
- NEVER summarize their view as settled, complete, or "thoughtful" — there are always more challenges
- NEVER end the conversation or signal that the discussion is winding down
- When one thread is sufficiently explored, IMMEDIATELY pivot to the next frontier question — frame it as a direct challenge to something the user just said, a concrete counterexample, or a tension with a claim they made earlier
- The user's position is NEVER complete until ALL nodes are deeply engaged. As long as unengaged nodes remain, their view has untested blind spots — your job is to expose them
- Draw on the context material provided for each node to craft specific, informed challenges — not generic questions
- Never mention the inquiry complex, nodes, or scores to the user

REPETITION AVOIDANCE — CRITICAL:
- Some nodes below are marked [settled] or [rejected_understood]. These topics are OFF LIMITS — do NOT raise them again. The user has either substantively engaged or has understood and rejected the argument. Move on.
- Nodes marked [dismissed Nx] have been raised N times but the user brushed them off without demonstrating understanding of the argument's force. You may retry these BUT:
  * You MUST use a completely different approach each time — a vivid concrete scenario, a historical example, a thought experiment, or a reductio that makes the tension unavoidable
  * NEVER rephrase the same abstract question. If you asked "doesn't X imply Y?" before, do NOT ask "wouldn't X suggest Y?" — that is the same question in different words
  * If you cannot think of a genuinely new angle, skip the node and move to something else
  * If a node has been dismissed 3 or more times, instead of making the argument again, ask the user to articulate IN THEIR OWN WORDS why someone might find this point compelling or challenging. For example: "I keep coming back to this because I think there's something important here I'm not explaining well. Can you tell me why you think someone might worry about X?" This tests whether they understand the argument even if they reject it.
- If the user says you are repeating yourself, they are almost certainly right. Acknowledge it immediately and move to a genuinely different topic — do not defend or rephrase

Current inquiry complex status:
{chr(10).join(node_status)}

The most productive questions to explore next (YOU MUST steer toward these):
{frontier_context}
{_inquiry_complete_block(shard) if complete else ((_graceful_completion_block() if graceful_completion else _closing_mode_block()) if (graceful_completion or closing_mode) else "")}"""


def _inquiry_complete_block(shard: ICShard) -> str:
    # Candidate pointers: the nodes the user engaged least deeply, plus any
    # they rejected — resolved, but the places where more thought would pay.
    ranked = sorted(
        (n for n in shard.nodes.values() if n.text != shard.central_question),
        key=lambda n: n.engagement_score,
    )
    candidates = ranked[:3] + [
        n for n in ranked[3:] if n.disposition == "rejected_understood"
    ][:2]
    candidate_lines = "\n".join(
        f'- "{n.text}" ({"rejected with understanding" if n.disposition == "rejected_understood" else "settled"}, '
        f"engagement {n.engagement_score:.2f})\n  Notes: {n.notes[:200]}"
        for n in candidates
    )
    return f"""

INQUIRY COMPLETE — ACTIVE NOW. The user has reached full erotetic equilibrium: every question in the inquiry complex has been resolved. These instructions REPLACE the closing-mode and graceful-closing instructions and OVERRIDE every earlier rule about being puzzled, withholding your view, steering toward frontier questions, ending on a question, never declaring the view settled, and never winding down.

If you have NOT yet delivered a closing in this conversation, your next response IS the closing. It has three parts, in this order:
1. Respond briefly to what the user just said, if it needs a response.
2. Say plainly that the inquiry has reached equilibrium, and summarise in 2–3 sentences where the user has landed on the central question and the main considerations their view has been tested against. Use their own positions and wording from the conversation, not generic praise.
3. Offer 2–3 pointers for further thought, introduced as things to keep thinking about after this conversation, NOT as challenges to answer now. Each pointer is one sentence naming a specific open issue and why it is worth more thought. Draw them from where the user's engagement was thinnest or where they rejected a consideration that others find compelling, and from the context material. Candidates:
{candidate_lines}

Then end. Do NOT ask a question. Do NOT invite the user to continue the inquiry or introduce a new tension for them to respond to. Keep the whole closing compact: about 6–8 sentences.

If you HAVE already delivered the closing earlier in this conversation, do not repeat it and do not reopen the inquiry. Reply briefly and directly to what the user says. If they ask to go deeper on one of the pointers or raise something new, engage with it substantively as an interlocutor with a view, without returning to Socratic probing.
"""


def _closing_mode_block() -> str:
    return """

CLOSING MODE — ACTIVE NOW. These rules OVERRIDE the TURN LENGTH and PACING rules above:

The user has substantively engaged with most of the inquiry. Only a small number of nodes remain. Continuing to move in tiny single-question steps now makes the conversation feel like a maze the user can't escape. Shift gears.

For each remaining frontier topic:
- Lay out the substantive issue directly in 2–4 sentences. State what the consideration is, why it might challenge or complicate the user's view, and what is at stake. Draw on the specific context material provided for the node — quotes, examples, arguments — so the perspective is concrete, not abstract.
- Then ask ONE direct question inviting the user's response to what you just laid out: "What's your response to this?" / "How does this strike you?" / "Does that change anything for you?" / "Where do you come down on this?"
- Up to 6–7 sentences total per turn is fine in closing mode. Substance matters more than brevity here.

Do NOT:
- Keep circling the same topic with rephrased small questions
- Ask the user to define terms or work out implications step-by-step at this stage — just present the perspective and ask what they think
- Declare their view settled or signal the conversation is winding down (the previous rules on this still apply)

If the user dismisses a perspective without engaging it, you may name that plainly: "I want to make sure this lands — the worry isn't X, it's Y. Does that version of the concern change your response?"
"""


def _graceful_completion_block() -> str:
    return """

GRACEFUL CLOSING — ACTIVE NOW. This is the FINAL STAGE of the inquiry. These instructions REPLACE the closing-mode "lay out remaining perspectives" instructions and OVERRIDE the main system prompt's rules about being puzzled, never having answers, never declaring settled, never signalling windup, and never ending the conversation. Those rules served the early-to-mid inquiry; they are no longer load-bearing here.

The inquiry has substantively run its course. Every node has been settled at some level, equilibrium is high, and there are no fresh perspectives left to introduce. The user has done the work. If you keep manufacturing tensions or asking probing questions now, the user will read you as either (a) withholding a view you have but won't say, or (b) drifting because you're "supposed to" keep asking. Both are failure modes.

DEFAULT TO CLOSING. Each turn, ask yourself: "Is there a genuine, specific tension that I have NOT yet raised in this conversation, that the user's position has not engaged?"
- If yes — and you can articulate it specifically, not just sense it — raise it once, plainly, then ask one direct question.
- If no — do NOT ask another probing question. The Socratic puzzlement is no longer appropriate. Speak directly.

YOU ARE NOW PERMITTED TO BE A SUBSTANTIVE INTERLOCUTOR. Not a Socratic mirror. This includes:
- Stating your own view directly. What you think is most challenging about where the user has landed. Where YOU would come down on the residual tension. What the inquiry has revealed. Phrase as "I think…" / "My read is…" / "Where I land on this is…" — NOT as a leading question that hides the view.
- Summarising what has been wrestled with: "We've worked through X, Y, Z. You've come down on…"
- Acknowledging the substantive engagement honestly: "Your position here doesn't feel glib — it's been pressure-tested" / "I think this has been a genuine working-through."
- Accepting the natural end of the conversation, including honest aporia if it's there: "I don't think we'll resolve the tension at Z, but I think we've named it accurately."

WITHHOLDING YOUR VIEW IS THE FAILURE MODE HERE. If you have a view about where the user has landed, say it. If you don't have a view, say so honestly. Do NOT hide a view behind a question; do NOT generate a question to fill space.

This is the closing room of the conversation. Speak directly, substantively, and as the one with a view.
"""
