#!/usr/bin/env python3
"""What turns a model's thinking up, down and off, on one provider.

Sends one question to each model named, once with no setting and once per variant (every level of
`reasoning_effort`, and each provider's own switches), and prints what the provider's usage says the
model spent thinking. This is how the table in runner/reasoning.py was measured: a level is in it
only where a row of this output showed it accepted and moving the count.

    THINKING_PROBE_BASE=https://openrouter.ai/api/v1 THINKING_PROBE_KEY=... \
        python3 probe.py chat:openai/gpt-5.4 responses:openai/gpt-5.4 messages:anthropic/claude-haiku-4.5 \
                         chat:google/gemini-3.5-flash:unset,e:none,e:low,e:high,g:0,g:lo,x:0

An argument is shape:model[:variants]; shape is chat (Chat Completions), responses or messages
(Anthropic). The variants are the keys of VARIANTS below; without a list the shape's default set
runs. `@file` reads the arguments from a file. Without the two variables it reads a Grok Build
turn's own route (GROK_HOME's config and HR_GROK_API_KEY), which is how to reach a connection of an
instance without holding its key: run it as a shell command of a turn on that connection.

Output: one line per model, variant=thinking tokens/output tokens@seconds, `+rc` when the answer
carried reasoning text, `!status message` for a refusal. Results also go to thinking_result.json.
One sample per cell: read the direction, not the number.
"""
import concurrent.futures, json, os, re, sys, time, urllib.request, urllib.error
base, key = os.environ.get("THINKING_PROBE_BASE", "").rstrip("/"), os.environ.get("THINKING_PROBE_KEY", "")
if not (base and key):
    home = os.environ["GROK_HOME"]; key = os.environ["HR_GROK_API_KEY"]
    base = re.search(r'^base_url = "([^"]+)"', open(home + "/config.toml").read(), re.M).group(1)
