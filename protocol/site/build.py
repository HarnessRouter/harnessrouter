#!/usr/bin/env python3
"""Build the unifiedharnessprotocol.io site from the specification.

The site is GENERATED from the markdown in protocol/, never written separately. A hand-maintained
copy of a specification is a second specification, and the two only ever agree on the day they are
written — the whole point of the standard is that there is one source for what the protocol says.

    python protocol/site/build.py            # build into protocol/site/dist
    python protocol/site/build.py --serve    # build, then serve on :8000 for review

Output is plain static HTML with no build chain and no runtime dependencies, so it can be published
to any static host.
"""
from __future__ import annotations

import html
import pathlib
import re
import shutil
import sys

try:
    import markdown
except ImportError:  # pragma: no cover
    sys.exit("Python-Markdown is required: pip install markdown")

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent                        # protocol/
DIST = HERE / "dist"
VERSION = "2026-08-11"
SITE = "unifiedharnessprotocol.io"

# ── information architecture ────────────────────────────────────────────────────────────
# Mirrors the shape a protocol site is expected to have — an introduction, a versioned
# specification, the machine-readable definitions, conformance, and the change process — so a
# developer arriving from another protocol's docs already knows where things are.
NAV = [
    ("Introduction", [
        ("index.html", "What is UHP?", ROOT / "README.md"),
    ]),
    (f"Specification · {VERSION}", [
        ("spec/index.html", "Overview", ROOT / f"versions/{VERSION}/index.md"),
        ("spec/architecture.html", "Architecture", ROOT / f"versions/{VERSION}/architecture.md"),
        ("spec/lifecycle.html", "Lifecycle", ROOT / f"versions/{VERSION}/lifecycle.md"),
        ("spec/harnesses.html", "Harnesses", ROOT / f"versions/{VERSION}/harnesses.md"),
        ("spec/tasks.html", "Tasks", ROOT / f"versions/{VERSION}/tasks.md"),
        ("spec/streaming.html", "Streaming", ROOT / f"versions/{VERSION}/streaming.md"),
        ("spec/sessions.html", "Sessions", ROOT / f"versions/{VERSION}/sessions.md"),
        ("spec/files.html", "Files", ROOT / f"versions/{VERSION}/files.md"),
        ("spec/errors.html", "Errors", ROOT / f"versions/{VERSION}/errors.md"),
        ("spec/security.html", "Security", ROOT / f"versions/{VERSION}/security.md"),
        ("spec/schema.html", "Schema", ROOT / f"versions/{VERSION}/schema.md"),
    ]),
    ("Conformance", [
        ("conformance.html", "Conformance suite", ROOT / "conformance/README.md"),
    ]),
    ("Community", [
        ("versioning.html", "Versioning", ROOT / "VERSIONING.md"),
        ("governance.html", "Governance", ROOT / "GOVERNANCE.md"),
        ("changelog.html", "Changelog", ROOT / "CHANGELOG.md"),
    ]),
]

