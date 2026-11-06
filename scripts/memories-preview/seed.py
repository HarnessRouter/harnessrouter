"""Fills the local preview with sample memories (sample data, not anyone's real data)."""
import json, os, sys, urllib.request

BASE = os.environ.get("HR_CONSOLE", "http://localhost:3000") + "/api/harness"
H = {"content-type": "application/json", "x-harness-org": "local", "x-harness-member": "local@localhost",
     "x-harness-workspace": "default", "x-harness-workspace-default": "1"}

def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, headers=H, data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path}: {e.code} {e.read()[:300]!r}")

if call("GET", "/v1/memories").get("data"):
    print("already seeded"); sys.exit(0)

# five setups
existing = {h["name"]: h["id"] for h in (call("GET", "/v1/harnesses").get("data") or [])}
S = {}
for n in ["Support agent", "Sales assistant", "Research analyst", "Content writer", "Onboarding guide"]:
    S[n] = existing.get(n) or call("POST", "/v1/harnesses", {"name": n, "base": "codex"})["id"]

C = {"blue": "#285aff", "violet": "#7c5cff", "teal": "#0f9d8a", "orange": "#f08a24", "pink": "#e0457b", "slate": "#5b6b82"}

def memory(name, desc, provider, setups, schema=None):
    m = call("POST", "/v1/memories", {"name": name, "description": desc, "provider": provider})
    if schema:
        call("PUT", f"/v1/memories/{m['id']}/schema", schema)
    for s in setups:
        call("POST", f"/v1/memories/{m['id']}/grants", {"principal": f"member:{S[s]}", "privileges": ["read", "write", "create"]})
    return m["id"]

def ent(mid, typ, title, text, **attrs):
    return call("POST", f"/v1/memories/{mid}/records", {"type": "entity", "title": title, "content": [{"type": "text", "text": text}],
                                                         "attributes": {"entity_type": typ, **attrs}})["id"]

def fact(mid, a, rel, b, text):
    return call("POST", f"/v1/memories/{mid}/records", {"type": "fact", "title": text, "content": [{"type": "text", "text": text}],
                                                         "attributes": {"relation": rel},
                                                         "references": [{"rel": "subject", "record_id": a}, {"rel": "object", "record_id": b}]})["id"]

def note(mid, typ, title, text, labels=None):
    return call("POST", f"/v1/memories/{mid}/records", {"type": typ, "title": title, "content": [{"type": "text", "text": text}],
                                                         "attributes": ({"labels": labels} if labels else {})})["id"]

# 1. Customers: 9 entities, 7 facts
m = memory("Customers", "Who our customers are, where they work and what they use.", "graphiti", ["Support agent", "Sales assistant", "Onboarding guide"], {
    "types": [
        {"name": "Person", "description": "Someone we talk to.", "color": C["blue"], "icon": "user", "x": 0, "y": 0,
         "properties": [{"name": "role", "type": "text"}, {"name": "email", "type": "text"}]},
        {"name": "Company", "description": "An organisation that buys from us.", "color": C["violet"], "icon": "building", "x": 320, "y": 0,
         "properties": [{"name": "plan", "type": "choice", "options": ["Free", "Pro", "Enterprise"]}, {"name": "seats", "type": "number"}]},
        {"name": "Product", "description": "Something we sell.", "color": C["teal"], "icon": "box", "x": 160, "y": 220,
         "properties": [{"name": "tier", "type": "text"}]}],
    "relations": [{"name": "works_at", "from": "Person", "to": "Company"}, {"name": "uses", "from": "Company", "to": "Product"}]})
p = {n: ent(m, "Person", n, d, role=r) for n, d, r in [
    ("Maya Chen", "Head of platform at Northwind. Prefers short weekly updates.", "Head of platform"),
    ("Jonas Weber", "Engineering lead at Lumen Health.", "Engineering lead"),
    ("Priya Nair", "Buyer at Acme Robotics. Renewal in March.", "Procurement"),
    ("Sam Okafor", "Developer at Northwind, first contact for API questions.", "Developer")]}
c = {n: ent(m, "Company", n, d, plan=pl) for n, d, pl in [
    ("Northwind", "Logistics software, 120 seats.", "Enterprise"), ("Lumen Health", "Clinic scheduling.", "Pro"), ("Acme Robotics", "Warehouse robots.", "Pro")]}
pr = {n: ent(m, "Product", n, d) for n, d in [("Agent API", "One API for every agent harness."), ("Console", "Where setups are built and watched.")]}
for a, b in [("Maya Chen", "Northwind"), ("Sam Okafor", "Northwind"), ("Jonas Weber", "Lumen Health"), ("Priya Nair", "Acme Robotics")]:
    fact(m, p[a], "works_at", c[b], f"{a} works at {b}.")
for a, b in [("Northwind", "Agent API"), ("Lumen Health", "Console"), ("Acme Robotics", "Agent API")]:
    fact(m, c[a], "uses", pr[b], f"{a} uses {b}.")

