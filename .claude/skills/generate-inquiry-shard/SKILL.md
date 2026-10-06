---
name: generate-inquiry-shard
description: This skill should be used when the user asks to "generate an inquiry complex shard from X", "generate an inquiry shard from X", "make a shard I can chat with", or otherwise wants a complete, ready-to-use shard from a source in one go. Builds the shard JSON and the context document for every question by running the ics-from-text and node-contexts skills in turn, then checks the result is ready for the Inquiry Chat app.
metadata:
  version: "1.0.0"
  title: Generate a complete inquiry shard
---

# Generate a complete inquiry shard

You produce a complete inquiry shard from a source, ready to use in the Inquiry Chat app: the shard's JSON file and a context document for every question in it, in the right place under `Shards/`.

You do this by running two existing skills one after the other and then checking the result. This skill holds no format rules of its own. The rules for the shard file are in `ics-from-text`; the rules for context documents are in `node-contexts`. Follow those skills as written, apart from the changes to their reporting listed under each stage below.

## How to run the other skills

For each stage, load the named skill and follow its instructions in full:

- If your agent has a skill mechanism, invoke the skill by name.
- Otherwise read its file: `skills/ics-from-text/SKILL.md` and `skills/node-contexts/SKILL.md`, relative to the project folder.

Read each skill at the stage where you need it, not from memory of an earlier run, since the skills change.

## Input

The user gives a source, referred to here as X, and optionally a central question, a title, and an output folder.

| X is | What to do |
|---|---|
| A path to a file | Read it. For formats other than plain text, extract the text as `node-contexts` describes |
| Text pasted into the conversation | Use it as given |
| Several files or passages | Treat them together as one source, and name each of them in the shard's `source` line |
| Only the name of a work, with no text | Ask the user for the text or a file. Do not build a shard from memory of a work. If the user says to go ahead without the text, do so, and say in the `source` line that the shard was built from general knowledge of the work and not from its text |

If no central question is given, determine one from the source as `ics-from-text` describes.

Settle the input before starting. Once the source is in hand, run all four stages without stopping to ask for confirmation between them.

## Stage 1: Build the shard file

Run `ics-from-text` on the source.

Changes to that skill's reporting for this combined run:

- Write the JSON file. Do not also print the JSON in your reply.
- Do not stop after writing it. Go on to stage 2.

Where the file goes:

- Default: a new folder under `Shards/`, named after the shard, as `ics-from-text` describes.
- If `Shards/` already has a folder for the same source work, ask yourself whether this shard belongs beside the ones in it. If it does, put the new file in that folder, and follow the `ics-from-text` rule on node IDs for shards that share a folder.
- Never overwrite an existing shard file. If the name is taken, choose a name that says what is different about this shard.

## Stage 2: Write the context documents

Run `node-contexts`, giving it the shard file from stage 1 and the same source text.

Changes to that skill's reporting for this combined run:

- Do not stop after writing the files. Go on to stage 3.

Write a document for every node, `CENTRAL` included. If a shard has many nodes, keep going until all are written; a shard with some documents missing is not finished.

## Stage 3: Check the result

Run the checker on the shard file:

```
python3 skills/generate-inquiry-shard/check_shard.py "<path to the shard .json>"
```

It needs only Python 3. It prints `READY` or `NOT READY`, with a line for each error and warning.

- **Errors:** fix every one, in the shard file or the context documents as appropriate, and run the checker again. Repeat until it prints `READY`. Fix the content, never the checker.
- **Warnings:** fix them where the fix is clear. Otherwise leave them and include them in your report.

If you cannot run commands, make the same checks by reading the files:

1. The top-level fields are `title`, `source`, `source_brief`, `central`, `nodes`, `edges`, in that order, with no others, and none is empty.
2. Every node has exactly `id`, `text`, `parent` and `notes`. IDs are unique.
3. There is a `CENTRAL` node, its `parent` is null, and its `text` is identical to `central`. Every other node has a parent that is a node in the shard.
4. Every parent link has a matching edge. Every edge joins two nodes in the shard and has a weight from 0.1 to 1.0.
5. Every edge that does not mirror a parent link has a `_comment` starting `Cross-edge:`. No other edge has a `_comment`.
6. `contexts/<NODE_ID>.md` exists next to the shard file for every node.

Then say in your report that the checks were made by reading and not by running the checker.

## Stage 4: Report

Reply with a short report and nothing else. Do not print the JSON or the context documents.

1. **Whether the shard is ready**, stated first, and how that was checked.
2. **Title and central question.**
3. **Where it is:** the path of the shard file.
4. **Size:** the number of questions, the number of cross-edges, and the number of context documents written.
5. **The source line** as recorded in the shard, so the user can correct it.
6. **Anything the user should know:** warnings left unfixed, parts of the source that could not be read, a central question you had to determine yourself, or a source line that rests on a guess.
7. **How to use it:** reload the Inquiry Chat page in the browser; the shard appears in the menu under its title. The server does not need restarting.

## Rules

- The shard must be grounded in the source. Both skills require this; a combined run does not relax it.
- Do not change the app's code, other shards, or their context documents. If a context document you need already exists because a sibling shard uses the same node ID, leave it as it is, as `node-contexts` describes.
- If a stage fails and you cannot recover, stop and report what was written and what was not, so nothing half-finished is mistaken for a ready shard.
