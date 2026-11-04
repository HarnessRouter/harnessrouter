#!/usr/bin/env python3
"""The licence check has to be able to fail: a check that passes everything is worse than none."""
import importlib.util
import json
import os
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("cl", os.path.join(here, "check-licenses.py"))
cl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cl)

for ok in ("MIT", "ISC", "Apache-2.0", "BSD-3-Clause", "(MIT OR Apache-2.0)", "MIT AND ISC", "MPL-2.0 OR Apache-2.0", "MIT-CMU", "Zlib"):
    assert cl.permissive(ok), ok
for no in ("", "GPL-3.0", "AGPL-3.0-only", "LGPL-3.0-or-later", "SSPL-1.0", "BUSL-1.1", "Elastic-2.0", "UNLICENSED", "MPL-2.0",
           "SEE LICENSE IN LICENSE", "Apache-2.0 AND LGPL-3.0-or-later AND MIT", "MIT AND GPL-2.0", "None"):
    assert not cl.permissive(no), no

with tempfile.TemporaryDirectory() as d:
    lock = os.path.join(d, "package-lock.json")
    with open(lock, "w") as f:
        json.dump({"packages": {
            "": {"name": "root"},
            "node_modules/fine": {"version": "1.0.0", "license": "MIT"},
            "node_modules/copyleft": {"version": "1.0.0", "license": "GPL-3.0"},
            "node_modules/undeclared": {"version": "1.0.0"},
            "node_modules/nested/node_modules/deep": {"version": "2.0.0", "license": "AGPL-3.0-only"},
            "node_modules/devonly": {"version": "1.0.0", "license": "GPL-3.0", "dev": True},
            "node_modules/linked": {"resolved": "vendor/x", "link": True},
            "vendor/x": {"version": "0.0.0", "license": "Apache-2.0"},
        }}, f)
    bad = " ".join(cl.js(lock))
    assert "copyleft" in bad and "undeclared" in bad and "deep" in bad, bad
    assert "fine" not in bad and "devonly" not in bad and "linked" not in bad, bad

    for name, body in {"lgpl": {"name": "lgpl", "version": "1.0.0", "license": "LGPL-3.0-or-later"},
                       "old": {"name": "old", "version": "1.0.0", "licenses": [{"type": "GPL-2.0"}]},
                       "ok": {"name": "ok", "version": "1.0.0", "license": "MIT"},
                       "marker": {"type": "module"}}.items():
        os.makedirs(os.path.join(d, "app", "node_modules", name))
        with open(os.path.join(d, "app", "node_modules", name, "package.json"), "w") as f:
            json.dump(body, f)
    bad = " ".join(cl.image((os.path.join(d, "app"),)))
    assert "lgpl@" in bad and "old@" in bad, bad
    assert "ok@" not in bad and "marker" not in bad, bad

# what's accepted stays short, and the thing this was written for doesn't come back through it
assert not any("sharp" in k for k in cl.ACCEPTED_JS), cl.ACCEPTED_JS
assert set(cl.ACCEPTED_PY) == {"certifi", "pyphen", "pypdfium2"}, cl.ACCEPTED_PY
assert set(cl.ACCEPTED_JS) == {"format"}, cl.ACCEPTED_JS
print("the licence check can fail")
