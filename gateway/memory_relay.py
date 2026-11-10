"""Memory services on the model relay.

A memory vendor's server (Graphiti, Hindsight, Mem0, ReMe) reads and searches with models: one it extracts with, one it
embeds with. Instead of a provider key of its own, it calls this gateway's relay (/v1/llm) with a credential for one
memory service, and the relay sends each call through this instance's own keys (Bring your own key) for that model.

  service    = a vendor's server set up for one pair of models. Kept in the registry, a vault document, so a credential
               can be withdrawn: `{id: {vendor, llm_model, small_model?, embedding_model, created_at, revoked}}`.
  credential = `hrm_<service id>.<signature>`, signed with the gateway's key. Checked against the registry on every call.
  a call     = on the inference paths only (chat completions, responses, embeddings), naming one of the service's own
               models. The model is sent as the key that serves it names it.

Which key serves a model: any of this instance's keys can. A model this module knows (the extraction models vendors
are built and measured with, and the embedding models, which aren't in the agents' catalog) goes to its maker's own key
first, then a gateway's; any other model goes where the agents' catalog sends it. An Azure key serves only what it has
deployed. An instance can limit and order the keys memory services use (HR_MEMORY_RELAY_KEYS: provider types or key
names, e.g. "vercel,azure-foundry"): the test instance does, so its memory vendors spend gateway credit, never a
provider's own key (Richard 2026-11-06: the platform supports every provider; dev and testing stick to Vercel AI Gateway
and Azure OpenAI).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time

PREFIX = "hrm_"
REGISTRY_KEY = "harness-memory-services"
# whose server holds a credential: a vendor's, or the operator's own tools (an evaluation's judge), on the same terms
VENDORS = ("graphiti", "hindsight", "mem0", "reme", "operator")
PATHS = {"chat/completions": "chat", "responses": "chat", "embeddings": "embedding"}

# Model -> what it is and its id at each kind of key, the maker first (an Azure deployment is named for its model).
_OPENAI = lambda m: {"openai": m, "azure": m, "vercel": f"openai/{m}", "openrouter": f"openai/{m}"}   # noqa: E731
MODELS: dict[str, dict] = {
    "gpt-4o-mini": {"kind": "chat", "label": "GPT-4o mini", "ids": _OPENAI("gpt-4o-mini")},
    "gpt-4.1-mini": {"kind": "chat", "label": "GPT-4.1 mini", "ids": _OPENAI("gpt-4.1-mini")},
    "text-embedding-3-small": {"kind": "embedding", "label": "text-embedding-3-small", "dims": 1536, "ids": _OPENAI("text-embedding-3-small")},
    "text-embedding-3-large": {"kind": "embedding", "label": "text-embedding-3-large", "dims": 3072, "ids": _OPENAI("text-embedding-3-large")},
}
_SID = re.compile(r"msvc_[0-9a-f]{16}")


def _sig(key: bytes, sid: str) -> str:
    return hmac.new(key, f"hrm|{sid}".encode(), hashlib.sha256).hexdigest()


def mint(key: bytes, sid: str) -> str:
    return f"{PREFIX}{sid}.{_sig(key, sid)}"


def verify(key: bytes, tok: str) -> str | None:
    """The service id a well-formed, correctly signed credential names, else None. The registry decides the rest."""
    if not tok or not tok.startswith(PREFIX):
        return None
    try:
        sid, sig = tok[len(PREFIX):].rsplit(".", 1)
    except ValueError:
        return None
    if not _SID.fullmatch(sid) or not hmac.compare_digest(sig, _sig(key, sid)):
        return None
    return sid


def new_id() -> str:
    return "msvc_" + secrets.token_hex(8)


def service_record(vendor: str, llm_model: str, embedding_model: str, small_model: str = "") -> dict:
    return {"vendor": vendor, "llm_model": llm_model, "small_model": small_model or "", "embedding_model": embedding_model,
            "created_at": int(time.time()), "revoked": False}


def models_of(service: dict) -> set[str]:
    return {m for m in (service.get("llm_model"), service.get("small_model"), service.get("embedding_model")) if m}


def kind_of(model: str, catalog: dict[str, str]) -> str | None:
    """`chat` or `embedding` for a model a memory service can be set up with, else None."""
    if model in MODELS:
        return MODELS[model]["kind"]
    return "chat" if model in catalog else None


def _kind(integ: dict) -> str:
    p = str(integ.get("provider") or "").lower()
    return "azure" if p.startswith("azure") else p


def _named(integ: dict, prefer: list[str]) -> int:
    """Where a key stands in the instance's list (by provider type or key name), or -1 when it isn't on it."""
    for i, want in enumerate(prefer):
        w = want.strip().lower()
        if w and w in (str(integ.get("provider") or "").lower(), _kind(integ), str(integ.get("name") or "").lower()):
            return i
    return -1


def pick(model: str, integrations: list[dict], catalog: dict[str, str], ids_of, prefer: list[str] | None = None) -> tuple[dict, str] | None:
    """(the key that serves `model`, the model's id there), or None. `catalog` is the agents' model -> key name map and
    `ids_of(key)` a key's model -> id map from the agents' tables. `prefer`, the instance's list, limits and orders keys."""
    keys = [i for i in integrations if i.get("enabled", True) is not False]
    if prefer:
        keys = sorted((i for i in keys if _named(i, prefer) >= 0), key=lambda i: _named(i, prefer))
    known = MODELS.get(model)

    def serves(integ: dict) -> str | None:
        k, listed = _kind(integ), ids_of(integ)
        if known:
            if k not in known["ids"] or (k == "azure" and model not in listed):
                return None
            return listed[model] if k == "azure" else known["ids"][k]
        return listed.get(model)
    if known and not prefer:
        # the maker's own key first, then a gateway's, in the order the model lists them
        for k in known["ids"]:
            for integ in keys:
                if _kind(integ) == k and (pid := serves(integ)):
                    return integ, pid
        return None
    if not known and not prefer:
        integ = next((i for i in keys if str(i.get("name") or "") == catalog.get(model)), None)
        return (integ, ids_of(integ).get(model, model)) if integ else None
    for integ in keys:
        if (pid := serves(integ)):
            return integ, pid
    return None


def model_in(body: bytes) -> str:
    try:
        doc = json.loads(body or b"{}")
    except ValueError:
        return ""
    return str(doc.get("model") or "") if isinstance(doc, dict) else ""


def with_model(body: bytes, pid: str) -> bytes:
    doc = json.loads(body)
    doc["model"] = pid
    return json.dumps(doc).encode()
