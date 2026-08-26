#!/usr/bin/env python3
"""Build the unifiedharnessprotocol.org site from the specification.

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
import json
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
# Published specification versions, latest first. The spec is served under a per-version path
# (/spec/<date>/…, mirroring MCP's /specification/<date>/…) so every version keeps a permanent
# address: a citation to the 2026-08-11 architecture never silently becomes a later version. Only
# the specification is versioned this way; conformance, governance and versioning are living docs.
VERSIONS = ["2026-08-11"]
SITE = "unifiedharnessprotocol.org"

# The specification's chapters, in reading order. NAV builds their per-version paths from this so
# the version lives in exactly one place; adding a version means prepending it to VERSIONS.
SPEC_CHAPTERS = [
    ("index", "Overview"),
    ("architecture", "Architecture"),
    ("lifecycle", "Lifecycle"),
    ("harnesses", "Harnesses"),
    ("tasks", "Tasks"),
    ("streaming", "Streaming"),
    ("sessions", "Sessions"),
    ("files", "Files"),
    ("errors", "Errors"),
    ("security", "Security"),
    ("schema", "Schema"),
]

# ── information architecture ────────────────────────────────────────────────────────────
# Mirrors the shape a protocol site is expected to have — an introduction, a versioned
# specification, the machine-readable definitions, conformance, and the change process — so a
# developer arriving from another protocol's docs already knows where things are.
NAV = [
    ("Introduction", [
        ("index.html", "What is UHP?", ROOT / "README.md"),
    ]),
    ("Specification", [
        (f"spec/{VERSION}/{name}.html", title, ROOT / f"versions/{VERSION}/{name}.md")
        for name, title in SPEC_CHAPTERS
    ]),
    ("Conformance", [
        ("conformance.html", "Conformance suite", ROOT / "conformance/README.md"),
    ]),
    ("Implement UHP", [
        ("connecting.html", "Implement a client", ROOT / "CONNECTING.md"),
        ("serving.html", "Implement a server", ROOT / "SERVING.md"),
    ]),
    ("Community", [
        ("versioning.html", "Versioning", ROOT / "VERSIONING.md"),
        ("governance.html", "Governance", ROOT / "GOVERNANCE.md"),
        ("changelog.html", "Changelog", ROOT / "CHANGELOG.md"),
    ]),
    ("Ecosystem", [
        ("examples.html", "Examples", ROOT / "IMPLEMENTATIONS.md"),
    ]),
]

# Pages reachable by link but not listed in the sidebar: background and context that should not sit
# above the specification. They are still built, sitemapped, and citable, just not in the nav.
EXTRA = [
    ("naming.html", "The Naming of the Unified Harness Protocol", ROOT / "naming.md"),
]

# Per-page meta descriptions. Search engines treat a site-wide description as one page repeated
# seventeen times; each entry states what its page — and only its page — defines. This dict is the
# metadata manifest: build() asserts every page has one, they are unique, and lengths sit in the
# 100–170 band that renders whole in Google, Bing, and the AI-engine retrieval snippets.
DESCRIPTIONS = {
    "index.html":
        "The Unified Harness Protocol (UHP) is an open standard for running complete agent "
        "harnesses — tasks, sessions, streaming, files — through one shared contract.",
    "connecting.html":
        "How to connect a product to a UHP server: discover the harness catalog, submit a "
        "task, stream progress, manage sessions, and take back files — client-side, over HTTP.",
    "serving.html":
        "How to serve UHP: the endpoints a conformant server answers, the order to build "
        "them in, and the conformance suite that proves the implementation works.",
    "examples.html":
        "Example implementations of the Unified Harness Protocol: servers that run harnesses "
        "behind the contract and clients that drive them, listed by pull request.",
    "spec/index.html":
        "The complete UHP specification: architecture, lifecycle, harnesses, tasks, streaming, "
        "sessions, files, errors, security, and schema — versioned and testable.",
    "spec/architecture.html":
        "UHP architecture: the resource model, object scoping, and conformance keywords that "
        "govern how a server exposes agent harnesses through one contract.",
    "spec/lifecycle.html":
        "UHP lifecycle: how a client and server negotiate protocol versions, discover "
        "capabilities, and track a task's states from submission to result.",
    "spec/harnesses.html":
        "UHP harness discovery: the harness object, model availability, and how a conformant "
        "server advertises what can run a client's work.",
    "spec/tasks.html":
        "UHP tasks: one unit of work, input in and result out — the request shape, execution "
        "semantics, and response contract clients build on.",
    "spec/streaming.html":
        "UHP streaming: how a server reports progress while long agent tasks run — the event "
        "stream, tool-call visibility, and reconnection rules.",
    "spec/sessions.html":
        "UHP sessions: continuing work where a task left off — conversation state, working "
        "directories, inspection, and stopping a session.",
    "spec/files.html":
        "UHP files and artifacts: getting files into a harness run and artifacts out, with the "
        "upload, download, and preview semantics servers provide.",
    "spec/errors.html":
        "UHP errors: one error envelope, a closed set of codes, and which failures are worth "
        "retrying — the contract client error handling relies on.",
    "spec/security.html":
        "UHP security: credentials, object scoping, and artifact handling — the requirements a "
        "server meets to run agent workloads for callers it has never met.",
    "spec/schema.html":
        "UHP schema: the machine-readable OpenAPI 3.1 and JSON Schema 2020-12 definitions that "
        "are normative for every object's structure.",
    "conformance.html":
        "The UHP conformance suite: local checks that grade any HTTP implementation into "
        "conformance classes — runnable by anyone, against anyone's server.",
    "versioning.html":
        "UHP versioning: date-based versions, what may change between them, and how clients and "
        "servers stay compatible as the specification evolves.",
    "governance.html":
        "UHP governance: the maintainer-led, proposal-first model for changing the protocol, and "
        "how decisions are recorded in the open.",
    "changelog.html":
        "The UHP changelog: every published specification version and what changed in it, from "
        "the current release backward.",
    "naming.html":
        "Why it is called the Unified Harness Protocol: the nine names weighed, why Unified won "
        "the letters UHP, and how the standard relates to HarnessRouter.",
}

# HarnessRouter's docs palette and type, so the two properties read as one family.
CSS = """
:root{
  --brand:#285aff; --brand-deep:#1641d8; --brand-soft:#eff3ff;
  --canvas:#fbfbfc; --surface:#fff; --subtle:#f7f7f9;
  --line:#e7e7eb; --line-strong:#d8d8df;
  --ink:#111317; --muted:#6f6f78; --faint:#9696a0;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  --sans:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  --display:"Newsreader",Georgia,"Times New Roman",serif;
  --sidebar:264px; --content:760px; --toc:220px;
  --shell-max:1360px; --gutter:clamp(16px,3vw,40px);
}