# 2. Support playbook: 7 entities, 5 facts
m = memory("Support playbook", "Known issues, what fixed them, and what they affect.", "graphiti", ["Support agent"], {
    "types": [
        {"name": "Issue", "color": C["pink"], "icon": "bug", "x": 0, "y": 0, "properties": [{"name": "severity", "type": "choice", "options": ["low", "high"]}]},
        {"name": "Fix", "color": C["teal"], "icon": "check", "x": 300, "y": 0, "properties": [{"name": "steps", "type": "text"}]},
        {"name": "Area", "color": C["slate"], "icon": "box", "x": 150, "y": 200}],
    "relations": [{"name": "fixed_by", "from": "Issue", "to": "Fix"}, {"name": "affects", "from": "Issue", "to": "Area"}]})
i = {n: ent(m, "Issue", n, d) for n, d in [("Stream stops after 60 s", "A long task's stream closes when a proxy times out."),
                                           ("Key rejected", "A new API key is used before it is saved."), ("File upload too large", "Uploads over 50 MB are refused.")]}
f = {n: ent(m, "Fix", n, d) for n, d in [("Raise the proxy timeout", "Set the proxy's read timeout above the task's length."),
                                         ("Save the key first", "Save, then copy the key."), ("Split the upload", "Send the file in parts.")]}
ar = ent(m, "Area", "Streaming", "Server-sent events from a running task.")
for a, b in zip(i, f):
    fact(m, i[a], "fixed_by", f[b], f"{a}: {b.lower()}.")
fact(m, i["Stream stops after 60 s"], "affects", ar, "Stream stops after 60 s affects streaming.")
fact(m, i["File upload too large"], "affects", ar, "Large uploads affect streaming tasks.")

# 3. Team and projects: 6 entities, 3 facts
m = memory("Team and projects", "Who works on what.", "graphiti", ["Research analyst"], {
    "types": [{"name": "Person", "color": C["blue"], "icon": "user", "x": 0, "y": 0},
              {"name": "Project", "color": C["orange"], "icon": "flag", "x": 300, "y": 0},
              {"name": "Team", "color": C["violet"], "icon": "users", "x": 150, "y": 200}],
    "relations": [{"name": "leads", "from": "Person", "to": "Project"}, {"name": "member_of", "from": "Person", "to": "Team"}]})
t = {n: ent(m, "Person", n, n + ".") for n in ["Richard", "Vivian", "Leo"]}
pj = {n: ent(m, "Project", n, d) for n, d in [("Memories", "Where agents keep what outlasts a task."), ("Community", "Events and ambassadors.")]}
tm = ent(m, "Team", "Product", "Builds the console.")
fact(m, t["Richard"], "leads", pj["Memories"], "Richard leads Memories.")
fact(m, t["Vivian"], "leads", pj["Community"], "Vivian leads Community.")
fact(m, t["Leo"], "member_of", tm, "Leo is on the product team.")

# 4. Writing style (labels): 5
m = memory("Writing style", "How we write: tone, words we use and avoid.", "hindsight", ["Content writer"],
           {"types": [{"name": "tone"}, {"name": "vocabulary"}, {"name": "format"}], "relations": []})
for ttl, txt, lb in [("Short sentences", "Keep sentences short. One idea each.", ["tone"]),
                     ("Lower-case nouns", "Common nouns stay lower-case: agent harness, setup.", ["vocabulary"]),
                     ("No dashes", "Use a full stop or a colon instead of a dash.", ["format"]),
                     ("Say what it does", "Describe behaviour, never internal names.", ["vocabulary"]),
                     ("Numbers are real", "Show a dash when a number is unknown.", ["tone"])]:
    note(m, "fact", ttl, txt, lb)

# 5. Sales notes: 5
m = memory("Sales notes", "What each prospect asked and what we promised.", "mem0", ["Sales assistant"])
for ttl, txt in [("Northwind wants SSO", "Northwind asked for SSO before rolling out to 400 seats."),
                 ("Acme asked about on-prem", "Acme Robotics wants to self-host Community Edition."),
                 ("Lumen compares harnesses", "Lumen is comparing Codex and Claude Code on their scheduling tasks."),
                 ("Pricing call on Friday", "Pricing call with Priya on Friday at 10."),
                 ("Send the benchmark", "Promised Jonas the latest benchmark numbers.")]:
    note(m, "fact", ttl, txt)

# 6. Onboarding: 3
m = memory("Onboarding", "The steps a new customer goes through in the first week.", "mem0", ["Onboarding guide", "Support agent"])
for ttl, txt in [("Day 1: first agent run", "Pick a demo and send the example request."),
                 ("Day 2: connect the app", "Add the API key and run the connection check."),
                 ("Day 5: check in", "Ask what they built and what got in the way.")]:
    note(m, "procedure", ttl, txt)

L = call("GET", "/v1/memories")["data"]
print(len(L), "memories,", sum(x["records"]["count"] or 0 for x in L), "records")
