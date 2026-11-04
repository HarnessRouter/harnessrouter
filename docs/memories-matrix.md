# Memories: what was measured

Measured on 2026-11-04 against a self-hosted image built from this branch, with each vendor running from [`deploy/memories`](../deploy/memories/README.md). The Mem0 Platform was reached with one workspace's own key, and a second workspace held the self-hosted Mem0, so both ran side by side on one instance. Models for the vendors' own extraction: `gpt-4o-mini` and `text-embedding-3-small`.

The runners are in [`scripts/support-matrix/memories/`](../scripts/support-matrix/memories/). What the raw results hold is in [`memories-matrix-results.json`](memories-matrix-results.json).

## Every route, on every vendor

`interface.py` calls each route of the Memories chapter once. `n/a` is a route the vendor doesn't serve, refused in the chapter's words and declared in its capability document.

| route | Mem0, self-hosted | Mem0 Platform | Graphiti | Hindsight | ReMe |
|---|---|---|---|---|---|
| GET providers | pass | pass | pass | pass | pass |
| GET types | pass | pass | pass | pass | pass |
| POST memories | pass | pass | pass | pass | pass |
| POST memories (child) | pass | pass | pass | pass | pass |
| GET memories | pass | pass | pass | pass | pass |
| GET memories?parent | pass | pass | pass | pass | pass |
| GET memory | pass | pass | pass | pass | pass |
| PUT memory | pass | pass | pass | pass | pass |
| POST grants | pass | pass | pass | pass | pass |
| GET grants | pass | pass | pass | pass | pass |
| GET harness memories | pass | pass | pass | pass | pass |
| PUT harness memories | pass | pass | pass | pass | pass |
| POST records | pass | pass | pass | pass | pass |
| POST records (entity, fact) | pass | pass | pass | pass | pass |
| POST records (retried with its key) | pass | pass | pass | pass | pass |
| GET record | pass | pass | pass | pass | pass |
| GET records | pass | pass | pass | pass | pass |
| GET records?type | pass | pass | pass | pass | pass |
| PATCH record | pass | pass | pass | pass | pass |
| GET history | pass | pass | pass | pass | pass |
| POST recall (subtree) | pass | pass | pass | pass | pass |
| POST recall (depth 0) | pass | pass | pass | pass | pass |
| POST recall (text) | pass | pass | pass | pass | pass |
| POST graph | pass | pass | pass | pass | pass |
| POST observe | pass | pass | pass | pass | pass |
| GET job | n/a | pass | n/a | pass | n/a |
| PUT query | n/a | n/a | n/a | n/a | n/a |
| GET queries | pass | pass | pass | pass | pass |
| POST query (named) | n/a | n/a | n/a | n/a | n/a |
| POST query (free) | n/a | n/a | n/a | n/a | n/a |
| POST operation | n/a | n/a | n/a | n/a | n/a |
| POST snapshots | pass | pass | pass | pass | pass |
| GET snapshots | pass | pass | pass | pass | pass |
| POST consolidations | n/a | n/a | n/a | pass | n/a |
| GET consolidations | n/a | n/a | n/a | pass | n/a |
| GET consolidation | n/a | n/a | n/a | pass | n/a |
| GET consolidation changes | n/a | n/a | n/a | pass | n/a |
| POST consolidation revert | n/a | n/a | n/a | n/a | n/a |
| DELETE record (forget) | pass | pass | pass | pass | pass |
| POST erase | pass | pass | pass | pass | pass |
| GET record (erased) | pass | pass | pass | pass | pass |
| DELETE grant | pass | pass | pass | pass | pass |
| GET harness memories (revoked) | pass | pass | pass | pass | pass |
| GET memory (unknown) | pass | pass | pass | pass | pass |
| DELETE memory | pass | pass | pass | pass | pass |
| **total** | 35 pass, 10 n/a, 0 fail | 36 pass, 9 n/a, 0 fail | 35 pass, 10 n/a, 0 fail | 40 pass, 5 n/a, 0 fail | 35 pass, 10 n/a, 0 fail |

## The chapter's conformance checks

`uhp-conformance --only ME-01,...,ME-13`.

| Vendor | Passed | Skipped |
|---|---|---|
| Mem0, self-hosted | 12 of 13 | ME-11, declared: its server records only text changes, so it doesn't declare `holds` |
| Mem0 Platform | 12 of 13 | ME-11, as above |
| Graphiti | 13 of 13 | |
| Hindsight | 13 of 13 | |
| ReMe | 13 of 13 | |

## Agents, on every vendor

`matrix.py` gives an agent a task in plain words, in a session of its own, then checks what the service holds afterwards. The prompts name no tool. Each cell is real turns on a real model.