# HarnessRouter's docs palette and type, so the two properties read as one family.
CSS = """
:root{
  --brand:#285aff; --brand-deep:#1641d8; --brand-soft:#eff3ff;
  --canvas:#fbfbfc; --surface:#fff; --subtle:#f7f7f9;
  --line:#e7e7eb; --line-strong:#d8d8df;
  --ink:#111317; --muted:#6f6f78; --faint:#9696a0;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  --sans:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  --sidebar:288px; --content:800px;
}
@media (prefers-color-scheme:dark){
  :root{--canvas:#0d0e11;--surface:#131519;--subtle:#181a1f;--line:#24262d;--line-strong:#31343d;
        --ink:#e9eaee;--muted:#9a9ba4;--faint:#6f7078;--brand-soft:#152246;}
}
:root[data-theme=dark]{--canvas:#0d0e11;--surface:#131519;--subtle:#181a1f;--line:#24262d;
  --line-strong:#31343d;--ink:#e9eaee;--muted:#9a9ba4;--faint:#6f7078;--brand-soft:#152246;}
:root[data-theme=light]{--canvas:#fbfbfc;--surface:#fff;--subtle:#f7f7f9;--line:#e7e7eb;
  --line-strong:#d8d8df;--ink:#111317;--muted:#6f6f78;--faint:#9696a0;--brand-soft:#eff3ff;}

*{box-sizing:border-box}
body{margin:0;background:var(--canvas);color:var(--ink);font-family:var(--sans);
  font-size:16px;line-height:1.65;-webkit-font-smoothing:antialiased}
a{color:var(--brand);text-decoration:none}
a:hover{text-decoration:underline}

header.top{position:sticky;top:0;z-index:30;background:var(--surface);
  border-bottom:1px solid var(--line);display:flex;align-items:center;gap:16px;
  padding:0 20px;height:56px}
.brand{display:flex;align-items:center;gap:10px;font-weight:680;color:var(--ink);letter-spacing:-.01em}
.brand .mark{width:22px;height:22px;border-radius:6px;background:var(--brand);color:#fff;
  display:grid;place-items:center;font:600 11px/1 var(--mono)}
.brand .ver{font:500 11px/1 var(--mono);color:var(--muted);background:var(--subtle);
  border:1px solid var(--line);border-radius:999px;padding:4px 8px}
.top .spacer{flex:1}
.top nav a{color:var(--muted);font-size:14px;font-weight:520;margin-left:18px}
.top nav a:hover{color:var(--ink);text-decoration:none}
#menu{display:none;background:none;border:1px solid var(--line);border-radius:8px;
  color:var(--ink);font-size:18px;line-height:1;padding:6px 10px;cursor:pointer}

.shell{display:grid;grid-template-columns:var(--sidebar) minmax(0,1fr);align-items:start;
  max-width:1320px;margin:0 auto}
aside{position:sticky;top:56px;height:calc(100vh - 56px);overflow-y:auto;
  border-right:1px solid var(--line);padding:24px 16px 48px}
aside .group{margin-bottom:22px}
aside .group h4{margin:0 0 8px;padding:0 10px;font-size:11px;font-weight:660;
  letter-spacing:.07em;text-transform:uppercase;color:var(--faint)}
aside a{display:block;padding:6px 10px;border-radius:7px;color:var(--muted);
  font-size:14px;line-height:1.4}
aside a:hover{background:var(--subtle);color:var(--ink);text-decoration:none}
aside a.active{background:var(--brand-soft);color:var(--brand-deep);font-weight:600}

main{padding:40px 40px 96px;min-width:0}
article{max-width:var(--content)}
article h1{font-size:34px;line-height:1.2;letter-spacing:-.02em;margin:0 0 8px;font-weight:700}
article h2{font-size:22px;line-height:1.3;letter-spacing:-.01em;margin:44px 0 12px;
  font-weight:660;padding-top:20px;border-top:1px solid var(--line)}
article h3{font-size:17px;margin:28px 0 8px;font-weight:640}
article p{margin:0 0 16px;color:var(--ink)}
article ul,article ol{margin:0 0 16px;padding-left:22px}
article li{margin:5px 0}
article strong{font-weight:640}

code{font-family:var(--mono);font-size:.875em;background:var(--subtle);
  border:1px solid var(--line);border-radius:5px;padding:1px 5px}
pre{background:var(--subtle);border:1px solid var(--line);border-radius:10px;
  padding:16px 18px;overflow-x:auto;margin:0 0 20px}
pre code{background:none;border:0;padding:0;font-size:13px;line-height:1.6}

.table-wrap{overflow-x:auto;margin:0 0 20px;border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;padding:10px 14px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--subtle);font-weight:640;font-size:12.5px;letter-spacing:.02em;
  color:var(--muted);text-transform:uppercase}
tr:last-child td{border-bottom:0}
td code{white-space:nowrap}

blockquote{margin:0 0 20px;padding:14px 18px;background:var(--brand-soft);
  border-left:3px solid var(--brand);border-radius:0 10px 10px 0}
blockquote p:last-child{margin-bottom:0}

hr{border:0;border-top:1px solid var(--line);margin:32px 0}

.hero{padding:56px 0 8px;max-width:var(--content)}
.hero h1{font-size:44px;letter-spacing:-.03em;margin-bottom:14px}
.hero .lede{font-size:19px;color:var(--muted);line-height:1.55}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;
  margin:28px 0 8px;max-width:var(--content)}
.card{display:block;border:1px solid var(--line);border-radius:12px;padding:18px;
  background:var(--surface);color:var(--ink)}
.card:hover{border-color:var(--brand);text-decoration:none}
.card b{display:block;font-size:15px;margin-bottom:4px}
.card span{color:var(--muted);font-size:13.5px;line-height:1.5}

.pager{display:flex;justify-content:space-between;gap:16px;margin-top:56px;
  padding-top:20px;border-top:1px solid var(--line);max-width:var(--content)}
.pager a{font-size:14px;font-weight:560}
footer{border-top:1px solid var(--line);margin-top:64px;padding:24px 0 0;
  color:var(--faint);font-size:13px;max-width:var(--content)}

@media (max-width:900px){
  .shell{grid-template-columns:1fr}
  aside{position:fixed;inset:56px auto 0 0;width:280px;background:var(--surface);
    transform:translateX(-100%);transition:transform .18s ease;z-index:25;height:calc(100vh - 56px)}
  aside.open{transform:none;box-shadow:0 12px 40px #0000001f}
  #menu{display:block}
  main{padding:28px 20px 72px}
  .top nav{display:none}
  article h1,.hero h1{font-size:28px}
  .hero{padding:32px 0 4px}
}
@media (max-width:560px){
  /* The wordmark and the version chip together are wider than a phone, and wrapping them broke
     the fixed-height bar. Collapse to the mark, which is what the header is for at this width. */
  header.top{gap:10px;padding:0 14px}
  .brand{font-size:0}
  .brand .mark{font-size:11px}
  .brand .ver,header.top>.ver{display:none}
  main{padding:22px 16px 64px}
}
"""

