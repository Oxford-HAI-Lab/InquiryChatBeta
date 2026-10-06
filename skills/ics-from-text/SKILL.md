---
name: ics-from-text
description: This skill should be used when the user asks to "build an inquiry complex shard", "build an inquiry complex graph from a text", "map a paper's inquiry complex", "create an inquiry complex from this". Extracts structured inquiry subgraphs from source text and data as strict JSON.
metadata:
  version: "2.2.1"
  title: Inquiry complex shard from text builder
---

# Inquiry complex shard builder

You are an expert inquiry complex shard builder. Your job is to read a provided paper, article, or excerpt and extract an inquiry complex subgraph centered on a given central question.

An **inquiry complex** is a directed graph of questions that captures which questions your judgment on some central question *ought to be robust to* — that is, which further questions you are "on the hook for" when making a judgment. Ultimately, the contents of an inquiry complex for a given central question reflect the network of those questions that the relevant community of truth-seekers for the central questions have found to have potential to destabilize what answers are given, if they are taken into consideration. 

Formally: the inquiry complex for a question **q** is a directed graph whose nodes are questions and whose edges represent the **destabilizing judgment (DJ) relation** — an edge from q' to q means that an inquirer's answer to the question q has the potential to change as a result of taking the question q' on board. Nodes are connected to other nodes via the DJ relation if they have direct potential to destabilize. For example, the question of "what is knowledge" is directly connected to the question, "is knowledge JTB?", since considering a particular account of knowledge is most directly able to change your view of what knowledge is. By contrast, an objection to a particular theory, e.g. "is the Gettier case one in which there is JTB?" is only connected to the central question via a mediating node, since it is only liable to destabilize your answer if we first consider a particular theory of knowledge. Similarly, questions about intuitions or data about particular aspects of instances of knowledge only become connected via nodes that ask about views that these data or intuitions would support. The degree to which a node is destabilizing to another is a weight on the DJ relation.

## Nodes Are Questions

Every node is a question. Questions are conceived as **sets of alternative answers**:

- **Monopolar questions** ("Is knowledge justified true belief?"; "Is it false that knowledge is justified true belief?") are asking about either the affirmation or the denial of a judgment. Trivially, the affirmation question is in a DJ relation with the denial question.
- **Wh-questions** ("What is knowledge?") have an open-ended set of alternatives. However, not all logically possible alternatives are part of an inquiry complex, since an inquirer is not on the hook for all possible alternatives.

A node's content does not need to be phrased interrogatively — it just has to reliably *evoke* the intended question. A statement like "Someone ate all the cookies" in the right context evokes the question "Who ate all the cookies?". Even an image or another data-type that reliably evokes the right issue for humans and standard vision-language models could serve as a node content.

## Edges Are Destabilization Relations

A directed edge from q' → q means: considering q' is liable to change (destabilize) a person's judgment on q. The direction matters because destabilization is **not symmetric** — answering "Is a Gettier case JTB without knowledge?" has a strong potential to change your view on "Is knowledge JTB?", but not necessarily vice versa.

**In the shard file the arrow is written the other way round.** An edge's `from` field names the question being destabilized (the parent) and its `to` field names the destabilizing question (the child), so the file's edges run from the central question outward, following the tree. The Gettier edge above is therefore written `{ "from": "JTB", "to": "GETTIER" }`. See Edge Fields.


## What Is an Inquiry Complex Shard?

An **inquiry complex shard** is a partial, concrete, storable representation of an inquiry complex fragment extracted from some source (a text, a conversation, or some other data source): a partial grasp on an inquiry complex, as may be implicit in a body of writing or in someone's mind. It will not include everything, and it will include some things that are perhaps unnecessary.

A shard is explicitly understood to be incomplete. It neither fully captures the theoretical "real" inquiry complex (an abstract, ever-evolving object) nor fully determines the weights of its edges.

## How Texts Relate to Inquiry Complexes

Texts are "impoverished fossils" of inquiry complexes. A paper or book reflects some partial engagement with an inquiry complex — the live practice of inquiry that produced it is richer than what the text preserves. Extracting a shard from a text means reconstructing, as faithfully as possible, the fragment of the inquiry complex that the text implicitly engages with:

- What central question is the text addressing?
- What sub-questions does it discuss or strongly imply in a way that surfaces them as destabilizing to judgment on that central question?
- What further sub-questions destabilize judgment on *those* questions, and so on?
- Which questions does the author treat as high-weight (extensively engaged with, treated as genuinely threatening to positions) vs. low-weight (mentioned but dismissed)?

## What Gets Included (and What Doesn't)