/* ── Implementations: compact list cards, not a wide table ──────────────────────────── */
.impl-actions{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0 26px}
.impl-cta{display:inline-flex;align-items:center;min-height:38px;border-radius:9px;
  background:var(--brand);color:#fff;font-size:14px;font-weight:600;padding:0 16px}
.impl-cta:hover{background:var(--brand-deep);text-decoration:none;color:#fff}
.impl-crit{display:inline-flex;align-items:center;min-height:38px;border-radius:9px;
  border:1px solid var(--line);color:var(--ink);font-size:14px;font-weight:550;padding:0 15px}
.impl-crit:hover{border-color:var(--brand);text-decoration:none}
.impl-list{display:grid;gap:12px;margin:0 0 32px}
.impl-card{border:1px solid var(--line);border-radius:12px;padding:16px 18px;background:var(--surface)}
.impl-card:hover{border-color:var(--line-strong)}
.impl-head{display:flex;align-items:center;gap:12px}
.impl-head b{font-size:16px;font-weight:640}
.impl-head a{color:var(--ink)}
.impl-head a:hover{color:var(--brand)}
.role{margin-left:auto;font-size:11px;font-weight:660;letter-spacing:.03em;text-transform:uppercase;
  border-radius:6px;padding:3px 9px;white-space:nowrap}
.role-server{background:var(--brand-soft);color:var(--brand-deep)}
.role-client{background:var(--subtle);color:var(--muted)}
.impl-card p{margin:8px 0 0;color:var(--muted);font-size:14px;line-height:1.55}
.impl-card .impl-meta{margin-top:8px;font:500 12px/1 var(--mono);color:var(--faint)}
/* Drawer nav: primary links shown inside the mobile sidebar drawer only */
.drawernav{display:none;margin-bottom:22px;padding-bottom:18px;border-bottom:1px solid var(--line)}
.drawernav a{display:block;padding:8px 10px;border-radius:7px;color:var(--ink);
  font-size:14px;font-weight:550}
.drawernav a:hover{background:var(--subtle);text-decoration:none}

/* ── Theme menu ─────────────────────────────────────────────────────────────────────── */
.theme{position:relative;margin-left:16px}
.tbtn{display:inline-grid;place-items:center;width:34px;height:34px;border:1px solid var(--line);
  border-radius:9px;background:var(--subtle);color:var(--muted);cursor:pointer;padding:0}
.tbtn:hover{color:var(--ink);border-color:var(--ink)}
.tmenu{position:absolute;top:calc(100% + 6px);right:0;min-width:130px;padding:5px;
  border:1px solid var(--line);border-radius:10px;background:var(--surface);
  box-shadow:0 12px 34px -12px rgba(15,17,21,.4);z-index:60}
.tmenu button{display:flex;align-items:center;justify-content:space-between;width:100%;
  border:0;border-radius:7px;background:none;color:var(--ink);cursor:pointer;
  font:inherit;font-size:13px;padding:7px 10px}
.tmenu button:hover{background:var(--subtle)}
.tmenu button[aria-checked=true]::after{content:"\\2713";color:var(--brand);font-weight:700}

/* ── Search: a compact trigger in the header, a dialog over the page ─────────────────── */
.sbtn{display:inline-flex;align-items:center;gap:7px;min-height:34px;min-width:200px;
  border:1px solid var(--line);border-radius:9px;background:var(--subtle);
  color:var(--muted);cursor:pointer;font:inherit;font-size:13px;padding:0 11px}
.sbtn .sbtn-label{flex:1;text-align:left}
.sbtn:hover{color:var(--ink);border-color:var(--ink)}
.sbtn kbd{border:1px solid var(--line);border-radius:4px;font-family:inherit;font-size:11px;
  padding:1px 5px;color:var(--muted)}
#sdlg{position:fixed;inset:0;z-index:90}
#sdlg .sbackdrop{position:absolute;inset:0;background:rgba(15,17,21,.45)}
#sdlg .spanel{position:relative;width:min(640px,calc(100% - 32px));margin:9vh auto 0;
  border:1px solid var(--line);border-radius:12px;background:var(--surface);
  box-shadow:0 24px 70px -20px rgba(15,17,21,.5);padding:10px 10px 8px}
#sinput{width:100%;min-height:44px;border:0;outline:0;background:transparent;color:var(--ink);
  font:inherit;font-size:16px;padding:0 8px;border-bottom:1px solid var(--line)}
#sresults{list-style:none;margin:6px 0 0;padding:0;max-height:52vh;overflow-y:auto}
#sresults li{border-radius:8px;padding:9px 10px;cursor:pointer}
#sresults li.sel,#sresults li:hover{background:rgba(0,0,0,.05)}
#sresults .st{font-weight:600;font-size:14px}
#sresults .st small{color:var(--muted);font-weight:400;margin-left:8px}
#sresults .sx{color:var(--muted);font-size:13px;line-height:1.45;margin-top:2px}
#sresults mark{background:transparent;color:var(--ink);font-weight:650}
#sresults .snone{color:var(--muted);padding:12px 10px;font-size:14px}
.shint{margin:8px 2px 2px;color:var(--muted);font-size:12px}
.shint kbd{border:1px solid var(--line);border-radius:4px;padding:0 4px;font-family:inherit;font-size:11px}

