"""Whether a served model id names the model the pair asked for: the gateway's rule, verbatim.

An aggregator adds or drops a vendor prefix (anthropic/claude-fable-5 is claude-fable-5) and a
provider appends a dated or versioned suffix (claude-haiku-4-5-20251001, gemini-2.5-flash-001);
those are the provider's alias of the same model. A different family or number under any prefix
(google/gemini-3-flash-preview for gemini-3.8-flash), or a tier word such as -lite, is another
model: a finding. The OSS tree carries the same file; keep them identical."""
import re

_VERSION_SUFFIX_RE = re.compile(r"^(-(\d{2,}|v\d+|preview|latest))+$")   # -20251001, -001, -v2, -preview-05-20; never -lite


def _table_ids() -> dict[str, set[str]]:
    """canonical -> every provider-native id the gateway's vendor tables map it to, read from the
    gateway's source without importing it (the same way the capability test reads it). A served id
    that IS the table's own name for the model asked for is the provider's alias by definition:
    tencent/hy3 for hunyuan-3, nvidia/nemotron-3-ultra-550b-a55b for nemotron-3-ultra."""
    import os, re
    src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "gateway", "app.py")
    out: dict[str, set[str]] = {}
    try:
        src = open(src_path).read()
    except OSError:
        return out
    m = re.search(r"_VENDOR_MODELS: dict\[str, dict\[str, str\]\] = (\{.*?\n\})\n", src, re.S)
    if not m:
        return out
    try:
        tables = eval(m.group(1), {"__builtins__": {}}, {})  # noqa: S307 — our own literal
    except Exception:  # noqa: BLE001
        return out
    for table in tables.values():
        for canonical, pid in table.items():
            out.setdefault(canonical, set()).add(pid.lower())
    for r in re.finditer(r"_(?:VERCEL|OPENROUTER)_RESLUG = (\{.*?\n\})\n", src, re.S):
        try:
            for canonical, pid in eval(r.group(1), {"__builtins__": {}}, {}).items():  # noqa: S307
                out.setdefault(canonical, set()).add(pid.lower())
        except Exception:  # noqa: BLE001
            pass
    return out


_TABLE_IDS: dict[str, set[str]] | None = None


def same_model(asked: str, served: str) -> bool:
    global _TABLE_IDS
    def norm(m: str) -> str:
        m = (m or "").strip().lower().split("/")[-1]
        return m.replace(".", "-")
    a, s = norm(asked), norm(served)
    if not a or not s:
        return False
    if a == s:
        return True
    if _TABLE_IDS is None:
        _TABLE_IDS = _table_ids()
    sv = (served or "").strip().lower()
    if sv in _TABLE_IDS.get((asked or "").strip().lower(), set()) or sv.split("/")[-1] in {x.split("/")[-1] for x in _TABLE_IDS.get((asked or "").strip().lower(), set())}:
        return True
    long, short = (s, a) if len(s) > len(a) else (a, s)
    return long.startswith(short + "-") and _VERSION_SUFFIX_RE.match(long[len(short):]) is not None


def alias_of(asked: str, served: str) -> bool:
    """A served entry may join the models one turn ran on with commas; it is an alias only when
    every id in it is the same model."""
    ids = [x.strip() for x in str(served or "").split(",") if x.strip()]
    return bool(ids) and all(same_model(asked, x) for x in ids)