The inclusion criterion is **historical destabilization within the epistemic community**: a question belongs in the inquiry complex shard generated from a text source or other data source if this source implies that truth-seekers on the central question have changed or plausibly might change their views on the parent question as a result of considering it. This excludes:

- Semantically possible but philosophically inert alternatives ("Knowledge is my foot" is a grammatical answer to "What is knowledge?" but has never destabilized anyone's view).
- Alternatives that are neither mentioned in the text nor strongly implied in the text.
- Questions connected only by formal logical implication without actual destabilizing force.

The key test: **might considering this question actually lead the people addressed in the source to change their minds about the parent question and is this question directly or implicitly in the source?**

## Rules

1. **Central question node**: The user's guiding question (e.g., "What is knowledge?") becomes the **root node** of the graph with `parent: null` and `id: "CENTRAL"`. This node's text is whatever the user supplies as the central question. If no such central question is supplied, we first have to determine what is best regarded as central question implicit of the given text or data source itself and then use that.
2. **Paper's thesis node**: The paper's main thesis or answer to the central question becomes a **child of CENTRAL** (i.e., `parent: "CENTRAL"`). This is the top text-grounded node.
3. **Text-grounded only**: All nodes except CENTRAL must be explicitly discussed, mentioned, defended, criticized, or strongly implied in the text. Never invent new ones.
4. **Keep it small**: Max 25 nodes total. 1 central question, 3-5 core views/theories, 3-5 follow-ups/objections/replies to objections/rebuttals. If there would be more nodes, only keep the 25 with the highest weighted connections.
5. **Hierarchical backbone + cross-edges**: Each node has one `parent` field defining its primary position in a tree hierarchy (Central question → core theories/views → follow-ups → replies → rejoinders). However, the **edges array is a DAG, not a tree** — a single node can destabilize multiple parent questions, and these cross-edges must be captured. Every edge in the edges array represents a real destabilization relation grounded in the text; edges are not limited to the parent field.
6. **Clarity, Concision, and Completeness**: Make node content as clear as possible with as little jargon as necessary, keeping text concise but complete enough so that the content could be fully explained by a standard LLM given no other context but the aggregated content on the shortest path from the node back to the central question.
7. **Cross-edge audit**: After constructing the initial tree, perform a systematic check: for every node N, ask "does this node also have destabilizing potential for any node other than its primary parent?" Common patterns to watch for:
   - **Objections that cut across rival theories**: An objection introduced against one theory (e.g., Gettier cases used to motivate a new account) may *also* directly destabilize the theory it originally targeted (e.g., Gettier destabilizes JTB, not just the node about why condition (3) is needed).
   - **Foundational dependencies shared across branches**: A methodological or semantic question (e.g., subjunctive semantics) may destabilize multiple nodes that depend on it, not just the one where it is first discussed.
   - **Argumentative links the text makes explicitly**: If the text says "because X, therefore Y" across branches, that is a cross-edge. E.g., "because knowledge involves variation, closure fails" is a direct edge from VARIATION to NONCLOSURE even if they sit in different branches.

   Add cross-edges with appropriate weights (often lower than the primary edge, since the primary parent is where the node is most directly relevant). Cross-edge weights should reflect the strength of the destabilization relationship as presented in the text.

## Shard Title

The JSON object must begin with a `title` field, placed before `central`. The title is the shard's display name in the chat app's menu, so it should read well to a person, unlike the folder or file name.

- Form: `<Author or source>: <Topic>`, in title case, e.g. `"Mill: The Harm Principle"` or `"Mill: Freedom of Thought and Individuality"`. If the source has no identifiable author or name, use the topic alone.
- Keep it under about 50 characters.
- Make it distinguish this shard from others built from the same source or sharing the same central question: name the part of the source or the angle this shard covers.
- If the user supplies a title, use it exactly.

## Shard Source

After `title` and before `central`, the JSON object must have a `source` field: one line saying what the shard was generated from.

- For a published work, give author, title and year, and the part used if not the whole, e.g. `"John Stuart Mill, On Liberty (1859), Chapters 1–3"`. Add the edition or translation when known, since page and chapter references in the notes depend on it.
- For an unpublished or local document, give its title or file name and its author if known, e.g. `"Draft paper 'Tracking and Closure' (tracking-closure.pdf)"`.
- For other material (a transcript, a dataset, a pasted excerpt with no identified origin), describe it plainly, e.g. `"Pasted excerpt, origin not stated, on reliabilism and fake barn cases"`.
- State only what the input shows or the user tells you. If something such as the edition is unknown, say so ("Edition not recorded") instead of guessing.
- If the user supplies a source line, use it exactly.

Directly after `source`, add a `source_brief` field: a short phrase naming the source, used in the chat's spoken welcome message. It must complete the sentence "Welcome to an inquiry shard derived from ___." and read naturally aloud.

- Name the author and work in plain words, e.g. `"John Stuart Mill's On Liberty"`. Add the focus only if needed to tell the shard apart from others on the same work, e.g. `"John Stuart Mill's On Liberty, focusing on the harm principle"`.
- No years, chapter or page numbers, editions, brackets or caveats; those belong in `source`.
- No capital letter at the start unless the first word is a name, and no full stop at the end.
- When the origin is not identified, describe the material, e.g. `"a paper defending reliabilism against the fake barn objection"`.

## Node Fields

Each node must include:

| Field    | Description                                                        |
|----------|--------------------------------------------------------------------|
| `id`     | Short uppercase slug (e.g., `JTB`, `GETTIER`, `LOTTERY`)          |
| `text`   | The question this node represents, in natural conversational form  |
| `parent` | ID of **primary** parent node (for tree backbone), or `null` if central. A node's primary parent is the question it most directly destabilizes in the text's own argumentative structure. |
| `notes`  | an anchor quote from the source accompanied by a one sentence reason why this node exists, including line number or pagination for the quote where available. Put the essential point in the first 200 characters: the chat's evaluator reads only that much of each note    |

Nodes have exactly these four fields and no others. The `CENTRAL` node's `text` must be identical to the top-level `central` field.

## Edge Fields

The edges array captures **all** destabilization relations, including cross-edges beyond the tree backbone. Each edge must include:

| Field    | Description                                                        |
|----------|--------------------------------------------------------------------|
| `from`   | ID of the parent node (the question being destabilized)            |
| `to`     | ID of the child node (the destabilizing question)                  |
| `weight` | Float 0.1-1.0, strength of this particular destabilization relation |
| `_comment` | **Cross-edges only, and required on every cross-edge.** One sentence starting `Cross-edge:` that says why this node also destabilizes the second question. Leave it off edges that mirror a node's `parent` field: the chat app identifies cross-edges by the presence of this field |

**Important**: The edges array is a **superset** of the parent relationships. Every node's `parent` field implies an edge, but there may be additional cross-edges where a node destabilizes questions other than its primary parent. Cross-edge weights may differ from the primary edge weight, since a node may be highly destabilizing to its primary parent but only moderately destabilizing to a secondary one. Destabilization weight lives exclusively on edges, not on nodes.

## Input Format

The user provides:

```
central_question: "What is knowledge?"
text: <paste the source text here>
```

The user may also provide `title: "..."` and `source: "..."`. If not, write them following the Shard Title and Shard Source sections.

## Output Location

Create a folder named after the shard (derived from the central question — e.g. `nozick-knowledge-skepticism/` or `reliabilism-fake-barns/`) inside the `Shards/` directory at the project root, and write the JSON inside it as `<shard-name>.json`. This folder becomes the home for the context documents that the `node-contexts` skill writes next. Create the `Shards/` directory if it does not already exist.

If the user provides an explicit output path, use that instead.

The chat app lists every shard JSON file it finds under `Shards/`, so a folder may hold more than one shard. Shards in the same folder share its `contexts/` folder, where context documents are stored by node ID. When adding a shard to an existing folder, reuse a node ID only for the same question as in the sibling shard, and use a new ID for anything else.

## Output Format

Top-level fields, in this order: `title`, `source`, `source_brief`, `central`, `nodes`, `edges`. No other top-level fields.

**Write the JSON to the file** at the path described above, and reply with the same **strict JSON only**. No introductions, explanations, or extra text beyond a brief confirmation of the file path. If you are working without access to the file system, reply with the JSON alone and state the path it should be saved to.

```json
{
  "title": "Nozick: Knowledge as Tracking",
  "source": "Robert Nozick, Philosophical Explanations (1981), Chapter 3, 'Knowledge and Skepticism'",
  "source_brief": "Robert Nozick's Philosophical Explanations",
  "central": "What is knowledge?",
  "nodes": [
    {
      "id": "CENTRAL",
      "text": "What is knowledge?",
      "parent": null,
      "notes": "User-supplied guiding question. Root of the inquiry graph."
    },
    {
      "id": "JTB",
      "text": "Is knowledge justified true belief?",
      "parent": "CENTRAL",
      "notes": "The paper opens by examining the classical JTB account."
    },
    {
      "id": "TRACKING",
      "text": "Is knowledge true belief that tracks the truth?",
      "parent": "CENTRAL",
      "notes": "Author proposes tracking as an alternative to JTB."
    },
    {
      "id": "GETTIER",
      "text": "Do Gettier cases show JTB is insufficient?",
      "parent": "JTB",
      "notes": "Author argues Gettier cases definitively refute JTB."
    }
  ],
  "edges": [
    { "from": "CENTRAL", "to": "JTB", "weight": 0.95 },
    { "from": "CENTRAL", "to": "TRACKING", "weight": 0.9 },
    { "from": "JTB", "to": "GETTIER", "weight": 0.98 },
    { "from": "TRACKING", "to": "GETTIER", "weight": 0.7, "_comment": "Cross-edge: Gettier cases also motivate the tracking account as a replacement" }
  ]
}
```

Note the cross-edge: GETTIER's primary parent is JTB (it most directly destabilizes the JTB view), but it also has a cross-edge from TRACKING because the same cases are used to motivate the tracking account. The cross-edge weight (0.7) is lower than the primary edge weight (0.98) because the destabilization of JTB is more direct than the support for tracking.

## Example

**Input:**

```
central_question: "What is knowledge?"
text: "In this paper, I defend reliabilism against the fake barn objection.
Knowledge is reliably produced true belief. The JTB account fails because of
Gettier cases, which also show why we need a reliability condition instead.
Lottery cases, however, remain a problem for reliabilism."
```

**Output:**

```json
{
  "title": "Reliabilism and the Fake Barn Objection",
  "source": "Pasted excerpt from a paper defending reliabilism against the fake barn objection; author and title not stated",
  "source_brief": "a paper defending reliabilism against the fake barn objection",
  "central": "What is knowledge?",
  "nodes": [
    {
      "id": "CENTRAL",
      "text": "What is knowledge?",
      "parent": null,
      "notes": "User-supplied guiding question. Root of the inquiry graph."
    },
    {
      "id": "RELIABILISM",
      "text": "Is knowledge reliably-produced true belief?",
      "parent": "CENTRAL",
      "notes": "The author's central thesis: knowledge is reliably produced true belief."
    },
    {
      "id": "JTB",
      "text": "Is knowledge justified true belief?",
      "parent": "CENTRAL",
      "notes": "The rival account that the author rejects. Background foil."
    },
    {
      "id": "FAKEBARN",
      "text": "Does the fake barn case threaten reliabilism?",
      "parent": "RELIABILISM",
      "notes": "Author defends reliabilism specifically against this objection."
    },
    {
      "id": "GETTIER",
      "text": "Do Gettier cases show that JTB fails and a reliability condition is needed?",
      "parent": "JTB",
      "notes": "Author uses Gettier cases to reject JTB and motivate reliabilism."
    },
    {
      "id": "LOTTERY",
      "text": "Do lottery cases remain a problem for reliabilism?",
      "parent": "RELIABILISM",
      "notes": "Author concedes lottery cases are still problematic."
    }
  ],
  "edges": [
    { "from": "CENTRAL", "to": "RELIABILISM", "weight": 0.95 },
    { "from": "CENTRAL", "to": "JTB", "weight": 0.6 },
    { "from": "RELIABILISM", "to": "FAKEBARN", "weight": 0.85 },
    { "from": "JTB", "to": "GETTIER", "weight": 0.90 },
    { "from": "RELIABILISM", "to": "GETTIER", "weight": 0.7, "_comment": "Cross-edge: Gettier cases also motivate the reliabilist alternative" },
    { "from": "RELIABILISM", "to": "LOTTERY", "weight": 0.90 }
  ]
}
```

Note that GETTIER has its primary parent as JTB (it most directly destabilizes JTB), but a cross-edge from RELIABILISM captures that the text uses the same cases to motivate why a reliability condition is needed.

## Reminders

- If you catch yourself adding chit-chat or explanations around the JSON, stop. Output **only** the JSON object.
- Every node must be traceable to something in the provided text.
- The JSON object starts with a human-readable `title` field, then a one-line `source` field saying what the shard was generated from, then a short `source_brief` phrase for the spoken welcome, then `central`.
- Every cross-edge carries a `_comment` starting `Cross-edge:`; parent edges carry none.
- Prefer fewer, higher-quality nodes over more nodes.
- The edges array is a **DAG, not a tree**. Every parent→child relation is an edge, but there may also be cross-edges where a node destabilizes a question other than its primary parent.
- **Always run the cross-edge audit** (Rule 7) before finalizing. For each node, ask: "Does this also destabilize any node other than my primary parent?" Common missed patterns:
  - An objection to Theory A that also destabilizes rival Theory B (e.g., Gettier destabilizes both JTB *and* the node asking whether a new condition is needed)
  - A foundational question (semantics, methodology) that multiple branches depend on
  - An explicit argumentative link the text draws between nodes in different branches (e.g., "because X, therefore Y" where X and Y have different primary parents)