JS = """
(function(){
  var b=document.getElementById('menu'),s=document.querySelector('aside');
  if(b&&s){b.addEventListener('click',function(){s.classList.toggle('open');});
    s.addEventListener('click',function(e){if(e.target.tagName==='A')s.classList.remove('open');});}
})();
"""


def render_markdown(text: str) -> str:
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "attr_list", "sane_lists"])
    out = md.convert(text)
    # Tables must scroll inside their own box rather than widening the page on a phone.
    out = re.sub(r"<table>", '<div class="table-wrap"><table>', out)
    out = re.sub(r"</table>", "</table></div>", out)
    return out


def rewrite_links(html_text: str, depth: int) -> str:
    """Point in-repo markdown links at their built pages."""
    up = "../" * depth
    pairs = [
        (rf'href="(?:\.\./)*versions/{VERSION}/([a-z]+)\.md"', rf'href="{up}spec/\1.html"'),
        (r'href="(?:\.\./)*README\.md"', f'href="{up}index.html"'),
        (r'href="(?:\.\./)*VERSIONING\.md"', f'href="{up}versioning.html"'),
        (r'href="(?:\.\./)*GOVERNANCE\.md"', f'href="{up}governance.html"'),
        (r'href="(?:\.\./)*CHANGELOG\.md"', f'href="{up}changelog.html"'),
        (r'href="(?:\.\./)*conformance/?"', f'href="{up}conformance.html"'),
        (r'href="(?:\.\./)*\.\./conformance/"', f'href="{up}conformance.html"'),
        (r'href="([a-z]+)\.md"', rf'href="\1.html"'),
        (r'href="(?:\.\./)*schema/([^"/]+)"',
         rf'href="{up}schema/\1"'),                       # the machine-readable files ship with the site
        (r'href="(?:\.\./)*schema/"', f'href="{up}spec/schema.html"'),
        (r'href="versions/2026-08-11/"', f'href="{up}spec/index.html"'),
        # An anchor into another document's section: keep the section, retarget the document.
        (r'href="(?:\.\./)*VERSIONING\.md#([^"]+)"', rf'href="{up}versioning.html#\1"'),
        (r'href="(?:\.\./)*GOVERNANCE\.md#([^"]+)"', rf'href="{up}governance.html#\1"'),
        (r'href="(?:\.\./)*README\.md#([^"]+)"', rf'href="{up}index.html#\1"'),
        (rf'href="(?:\.\./)*versions/{VERSION}/([a-z]+)\.md#([^"]+)"',
         rf'href="{up}spec/\1.html#\2"'),
    ]
    for pat, repl in pairs:
        html_text = re.sub(pat, repl, html_text)
    return html_text


def flat_pages():
    return [(path, title, src) for _, items in NAV for path, title, src in items]


def sidebar(current: str, depth: int) -> str:
    up = "../" * depth
    out = []
    for group, items in NAV:
        out.append(f'<div class="group"><h4>{html.escape(group)}</h4>')
        for path, title, _ in items:
            cls = ' class="active"' if path == current else ""
            out.append(f'<a href="{up}{path}"{cls}>{html.escape(title)}</a>')
        out.append("</div>")
    return "\n".join(out)


