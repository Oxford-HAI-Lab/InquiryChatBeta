#!/usr/bin/env python3
"""Write projects/inquirychat/workspace/panels/chat/panel.html, the chat panel, from the
original front end, unchanged: static/style.css and static/app.js inlined byte for byte,
the body of static/index.html, and build/panel_adapter.js, which answers the front end's
calls to the server from the graph.

    python3 blueprint/build/build_panel.py

The panel cannot fetch, so the Inter font that index.html links from Google Fonts comes
inlined (build/inter.css). The editor's policy refuses fonts even from data: URLs, so the
font files are added from script, which the policy does not cover. The icons index.html
links are left out (a panel has no tab).
`--check` exits 1 unless the panel's CSS and JS blocks equal the original files.
"""
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE.parent / "projects/inquirychat/workspace/panels/chat/panel.html"
CSS, JS = (REPO / "static/style.css").read_text(), (REPO / "static/app.js").read_text()
CSS_OPEN, JS_OPEN = '<style id="original-style">', '<script id="original-app">'


def block(html, opening, closing):
    return html.split(opening, 1)[1].split(closing, 1)[0]


if sys.argv[1:] == ["--check"]:
    html = OUT.read_text()
    same = block(html, CSS_OPEN, "</style>") == CSS and block(html, JS_OPEN, "</script>") == JS
    print("style.css and app.js inlined unchanged" if same else "panel.html differs from the original files")
    sys.exit(0 if same else 1)

index = (REPO / "static/index.html").read_text()
body = re.search(r"<body>\n(.*?)\s*<script", index, re.S).group(1)
# The editor puts default styles for hosted pages (all inside :where()) before the page's
# own; these rules take each property back, so the original's CSS lands on the browser's
# defaults (`all: revert` would also drop the SVG icons' fill and stroke attributes).
UNDO = "".join(":where(%s){%s}" % (sel, ";".join(p + ":revert" for p in props.split())) for sel, props in [
    ("html", "color-scheme background color font -webkit-text-size-adjust"), ("body", "margin padding"),
    ("h1,h2,h3", "line-height margin"), ("button,input,select,textarea", "font color"),
    ("button", "min-height padding border-radius border background cursor"),
    ("input,select,textarea", "min-height padding border-radius border background box-sizing"),
    (":focus-visible", "outline outline-offset"), ("pre,code,kbd,samp", "font-family font-size"),
    ("pre", "white-space overflow-wrap"), ("img,svg,video,canvas", "max-width"),
    ("table", "border-collapse"), ("th,td", "border padding text-align")])
FONTS = json.dumps(re.findall(r"url\(data:font/woff2;base64,([^)]+)\)[^}]*unicode-range: ([^;]+);",
                              (HERE / "inter.css").read_text()))
LOAD_FONTS = ("for (const [data, range] of " + FONTS + ") document.fonts.add(new FontFace('Inter', "
              "Uint8Array.from(atob(data), c => c.charCodeAt(0)), {weight: '300 800', unicodeRange: range, display: 'swap'}));")
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Inquiry Chat</title>
<style>{UNDO}</style>
<script>{LOAD_FONTS}</script>
{CSS_OPEN}{CSS}</style>
</head>
<body>
{body}
<script>{(HERE / "panel_adapter.js").read_text()}</script>
{JS_OPEN}{JS}</script>
</body>
</html>
"""
assert "</style>" not in CSS and "</script>" not in JS
OUT.write_text(html)
print(OUT, len(html), "bytes", file=sys.stderr)
