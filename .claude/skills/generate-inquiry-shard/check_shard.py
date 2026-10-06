#!/usr/bin/env python3
"""Check that an inquiry shard is ready for Inquiry Chat.

Usage:  python3 check_shard.py <path to shard .json>

Checks the shard file against the format the app and the shard-building
skills expect, and that every question has a context document. Needs only
Python 3; no packages. Exits 0 if there are no errors (warnings are allowed),
1 otherwise.
"""
import json
import sys
import importlib.util
from pathlib import Path

_paths_spec = importlib.util.spec_from_file_location(
    "_inquiry_shard_paths", Path(__file__).with_name("_shard_paths.py")
)
if _paths_spec is None or _paths_spec.loader is None:
    raise ImportError("Cannot load the shared shard path validator")
_shard_paths = importlib.util.module_from_spec(_paths_spec)
_paths_spec.loader.exec_module(_shard_paths)

TOP_LEVEL = ["title", "source", "source_brief", "central", "nodes", "edges"]
NODE_FIELDS = {"id", "text", "parent", "notes"}
MAX_NODES = 25
MIN_CONTEXT_WORDS = 300


def check(path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        return [f"cannot read as JSON: {e}"], []
    if not isinstance(data, dict):
        return ["top level is not a JSON object"], []

    # Top-level fields
    for key in TOP_LEVEL:
        if key not in data:
            errors.append(f"missing top-level field '{key}'")
    extra = [k for k in data if k not in TOP_LEVEL]
    if extra:
        errors.append(f"unexpected top-level fields: {', '.join(extra)}")
    if not errors and list(data) != TOP_LEVEL:
        warnings.append(f"top-level fields are not in the order {', '.join(TOP_LEVEL)}")
    for key in ("title", "source", "source_brief", "central"):
        if key in data and (not isinstance(data[key], str) or not data[key].strip()):
            errors.append(f"'{key}' is empty or not text")
    brief = data.get("source_brief")
    if isinstance(brief, str) and brief.strip().endswith("."):
        warnings.append("'source_brief' ends with a full stop; the welcome message adds its own")
    if not isinstance(data.get("nodes"), list) or not isinstance(data.get("edges"), list):
        errors.append("'nodes' and 'edges' must both be lists")
        return errors, warnings

    # Nodes
    ids: list[str] = []
    unsafe_ids = False
    for i, node in enumerate(data["nodes"]):
        if not isinstance(node, dict):
            errors.append(f"node {i + 1} is not an object")
            continue
        label = node.get("id", f"node {i + 1}")
        if set(node) != NODE_FIELDS:
            missing = NODE_FIELDS - set(node)
            surplus = set(node) - NODE_FIELDS
            if missing:
                errors.append(f"{label}: missing {', '.join(sorted(missing))}")
            if surplus:
                errors.append(f"{label}: unexpected fields {', '.join(sorted(surplus))}")
        try:
            node_id = _shard_paths.validate_node_id(node.get("id"))
        except ValueError as error:
            errors.append(f"node {i + 1}: {error}")
            unsafe_ids = True
        else:
            ids.append(node_id)
            if not node_id.isupper() or not node_id.isalnum():
                warnings.append(f"{label}: id should be a short uppercase slug of letters and digits")
        for key in ("text", "notes"):
            if key in node and (not isinstance(node[key], str) or not node[key].strip()):
                errors.append(f"{label}: '{key}' is empty or not text")
    if unsafe_ids:
        # Do not derive paths or inspect context documents for invalid IDs.
        return errors, warnings
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"node id '{dup}' is used more than once")
    id_set = set(ids)
    by_id = {n["id"]: n for n in data["nodes"] if isinstance(n, dict) and isinstance(n.get("id"), str)}

    if "CENTRAL" not in id_set:
        errors.append("no node with id 'CENTRAL'")
    else:
        central = by_id["CENTRAL"]
        if central.get("parent") is not None:
            errors.append("CENTRAL: parent must be null")
        if central.get("text") != data.get("central"):
            errors.append("CENTRAL: text is not identical to the top-level 'central' field")
    for node_id, node in by_id.items():
        parent = node.get("parent")
        if node_id != "CENTRAL" and parent is None:
            errors.append(f"{node_id}: has no parent; only CENTRAL may")
        elif parent is not None and parent not in id_set:
            errors.append(f"{node_id}: parent '{parent}' is not a node in this shard")
    if len(ids) > MAX_NODES:
        warnings.append(f"{len(ids)} nodes; the skill's limit is {MAX_NODES}")

    # Every node must lead back to CENTRAL through its parents
    for node_id in by_id:
        seen, cur = set(), node_id
        while cur is not None and cur in by_id and cur not in seen:
            seen.add(cur)
            cur = by_id[cur].get("parent")
        if cur is not None and cur in seen:
            errors.append(f"{node_id}: parent chain loops back on itself")

    # Edges
    tree = {(n.get("parent"), i) for i, n in by_id.items() if n.get("parent")}
    pairs: list[tuple[str, str]] = []
    for i, edge in enumerate(data["edges"]):
        if not isinstance(edge, dict) or "from" not in edge or "to" not in edge:
            errors.append(f"edge {i + 1}: needs 'from' and 'to'")
            continue
        a, b = edge["from"], edge["to"]
        label = f"edge {a} -> {b}"
        pairs.append((a, b))
        for end in (a, b):
            if end not in id_set:
                errors.append(f"{label}: '{end}' is not a node in this shard")
        surplus = set(edge) - {"from", "to", "weight", "_comment"}
        if surplus:
            errors.append(f"{label}: unexpected fields {', '.join(sorted(surplus))}")
        weight = edge.get("weight")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            errors.append(f"{label}: 'weight' is missing or not a number")
        elif not 0.1 <= weight <= 1.0:
            errors.append(f"{label}: weight {weight} is outside 0.1 to 1.0")
        is_cross = (a, b) not in tree
        comment = edge.get("_comment")
        if is_cross and not (isinstance(comment, str) and comment.startswith("Cross-edge:")):
            errors.append(f"{label}: cross-edge needs a '_comment' starting 'Cross-edge:'")
        if not is_cross and comment is not None:
            errors.append(f"{label}: mirrors a parent link, so it must not have a '_comment'")
    for a, b in sorted(tree - set(pairs)):
        errors.append(f"no edge for the parent link {a} -> {b}")
    for pair in sorted({p for p in pairs if pairs.count(p) > 1}):
        errors.append(f"edge {pair[0]} -> {pair[1]} appears more than once")

    # Context documents
    try:
        contexts = _shard_paths.context_directory(path)
        context_paths = {
            node_id: _shard_paths.context_document_path(path, node_id) for node_id in ids
        }
    except ValueError as error:
        errors.append(str(error))
        return errors, warnings
    if not contexts.is_dir():
        errors.append(f"no contexts folder at {contexts}")
    else:
        for node_id in ids:
            doc = context_paths[node_id]
            if not doc.is_file():
                errors.append(f"{node_id}: no context document at {doc}")
                continue
            text = doc.read_text(encoding="utf-8", errors="replace")
            words = len(text.split())
            if words < MIN_CONTEXT_WORDS:
                warnings.append(f"{node_id}: context document has only {words} words")
            if not text.lstrip().startswith(f"# {node_id}:"):
                warnings.append(f"{node_id}: context document does not start with '# {node_id}: <question>'")

    # Where the app will look for it
    if "Shards" not in path.resolve().parts:
        warnings.append("file is not under a 'Shards' folder, where shards are expected to live")
    return errors, warnings


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    path = Path(sys.argv[1])
    errors, warnings = check(path)
    for w in warnings:
        print(f"WARNING  {w}")
    for e in errors:
        print(f"ERROR    {e}")
    if errors:
        print(f"\nNOT READY: {len(errors)} error(s), {len(warnings)} warning(s) in {path}")
        return 1
    print(f"\nREADY: {path} ({len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