def page(current: str, title: str, body: str, depth: int, hero: str = "") -> str:
    up = "../" * depth
    pages = flat_pages()
    idx = next((i for i, (p, _, _) in enumerate(pages) if p == current), -1)
    prev_ = pages[idx - 1] if idx > 0 else None
    next_ = pages[idx + 1] if 0 <= idx < len(pages) - 1 else None
    pager = ""
    if prev_ or next_:
        left = f'<a href="{up}{prev_[0]}">&larr; {html.escape(prev_[1])}</a>' if prev_ else "<span></span>"
        right = f'<a href="{up}{next_[0]}">{html.escape(next_[1])} &rarr;</a>' if next_ else "<span></span>"
        pager = f'<div class="pager">{left}{right}</div>'

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · Unified Harness Protocol</title>
<meta name="description" content="The Unified Harness Protocol (UHP): an open standard for running complete agent harnesses as shared infrastructure.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<header class="top">
  <button id="menu" aria-label="Toggle navigation">☰</button>
  <a class="brand" href="{up}index.html"><span class="mark">U</span> Unified Harness Protocol</a>
  <span class="ver">{VERSION}</span>
  <span class="spacer"></span>
  <nav>
    <a href="{up}spec/index.html">Specification</a>
    <a href="{up}conformance.html">Conformance</a>
    <a href="{up}governance.html">Governance</a>
    <a href="https://github.com/HarnessRouter/harnessrouter">GitHub</a>
  </nav>
</header>
<div class="shell">
  <aside>{sidebar(current, depth)}</aside>
  <main>
    {hero}
    <article>{body}</article>
    {pager}
    <footer>
      Unified Harness Protocol {VERSION} · Apache-2.0 ·
      defined and maintained in the
      <a href="https://github.com/HarnessRouter/harnessrouter">HarnessRouter open-source repository</a>.
      The standard can be implemented without HarnessRouter Cloud.
    </footer>
  </main>
</div>
<script>{JS}</script>
</body>
</html>
"""


HERO = """
<div class="hero">
  <h1>The Unified Harness Protocol</h1>
  <p class="lede">One open standard for driving complete agent harnesses — Codex, Claude Code,
  Hermes, and whatever ships next — so a product integrates once instead of once per harness.</p>
</div>
<div class="cards">
  <a class="card" href="spec/index.html"><b>Read the specification</b>
    <span>Normative, versioned, and testable. Ten chapters from architecture to errors.</span></a>
  <a class="card" href="conformance.html"><b>Run the conformance suite</b>
    <span>47 checks across three classes. Passing it is the only conformance claim that means anything.</span></a>
  <a class="card" href="spec/schema.html"><b>Generate a client</b>
    <span>OpenAPI 3.1 and JSON Schema 2020-12, published per version.</span></a>
  <a class="card" href="governance.html"><b>Propose a change</b>
    <span>Prose first. Spec, reference implementation and suite move together.</span></a>
</div>
"""


def build() -> int:
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "spec").mkdir(parents=True)

    built = 0
    for path, title, src in flat_pages():
        if not src.exists():
            print(f"  !! missing source: {src}")
            return 1
        depth = path.count("/")
        body = rewrite_links(render_markdown(src.read_text()), depth)
        # The home page leads with the hero; its markdown H1 would repeat it.
        hero = ""
        if path == "index.html":
            hero = HERO
            body = re.sub(r"<h1>.*?</h1>", "", body, count=1, flags=re.S)
            body = re.sub(r"<p><strong>An open standard.*?</strong></p>", "", body, count=1, flags=re.S)
        (DIST / path).write_text(page(path, title, body, depth, hero))
        built += 1

    # Publishing metadata: a protocol site that cannot be crawled is a protocol nobody finds.
    (DIST / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: https://{SITE}/sitemap.xml\n")
    urls = "".join(f"  <url><loc>https://{SITE}/{p}</loc></url>\n" for p, _, _ in flat_pages())
    (DIST / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n')

    # The machine-readable definitions are part of the standard, so they are served with it.
    shutil.copytree(ROOT / "schema", DIST / "schema",
                    ignore=shutil.ignore_patterns("build.py", "__pycache__"))

    print(f"built {built} pages + schema into {DIST}")
    return 0


def main() -> int:
    rc = build()
    if rc or "--serve" not in sys.argv:
        return rc
    import http.server
    import functools
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DIST))
    print(f"serving {DIST} on http://127.0.0.1:8000 — Ctrl-C to stop")
    http.server.HTTPServer(("127.0.0.1", 8000), handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
