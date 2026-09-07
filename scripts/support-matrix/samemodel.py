"""Whether a served model id names the model the pair asked for: the gateway's rule, verbatim.

An aggregator adds or drops a vendor prefix (anthropic/claude-fable-5 is claude-fable-5) and a
provider appends a dated or versioned suffix (claude-haiku-4-5-20251001, gemini-2.5-flash-001);
those are the provider's alias of the same model. A different family or number under any prefix
(google/gemini-3-flash-preview for gemini-3.8-flash), or a tier word such as -lite, is another
model: a finding. The OSS tree carries the same file; keep them identical."""
import re

_VERSION_SUFFIX_RE = re.compile(r"^(-(\d{2,}|v\d+|preview|latest))+$")   # -20251001, -001, -v2, -preview-05-20; never -lite


def same_model(asked: str, served: str) -> bool:
    def norm(m: str) -> str:
        m = (m or "").strip().lower().split("/")[-1]
        return m.replace(".", "-")
    a, s = norm(asked), norm(served)
    if not a or not s:
        return False
    if a == s:
        return True
    long, short = (s, a) if len(s) > len(a) else (a, s)
    return long.startswith(short + "-") and _VERSION_SUFFIX_RE.match(long[len(short):]) is not None


def alias_of(asked: str, served: str) -> bool:
    """A served entry may join the models one turn ran on with commas; it is an alias only when
    every id in it is the same model."""
    ids = [x.strip() for x in str(served or "").split(",") if x.strip()]
    return bool(ids) and all(same_model(asked, x) for x in ids)
