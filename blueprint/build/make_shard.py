#!/usr/bin/env python3
"""Write the trimmed shard in blueprint/shard/: the original shard file unchanged,
with each context document cut to CAP characters (at the last whitespace before
CAP), so that the prompts fit a model window of 8,192 tokens."""
import json, pathlib, shutil, sys

CAP = 500
root = pathlib.Path(__file__).resolve().parents[2]
src = root / "Shards/mill-on-liberty/mill_thought_individuality.json"
out = root / "blueprint/shard"
(out / "contexts").mkdir(parents=True, exist_ok=True)
shutil.copyfile(src, out / src.name)
for node in json.loads(src.read_text())["nodes"]:
    text = (src.parent / "contexts" / f"{node['id']}.md").read_text()
    if len(text) > CAP:
        text = text[:CAP].rsplit(None, 1)[0] + "\n"
    (out / "contexts" / f"{node['id']}.md").write_text(text)
print(out / src.name, CAP, file=sys.stderr)
