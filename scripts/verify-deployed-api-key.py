"""Verify the self-hosted public API-key path through both Gateway and Console BFF.

The generated key is held only in memory and is revoked in ``finally``. The script deliberately
prints status labels only; neither the key nor the internal trust header is ever printed.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import httpx


def _load_internal_key() -> str:
    value = os.environ.get("HARNESS_INTERNAL_KEY", "")
    if value:
        return value
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    try:
        with open(env_path, encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if line.startswith("HARNESS_INTERNAL_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    raise RuntimeError("HARNESS_INTERNAL_KEY is required; set it or provide a project .env file")


async def main() -> None:
    internal = _load_internal_key()
    org = "verify-api-key-" + uuid.uuid4().hex[:12]
    identity = {
        "x-harness-internal": internal,
        "x-harness-org": org,
        "x-harness-member": "api-key-verification@example.invalid",
    }
    key_id = ""
    api_key = ""
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            minted = await client.post(
                f"http://127.0.0.1:8080/v1/orgs/{org}/keys",
                headers=identity,
                json={"name": "temporary-api-key-verification", "member_id": identity["x-harness-member"]},
            )
            assert minted.status_code == 200, minted.text
            body = minted.json()
            key_id, api_key = str(body["id"]), str(body["key"])
            assert api_key.startswith("sk-hr-")

            bearer = {"authorization": f"Bearer {api_key}", "x-harness-org": org,
                      "x-harness-member": identity["x-harness-member"]}
            native = await client.get("http://127.0.0.1:8080/v1/harnesses", headers=bearer)
            assert native.status_code == 200, native.text

            bff = await client.get("http://127.0.0.1:3000/api/harness/v1/harnesses", headers=bearer)
            assert bff.status_code == 200, bff.text

            revoked = await client.delete(
                f"http://127.0.0.1:8080/v1/orgs/{org}/keys/{key_id}", headers=identity
            )
            assert revoked.status_code == 200, revoked.text
            after = await client.get("http://127.0.0.1:8080/v1/harnesses", headers=bearer)
            assert after.status_code == 401, after.text
            print(json.dumps({"mint": 200, "native_api_key": native.status_code,
                              "bff_api_key": bff.status_code, "revoke": revoked.status_code,
                              "after_revoke": after.status_code}))
        finally:
            if key_id:
                await client.delete(f"http://127.0.0.1:8080/v1/orgs/{org}/keys/{key_id}", headers=identity)


if __name__ == "__main__":
    asyncio.run(main())