| vendor | base | model | remember | recall | subtree | reach | revise | graph | forget | task_memory | viewer | observe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Mem0, self-hosted | claude-code | claude-sonnet-5.5 | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass |
| Mem0, self-hosted | codex | gpt-6.1-sol | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass |
| Mem0 Platform | claude-code | claude-sonnet-5.5 | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass |
| Mem0 Platform | codex | gpt-6.1-sol | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass |
| Graphiti | claude-code | claude-sonnet-5.5 | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass |
| Graphiti | codex | gpt-6.1-sol | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass |
| Hindsight | claude-code | claude-sonnet-5.5 | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass |
| Hindsight | codex | gpt-6.1-sol | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass |
| ReMe | claude-code | claude-sonnet-5.5 | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass |
| ReMe | codex | gpt-6.1-sol | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass |

The `asset` and `document` scenarios need agents to be offered a file to keep, which this instance doesn't do, so they weren't asked.

## Every agent base, on one vendor

The memory tools are the same on every vendor, and what differs by base is how each wires them up. So every base ran the three scenarios that exercise that, on Graphiti, the vendor that found the most. System One is left out because it chooses among offered actions and has no tools to call.

| base | model | remember | recall | forget |
|---|---|---|---|---|
| agentzero | gpt-6.1-sol | pass | pass | pass |
| aider | gpt-6.1-sol | pass | pass | pass |
| cheetahclaws | gpt-5.4 | pass | pass | pass (after the fix below) |
| claude-code | claude-sonnet-5.5 | pass | pass | pass |
| cline | gpt-5.4 | pass | pass | pass (after the fix below) |
| codex | gpt-6.1-sol | pass | pass | pass |
| dcode | gpt-6.1-sol | pass | pass | pass |
| docker-agent | gpt-5.4 | pass | pass | pass (after the fix below) |
| dsh | deepseek-v4-pro | pass | pass | pass |
| fast-agent | gpt-5.4 | pass | pass | pass |
| gemini | gemini-3.8-flash | pass | pass | pass |
| goose | gpt-6.1-sol | pass | pass | pass |
| grok | grok-4.6 | pass | pass | pass |
| hermes | gpt-6.1-sol | pass | pass | pass |
| jcode | gpt-5.4 | pass | pass | pass |
| kilo | gpt-6.1-sol | pass | pass | pass |
| kimi | kimi-k3 | pass | pass | pass |
| mimo | gpt-6.1-sol | pass | pass | pass |
| minimax | minimax-m3 | pass | pass | pass |
| nanobot | gpt-5.4 | pass | pass | pass (after the fix below) |
| omp | gpt-6.1-sol | pass | pass | pass |
| opencode | gpt-6.1-sol | pass | pass | pass |
| openhands | gpt-5.4 | pass | pass | pass |
| opensquilla | gpt-5.4 | pass | pass | pass |
| pi | gpt-6.1-sol | pass | pass | pass |
| qoder |  | FAIL | FAIL | FAIL |
| qwen | qwen3.7-max | pass | pass | pass |
| vibe | gpt-5.4 | pass | pass | pass |
| zeroclaw | gpt-5.4 | pass | pass | pass (after the fix below) |

28 of 29 bases pass. Qoder has no key on this instance, so it says nothing either way.

## What this doesn't show

- Not every base on every vendor. That would be about a thousand turns, for tools that are the same on each.
- How well any vendor recalls. This is whether the integration is right, not a benchmark, and we make no claim about which is best.
- The schema findings in the [vendor guide](../deploy/memories/README.md) come from a few paragraphs, repeated, not a corpus.

## What the matrix found on the way, and what was changed

| Found | Changed |
|---|---|
| A finished answer sat 5 to 7 seconds before completing, on a vendor that extracts before it answers | The turn no longer waits for its memory to take the episode: 0.3 to 0.4 s after the last words |
| Asked to correct a title, Graphiti learned the old one again from the very turn that corrected it | A turn in which the agent revises or forgets isn't observed |
| Asked to forget, an agent closed everything it could find except the raw conversation, which still held the words | Forgetting a fact closes the conversation that taught it. What else it taught stays |
| Graphiti refused to forget an episode, and read its words back as context for the next extraction | An episode can be forgotten, and its words leave what extraction reads |
| A key held to one workspace could name another in a header and spend that workspace's vendor account. The routes also disagreed with the plug routes about which workspace a call meant | One rule for both, and a key stays in its workspace |
| Hindsight's list showed only facts, which also hid conversations from this check, and its count read zero for minutes | Its list holds all three kinds, and its count comes from them |
| Setting ReMe's embedding key turned nothing on: a search for "exercise habits" didn't find "the gym" | The compose setup turns search by meaning on, and what's declared follows each server's own health |
| Asked to keep a person, a company and how they relate, an agent wrote facts and no entity | The remember tool's description lists `entity` and says how a fact names its `subject` and `object` |
| The agent kept its graph in a child memory and the graph asked at the root was empty | A memory's graph covers the memory and what is below it, as a search does (chapter §6.6) |
| Three bases kept what they were told in a notes or memory feature of their own | The Memory section of an agent's instructions says these tools are the memory to use. Two of the three now pass |
| Two models declined to keep or repeat a "codeword" and a "passphrase" | The scenarios use everyday nouns |
| A record derived from the conversation that states a change ("it was A, it is now B") read as stale | A record that gives both is a statement of the change, not a stale one |