Q = "How many integers between 1 and 1000 inclusive are divisible by none of 6, 10 and 15? Reply with the number only."
CAP = 6000
VARIANTS = {
    "chat": {
        "unset": {},
        "e:none": {"reasoning_effort": "none"}, "e:minimal": {"reasoning_effort": "minimal"},
        "e:low": {"reasoning_effort": "low"}, "e:medium": {"reasoning_effort": "medium"},
        "e:high": {"reasoning_effort": "high"}, "e:xhigh": {"reasoning_effort": "xhigh"},
        "r:off": {"reasoning": {"enabled": False}}, "r:low": {"reasoning": {"effort": "low"}},
        "r:high": {"reasoning": {"effort": "high"}}, "r:none": {"reasoning": {"effort": "none"}},
        "g:0": {"providerOptions": {"google": {"thinkingConfig": {"thinkingBudget": 0}}}},
        "g:512": {"providerOptions": {"google": {"thinkingConfig": {"thinkingBudget": 512}}}},
        "x:0": {"extra_body": {"google": {"thinking_config": {"thinking_budget": 0}}}},
        "g:med": {"providerOptions": {"google": {"thinkingConfig": {"thinkingLevel": "medium"}}}},
        "x:hi": {"extra_body": {"google": {"thinking_config": {"thinking_level": "high"}}}},
        "x:med": {"extra_body": {"google": {"thinking_config": {"thinking_level": "medium"}}}},
        "x:min": {"extra_body": {"google": {"thinking_config": {"thinking_level": "minimal"}}}},
        "g:min": {"providerOptions": {"google": {"thinkingConfig": {"thinkingLevel": "minimal"}}}},
        "g:lo": {"providerOptions": {"google": {"thinkingConfig": {"thinkingLevel": "low"}}}},
        "g:hi": {"providerOptions": {"google": {"thinkingConfig": {"thinkingLevel": "high"}}}},
        "x:lo": {"extra_body": {"google": {"thinking_config": {"thinking_level": "low"}}}},
        "x:512": {"extra_body": {"google": {"thinking_config": {"thinking_budget": 512}}}},
        "r:minimal": {"reasoning": {"effort": "minimal"}}, "r:max0": {"reasoning": {"max_tokens": 0}},
        "r:max512": {"reasoning": {"max_tokens": 512}},
        "pa:off": {"providerOptions": {"anthropic": {"thinking": {"type": "disabled"}}}},
        "t:off": {"thinking": {"type": "disabled"}}, "t:on": {"thinking": {"type": "enabled"}},
        "q:off": {"enable_thinking": False}, "q:on": {"enable_thinking": True},
    },
    "responses": {
        "unset": {}, "e:none": {"reasoning": {"effort": "none"}}, "e:minimal": {"reasoning": {"effort": "minimal"}},
        "e:low": {"reasoning": {"effort": "low"}}, "e:medium": {"reasoning": {"effort": "medium"}},
        "e:high": {"reasoning": {"effort": "high"}}, "e:xhigh": {"reasoning": {"effort": "xhigh"}},
    },
    "messages": {
        "unset": {}, "t:off": {"thinking": {"type": "disabled"}},
        "t:1024": {"thinking": {"type": "enabled", "budget_tokens": 1024}},
        "t:4000": {"thinking": {"type": "enabled", "budget_tokens": 4000}},
        "a": {"thinking": {"type": "adaptive"}},
        "bt": {"thinking": {"type": "between_tools"}},
        "a:medium": {"thinking": {"type": "adaptive"}, "output_config": {"effort": "medium"}},
        "a:xhigh": {"thinking": {"type": "adaptive"}, "output_config": {"effort": "xhigh"}},
        "a:max": {"thinking": {"type": "adaptive"}, "output_config": {"effort": "max"}},
        "a:low": {"thinking": {"type": "adaptive"}, "output_config": {"effort": "low"}},
        "a:high": {"thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}},
        "o:low": {"output_config": {"effort": "low"}}, "o:high": {"output_config": {"effort": "high"}},
    },
}
DEFAULT = {"chat": "unset,e:none,e:minimal,e:low,e:medium,e:high,e:xhigh", "responses": "unset,e:none,e:minimal,e:low,e:medium,e:high,e:xhigh",
           "messages": "unset,t:off,t:1024,t:4000,a,a:low,a:high,o:low,o:high"}

def one(shape, model, vname):
    extra = VARIANTS[shape][vname]
    if shape == "chat":
        path, body = "/chat/completions", {"model": model, "stream": False, "max_tokens": CAP, "messages": [{"role": "user", "content": Q}]}
    elif shape == "responses":
        path, body = "/responses", {"model": model, "stream": False, "max_output_tokens": CAP, "input": Q}
    else:
        path, body = "/messages", {"model": model, "stream": False, "max_tokens": CAP, "messages": [{"role": "user", "content": Q}]}
    body.update(extra)
    hdr = {"authorization": "Bearer " + key, "content-type": "application/json"}
    if shape == "messages":
        hdr["anthropic-version"] = "2023-06-01"
    rec = {"shape": shape, "model": model, "variant": vname}
    t0 = time.time()
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request(base + path, data=json.dumps(body).encode(), headers=hdr), timeout=240).read())
        u = d.get("usage") or {}
        det = u.get("completion_tokens_details") or u.get("output_tokens_details") or {}
        rec["rt"] = det.get("reasoning_tokens")
        rec["out"] = u.get("completion_tokens", u.get("output_tokens"))
        rec["served"] = d.get("model")
        if shape == "chat":
            m = (d.get("choices") or [{}])[0].get("message") or {}
            rec["ans"] = str(m.get("content") or "")[:24]
            rec["rc"] = len(str(m.get("reasoning") or m.get("reasoning_content") or ""))
        elif shape == "responses":
            rec["ans"] = "".join(c.get("text", "") for it in d.get("output") or [] if it.get("type") == "message" for c in it.get("content") or [])[:24]
            rec["rc"] = sum(1 for it in d.get("output") or [] if it.get("type") == "reasoning")
        else:
            cs = d.get("content") or []
            rec["ans"] = "".join(c.get("text", "") for c in cs if c.get("type") == "text")[:24]
            rec["rc"] = sum(len(c.get("thinking") or "") for c in cs if c.get("type") == "thinking") or sum(1 for c in cs if c.get("type") == "redacted_thinking")
    except urllib.error.HTTPError as e:
        rec["err"] = str(e.code) + " " + e.read()[:260].decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        rec["err"] = repr(e)[:160]
    rec["s"] = round(time.time() - t0, 1)
    return rec

jobs = []
ARGS = open(sys.argv[1][1:]).read().split() if sys.argv[1].startswith('@') else sys.argv[1:]
for a in ARGS:
    parts = a.split(":", 2)
    shape, model = parts[0], parts[1]
    for v in (parts[2] if len(parts) > 2 else DEFAULT[shape]).split(","):
        jobs.append((shape, model, v))
with concurrent.futures.ThreadPoolExecutor(8) as ex:
    out = list(ex.map(lambda j: one(*j), jobs))
json.dump(out, open("thinking_result.json", "w"), indent=0)
by = {}
for r in out:
    by.setdefault((r["shape"], r["model"]), []).append(r)
for (shape, model), rs in by.items():
    cells = []
    for r in rs:
        if "err" in r:
            m = re.search(r'"message"\s*:\s*"([^"]{0,90})', r["err"])
            cells.append(f"{r['variant']}=!{r['err'].split(' ', 1)[0]} {m.group(1) if m else r['err'][4:60]}")
        else:
            cells.append(f"{r['variant']}={r.get('rt')}/{r.get('out')}{'+rc' if r.get('rc') else ''}@{r.get('s')}")
    print(f"{shape[:4]} {model}: " + " | ".join(cells))
print("wrote", len(out))
