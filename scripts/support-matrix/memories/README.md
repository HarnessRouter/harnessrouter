# The memories matrix

Two runners, both against a running instance through its public API, both with nothing but the
Python standard library.

| Runner | Dimensions | What a cell proves |
|---|---|---|
| `interface.py` | memory engine × route | Every route of the Memories chapter answers as the chapter says on that engine, or the engine declares it does not serve it and the route refuses in the chapter's words |
| `matrix.py` | memory engine × harness base × scenario | An agent on that base, granted memories on that engine, does with them what memory is for |

The rules themselves (who may read what, what a version is, what a graph holds) are the
conformance suite's: `uhp-conformance --class full --only ME-01,ME-02,…`. Run all three when an
engine or a base is added.

## Run

```sh
KEY=…   # an API key of the instance
B=https://your-instance/api/harness

python3 memories/interface.py --base-url $B --api-key "$KEY" --engines mem0 \
    --out interface.json --md interface.md

python3 memories/matrix.py --base-url $B --api-key "$KEY" --engines mem0 --bases all \
    --workers 2 --out matrix.json --md matrix.md
```

The engine must be connected on the instance first (its key on the Bring Your Own Key page, or
`PUT /v1/plugs/mem0`). `matrix.py --out` is also its resume point: a cell that passed is not run
again unless `--rerun`, so a long run can be stopped and continued, and a fix is retested by
running the same command.

Keep `--workers` low on a shared instance: every scenario is a real task on a real agent.

## The scenarios

Each is one task in plain words, in a session of its own, so memory is the only thing that carries
anything from one to the next. The prompts name no tool, and use everyday nouns: a first version asked
for a "codeword" and a "passphrase", and two models declined to keep or repeat what sounded like a secret.

| Scenario | The task | Passes when |
|---|---|---|
| `remember` | "Remember this for later: the working title of our launch is …" | A record holding it is in the harness's default memory, written by the agent as a member |
| `recall` | "What is the working title of our launch?" in a new session | The answer has it |
| `subtree` | "What is the archive shelf label, and which memory is it kept in?" | The answer has the label, kept one level below where the agent was granted, and names that memory |
| `reach` | "What is the vault folder number? Look everywhere." | The answer does not have it: the vault is restricted and the agent holds nothing on it |
| `revise` | "The working title changed to …; correct your memory." | The new one is an active record and the old one is not |
| `graph` | "Keep this as a small graph: a person, a company, and that she runs purchasing there." | The service's graph has a fact whose subject is the person and whose object is the company |
| `forget` | "Forget the working title of our launch." | No active record holds it |
| `task_memory` | A task that names another memory in `metadata.memory` | The record is written there, not in the default |
| `viewer` | The same "remember" asked of an agent granted read only | Nothing was written anywhere |
| `observe` | A conversation with nothing asked of memory | The default memory holds an episode, or a record the engine derived from it |

A scenario an engine cannot serve (no entity records, nothing derived from conversations) reads
`n/a` from that engine's capability document. A failed scenario is retried once.

## Growing it

- **An engine**: connect it, add its id to `--engines`. Nothing else: both runners read what it
  can do from `GET /v1/memories/providers`.
- **A base**: nothing. `--bases all` reads the instance's own list.
- **A scenario**: a function `s_name(cell) -> (ok, why)` and one line in `SCENARIOS`. Judge on what
  the service holds afterwards; judge on the answer only when the answer is the point.
- **A route**: one probe in `interface.py`'s `probes`.