@media (prefers-color-scheme:dark){
  :root{--canvas:#0d0e11;--surface:#131519;--subtle:#181a1f;--line:#24262d;--line-strong:#31343d;
        --ink:#e9eaee;--muted:#9a9ba4;--faint:#6f7078;
        --brand:#5b82ff;--brand-deep:#84a3ff;--brand-soft:#182444;}
}
:root[data-theme=dark]{--canvas:#0d0e11;--surface:#131519;--subtle:#181a1f;--line:#24262d;
  --line-strong:#31343d;--ink:#e9eaee;--muted:#9a9ba4;--faint:#6f7078;
  --brand:#5b82ff;--brand-deep:#84a3ff;--brand-soft:#182444;}
:root[data-theme=light]{--canvas:#fbfbfc;--surface:#fff;--subtle:#f7f7f9;--line:#e7e7eb;
  --line-strong:#d8d8df;--ink:#111317;--muted:#6f6f78;--faint:#9696a0;
  --brand:#285aff;--brand-deep:#1641d8;--brand-soft:#eff3ff;}
:root{color-scheme:light}
@media (prefers-color-scheme:dark){:root{color-scheme:dark}}
:root[data-theme=light]{color-scheme:light}
:root[data-theme=dark]{color-scheme:dark}

*{box-sizing:border-box}
body{margin:0;background:var(--canvas);color:var(--ink);font-family:var(--sans);
  font-size:16.5px;line-height:1.68;letter-spacing:-.003em;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
a{color:var(--brand);text-decoration:none}
a:hover{text-decoration:underline}

header.top{position:sticky;top:0;z-index:30;background:var(--surface);
  border-bottom:1px solid var(--line);height:56px}
.header-inner{display:flex;align-items:center;gap:16px;height:100%;
  width:min(100%,var(--shell-max));margin:0 auto;padding:0 var(--gutter);box-sizing:border-box}
.brand{display:flex;align-items:center;gap:10px;font-weight:680;color:var(--ink);letter-spacing:-.01em}
.brand .mark{width:22px;height:22px;border-radius:6px;background:var(--brand);color:#fff;
  display:grid;place-items:center;font:600 11px/1 var(--mono)}
.brand .ver{font:500 11px/1 var(--mono);color:var(--muted);background:var(--subtle);
  border:1px solid var(--line);border-radius:999px;padding:4px 8px}
.ver{position:relative;margin-left:2px}
.verpill{display:inline-flex;align-items:center;gap:6px;cursor:pointer;
  font:500 11.5px/1 var(--mono);color:var(--muted);background:var(--subtle);
  border:1px solid var(--line);border-radius:999px;padding:5px 9px 5px 10px;white-space:nowrap}
.verpill:hover{color:var(--ink);border-color:var(--line-strong)}
.verpill[aria-expanded=true]{color:var(--ink);border-color:var(--ink)}
.verpill .dot{width:6px;height:6px;border-radius:50%;background:#16a34a;flex:none;
  box-shadow:0 0 0 3px rgba(22,163,74,.15)}
.verpill .vchev{opacity:.6;margin-left:1px}
.vmenu{position:absolute;top:calc(100% + 6px);left:0;min-width:190px;padding:5px;
  border:1px solid var(--line);border-radius:10px;background:var(--surface);
  box-shadow:0 12px 34px -12px rgba(15,17,21,.4);z-index:60}
.vmenu-h{margin:4px 8px 5px;font:660 10px/1 var(--sans);letter-spacing:.07em;
  text-transform:uppercase;color:var(--faint)}
.vmenu a{display:flex;align-items:center;gap:8px;border-radius:7px;padding:7px 9px;
  color:var(--ink);font:500 13px/1 var(--mono)}
.vmenu a:hover{background:var(--subtle);text-decoration:none}
.vmenu .vname{flex:1}
.vmenu .vtag{font:600 10px/1 var(--sans);letter-spacing:.03em;text-transform:uppercase;
  color:#16a34a;background:rgba(22,163,74,.12);border-radius:4px;padding:3px 6px}
.top .spacer{flex:1}
.top nav a{color:var(--muted);font-size:14px;font-weight:520;margin-left:18px}
.top nav a:hover{color:var(--ink);text-decoration:none}
#menu{display:none;background:none;border:1px solid var(--line);border-radius:8px;
  color:var(--ink);font-size:18px;line-height:1;padding:6px 10px;cursor:pointer}

.shell{display:grid;grid-template-columns:var(--sidebar) minmax(0,1fr) var(--toc);align-items:start;
  width:min(100%,var(--shell-max));margin:0 auto;padding:0 var(--gutter);box-sizing:border-box}
.shell.no-toc{grid-template-columns:var(--sidebar) minmax(0,1fr)}
.toc{position:sticky;top:56px;max-height:calc(100vh - 56px);overflow-y:auto;
  overscroll-behavior:contain;padding:40px 16px 48px 12px;scrollbar-width:thin}
.toc .toc-h{margin:0 0 8px;padding:0 10px;font:650 11px/1 var(--mono);
  letter-spacing:.02em;text-transform:uppercase;color:var(--faint)}
.toc ul{display:grid;gap:1px;margin:0;padding:0;list-style:none}
.toc a{display:flex;align-items:center;min-height:31px;padding:5px 10px;border-radius:7px;
  color:var(--muted);font-size:13px;line-height:1.35;text-decoration:none}
.toc a.lvl3{padding-left:22px;font-size:12.5px;color:var(--faint)}
.toc a:hover{color:var(--ink);background:var(--subtle)}
.toc a[aria-current=location]{color:var(--ink);font-weight:660}
.toc a.lvl3[aria-current=location]{color:var(--ink)}
aside{position:sticky;top:56px;height:calc(100vh - 56px);overflow-y:auto;
  border-right:1px solid var(--line);padding:24px 20px 48px 0}
.verbadge{display:flex;align-items:center;gap:8px;margin:0 6px 22px;padding:9px 11px;
  border:1px solid var(--line);border-radius:9px;background:var(--subtle)}
.verbadge .verlabel{font-size:11px;font-weight:660;letter-spacing:.07em;text-transform:uppercase;color:var(--faint)}
.verbadge .vertag{display:flex;align-items:center;gap:7px;margin-left:auto;
  font:600 12px/1 var(--mono);color:var(--ink)}
.verbadge .vertag em{font:500 10px/1 var(--sans);font-style:normal;letter-spacing:.03em;
  text-transform:uppercase;color:#16a34a;background:rgba(22,163,74,.12);border-radius:4px;padding:3px 6px}
.verbadge .dot{width:7px;height:7px;border-radius:50%;background:#16a34a;flex:none;
  box-shadow:0 0 0 3px rgba(22,163,74,.15)}
aside .group{margin-bottom:22px}
aside .group h4{margin:0 0 8px;padding:0 10px;font-size:11px;font-weight:660;
  letter-spacing:.07em;text-transform:uppercase;color:var(--faint)}
aside a{display:block;padding:6px 10px;border-radius:7px;color:var(--muted);
  font-size:14px;line-height:1.4}
aside a:hover{background:var(--subtle);color:var(--ink);text-decoration:none}
aside a.active{background:var(--brand-soft);color:var(--brand-deep);font-weight:600;box-shadow:inset 2px 0 0 var(--brand)}

main{padding:40px 40px 96px;min-width:0}
article{max-width:var(--content)}
article h1{font-family:var(--display);font-size:40px;line-height:1.12;letter-spacing:-.01em;
  margin:0 0 10px;font-weight:600}
article h2{font-family:var(--display);font-size:26px;line-height:1.25;letter-spacing:-.005em;
  margin:46px 0 14px;font-weight:600;padding-top:22px;border-top:1px solid var(--line)}
article h3{font-size:17px;margin:30px 0 8px;font-weight:640;letter-spacing:-.005em}
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
.hero h1{font-family:var(--display);font-size:52px;line-height:1.06;letter-spacing:-.015em;font-weight:600;margin-bottom:16px}
.hero .lede{font-size:19px;color:var(--muted);line-height:1.55}
/* ── Homepage role flow: Client -> UHP server -> Harness (rendering of architecture Roles) ── */
.quicklinks{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin:8px 0 40px;max-width:var(--content)}
@media (max-width:640px){.quicklinks{grid-template-columns:1fr}}
.home-h2{font-family:var(--display);font-size:20px;font-weight:600;margin:38px 0 4px;letter-spacing:-.005em}
.role-flow{display:flex;align-items:stretch;flex-wrap:wrap;gap:10px;margin:30px 0 14px}
.role-flow .node{display:flex;flex-direction:column;justify-content:center;gap:2px;
  border:1px solid var(--line);border-radius:12px;padding:12px 16px;background:var(--surface);min-width:0}
.role-flow .node b{font-size:14.5px;font-weight:640}
.role-flow .node small{color:var(--muted);font-size:12px}
.role-flow .arrow{align-self:center;color:var(--faint);flex:none}
.role-note{margin:0 0 6px;color:var(--muted);font-size:14px;max-width:var(--content)}
.card-badge{align-self:flex-start;font-size:11px;font-weight:660;letter-spacing:.02em;
  border-radius:6px;padding:3px 9px;margin-bottom:10px;background:var(--brand-soft);color:var(--brand-deep)}
.card-badge-quiet{background:var(--subtle);color:var(--muted)}
@media (max-width:560px){.role-flow .arrow{transform:rotate(90deg)}.role-flow{flex-direction:column}}
.cards-primary{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:30px 0 14px;max-width:var(--content)}
.card-lg{display:flex;flex-direction:column;border:1px solid var(--line);border-radius:14px;
  padding:22px;background:var(--surface);color:var(--ink);transition:border-color .15s,box-shadow .15s}
.card-lg:hover{border-color:var(--brand);text-decoration:none;box-shadow:0 6px 24px -14px var(--brand)}
.card-lg svg{color:var(--brand);margin-bottom:12px}
.card-lg b{font-size:17px;font-weight:640;margin-bottom:6px}
.card-lg span{color:var(--muted);font-size:14px;line-height:1.55;flex:1}
.card-lg em{margin-top:14px;font-style:normal;font-size:13.5px;font-weight:600;color:var(--brand)}
.cards-secondary{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:0 0 8px;max-width:var(--content)}
.card-sm{display:block;border:1px solid var(--line);border-radius:11px;padding:14px 16px;
  background:transparent;color:var(--ink)}
.card-sm:hover{border-color:var(--brand);text-decoration:none;background:var(--subtle)}
.card-sm b{display:block;font-size:14.5px;font-weight:620;margin-bottom:3px}
.card-sm span{color:var(--muted);font-size:13px;line-height:1.5}
@media (max-width:640px){.cards-primary,.cards-secondary{grid-template-columns:1fr}}

.pager{display:flex;justify-content:space-between;gap:16px;margin-top:56px;
  padding-top:20px;border-top:1px solid var(--line);max-width:var(--content)}
.pager a{font-size:14px;font-weight:560}
footer{border-top:1px solid var(--line);margin-top:64px;padding:24px 0 0;
  color:var(--faint);font-size:13px;max-width:var(--content)}

/* ── Tablet/below: sidebar becomes a drawer, top nav collapses into the drawer ───────── */
@media (max-width:960px){
  .shell,.shell.no-toc{grid-template-columns:1fr}
  .toc{display:none}
  aside{position:fixed;inset:56px auto 0 0;width:min(300px,84vw);background:var(--surface);
    transform:translateX(-100%);transition:transform .18s ease;z-index:25;height:calc(100vh - 56px)}
  aside.open{transform:none;box-shadow:0 12px 40px #0000001f}
  #menu{display:grid;place-items:center}
  main{padding:28px 20px 72px}
  /* Move the primary nav links into the drawer instead of dropping them entirely. */
  .top nav{display:none}
  aside .drawernav{display:block}
  .ver{display:none}
  /* Search shrinks to an icon-only button — same target, no dead label space. */
  .sbtn{min-width:0;width:34px;padding:0;justify-content:center}
  .sbtn-label,.sbtn kbd{display:none}
  article h1{font-size:30px}
  .hero h1{font-size:34px}
  .hero{padding:32px 0 4px}
}
/* ── Phone: keep the wordmark text (readable), tighten spacing ───────────────────────── */
@media (max-width:560px){
  header.top{gap:10px;padding:0 12px}
  .brand{font-size:15px;gap:8px}
  .theme{margin-left:8px}
  main{padding:22px 16px 64px}
}
/* ── Very narrow: drop the wordmark text, keep the mark ──────────────────────────────── */
@media (max-width:400px){
  .brand span:not(.mark){position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
}
"""

JS = """
(function(){
  var b=document.getElementById('menu'),s=document.querySelector('aside');
  if(b&&s){b.addEventListener('click',function(){s.classList.toggle('open');});
    s.addEventListener('click',function(e){if(e.target.tagName==='A')s.classList.remove('open');});}

  // Theme: Auto / Light / Dark, persisted to localStorage; Auto defers to the OS media query.
  var tb=document.getElementById('tbtn'),tm=tb&&tb.parentElement.querySelector('.tmenu');
  if(tb&&tm){
    function cur(){try{return localStorage.getItem('theme')||'auto';}catch(e){return 'auto';}}
    function mark(){var v=cur();tm.querySelectorAll('[data-theme-set]').forEach(function(x){
      x.setAttribute('aria-checked', x.getAttribute('data-theme-set')===v?'true':'false');});}
    function set(v){try{ if(v==='auto'){localStorage.removeItem('theme');delete document.documentElement.dataset.theme;}
      else{localStorage.setItem('theme',v);document.documentElement.dataset.theme=v;} }catch(e){}
      mark();}
    function openM(o){tm.hidden=!o;tb.setAttribute('aria-expanded',o?'true':'false');if(o)mark();}
    tb.addEventListener('click',function(e){e.stopPropagation();openM(tm.hidden);});
    tm.querySelectorAll('[data-theme-set]').forEach(function(x){
      x.addEventListener('click',function(){set(x.getAttribute('data-theme-set'));openM(false);});});
    document.addEventListener('click',function(){if(!tm.hidden)openM(false);});
    document.addEventListener('keydown',function(e){if(e.key==='Escape'&&!tm.hidden)openM(false);});
    mark();
  }

  // Version dropdown: toggle the menu, close on outside click or Escape.
  var vb=document.getElementById('vbtn'),vm=vb&&vb.parentElement.querySelector('.vmenu');
  if(vb&&vm){
    function vopen(o){vm.hidden=!o;vb.setAttribute('aria-expanded',o?'true':'false');}
    vb.addEventListener('click',function(e){e.stopPropagation();vopen(vm.hidden);});
    document.addEventListener('click',function(){if(!vm.hidden)vopen(false);});
    document.addEventListener('keydown',function(e){if(e.key==='Escape'&&!vm.hidden)vopen(false);});
  }

  // On-this-page scroll-spy: mark the last heading whose top has crossed an anchor line 32% down
  // the viewport (capped at 220px). Throttled through requestAnimationFrame; forces the final item
  // when the page is scrolled to the bottom so a short last section still lights up.
  var toc=document.querySelector('.toc');
  if(toc){
    var tlinks=[].slice.call(toc.querySelectorAll('a[href^="#"]'));
    var tids=tlinks.map(function(a){return decodeURIComponent(a.getAttribute('href').slice(1));});
    var theads=tids.map(function(id){return document.getElementById(id);});
    var tcur=null,tsched=false;
    function tpick(){
      var anchor=window.scrollY+Math.min(window.innerHeight*0.32,220),id=tids[0]||null;
      for(var i=0;i<theads.length;i++){ var h=theads[i]; if(!h)continue;
        if(h.getBoundingClientRect().top+window.scrollY<=anchor){id=tids[i];}else{break;} }
      if(tids.length&&window.scrollY+window.innerHeight>=document.documentElement.scrollHeight-4)
        id=tids[tids.length-1];
      if(id!==tcur){ tcur=id;
        tlinks.forEach(function(a){
          if(decodeURIComponent(a.getAttribute('href').slice(1))===id)a.setAttribute('aria-current','location');
          else a.removeAttribute('aria-current'); }); }
    }
    function tspy(){ if(tsched)return; tsched=true;
      requestAnimationFrame(function(){tsched=false;tpick();}); }
    window.addEventListener('scroll',tspy,{passive:true});
    window.addEventListener('resize',tspy);
    tpick();
  }

  var dlg=document.getElementById('sdlg'),inp=document.getElementById('sinput'),
      res=document.getElementById('sresults'),btn=document.getElementById('sbtn');
  if(!dlg||!inp||!btn)return;
  var root=inp.getAttribute('data-root')||'',idx=null,sel=-1,rows=[];

  function load(cb){ if(idx){cb();return;}
    fetch(root+'search-index.json').then(function(r){return r.json();})
      .then(function(d){idx=d;cb();}).catch(function(){idx=[];cb();}); }
  function open_(){ dlg.hidden=false; load(function(){inp.focus();run();}); }
  function close_(){ dlg.hidden=true; sel=-1; }
  function esc(t){return t.replace(/[&<>]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});}
  function mark(t,q){ if(!q)return esc(t);
    var i=t.toLowerCase().indexOf(q.toLowerCase()); if(i<0)return esc(t);
    return esc(t.slice(0,i))+'<mark>'+esc(t.slice(i,i+q.length))+'</mark>'+esc(t.slice(i+q.length)); }
  function excerpt(body,q){ var i=body.toLowerCase().indexOf(q.toLowerCase());
    if(i<0)return esc(body.slice(0,120));
    var a=Math.max(0,i-40); return (a>0?'&hellip;':'')+mark(body.slice(a,i+q.length+80),q)+'&hellip;'; }
  function run(){ var q=inp.value.trim(); res.innerHTML=''; sel=-1; rows=[];
    if(!idx){return;}
    var out=[];
    if(q){ var ql=q.toLowerCase();
      for(var i=0;i<idx.length;i++){ var p=idx[i];
        var t=(p.title+' '+p.body).toLowerCase(); var k=t.indexOf(ql);
        if(k>=0){ out.push([p, (p.title.toLowerCase().indexOf(ql)>=0?0:1), k]); } }
      out.sort(function(a,b){return a[1]-b[1]||a[2]-b[2];});
      out=out.slice(0,8);
    }
    if(q && !out.length){ res.innerHTML='<li class="snone">No matches for &ldquo;'+esc(q)+'&rdquo;</li>'; return; }
    out.forEach(function(e){ var p=e[0]; var li=document.createElement('li');
      li.innerHTML='<div class="st">'+mark(p.title,q)+'<small>'+esc(p.section)+'</small></div>'+
                   '<div class="sx">'+excerpt(p.body,q)+'</div>';
      li.addEventListener('click',function(){location.href=root+p.url;});
      res.appendChild(li); rows.push(p); });
  }
  function move(d){ var items=res.querySelectorAll('li'); if(!items.length)return;
    if(sel>=0)items[sel].classList.remove('sel');
    sel=(sel+d+items.length)%items.length; items[sel].classList.add('sel');
    items[sel].scrollIntoView({block:'nearest'}); }

  btn.addEventListener('click',open_);
  dlg.querySelector('.sbackdrop').addEventListener('click',close_);
  inp.addEventListener('input',run);
  document.addEventListener('keydown',function(e){
    if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();dlg.hidden?open_():close_();return;}
    if(dlg.hidden)return;
    if(e.key==='Escape'){close_();}
    else if(e.key==='ArrowDown'){e.preventDefault();move(1);}
    else if(e.key==='ArrowUp'){e.preventDefault();move(-1);}
    else if(e.key==='Enter'&&sel>=0&&rows[sel]){location.href=root+rows[sel].url;} });
})();
"""


def render_markdown(text: str):
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "attr_list", "sane_lists"])
    out = md.convert(text)
    # Tables must scroll inside their own box rather than widening the page on a phone.
    out = re.sub(r"<table>", '<div class="table-wrap"><table>', out)
    out = re.sub(r"</table>", "</table></div>", out)
    # Collect h2/h3 for the on-this-page rail; ids come from the toc extension.
    toc = [(int(m.group(1)), m.group(2), re.sub("<[^>]+>", "", m.group(3)))
           for m in re.finditer(r'<h([23]) id="([^"]+)">(.*?)</h[23]>', out, re.S)]
    return out, toc


def toc_html(toc):
    if len(toc) < 2:
        return ""
    items = "".join(
        f'<li><a href="#{i}" class="lvl{lvl}">{html.escape(t)}</a></li>' for lvl, i, t in toc)
    return (f'<nav class="toc" aria-label="On this page"><p class="toc-h">On this page</p>'
            f'<ul>{items}</ul></nav>')


def rewrite_links(html_text: str, depth: int) -> str:
    """Point in-repo markdown links at their built pages (root-absolute, see url_for)."""
    up = "/"
    samedir = f"/spec/{VERSION}/" if depth else "/"
    pairs = [
        # The spec overview is served at /spec/<version> (index stripped), so map it before the
        # general chapter rule, which would otherwise turn index.md into …/index (a 404).
        (rf'href="(?:\.\./)*versions/{VERSION}/index\.md"', rf'href="{up}spec/{VERSION}"'),
        (rf'href="(?:\.\./)*versions/{VERSION}/([a-z]+)\.md"', rf'href="{up}spec/{VERSION}/\1"'),
        (r'href="(?:\.\./)*README\.md"', f'href="{url_for("index.html", up)}"'),
        (r'href="(?:\.\./)*VERSIONING\.md"', f'href="{up}versioning"'),
        (r'href="(?:\.\./)*GOVERNANCE\.md"', f'href="{up}governance"'),
        (r'href="(?:\.\./)*CHANGELOG\.md"', f'href="{up}changelog"'),
        (r'href="(?:\.\./)*SERVING\.md"', f'href="{up}serving"'),
        (r'href="(?:\.\./)*CONNECTING\.md"', f'href="{up}connecting"'),
        (r'href="(?:\.\./)*IMPLEMENTATIONS\.md"', f'href="{up}examples"'),
        (r'href="(?:\.\./)*conformance/README\.md"', f'href="{up}conformance"'),
        (r'href="(?:\.\./)*conformance/?"', f'href="{up}conformance"'),
        (r'href="(?:\.\./)*\.\./conformance/"', f'href="{up}conformance"'),
        (r'href="([a-z]+)\.md"', rf'href="{samedir}\1"'),
        (r'href="(?:\.\./)*schema/([^"/]+)"',
         rf'href="{up}schema/\1"'),                       # the machine-readable files ship with the site
        (r'href="(?:\.\./)*schema/"', f'href="{up}spec/{VERSION}/schema"'),
        (rf'href="versions/{VERSION}/"', f'href="{up}spec/{VERSION}"'),
        # An anchor into another document's section: keep the section, retarget the document.
        (r'href="(?:\.\./)*VERSIONING\.md#([^"]+)"', rf'href="{up}versioning#\1"'),
        (r'href="(?:\.\./)*GOVERNANCE\.md#([^"]+)"', rf'href="{up}governance#\1"'),
        (r'href="(?:\.\./)*README\.md#([^"]+)"', rf'href="{url_for("index.html", up)}#\1"'),
        (rf'href="(?:\.\./)*versions/{VERSION}/([a-z]+)\.md#([^"]+)"',
         rf'href="{up}spec/{VERSION}/\1#\2"'),
    ]
    for pat, repl in pairs:
        html_text = re.sub(pat, repl, html_text)
    return html_text


def redirect_html(target: str, label: str) -> str:
    """A tiny bounce page. /spec has no version of its own — it forwards to the latest, so a typed
    or cited /spec always lands on the current specification without duplicating its content. The
    canonical points at the dated page, so crawlers index that, not this."""
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="refresh" content="0; url={target}">'
        f'<link rel="canonical" href="https://{SITE}{target}">'
        f'<meta name="robots" content="noindex,follow">'
        f'<title>{html.escape(label)} · Unified Harness Protocol</title></head>'
        f'<body style="font-family:system-ui,sans-serif;padding:2rem">'
        f'Redirecting to the <a href="{target}">current specification</a>&hellip;</body></html>')


def ver_menu_html() -> str:
    """The version dropdown's rows: each published version links to its own spec overview, latest
    marked. With one version it is a one-row menu; it grows by prepending to VERSIONS, and the
    per-version URLs already exist, so no page has to move when a version is added."""
    rows = []
    for i, v in enumerate(VERSIONS):
        tag = '<span class="vtag">latest</span>' if i == 0 else ""
        rows.append(f'<a role="menuitem" href="/spec/{v}"><span class="vname">{v}</span>{tag}</a>')
    return "".join(rows)


def desc_key(path: str) -> str:
    """Map a built page path to its description key. Spec pages carry the version in their path
    (spec/2026-08-11/architecture.html) but their descriptions are authored per chapter, version-
    independent (spec/architecture.html) — one description serves every version of a chapter."""
    return re.sub(rf"^spec/{re.escape(VERSION)}/", "spec/", path)


def section_of(path):
    for group, items in NAV:
        for pp, _, _ in items:
            if pp == path:
                return group
    return "Background"


def plain_text(html_body: str) -> str:
    """Body HTML to a single line of searchable text."""
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_body, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def flat_pages():
    return [(path, title, src) for _, items in NAV for path, title, src in items]


def url_for(path: str, up: str = "") -> str:
    """The URL a LINK should use. Files keep .html on disk; links drop it.

    A standards site gets cited, and a citation to .../spec/errors.html cannot survive a change
    of static host or generator, while .../spec/errors can. vercel.json sets cleanUrls, which
    serves the extensionless form and redirects the .html one, so old links keep working.

    Links are root-absolute. cleanUrls serves spec/index.html at /spec — no trailing slash — so a
    RELATIVE same-directory link on that page resolves against the site root and 404s. Absolute
    paths resolve identically from every serve path.
    """
    if path == "index.html":
        rel = ""
    elif path.endswith("/index.html"):
        rel = path[: -len("/index.html")]          # spec/index.html -> spec
    else:
        rel = path[: -len(".html")]                # conformance.html -> conformance
    return "/" + rel


def sidebar(current: str, depth: int) -> str:
    up = "../" * depth
    out = [f'<nav class="drawernav">'
           f'<a href="{url_for(f"spec/{VERSION}/index.html", up)}">Specification</a>'
           f'<a href="{url_for("conformance.html", up)}">Conformance</a>'
           f'<a href="{url_for("governance.html", up)}">Governance</a>'
           f'<a href="https://github.com/HarnessRouter/harnessrouter">GitHub</a>'
           f'</nav>']
    for group, items in NAV:
        out.append(f'<div class="group"><h4>{html.escape(group)}</h4>')
        for path, title, _ in items:
            cls = ' class="active"' if path == current else ""
            out.append(f'<a href="{url_for(path, up)}"{cls}>{html.escape(title)}</a>')
        out.append("</div>")
    return "\n".join(out)


def page(current: str, title: str, body: str, depth: int, hero: str = "", toc: str = "") -> str:
    up = "../" * depth
    # On a dated spec page the pill names that page's version; elsewhere it names the latest.
    page_ver = next((v for v in VERSIONS if current.startswith(f"spec/{v}/")), VERSION)
    shell_wide = "" if toc else " no-toc"
    pages = flat_pages()
    idx = next((i for i, (p, _, _) in enumerate(pages) if p == current), -1)
    prev_ = pages[idx - 1] if idx > 0 else None
    next_ = pages[idx + 1] if 0 <= idx < len(pages) - 1 else None
    pager = ""
    if prev_ or next_:
        left = f'<a href="{url_for(prev_[0], up)}">&larr; {html.escape(prev_[1])}</a>' if prev_ else "<span></span>"
        right = f'<a href="{url_for(next_[0], up)}">{html.escape(next_[1])} &rarr;</a>' if next_ else "<span></span>"
        pager = f'<div class="pager">{left}{right}</div>'

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · Unified Harness Protocol</title>
<meta name="description" content="{html.escape(DESCRIPTIONS[desc_key(current)])}">
<link rel="canonical" href="https://{SITE}/{url_for(current).lstrip("./")}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;450;500;600;700&family=Newsreader:opsz,wght@6..72,500;6..72,600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<script>try{{var t=localStorage.getItem("theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}}catch(e){{}}</script>
<style>{CSS}</style>
</head>
<body>
<header class="top">
  <div class="header-inner">
  <button id="menu" aria-label="Toggle navigation">☰</button>
  <a class="brand" href="{url_for("index.html", up)}"><span class="mark">U</span><span>Unified Harness Protocol</span></a>
  <div class="ver" id="ver">
    <button id="vbtn" class="verpill" aria-haspopup="menu" aria-expanded="false" aria-label="Specification version">
      <span class="dot"></span><span class="vcur">{page_ver}</span>
      <svg class="vchev" viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.4" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
    </button>
    <div class="vmenu" role="menu" hidden>
      <p class="vmenu-h">Specification version</p>
      {ver_menu_html()}
    </div>
  </div>
  <button id="sbtn" class="sbtn" aria-label="Search the site" aria-haspopup="dialog">
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.8-3.8"/></svg>
    <span class="sbtn-label">Search&hellip;</span><kbd>&#8984;K</kbd>
  </button>
  <span class="spacer"></span>
  <nav>
    <a href="{url_for(f"spec/{VERSION}/index.html", up)}">Specification</a>
    <a href="{url_for("conformance.html", up)}">Conformance</a>
    <a href="{url_for("governance.html", up)}">Governance</a>
    <a href="https://github.com/HarnessRouter/harnessrouter">GitHub</a>
  </nav>
  <div class="theme" id="theme">
    <button id="tbtn" class="tbtn" aria-label="Theme" aria-haspopup="menu" aria-expanded="false">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2m-3.5-6.5-1.4 1.4M6.9 17.1l-1.4 1.4m0-13 1.4 1.4m10.2 10.2 1.4 1.4"/></svg>
    </button>
    <div class="tmenu" role="menu" hidden>
      <button role="menuitemradio" data-theme-set="auto">Auto</button>
      <button role="menuitemradio" data-theme-set="light">Light</button>
      <button role="menuitemradio" data-theme-set="dark">Dark</button>
    </div>
  </div>
  </div>
</header>
<div id="sdlg" hidden role="dialog" aria-modal="true" aria-label="Search">
  <div class="sbackdrop"></div>
  <div class="spanel">
    <input id="sinput" type="search" placeholder="Search the specification&hellip;"
           autocomplete="off" spellcheck="false" data-root="{up}">
    <ol id="sresults" role="listbox"></ol>
    <p class="shint"><kbd>&uarr;</kbd><kbd>&darr;</kbd> navigate &middot; <kbd>Enter</kbd> open &middot; <kbd>Esc</kbd> close</p>
  </div>
</div>
<div class="shell{shell_wide}">
  <aside>{sidebar(current, depth)}</aside>
  <main>
    {hero}
    <article>{body}</article>
    {pager}
    <footer>
      Unified Harness Protocol {VERSION} · Apache-2.0 ·
      defined and maintained in the
      <a href="https://github.com/HarnessRouter/harnessrouter">HarnessRouter open-source repository</a>.
      The standard can be implemented independently of any hosted service.
    </footer>
  </main>
  {toc}
</div>
<script>{JS}</script>
</body>
</html>
"""


def check_links(dist: pathlib.Path) -> None:
    """Fail the build on any broken same-site link, so a dead cross-link can never reach deploy.

    A standards site's URLs are a contract: pages get cited, and a link that 404s — or an anchor
    that points at a heading that was renamed — is a defect in the standard's presentation. This
    runs on every build, local and CI, so the check lives with the generator and cannot drift from
    a separate linter. Across all output HTML it verifies three things for every same-site `href`
    and `src`: no in-repo `.md` link leaked through link rewriting; the path resolves to a file the
    build produced (honouring cleanUrls — /foo is served by foo.html or foo/index.html, and
    /schema/x.yaml is an exact file); and any `#fragment` matches an id on the target page. External
    schemes (http, mailto, tel, data, javascript) are out of scope.
    """
    import urllib.parse
    assets = {"/" + p.relative_to(dist).as_posix() for p in dist.rglob("*") if p.is_file()}
    id_cache: dict = {}

    def file_for(path_url: str):
        """The built file that serves a cleanUrls path, or None."""
        if path_url in assets:
            return path_url                                    # exact file (e.g. a schema asset)
        if path_url == "/":
            return "/index.html" if "/index.html" in assets else None
        for c in (path_url + ".html", path_url.rstrip("/") + "/index.html"):
            if c in assets:
                return c
        return None

    def ids_of(file_rel: str):
        if file_rel not in id_cache:
            id_cache[file_rel] = set(
                re.findall(r'id="([^"]+)"', (dist / file_rel.lstrip("/")).read_text()))
        return id_cache[file_rel]

    def page_url(rel: str) -> str:
        if rel == "/index.html":
            return "/"
        if rel.endswith("/index.html"):
            return rel[: -len("index.html")]                   # ".../index.html" -> ".../"
        return rel[:-5] if rel.endswith(".html") else rel

    external = ("http://", "https://", "mailto:", "tel:", "data:", "javascript:")
    bare_md, broken, bad_frag = [], [], []
    for p in sorted(dist.rglob("*.html")):
        rel = "/" + p.relative_to(dist).as_posix()
        base = page_url(rel)
        for _attr, href in re.findall(r'\b(href|src)="([^"]+)"', p.read_text()):
            if href.startswith(external):
                continue                                       # github .md blobs etc. are not ours
            if href.endswith(".md") or ".md#" in href:
                bare_md.append((rel, href))
                continue
            u = urllib.parse.urlsplit(href)
            if not u.path:                                     # a same-page "#anchor"
                if u.fragment and u.fragment not in ids_of(rel):
                    bad_frag.append((rel, href))
                continue
            path = u.path if u.path.startswith("/") else urllib.parse.urljoin(base, u.path)
            f = file_for(urllib.parse.unquote(path))
            if f is None:
                broken.append((rel, href))
            elif u.fragment and u.fragment not in ids_of(f):
                bad_frag.append((rel, href))
    assert not bare_md, f"in-repo .md links leaked into the build (link rewriting missed them): {bare_md[:10]}"
    assert not broken, f"internal links resolve to no built page: {broken[:15]}"
    assert not bad_frag, f"internal links point to a missing #anchor: {bad_frag[:15]}"


def check_count() -> int:
    """How many checks the conformance suite actually registers.

    Counted from checks.py rather than typed here. The hero said 47 while the suite registered 52,
    because a number written by hand into a second file is only correct on the day it is written —
    and on a standards site, a wrong count is a claim about the standard.
    """
    src = (ROOT / "conformance/uhp_conformance/checks.py").read_text()
    n = len(re.findall(r"^@check\(", src, flags=re.M))
    if n == 0:
        sys.exit("build: found no @check-registered conformance checks — decorator renamed?")
    return n


HERO = f"""
<div class="quicklinks">
  <a class="card-sm" href="/spec/{VERSION}"><b>Specification</b><span>The normative contract — ten versioned chapters.</span></a>
  <a class="card-sm" href="/conformance"><b>Conformance suite</b><span>{check_count()} runnable checks; the definition of conformant.</span></a>
  <a class="card-sm" href="/connecting"><b>Implement a client</b><span>Discovery, tasks, events, artifacts — over HTTP.</span></a>
  <a class="card-sm" href="/serving"><b>Implement a server</b><span>The operations a server answers behind the contract.</span></a>
</div>
"""


def build() -> int:
    # The description manifest must cover every page, one page per description, at snippet length.
    # Asserted here so a new page cannot ship with the homepage's description by accident.
    all_pages = {desc_key(p) for p, _, _ in flat_pages() + EXTRA}
    assert all_pages == set(DESCRIPTIONS), (
        f"description manifest out of sync — missing: {sorted(all_pages - set(DESCRIPTIONS))}, "
        f"stale: {sorted(set(DESCRIPTIONS) - all_pages)}")
    assert len(set(DESCRIPTIONS.values())) == len(DESCRIPTIONS), "duplicate meta descriptions"
    bad_len = {p: len(d) for p, d in DESCRIPTIONS.items() if not 100 <= len(d) <= 170}
    assert not bad_len, f"meta descriptions outside the 100-170 char band: {bad_len}"

    # Every version the dropdown offers must have a frozen source tree — a version is an address to
    # snapshotted markdown under protocol/versions/<date>/, never a re-render of the current text.
    missing_src = [v for v in VERSIONS if not (ROOT / "versions" / v).is_dir()]
    assert not missing_src, (
        f"VERSIONS lists versions with no source tree under protocol/versions/: {missing_src}")

    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "spec" / VERSION).mkdir(parents=True)

    built = 0
    search_index = []
    for path, title, src in flat_pages():
        if not src.exists():
            print(f"  !! missing source: {src}")
            return 1
        depth = path.count("/")
        md_text = src.read_text()
        GUIDE_CTA = (
            "\n\n---\n\n### Implementation guidance\n\n"
            "**[Implement a client](CONNECTING.md)** — discovery, task submission, event "
            "handling, and artifact retrieval.  \n"
            "**[Implement a server](SERVING.md)** — the operations a server answers and how it "
            "connects one or more harnesses.\n")
        if path in ("connecting.html", "serving.html"):
            md_text += GUIDE_CTA
        if path == "conformance.html":
            md_text += (
                "\n\n## Example implementations\n\n"
                "The [examples](IMPLEMENTATIONS.md) page lists the servers and clients "
                "built against UHP, with the version each targets. A listing is a factual entry, "
                "not a certification — this suite is the only thing that certifies.\n")
        rendered, toc = render_markdown(md_text)
        body = rewrite_links(rendered, depth)
        # The home page leads with the hero; its markdown H1 would repeat it.
        hero, toc_markup = "", toc_html(toc)
        if path == "index.html":
            # README is the homepage body (single source of truth). The quick-entry cards are
            # navigation scaffolding, not content — they follow the definition rather than
            # preceding the title, so the page reads title → definition → where to go next
            # (the neutral-standard order). Inject before the first H2 section.
            m = re.search(r"<h2", body)
            body = body[: m.start()] + HERO + body[m.start():] if m else body + HERO
            hero = ""
            # The homepage is a long, multi-section page like any other — keep its on-this-page
            # rail (toc_markup) so it navigates consistently with the rest of the site.
        (DIST / path).write_text(page(path, title, body, depth, hero, toc_markup))
        search_index.append({"title": title, "section": section_of(path),
                             "url": url_for(path).lstrip("/"),
                             "body": plain_text(body)[:1400]})
        built += 1

    for path, title, src in EXTRA:
        if not src.exists():
            print(f"  !! missing source: {src}")
            return 1
        depth = path.count("/")
        rendered, toc = render_markdown(src.read_text())
        body = rewrite_links(rendered, depth)
        (DIST / path).write_text(page(path, title, body, depth, "", toc_html(toc)))
        search_index.append({"title": title, "section": "Background",
                             "url": url_for(path).lstrip("/"),
                             "body": plain_text(body)[:1400]})
        built += 1

    # The dropdown offers every entry in VERSIONS; each must actually have been built, or a reader
    # who picks it lands on a 404. Today NAV emits only the latest version's chapters, so adding a
    # second version means teaching the build to emit its pages too — this assertion makes that a
    # hard build failure rather than a silent dead link.
    unbuilt = [v for v in VERSIONS if not (DIST / "spec" / v / "index.html").exists()]
    assert not unbuilt, (
        f"VERSIONS offers versions whose spec pages were not built: {unbuilt} — "
        f"extend NAV/build to emit /spec/<version>/ for each before listing it")

    # /spec forwards to the latest version's overview: a stable, friendly entry that never holds
    # content of its own, so there is nothing to keep in sync with the dated page it points at.
    (DIST / "spec" / "index.html").write_text(
        redirect_html(f"/spec/{VERSION}", "Specification"))

    # Publishing metadata: a protocol site that cannot be crawled is a protocol nobody finds.
    (DIST / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: https://{SITE}/sitemap.xml\n")
    urls = "".join(f"  <url><loc>https://{SITE}/{url_for(p).lstrip('./')}</loc></url>\n"
                   for p, _, _ in flat_pages() + EXTRA)
    (DIST / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n')

    # llms.txt: the same index the sitemap provides, in the markdown form AI tooling ingests when
    # someone hands it the site. Generated from the same page list, so it cannot drift.
    llms = [f"# Unified Harness Protocol\n\n> {DESCRIPTIONS['index.html']}\n"]
    for group, items in NAV:
        llms.append(f"\n## {group}\n")
        for p, title, _ in items:
            llms.append(f"- [{title}](https://{SITE}/{url_for(p).lstrip('./')}): {DESCRIPTIONS[desc_key(p)]}")
    llms.append("\n## Background\n")
    for p, title, _ in EXTRA:
        llms.append(f"- [{title}](https://{SITE}/{url_for(p).lstrip('./')}): {DESCRIPTIONS[desc_key(p)]}")
    (DIST / "llms.txt").write_text("\n".join(llms) + "\n", encoding="utf-8")

    # Search index: every page's title and plain-text body, built from the same render as the
    # pages themselves so it can never describe a page that no longer exists. Served static; the
    # search dialog fetches it once and filters in the browser — no search service, no build chain.
    (DIST / "search-index.json").write_text(json.dumps(search_index, ensure_ascii=False),
                                            encoding="utf-8")

    # One host config, at protocol/vercel.json — the Vercel project's Root Directory is protocol/,
    # so the Git integration reads it there on every push. It is also copied into the build so a
    # manual `vercel deploy site/dist` publishes with the identical cleanUrls/headers/redirects;
    # a single source means the two paths can never drift.
    shutil.copy(ROOT / "vercel.json", DIST / "vercel.json")

    # The machine-readable definitions are part of the standard, so they are served with it.
    shutil.copytree(ROOT / "schema", DIST / "schema",
                    ignore=shutil.ignore_patterns("build.py", "__pycache__"))

    # Last: every link in the finished site must resolve. Runs after schema is in place so links
    # to the machine-readable files are checked against the files that actually shipped.
    check_links(DIST)

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
