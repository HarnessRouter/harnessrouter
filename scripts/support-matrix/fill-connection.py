"""Stamp each pair with the connection its session ran on (the session's last_connection, read
from GET /v1/sessions/{id}), so the provider column says what actually served the run.
Usage: BASE=https://your-instance HR_API_KEY=... python3 fill-connection.py results-A.json results-B.json"""
import json, os, ssl, sys, urllib.request
BASE = os.environ["BASE"].rstrip("/"); KEY = os.environ["HR_API_KEY"]
CTX = ssl._create_unverified_context() if os.environ.get("IGNORE_TLS") == "1" else None
def session(sid):
    req = urllib.request.Request(f"{BASE}/api/harness/v1/sessions/{sid}", headers={"authorization": f"Bearer {KEY}"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=60, context=CTX).read().decode())
    except Exception as e:  # noqa: BLE001
        print(sid, "not read:", str(e)[:80]); return {}
for path in sys.argv[1:]:
    try: res = json.load(open(path))
    except Exception: continue
    n = 0
    for k, r in res.items():
        sid = r.get("sid")
        if not sid or r.get("connection"): continue
        v = session(sid).get("last_connection") or ""
        if v: r["connection"] = v; n += 1
    json.dump(res, open(path, "w"), indent=1); print(path, "stamped", n)
