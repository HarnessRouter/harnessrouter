"""The engine an agent gets follows from what it is for (memory_choice): labelled agents, each with the engine
and scope a person would pick for it, the fallback when that engine isn't running, and the case of none."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_choice as mc  # noqa: E402

# (name, description, instructions, tools, expected nature, expected scope)
CASES = [
    # works on what it is given: no memory
    ("Translator", "Translates product copy from English to Japanese.", "", (), mc.NONE, mc.SHARED),
    ("JSON to CSV", "Converts the given JSON file to CSV.", "", (), mc.NONE, mc.SHARED),
    ("Invoice extractor", "Extracts the totals and dates from an invoice PDF.", "", (), mc.NONE, mc.SHARED),
    ("Ticket triage", "Classifies each incoming ticket by product area and urgency.", "", (), mc.NONE, mc.SHARED),
    ("Summaries", "Summarizes the pasted text into three bullets.", "", (), mc.NONE, mc.SHARED),
    ("Diff reviewer", "Reviews a given diff for style problems and returns comments.", "", ("github",), mc.NONE, mc.SHARED),
    ("Linter", "Lints Python files and reports problems.", "", (), mc.NONE, mc.SHARED),
    ("Proofreader", "Proofreads a paragraph and fixes grammar. Stateless.", "", (), mc.NONE, mc.SHARED),
    ("Receipt OCR", "Reads a photo of a receipt and returns its lines.", "Each request is independent.", (), mc.NONE, mc.SHARED),
    ("Code reviewer", "Reviews pull requests and leaves comments.", "", (), mc.NONE, mc.SHARED),
    # serves people and should know them: Mem0, each person apart
    ("Support replies", "Answers customer support questions for our app.", "", ("zendesk",), mc.MEM0, mc.PER_USER),
    ("Math tutor", "Tutors high school students in algebra at their own pace.", "", (), mc.MEM0, mc.PER_USER),
    ("Fitness coach", "Coaches each user through a weekly training plan.", "", (), mc.MEM0, mc.PER_USER),
    ("Hotel concierge", "Books restaurants and tours for hotel guests.", "", (), mc.MEM0, mc.PER_USER),
    ("Personal assistant", "Keeps my calendar and errands in order.", "", (), mc.MEM0, mc.PER_USER),
    ("Onboarding guide", "Walks new customers through setting up their account.", "", (), mc.MEM0, mc.PER_USER),
    ("Shopping helper", "Recommends products that match the shopper's preferences.", "", ("shopify",), mc.MEM0, mc.PER_USER),
    ("Companion", "A friendly companion to chat with in the evening.", "", (), mc.MEM0, mc.PER_USER),
    # tracks things that change and relate: Graphiti
    ("Market research", "Researches competitors and how their products change.", "", (), mc.GRAPHITI, mc.SHARED),
    ("Account briefs", "Keeps track of our key accounts, their stakeholders and deals.", "", ("salesforce",), mc.GRAPHITI, mc.SHARED),
    ("Pipeline tracker", "Tracks the sales pipeline: who we talked to, what they want and when.", "", ("hubspot",), mc.GRAPHITI, mc.SHARED),
    ("Incident investigator", "Investigates fraud cases and builds a timeline of who did what.", "", (), mc.GRAPHITI, mc.SHARED),
    ("Project monitor", "Monitors our projects and reports what changed this week.", "", ("linear",), mc.GRAPHITI, mc.SHARED),
    ("Due diligence", "Maps a company's owners, subsidiaries and their relationships over time.", "", (), mc.GRAPHITI, mc.SHARED),
    # gets better at its own work: Hindsight
    ("Bug fixer", "Fixes failing tests in our repository and opens a pull request.", "", ("github",), mc.HINDSIGHT, mc.SHARED),
    ("Deploy helper", "Deploys services to Kubernetes and rolls back on errors.", "", (), mc.HINDSIGHT, mc.SHARED),
    ("On-call", "Handles incidents and alerts overnight, and writes the postmortem facts.", "", ("pagerduty",), mc.HINDSIGHT, mc.SHARED),
    ("Data pipelines", "Automates our ETL pipelines and debugs failed runs.", "", (), mc.HINDSIGHT, mc.SHARED),
    ("Coding agent", "Writes code for small features and learns from its past mistakes.", "", (), mc.HINDSIGHT, mc.SHARED),
    # produces memory people read and edit: ReMe
    ("Team wiki", "Keeps the engineering wiki and handbook current.", "", ("confluence",), mc.REME, mc.SHARED),
    ("Meeting notes", "Writes meeting notes and keeps them in markdown.", "", (), mc.REME, mc.SHARED),
    ("Journal", "Helps me keep a daily journal.", "", (), mc.REME, mc.SHARED),
    ("Docs writer", "Drafts documentation for new features.", "", ("notion",), mc.REME, mc.SHARED),
    ("Knowledge base", "Builds a knowledge base from what the team decides.", "", (), mc.REME, mc.SHARED),
    # says nothing about itself: taken to serve people, kept apart for each
    ("Helper", "", "", (), "", mc.PER_USER),
]


@pytest.mark.parametrize("name,description,instructions,tools,nature,scope", CASES, ids=[c[0] for c in CASES])
def test_each_agent_gets_the_engine_and_scope_its_nature_asks_for(name, description, instructions, tools, nature, scope):
    fits, scores = mc.scores(name=name, description=description, instructions=instructions, tools=tools)
    assert fits == nature, (fits, scores)
    got = mc.choose(name=name, description=description, instructions=instructions, tools=tools)
    assert got.scope == scope and got.fits == nature
    if nature == mc.NONE:
        assert got.engine is None and got.reason == mc.REASON[mc.NONE]
    elif nature:
        assert got.engine == nature and got.reason == mc.REASON[nature]
    else:
        assert got.engine == mc.MEM0 and got.reason == mc.UNSAID


def test_there_are_enough_labelled_agents_and_every_nature_is_among_them():
    assert len(CASES) >= 30
    assert {c[4] for c in CASES} == {mc.NONE, mc.MEM0, mc.GRAPHITI, mc.HINDSIGHT, mc.REME, ""}


def test_the_same_agent_always_gets_the_same_answer():
    agent = {"name": "Account briefs", "description": "Keeps track of our key accounts and deals.", "tools": ["salesforce"]}
    assert len({mc.choose(**agent) for _ in range(20)}) == 1


def test_a_tie_goes_to_the_earlier_nature():
    # "support" (people) and "research" (things that relate) score the same: people come first
    fits, sc = mc.scores(name="", description="support and research")
    assert sc[mc.MEM0] == sc[mc.GRAPHITI] and fits == mc.MEM0
    fits, sc = mc.scores(description="translate and support")
    assert sc[mc.NONE] == sc[mc.MEM0] and fits == mc.NONE


def test_the_instructions_count_but_the_name_counts_more():
    fits, _ = mc.scores(name="Support replies", instructions="Research the customer's account before you answer.")
    assert fits == mc.MEM0


# ── the engine that fits isn't running ───────────────────────────────────────────────────────────
def test_the_next_best_running_engine_keeps_it_and_the_reason_says_so():
    got = mc.choose(name="Market research", description="Researches competitors over time.", running=["mem0", "reme"])
    assert got.engine == mc.MEM0 and got.fits == mc.GRAPHITI and got.scope == mc.SHARED
    assert got.reason == (mc.REASON[mc.GRAPHITI] + " Graphiti fits best; it isn't running here, so Mem0 keeps it for now.")


def test_the_next_best_is_the_one_that_scored_highest_among_the_running():
    # a coding agent that also writes docs: Hindsight fits, ReMe is next, Mem0 scored nothing
    got = mc.choose(name="Coding agent", description="Fixes bugs and writes the docs for them.", running=["mem0", "reme"])
    assert got.engine == mc.REME and "Hindsight fits best" in got.reason and "ReMe keeps it for now" in got.reason


def test_a_person_serving_agent_on_another_engine_is_still_kept_apart_for_each_person():
    got = mc.choose(name="Support replies", description="Answers customer questions.", running=["graphiti"])
    assert got.engine == mc.GRAPHITI and got.scope == mc.PER_USER and "Mem0 fits best" in got.reason


def test_nothing_running_means_no_memory_and_says_how_to_start_one():
    got = mc.choose(name="Support replies", description="Answers customer questions.", running=[])
    assert got.engine is None and got.reason == mc.NO_ENGINE and mc.START_COMMAND in got.reason
    assert got.scope == mc.PER_USER, "the nature is still known, for when an engine starts"


def test_an_agent_that_needs_no_memory_says_so_whatever_is_running():
    for running in ([], ["mem0"], None):
        got = mc.choose(name="Translator", description="Translates text.", running=running)
        assert got.engine is None and got.reason == mc.REASON[mc.NONE]


def test_an_engine_not_among_the_four_is_never_chosen():
    assert mc.choose(name="Support replies", running=["fixture", "mem0"]).engine == mc.MEM0
    assert mc.choose(name="Support replies", running=["fixture"]).engine is None


# ── the setup builder's hint ─────────────────────────────────────────────────────────────────────
def test_a_hint_that_names_a_clear_nature_decides():
    agent = {"name": "Weekly report", "description": "Writes the weekly status report for each customer account."}
    assert mc.scores(**agent)[0] != mc.HINDSIGHT
    fits, _ = mc.scores(**agent, hint="Learn from each run so the deploy steps get better over time; keep lessons.")
    assert fits == mc.HINDSIGHT


def test_a_vague_hint_is_read_with_everything_else_and_decides_nothing_alone():
    agent = {"name": "Support replies", "description": "Answers customer questions."}
    fits, _ = mc.scores(**agent, hint="Remember what matters.")
    assert fits == mc.MEM0
    # two natures named about equally: not a clear category, so the agent's own words still count
    fits, _ = mc.scores(**agent, hint="the customer's notes")
    assert fits == mc.MEM0


def test_reasons_are_plain_sentences_without_dashes():
    for r in [*mc.REASON.values(), mc.UNSAID, mc.NO_ENGINE]:
        assert "—" not in r and "–" not in r and r[0].isupper()


def test_scope_follows_the_nature():
    assert mc.scope_of(mc.MEM0) == mc.PER_USER and mc.scope_of("") == mc.PER_USER
    assert all(mc.scope_of(n) == mc.SHARED for n in (mc.GRAPHITI, mc.HINDSIGHT, mc.REME, mc.NONE))


def test_an_engine_named_by_the_caller_keeps_the_scope_of_the_agents_nature():
    assert mc.for_engine("graphiti", name="Support replies").scope == mc.PER_USER
    assert mc.for_engine("mem0", name="Team wiki", description="Keeps the handbook.").scope == mc.SHARED


def test_tools_count_by_their_name_whatever_the_shape():
    fits, _ = mc.scores(name="Agent", tools=[{"name": "salesforce"}, "hubspot"])
    assert fits == mc.GRAPHITI


# ── a memory made by hand (New memory, GET /v1/memories/choose) ─────────────────────────────────
MEMORIES = [
    ("Customer preferences", "", mc.MEM0),
    ("Competitor research", "Who our competitors are and how that changes.", mc.GRAPHITI),
    ("Deployment incidents", "Lessons from each outage.", mc.HINDSIGHT),
    ("Team handbook", "The wiki people read and edit.", mc.REME),
]


@pytest.mark.parametrize("name,description,engine", MEMORIES, ids=[m[0] for m in MEMORIES])
def test_a_memory_is_read_by_the_same_words_as_an_agent(name, description, engine):
    c = mc.for_memory(name=name, description=description)
    assert c.engine == engine and c.reason == mc.REASON[engine]
    assert c == mc.choose(name=name, description=description), "one reading, for a memory and for an agent"


def test_a_memory_always_has_an_engine():
    # words that say "works on what it is given" mean nothing for a memory: the next that fits keeps it, or the default
    assert mc.for_memory(name="Translations").engine == mc.MEM0 and mc.for_memory(name="Translations").reason == mc.UNSAID
    assert mc.for_memory(name="Translated research notes").engine == mc.GRAPHITI
    assert mc.choose(name="Translations").engine is None


def test_a_memory_falls_back_and_says_so_and_says_how_to_start_one():
    c = mc.for_memory(name="Competitor research", running=["mem0", "reme"])
    assert c.engine in ("mem0", "reme") and c.reason.endswith(f"Graphiti fits best; it isn't running here, so {mc.LABEL[c.engine]} keeps it for now.")
    assert mc.for_memory(name="Anything", running=[]) == mc.Choice(None, mc.PER_USER, mc.NO_ENGINE, "")
