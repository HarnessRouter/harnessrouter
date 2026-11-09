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

## A world that exists

`matrix.py` builds its own memories and agents through the instance, which needs the instance to
serve `/v1/memories`. An instance may instead give its agents the memory tools over memories that
another server keeps. There the runner builds nothing and is told what exists:

```sh
MATRIX_MEMORIES_BEARER=…  MATRIX_OUTSIDER_BEARER=…  \
python3 memories/matrix.py --base-url $B --api-key "$KEY" --world world.json --out matrix.json
```

```json
{
  "dedicated": true,
  "memories": { "base_url": "https://memories.example/api", "bearer_env": "MATRIX_MEMORIES_BEARER",
                "root": "…", "notes": "…", "archive": "…", "client": "…", "vault": "…" },
  "agents": [ { "base": "claude-code", "harness_id": "…", "writer": "…", "reader_harness_id": "…" } ],
  "outsider": { "bearer_env": "MATRIX_OUTSIDER_BEARER" },
  "not_served": { "task_memory": "a task names no memory on this instance" }
}
```

- **`memories`**: the five memories by role, and where the runner reads them: the server that
  keeps them and the name of an environment variable holding a bearer that reads and writes all
  five. The bearer is never in the file. `notes` is the agent's default memory and it writes
  there and in `client`; it reads `root`, which `archive` is below; it holds nothing on `vault`.
  Give `archive` a name the runner's question does not contain ("Depot 7C", not "Archive"): the
  agent is asked which memory the archive shelf label is kept in, and must have found the name.
- **`agents`**: one per base. `writer` is the id the agent's records are stamped with when that
  is not the harness id. `reader_harness_id` is an agent that reads `root` and writes nowhere;
  without one, `viewer` reads `n/a`.
- **`outsider`**: a bearer of a member of another organization, on the same server. With it the
  file scenarios check that neither the record nor its bytes answer to that member.
- **`not_served`**: scenarios this instance cannot be asked, each with its reason, which is printed.
- **`dedicated`** must be `true`. The runner forgets every record in the five memories before and
  after a run (a record that follows a document is left), so they must be the matrix's own. One
  cell runs at a time, since every agent uses the same five.

The world file names an organization's memories and agents. Keep it out of the repository.

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
| `asset` | "Generate a small image … then keep the image itself in your memory." | A record the agent wrote holds the image as a file with a line saying what it shows; the bytes read back as an image; they still read with the conversation that made them deleted; a member of another organization gets neither record nor bytes; a new conversation finds it by that line |
| `document` | "Write a file … containing exactly this line. Then keep the file itself in your memory." | The same, and the bytes kept are the line that was written |

The two file scenarios run where the instance's agents are offered a file to keep: a given world
unless it says otherwise, or `--files` on a world the runner builds. Elsewhere they read `n/a`.

A scenario an engine cannot serve (no entity records, nothing derived from conversations) reads
`n/a` from that engine's capability document. A failed scenario is retried once.

## Growing it

- **An engine**: connect it, add its id to `--engines`. Nothing else: both runners read what it
  can do from `GET /v1/memories/providers`.
- **A base**: nothing. `--bases all` reads the instance's own list.
- **A scenario**: a function `s_name(cell) -> (ok, why)` and one line in `SCENARIOS`. Judge on what
  the service holds afterwards; judge on the answer only when the answer is the point.
- **A route**: one probe in `interface.py`'s `probes`.

`test_matrix.py` runs the runner against a memory server and an agent written in the test, so a
change to it is checked without an instance: `python -m pytest scripts/support-matrix/memories`.
