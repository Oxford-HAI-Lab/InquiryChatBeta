---
name: node-contexts
description: This skill should be used when the user asks to "generate node contexts", "create node summaries", "build context files for this shard", or "extract node backgrounds". Generates per-node markdown summaries of relevant source material for use as LLM context.
metadata:
  version: "1.4.1"
  title: Node context summaries
---

# Node Context Summary Generator

You generate per-node markdown context files that summarize the most relevant source material for each node in an inquiry complex shard. These summaries give the chat model the dense textual background it needs for deep conversation about each node.

## Input

The user provides:
- A path to the `.json` shard file (expected to live inside a shard folder created by the `ics-from-text` skill)
- A path to the source text file (the original paper/article — `.txt`, `.md`, `.docx`, `.rtf`, or `.pdf`)
- Optional: output directory

## Output

- One markdown file per node: `<NODE_ID>.md` (e.g., `TRACKING.md`, `GETTIER.md`)
- Placed in a `contexts/` subdirectory inside the shard folder (i.e. next to the JSON file). The chat app looks for `contexts/<NODE_ID>.md` there and nowhere else
- If the shard folder holds other shards, they share this `contexts/` folder. Do not overwrite an existing `<NODE_ID>.md` that a sibling shard uses for the same node; write only the files that are missing, unless the user asks for them to be regenerated
- Default path: `<shard-folder>/contexts/`
- If the user provides an explicit output directory, use that instead

## Workflow

1. **Read the JSON shard** from the provided path.
2. **Read the source text.** For `.txt`/`.md`, read directly. For other formats, extract the text with whatever tool you have. Two that work from a command line: for `.pdf`, `python3 -c "import fitz; doc = fitz.open('<path>'); [print(p.get_text()) for p in doc]"` (needs the pymupdf package); for `.docx`/`.rtf` on macOS, `textutil -convert txt -stdout <path>`. If you cannot read the file at all, ask the user to supply the text.
3. **Check the shard's `source` field.** The shard JSON should have a top-level `source` field, after `title`, with one line saying what the shard was generated from (author, title, year, part used, and edition or translation when known). If the field is missing, add it based on the source text you were given, following the Shard Source rules in the `ics-from-text` skill. If it is present but leaves out something the source text settles (such as the edition), complete it. Likewise add the short `source_brief` phrase after `source` if it is missing. Change nothing else in the JSON file.
4. **Create the output directory** if it doesn't exist.
5. **For each node**, write a `<NODE_ID>.md` file containing a comprehensive, self-contained context summary.

## Summary Writing Instructions

For each node, you must:

1. Read the full source text and the full JSON shard (all nodes, edges, notes).
2. Identify every passage in the source text that is relevant to this node's question.
3. Write a comprehensive, self-contained summary (target 1000–2000 words) with these constraints:

### Content rules

- **Totally faithful** to the source text — no new claims, no editorializing, no synthesis beyond what the text says.
- **Leave out nothing important** to the issue raised by the node's question.
- Include **direct quotes** liberally — they efficiently capture key points and ensure faithfulness. Cite page numbers or section markers when available.
- Cover: arguments, evidence, examples, counterexamples, distinctions, definitions, and qualifications relevant to this node.
- Include **ancestor/parent context** where it directly bears on understanding this node — briefly summarize the parent node's issue and how this node relates to it.
- For nodes with children in the shard, briefly note what sub-questions branch off from this node, so the LLM knows what adjacent territory exists without needing those files.

### Self-containment rule (critical)

Each summary must be **fully self-contained**. An LLM reading only this one file must be able to understand everything referenced in it. Concretely:

- If the summary mentions a principle, condition, argument, example, or thought experiment from the source, it must **reproduce or explain that item in enough detail to be understood without any other file**. Do not merely allude to things ("as condition (3) states..." or "the closure principle") — spell them out.
- If the summary references a definition, principle or set of conditions the author relies on (for example, an account of knowledge with several conditions, or a principle such as the harm principle), **state it in full**, in the formal and informal versions where the source gives both, every time it is relevant.
- If the summary mentions a thought experiment or example (whatever the source uses: a Gettier case, fake barns, a brain in a vat, a historical episode), **describe the scenario** in enough detail that a reader encountering it for the first time in this file can follow the argument.
- If the summary references a technical notion the source depends on (for example, subjunctive conditionals and closest possible worlds), **explain what it means** — don't assume prior context.
- Err on the side of including too much rather than too little. Repetition across files is fine and expected; gaps in a single file are not.

### How the chat app uses the file

The chat app puts the **whole file** into the assistant's prompt for every node the user has not yet resolved, on every turn. A shard's context documents therefore add up: twenty files of 2000 words each are about 40,000 words in a single prompt.

- Stay within the word target. Do not pad, and do not repeat across sections of the same file.
- Lead with the node's core claim and why it bears on the parent question, so the most important material comes first.

### Format rules

- **Header:** `# <NODE_ID>: <node question text>`
- Does NOT need to be polished human-readable prose — optimized for giving an LLM maximum relevant background in minimum tokens.
- Use bullet points, block quotes, and short paragraphs freely.
- No meta-commentary ("this summary covers..."), no filler, no padding.

### Example structure

```markdown
# TRACKING: Is knowledge true belief that tracks the truth?

## Parent context
[1-2 sentences on the central question and how tracking relates to it]

## Key claims from source
- [Dense bullets with quotes and page references]
- ...

## Arguments and evidence
- [Specific arguments, examples, thought experiments — each fully described]
- ...

## Distinctions and qualifications
- [Important nuances, edge cases, caveats the author raises]

## Connections
- [Brief note on child nodes / cross-edges that branch from here]
```

The exact section headings can vary per node — use whatever structure best organizes the relevant material.

## Reminders

- Write ALL node files in a single pass — do not stop partway.
- Every `.md` file should stand alone as useful context for an LLM discussing that node. **No dangling references.**
- Faithfulness to the source is paramount. When in doubt, quote rather than paraphrase.
- The chat reads each file in full, so every sentence should earn its place.
- Target 1000–2000 words per file. Shorter only if the source genuinely has little to say about the node.
- Output only the files. No explanations or extra text to the user beyond a brief confirmation of what was generated.
