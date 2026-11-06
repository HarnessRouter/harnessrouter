"""Local design preview only (not part of the repo): the gateway with sample memory services.

Each sample service keeps records in this process like the conformance fixture, and answers with
the real vendor's capability document, so the Console draws what it would draw for that vendor.
Nothing is kept across a restart; seed.py fills it again.
"""
import os, sys
GW = os.environ.get("HR_GATEWAY_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "gateway")
sys.path.insert(0, os.path.abspath(GW))
import app as gateway  # noqa: E402
import memory_plane as mp  # noqa: E402
import memory_fixture  # noqa: E402


def sample(pid):
    real = mp.PROVIDERS.get(pid)
    caps = dict(real.capabilities()) if real else {}

    class Sample(memory_fixture.FixtureProvider):
        id = pid
        def capabilities(self):
            c = super().capabilities()
            c.update({k: v for k, v in caps.items() if k in ("observe", "history", "revise", "forget", "erase", "schema", "layout", "derivation", "graph")})
            c["id"] = pid
            return c
        async def bind(self, org, workspace):
            return self
        async def apply_schema(self, mid, schema):
            return None
    return Sample()


for pid in ("graphiti", "hindsight", "mem0"):
    mp.PROVIDERS[pid] = sample(pid)
# the conformance fixture is a test provider, not a service anyone would choose
mp.PROVIDERS.pop("fixture", None)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(gateway.app, host="127.0.0.1", port=int(os.environ.get("HR_GW_PORT", "8080")), log_level="warning")
