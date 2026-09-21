"""The dual loop's platform side (docs/dual-loop.md in the System One Harness repository, App. B).

A Calibrator harness drives ONE inner harness through the platform's own API. Its turn is handed
the API and a credential scoped to that harness and expiring with the turn: never an org key,
never a provider key. The credential reaches the routes that start and read that harness's runs
and publish its package, and nothing else. A run that ends on a refusal or an escalation carries
its handoff beside its reason.
"""
import os
import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

INNER = "chrn_0123456789abcdef0123456789abcdef"


def test_a_harness_that_drives_another_names_it_and_the_setting_round_trips():
    body = gw.HarnessBody(name="Calibrator", base="pi", calibrates=INNER)
    assert gw._harness_props(body)["calibrates"] == INNER
    assert gw._harness_out({"id": "h", "calibrates": INNER})["calibrates"] == INNER
    assert gw._harness_out({"id": "h"})["calibrates"] == ""


def test_a_turn_of_such_a_harness_is_handed_the_api_and_a_scoped_credential_and_no_other_turn_is():
    assert gw._calibration_env({"calibrates": ""}, "org", "hsess1", 600) is None
    assert gw._calibration_env(None, "org", "hsess1", 600) is None
    env = gw._calibration_env({"calibrates": INNER}, "org-a", "hsess1", 600)
    assert env["HR_API_URL"] == gw.HR_PLATFORM_API_URL and env["HR_INNER_HARNESS"] == INNER
    tok = env["HR_CALIBRATION_TOKEN"]
    assert tok.startswith("hrc_")
    c = gw._verify_calibration_token(tok)
    assert c["org"] == "org-a" and c["inner"] == INNER and c["sid"] == "hsess1"
    assert 600 < c["exp"] - time.time() <= 1200          # the turn's cap plus a margin


def test_the_credential_expires_and_a_tampered_one_is_nothing():
    tok = gw._mint_calibration_token("hsess1", "org-a", INNER, 60)
    assert gw._verify_calibration_token(tok) is not None
    # an expired one, built the way the minter builds them with a past expiry (the minter itself
    # never mints one shorter than a minute)
    import base64
    import hashlib
    import hmac
    body = f"hsess1|org-a|{INNER}|{int(time.time()) - 5}"
    sig = hmac.new((gw.INTERNAL_KEY or "dev-insecure").encode(), b"calibration|" + body.encode(), hashlib.sha256).hexdigest()
    expired = "hrc_" + base64.urlsafe_b64encode(body.encode()).decode().rstrip("=") + "." + sig
    assert gw._verify_calibration_token(expired) is None
    head, sig = tok.split(".", 1)
    assert gw._verify_calibration_token(head + "." + ("0" if sig[0] != "0" else "1") + sig[1:]) is None
    assert gw._verify_calibration_token("hrc_garbage") is None
    assert gw._verify_calibration_token("hrc_") is None


def test_the_credential_reaches_its_harness_s_routes_and_nothing_else():
    ok = gw._calibration_route_allowed
    other = "chrn_ffffffffffffffffffffffffffffffff"
    assert ok("POST", "/v1/responses", INNER)
    assert ok("GET", "/v1/responses/resp_1", INNER)
    assert ok("POST", "/v1/responses/resp_1/cancel", INNER)
    assert ok("GET", "/v1/sessions", INNER) and ok("GET", "/v1/sessions/hsess1", INNER)
    assert ok("GET", "/v1/sessions/hsess1/turns", INNER)
    assert ok("GET", "/v1/sessions/hsess1/files", INNER) and ok("GET", "/v1/sessions/hsess1/files/observations/000001.jpg", INNER)
    assert ok("GET", f"/v1/harnesses/{INNER}", INNER) and ok("PUT", f"/v1/harnesses/{INNER}", INNER)
    assert ok("GET", f"/v1/harnesses/{INNER}/plugin", INNER) and ok("PUT", f"/v1/harnesses/{INNER}/plugin", INNER)
    # the installed package's files, which is what the outer loop edits (the export route is a
    # generated package named after the harness, and publishing it back made a stray, 2026-09-21)
    assert ok("GET", f"/v1/harnesses/{INNER}/plugins/mario-env/files", INNER)
    assert not ok("GET", f"/v1/harnesses/{other}/plugins/mario-env/files", INNER)
    assert not ok("PUT", f"/v1/harnesses/{INNER}/plugins/mario-env/files", INNER)
    assert ok("POST", "/v1/kits/mario/launch", INNER)
    assert ok("get", "/api/harness/v1/sessions", INNER)         # through the console's proxy prefix
    # not its harness, not its business
    assert not ok("GET", f"/v1/harnesses/{other}", INNER) and not ok("PUT", f"/v1/harnesses/{other}/plugin", INNER)
    assert not ok("DELETE", f"/v1/harnesses/{INNER}", INNER)
    assert not ok("POST", "/v1/harnesses", INNER)
    assert not ok("POST", "/v1/orgs/org-a/keys", INNER) and not ok("GET", "/v1/orgs/org-a/keys", INNER)
    assert not ok("GET", "/v1/admin/integrations", INNER) and not ok("PUT", "/v1/admin/integrations", INNER)
    assert not ok("PUT", "/v1/sessions/hsess1/files/x.txt", INNER)
    assert not ok("DELETE", "/v1/sessions/hsess1", INNER)
    assert not ok("GET", "/v1/harnesses", INNER)


def test_the_principal_of_a_credential_carries_its_scope_and_is_refused_off_its_routes():
    import asyncio
    from fastapi import HTTPException
    tok = gw._mint_calibration_token("hsess1", "org-a", INNER, 600)

    class _Req:
        def __init__(self, method, path, auth):
            self.method = method
            self.headers = {"authorization": auth}
            self.url = type("U", (), {"path": path})()

    p = asyncio.run(gw._principal(_Req("POST", "/v1/responses", "Bearer " + tok)))
    assert p["org"] == "org-a" and p["member"] == "calibrator:hsess1" and p["calibration"]["inner"] == INNER
    with pytest.raises(HTTPException) as e:
        asyncio.run(gw._principal(_Req("POST", "/v1/orgs/org-a/keys", "Bearer " + tok)))
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        asyncio.run(gw._principal(_Req("POST", "/v1/responses", "Bearer hrc_forged.deadbeef")))
    assert e.value.status_code == 401


def test_an_incomplete_response_carries_the_handoff_beside_its_reason():
    t = gw._RespTranslator("resp_1", "m", None, True, time.time())
    t.incomplete_reason = "no_confident_action"
    t.handoff = {"reason": "no_confident_action", "step": 7, "weakest": 0.41, "threshold": 0.7, "risk": "write",
                 "state": "...", "questions": {}, "answers": {}}
    out = t._response_obj("incomplete")
    assert out["incomplete_details"] == {"reason": "no_confident_action", "handoff": t.handoff}
    t2 = gw._RespTranslator("resp_2", "m", None, True, time.time())
    t2.incomplete_reason = "max_steps"
    assert t2._response_obj("incomplete")["incomplete_details"] == {"reason": "max_steps", "handoff": None}
    assert t2._response_obj("completed")["incomplete_details"] is None
