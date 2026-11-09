"""Which memory engine an agent gets, from what the agent is for.

An agent remembers what matters for its job from its first task, with nobody choosing a vendor. What it
should remember follows from what it does: an agent that serves people keeps each person's facts, one that
tracks companies keeps how they relate over time, one that runs deployments keeps the lessons of the last
one, one that writes a handbook keeps notes people read. So the agent's own words (its name, description,
instructions, the goal it was set up from, its tools, plugins and skills) are read for those natures, each
one a list of words with weights, and the nature that scores highest names the engine.

Pure and deterministic: the same agent always gets the same answer, and the answer is one sentence a
person can read and disagree with. No model runs here, and nothing is fetched. What is running is the
caller's to say (`running`); this module only chooses among it.

  none       works on what it is given each time (translate, convert, classify, lint, review a given diff)
  mem0       serves people and should know them: kept separately for each person
  graphiti   tracks people and things that change and relate
  hindsight  should get better at its own work
  reme       produces memory people read and edit

Ties go to the earlier line. The goal's hint (New setup's `memory_hint`) decides only when it names one
nature clearly; otherwise it is read with everything else. An agent that says nothing about itself is
taken to serve people: that is what most agents do, and keeping each person apart is the safe way to be
wrong.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

NONE, MEM0, GRAPHITI, HINDSIGHT, REME = "none", "mem0", "graphiti", "hindsight", "reme"
ORDER = (NONE, MEM0, GRAPHITI, HINDSIGHT, REME)
ENGINES = (MEM0, GRAPHITI, HINDSIGHT, REME)
LABEL = {MEM0: "Mem0", GRAPHITI: "Graphiti", HINDSIGHT: "Hindsight", REME: "ReMe"}
PER_USER, SHARED = "per_user", "shared"

REASON = {
    NONE: "This agent works on what it's given each time; memory would add nothing.",
    MEM0: "It serves people, so it keeps each person's facts and preferences, separately per person.",
    GRAPHITI: "It tracks people, things and how they relate over time.",
    HINDSIGHT: "It learns from its own work, consolidating experience into lessons.",
    REME: "Its memory is notes people can read and edit.",
}
UNSAID = "Nothing about it says otherwise, so it keeps each person's facts and preferences, separately per person."
START_COMMAND = "deploy/memories/up.sh"
NO_ENGINE = f"No memory engine is running here; one command starts them: {START_COMMAND}"

# How much a word counts where it is said: an agent's name says what it is, its instructions say much else.
FIELD_WEIGHT = {"name": 3.0, "description": 2.0, "hint": 2.0, "instructions": 1.0, "tools": 1.0}
# The hint decides alone when its best nature scores at least this, and no other comes within half of it.
HINT_CLEAR = 2.0

# (pattern, weight) per nature. A pattern with a space in it is a phrase: it is read first, and the words it
# took are not read again, so "code review" is a review and not code, and "sales pipeline" is a CRM.
_WORDS: dict[str, list[tuple[str, float]]] = {
    NONE: [
        (r"translat\w*", 2), (r"reformat\w*", 2), (r"formatter\w*", 2), (r"pretty[- ]print\w*", 2),
        (r"convert\w*", 2), (r"conversions?", 1.5), (r"extract(?:s|or|ors|ion|ions|ing)?", 2),
        (r"classif\w*", 2), (r"categori[sz]\w*", 1.5), (r"summari[sz]\w*", 2), (r"tl;?dr", 2),
        (r"lint(?:s|er|ers|ing)?", 2), (r"proofread\w*", 2), (r"spell[- ]?check\w*", 2), (r"paraphras\w*", 2),
        (r"rewrit\w*", 1.5), (r"transcri\w*", 2), (r"pars(?:e|es|er|ers|ing)", 1.5), (r"ocr", 2),
        (r"redact\w*", 1.5), (r"validat\w*", 1.5), (r"stateless", 3), (r"one[- ](?:shot|off)", 3),
        (r"single[- ]shot", 3),
        (r"code reviews?", 3), (r"code reviewers?", 3), (r"diff reviews?", 3),
        (r"review\w* (?:a |the |each |every |one )?(?:given |submitted |incoming )?(?:diffs?|patch(?:es)?|pull requests?|prs?)", 3),
        (r"(?:no|without|doesn't need|does not need) (?:any )?(?:memory|history|context)", 3),
        (r"each (?:request|input|message|call|document) (?:is )?(?:independent|on its own|separately|in isolation)", 3),
        (r"(?:the|a|any|each) (?:given|provided|pasted|supplied) (?:text|document|file|input|diff|image|code|data)", 2),
    ],
    MEM0: [
        (r"assistants?", 2), (r"support", 2), (r"customers?", 2), (r"tutor\w*", 2), (r"coach\w*", 2),
        (r"concierge\w*", 2), (r"sales", 2), (r"onboard\w*", 2), (r"companions?", 2), (r"personal\w*", 2),
        (r"helpdesk", 2), (r"chat ?bots?", 2), (r"receptionists?", 2), (r"therap\w*", 2), (r"mentor\w*", 2),
        (r"advis[oe]rs?", 1.5), (r"patients?", 2), (r"students?", 2), (r"learners?", 2), (r"clients?", 1.5),
        (r"preferences?", 2), (r"shoppers?", 1.5), (r"shopping", 1.5), (r"guests?", 1.5), (r"tenants?", 1),
        (r"help desk", 2), (r"end[- ]users?", 1.5), (r"each (?:user|person|customer|student|client|patient|member)", 3),
        (r"(?:know|remember) (?:them|each (?:user|person)|the (?:user|person|customer))", 2),
        (r"(?:their|his|her|the user's|the customer's) (?:history|preferences|goals|progress)", 2),
    ],
    GRAPHITI: [
        (r"research\w*", 2), (r"accounts?", 2), (r"crm", 3), (r"projects?", 1.5), (r"investigat\w*", 2),
        (r"monitor\w*", 2), (r"competit\w*", 2), (r"timelines?", 3), (r"relationships?", 3), (r"entit(?:y|ies)", 2),
        (r"track(?:s|ing|er|ers)?", 1.5), (r"deals?", 1.5), (r"stakeholders?", 1.5), (r"intelligence", 1.5),
        (r"genealog\w*", 2), (r"portfolios?", 1.5), (r"suppliers?", 1.5), (r"prospects?", 1.5), (r"leads", 1),
        (r"chronolog\w*", 2), (r"dependenc(?:y|ies)", 2), (r"interdependen\w*", 3), (r"relations", 2),
        (r"knowledge graph", 3), (r"due diligence", 2), (r"supply chain", 1.5), (r"over time", 2),
        (r"who,? what,? (?:and )?when", 3), (r"sales pipelines?", 3), (r"account (?:manager|management|executive|plans?)\w*", 3),
        (r"market (?:research|intelligence|watch)", 3),
        # How things relate and change, however it is put (sslip, 11-09: each of these stayed on Mem0). "Between"
        # outweighs a person-serving word in the name: "an assistant that keeps the links between teams" tracks links.
        (r"how (?:\w+ ){0,3}(?:relates?|related|connect(?:s|ed)?|depends?|interacts?|fit together|link(?:s|ed)?)", 3),
        (r"(?:relat(?:e|es|ed)|depend(?:s|ed)?|connect(?:s|ed)?|interact(?:s|ed)?) (?:to |on |with )?(?:each other|one another)", 3),
        (r"(?:relationships?|connections?|links?|dependenc(?:y|ies)) between", 3.5),
        (r"dependency (?:graph|map|tree)s?", 3), (r"what changed(?:,? and)? when", 3), (r"what changed", 2),
        (r"when (?:\w+ ){0,3}changed", 2), (r"who knows (?:whom|who)", 3), (r"who reports to (?:whom|who)", 3),
        (r"who works with (?:whom|who)", 3), (r"who did what", 3), (r"by whom", 2), (r"org(?:anization(?:al)?)? charts?", 3),
    ],
    HINDSIGHT: [
        (r"cod(?:e|es|ing|er|ers)", 2), (r"programm\w*", 2), (r"software", 1.5), (r"developers?", 1.5),
        (r"devops", 3), (r"ops", 2), (r"sre", 3), (r"automat\w*", 2), (r"pipelines?", 2), (r"agentic", 2),
        (r"debug\w*", 2), (r"deploy\w*", 2), (r"incidents?", 2), (r"on-?call", 2), (r"infrastructure", 2),
        (r"kubernetes", 2), (r"k8s", 2), (r"ci", 1.5), (r"bugs?", 1.5), (r"refactor\w*", 2),
        (r"repos?(?:itory|itories)?", 1.5), (r"terraform", 2), (r"scripts?", 1), (r"lessons?", 2), (r"etl", 2),
        (r"alerts?", 1.5), (r"postmortems?", 2), (r"outages?", 2), (r"builds?", 1), (r"tests?", 1), (r"testing", 1),
        (r"dev ops", 3), (r"ci/cd", 2), (r"ai agents", 1.5), (r"multi-agent\w*", 2), (r"data engineering", 2),
        (r"learns? from (?:its|their|past|previous|each|every|experience|mistakes)", 3),
        (r"(?:gets?|getting) better at", 3), (r"improv\w* (?:at|over time|with experience|from)", 3),
        (r"self[- ]improv\w*", 3), (r"build failures?", 2),
    ],
    REME: [
        (r"docs", 2), (r"documentation", 2), (r"writing", 2), (r"writers?", 2), (r"notes?", 2), (r"wikis?", 3),
        (r"handbooks?", 3), (r"journal\w*", 2.5), (r"diar(?:y|ies)", 2), (r"playbooks?", 2), (r"runbooks?", 2),
        (r"markdown", 1.5), (r"blog\w*", 2), (r"drafts?", 1), (r"notebooks?", 2), (r"obsidian", 3), (r"manuals?", 1.5),
        (r"knowledge ?base", 3), (r"note[- ]?taking", 3), (r"meeting notes", 3), (r"second brain", 3),
        (r"style guides?", 2), (r"read and edit", 3),
    ],
}

# A tool, plugin or skill by its name: what an agent connects says what it does.
_TOOLS = {
    "github": HINDSIGHT, "gitlab": HINDSIGHT, "linear": HINDSIGHT, "jira": HINDSIGHT, "sentry": HINDSIGHT,
    "pagerduty": HINDSIGHT, "datadog": HINDSIGHT, "vercel": HINDSIGHT, "insforge": HINDSIGHT, "database": HINDSIGHT,
    "zendesk": MEM0, "intercom": MEM0, "freshdesk": MEM0, "helpscout": MEM0, "shopify": MEM0,
    "salesforce": GRAPHITI, "hubspot": GRAPHITI, "pipedrive": GRAPHITI, "crunchbase": GRAPHITI, "apollo": GRAPHITI,
    "notion": REME, "confluence": REME, "obsidian": REME, "google-docs": REME, "gdocs": REME,
}
_TOOL_WEIGHT = 1.5


def _compile() -> dict[str, tuple[list, list]]:
    out = {}
    for nature, pats in _WORDS.items():
        phrases = [(re.compile(rf"\b(?:{p})\b"), w) for p, w in pats if " " in p]
        words = [(re.compile(rf"\b(?:{p})\b"), w) for p, w in pats if " " not in p]
        out[nature] = (phrases, words)
    return out


_COMPILED = _compile()


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().replace("’", "'").replace("_", " ").split())


def _score_text(text: str) -> dict[str, float]:
    """Each nature's score in one text: every pattern counted once, phrases first and then the words
    the phrases did not take."""
    t = _norm(text)
    scores = dict.fromkeys(ORDER, 0.0)
    if not t:
        return scores
    for nature in ORDER:
        for pat, w in _COMPILED[nature][0]:
            if pat.search(t):
                scores[nature] += w
    masked = t
    for nature in ORDER:
        for pat, _w in _COMPILED[nature][0]:
            masked = pat.sub(" ", masked)
    for nature in ORDER:
        for pat, w in _COMPILED[nature][1]:
            if pat.search(masked):
                scores[nature] += w
    return scores


def _add(into: dict[str, float], got: dict[str, float], weight: float) -> None:
    for k, v in got.items():
        into[k] += v * weight


def _best(scores: dict[str, float]) -> str:
    """The highest score; a tie goes to the nature listed first. '' when nothing scored."""
    top = max(scores.values())
    if top <= 0:
        return ""
    return next(n for n in ORDER if scores[n] == top)


def _clear(scores: dict[str, float]) -> str:
    """The one nature a text names clearly, or ''."""
    best = _best(scores)
    if not best or scores[best] < HINT_CLEAR:
        return ""
    if any(scores[n] * 2 > scores[best] for n in ORDER if n != best):
        return ""
    return best


def _tool_names(*groups) -> list[str]:
    out = []
    for g in groups:
        for x in g or ():
            s = str((x.get("name") or x.get("id") or x.get("type") or "") if isinstance(x, dict) else x or "").strip()
            if s:
                out.append(s)
    return out


def scores(*, name: str = "", description: str = "", instructions: str = "", hint: str = "",
           tools=(), plugins=(), skills=()) -> tuple[str, dict[str, float]]:
    """(the nature that fits, every nature's score). The nature is '' when nothing about the agent says."""
    total = dict.fromkeys(ORDER, 0.0)
    for field, text in (("name", name), ("description", description), ("instructions", instructions)):
        _add(total, _score_text(text), FIELD_WEIGHT[field])
    names = _tool_names(tools, plugins, skills)
    _add(total, _score_text(" ".join(names)), FIELD_WEIGHT["tools"])
    for n in names:
        nature = _TOOLS.get(_norm(n).replace(" ", "-")) or _TOOLS.get(_norm(n).split(" ")[0])
        if nature:
            total[nature] += _TOOL_WEIGHT
    said = _score_text(hint)
    clear = _clear(said)
    if clear:
        return clear, {k: round(v, 2) for k, v in said.items()}
    _add(total, said, FIELD_WEIGHT["hint"])
    return _best(total), {k: round(v, 2) for k, v in total.items()}


def scope_of(nature: str) -> str:
    """Whether what is kept is kept for each person apart, or once for the agent."""
    return PER_USER if nature in (MEM0, "") else SHARED


@dataclass(frozen=True)
class Choice:
    engine: str | None      # the engine that keeps this agent's memory here; None for no memory
    scope: str              # per_user | shared
    reason: str             # one or two sentences a person can read
    fits: str               # the nature that fits best: none, an engine, or '' when nothing was said


def choose(*, running=None, **agent) -> Choice:
    """The engine for this agent among the ones `running` here (connected and answering; None means all of
    them), its scope, and why. When the one that fits best isn't running, the next best that is keeps it, and
    the reason says so. With none running there is no memory, and the reason says how to start them."""
    fits, sc = scores(**agent)
    if fits == NONE:
        return Choice(None, SHARED, REASON[NONE], NONE)
    return _among(fits, sc, running)


def for_memory(*, running=None, name: str = "", description: str = "") -> Choice:
    """The engine for a memory a person makes by hand (New memory), read from its name and description the way an
    agent is read (choose), with one difference: a memory always has an engine. Words that say "works on what it is
    given" mean nothing for a memory, so the nature that fits next keeps it, or, when nothing else was said, the one
    an agent that says nothing gets. The console asks this as the name is typed (GET /v1/memories/choose)."""
    fits, sc = scores(name=name, description=description)
    if fits == NONE:
        fits = _best({**sc, NONE: 0.0})
    return _among(fits, sc, running)


def _among(fits: str, sc: dict[str, float], running) -> Choice:
    """The engine for the nature that fits (an engine's, or '' when nothing was said) among the ones running."""
    best = fits or MEM0
    why = REASON[best] if fits else UNSAID
    scope = scope_of(fits)
    up = list(ENGINES) if running is None else [e for e in ENGINES if e in set(running)]
    if best in up:
        return Choice(best, scope, why, fits)
    if not up:
        return Choice(None, scope, NO_ENGINE, fits)
    alt = sorted(up, key=lambda e: (-sc.get(e, 0.0), ORDER.index(e)))[0]
    return Choice(alt, scope, f"{why} {LABEL[best]} fits best; it isn't running here, so {LABEL[alt]} keeps it for now.", fits)


def for_engine(engine: str, **agent) -> Choice:
    """An engine the caller named: kept as named, with the scope the agent's nature asks for."""
    fits, _ = scores(**agent)
    return Choice(engine, scope_of(fits) if fits != NONE else SHARED, f"{LABEL.get(engine, engine)} was chosen for it.", fits)
