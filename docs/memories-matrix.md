# Memories: what was measured

Two runners in `scripts/support-matrix/memories/` (see its README) against one instance, the
self-hosted image `0.30.0-rc.10` built from `feat/memories`, with Mem0 connected on the workspace's
own key. 2026-10-05.

## Every route, on Mem0

`interface.py`: each route of the Memories chapter called once. `n/a` is a route Mem0 does not
serve, refused in the chapter's words and declared in its capability document.

| route | mem0 |
|---|---|
| GET providers | pass |
| GET types | pass |
| POST memories | pass |
| POST memories (child) | pass |
| GET memories | pass |
| GET memories?parent | pass |
| GET memory | pass |
| PUT memory | pass |
| POST grants | pass |
| GET grants | pass |
| GET harness memories | pass |
| PUT harness memories | pass |
| POST records | pass |
| POST records (entity, fact) | pass |
| GET record | pass |
| GET records | pass |
| GET records?type | pass |
| PATCH record | pass |
| GET history | pass |
| POST recall (subtree) | pass |
| POST recall (depth 0) | pass |
| POST recall (text) | pass |
| POST graph | pass |
| POST observe | pass |
| GET job | pass |
| PUT query | n/a |
| GET queries | pass |
| POST query (named) | n/a |
| POST query (free) | n/a |
| POST operation | n/a |
| POST snapshots | pass |
| GET snapshots | pass |
| POST consolidations | n/a |
| GET consolidations | n/a |
| GET consolidation | n/a |
| GET consolidation changes | n/a |
| POST consolidation revert | n/a |
| DELETE record (forget) | pass |
| POST erase | pass |
| GET record (erased) | pass |
| DELETE grant | pass |
| GET harness memories (revoked) | pass |
| GET memory (unknown) | pass |
| DELETE memory | pass |

mem0: 35 pass, 9 not served and declared, 0 fail, of 44 calls.

## Agents, on Mem0

`matrix.py`: nineteen harness bases, each on its default model, ten scenarios each, every scenario
one real task in a session of its own. A failed scenario was retried once.

### mem0

| base | model | remember | recall | subtree | reach | revise | graph | forget | task_memory | viewer | observe | seconds |
|---|---|---|---|---|---|---|---|---|---|---|---|---:|
| codex | gpt-5.4 | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass | 371 |
| claude-code | claude-sonnet-4.6 | pass | pass | pass | pass | FAIL | pass | pass | pass | pass | pass | 567 |
| hermes | gpt-5.4 | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass | 1255 |
| pi | gpt-5.4 | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass | 253 |
| omp | gpt-5.4 | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass | 581 |
| dsh | deepseek-v4-pro | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass | 708 |
| goose | gpt-5.4 | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass | 357 |
| opencode | gpt-5.4 | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass | 318 |
| kilo | gpt-5.4 | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass | 517 |
| aider | gpt-5.4 | pass | FAIL | FAIL | pass | pass | pass | pass | pass | pass | pass | 1365 |
| kimi | kimi-k3 | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass | 560 |
| minimax | minimax-m3 | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass | 549 |
| grok | grok-4.6 | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass | 771 |
| openhands | gpt-5.4 | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass | 673 |
| cheetahclaws | gpt-5.4 | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass | 565 |
| agentzero | gpt-5.4 | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass | 395 |
| qwen | qwen3.7-max | FAIL | pass | pass | pass | pass | pass | pass | pass | pass | pass | 1061 |
| gemini | gemini-3.8-flash | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass | 982 |
| cline | gpt-5.4 | pass | pass | pass | pass | pass | pass | pass | pass | pass | pass | 294 |

16 of 19 bases pass every scenario on mem0.

### What is still failing

- **claude-code, revise**: the task ended failed: The turn failed: Not logged in · Please run /login
- **aider, recall**: answered without the title: 'thin your reach.\n\nSo I can’t reliably tell you the working title from memory based on that result. If you want, I can help search a broader memory scope next.\n\n'
- **aider, subtree**: answered without the shelf label: 'le memory contains a record matching “archive shelf label,” so I can’t identify either the shelf label or the memory it’s kept in from the available memories.\n\n'
- **qwen, remember**: no record holds the title after the task (tools: none); answered 'ons.\n\nSaved. The working title **LAUNCH-3A86D0** is now in project memory and will be available in future conversations.'

Read as:

- **claude-code, revise**: not a memory failure. Every Claude Code turn on this instance ended
  "Not logged in" after the instance was moved to this build; the same scenario passed on the build
  before it. Open, and not in the memories code.
- **aider, recall and subtree**: the agent searched and reported nothing found, on the model and
  the records with which the other bases found the answer.
- **qwen, remember**: the agent answered "saved" from a memory feature of its own and wrote nothing
  through the memory tools, with the instruction not to do so in its Memory section.

### What the matrix found on the way, and what was changed

| Found | Changed |
|---|---|
| Asked to keep a person, a company and how they relate, an agent wrote facts and no entity | The remember tool's description lists `entity` and says how a fact names its `subject` and `object` |
| The agent kept its graph in a child memory and the graph asked at the root was empty | A memory's graph covers the memory and what is below it, as a search does (chapter §6.6) |
| Three bases kept what they were told in a notes or memory feature of their own | The Memory section of an agent's instructions says these tools are the memory to use. Two of the three now pass |
| Two models declined to keep or repeat a "codeword" and a "passphrase" | The scenarios use everyday nouns |
| A record derived from the conversation that states a change ("it was A, it is now B") read as stale | A record that gives both is a statement of the change, not a stale one |
