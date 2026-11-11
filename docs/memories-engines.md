# Memory engines

HarnessRouter keeps no memory of its own. A memory lives in an engine, and agents reach it through the same tools whichever engine it is. These are the four open source engines that `deploy/memories/up.sh` starts beside your instance, each with a different idea of what a memory is. The [self-hosting guide](self-hosting-guide.md#memories) has the one command; this page is the detail behind it.

| Engine | Licence | A memory is | Search | Schema |
|---|---|---|---|---|
| [Mem0](https://github.com/mem0ai/mem0) | Apache-2.0 | Short facts drawn from what was said | By meaning | None |
| [Graphiti](https://github.com/getzep/graphiti), the open engine behind Zep | Apache-2.0 | A graph of things and how they relate, over time | Meaning and words | Types, properties and relations |
| [Hindsight](https://github.com/vectorize-io/hindsight) | MIT | Facts and the things they involve, consolidated in the background | Meaning and words | Labels on facts |
| [ReMe](https://github.com/agentscope-ai/ReMe) | Apache-2.0 | Markdown files in folders, with links | Meaning and words here, words alone on its defaults | None |

Each is its own project under its own licence. `deploy/memories` runs their published images or builds from their source, and ships none of their code. The small server in `deploy/memories/graphiti/` is ours, because Graphiti is a library and its own server doesn't accept types.

## Which engine an agent gets

When an agent is created with memory left to HarnessRouter, it gets the engine that suits what it does, and the reason is shown with it:

| The agent | Engine | Kept |
|---|---|---|
| Serves people and should know them: an assistant, support, a tutor, sales | Mem0 | Separately for each person |
| Tracks things that change and relate: research, accounts, projects, monitoring | Graphiti | Shared by the agent |
| Should get better at its own work: coding, operations, automation | Hindsight | Shared by the agent |
| Writes notes people read and edit: docs, a knowledge base, a handbook | ReMe | Shared by the agent |
| Works only on what it's given each time: translating, formatting, reviewing a diff | None | Nothing |

When the engine that fits best isn't running, the next best one that is keeps the memory, and the reason says so. Any agent's engine can be changed in its settings; the old memory is kept, unattached.

## What up.sh sets up

| Engine | Address on the network | How HarnessRouter connects |
|---|---|---|
| Mem0 | `http://mem0:8000` | With `MEM0_ADMIN_API_KEY` from `.env` |
| Graphiti | `http://graphiti:8000` | With `GRAPHITI_API_KEY` from `.env` |
| Hindsight | `http://hindsight:8888` | No key |
| ReMe | `http://reme:2333` | No key |

Mem0 and Hindsight share one Postgres (pgvector), which `up.sh` gives a generated password. Nothing publishes a port, and Hindsight and ReMe take no key, so keep them on the `harnessrouter-memories` network and nothing else.

**Models.** The engines read and search with two models, `MEMORY_MODEL` and `EMBEDDING_MODEL` in `.env` (`gpt-4o-mini` and `text-embedding-3-small` unless changed; those are what the conformance suite ran with). They call them through HarnessRouter's model relay with a credential `up.sh` gets for each engine (`MEM0_MODEL_KEY` and the like), so the call goes out on the model keys your instance already has. A credential reaches only the relay, only for its engine's two models, and HarnessRouter can withdraw it; `up.sh` then makes a new one. To use a key of your own instead, put it in `OPENAI_API_KEY` with `MEMORY_BASE_URL` set to where it works. On an instance shared by several organizations, every organization's memory work (extraction and embeddings) runs on the operator's own model keys, through the memory relay; organizations' own connections are never used for it.

**Files.** `.env` (mode 600) holds every secret here; keep it, because the database keeps the password it was first given. The data is in Docker volumes named after the stack: `harnessrouter-memories_postgres`, `_graphiti`, `_reme`, `_mem0-history` and `_hindsight-cache`. Back those up, with `.env`.

## Running them by hand

`up.sh` is the short way. The same thing by hand, from `deploy/memories`:

```sh
docker network create harnessrouter-memories
cp .env.example .env && chmod 600 .env    # then fill it in: secrets of your choice, and a model credential or key
docker compose --profile mem0 --profile graphiti up -d
docker network connect harnessrouter-memories <your HarnessRouter container>
```

The profiles are `mem0`, `graphiti`, `hindsight` and `reme`. A model credential comes from `POST /v1/memory-services` on your instance (internal key only), with `MEMORY_BASE_URL` set to `http://<your HarnessRouter container>:3000/api/harness/v1/llm/v1`. Then connect each engine in the console under **Memories** with the address and key in the table above. A connection is tried before it's kept, so a wrong address or key is refused then, with the reason.

The Mem0 Platform also works: connect it with its key and no address.

## Does a memory need a schema?

A schema is only worth having where something reads it. So what you can set follows what the engine does, and the console offers only that.

**Graphiti reads a whole schema when it extracts.** We measured what it does with one:

- Types work for things with a name, like people, companies and products. Concepts such as an issue or a fix were not picked up as things, even with a type for them.
- Properties fill in: a `seats` property came back as 40 and 12 on the right companies.
- A relation you name replaces the word Graphiti would have chosen, so "uses" came back as `BUYS`. A fact that fits none may come back as `RELATES_TO`, with its sentence kept. Name every kind you care about.
- With types and no relations, its own words stay, such as `SIGNED_UP_FOR` and `REPORTS_TO`. Leaving relations out is a fair choice.

**Hindsight reads labels.** They classify a fact and not a thing, and a search can be scoped to one. It applies them only to what it extracts from a conversation. A record you state is kept word for word, with no extraction.

**Mem0 and ReMe read none.** Mem0 keeps free text, and in ReMe the folders, frontmatter and links are the structure. Setting a schema on either is refused, because it would look like it was doing something.

## What deleting leaves behind

Deleting a memory removes it from HarnessRouter and from its engine's store, so nothing recalls or shows it again. Two of the engines also keep copies of their own that deleting doesn't reach yet; a coming release clears them with the memory. Until then, this is where they are and how to clear them. The commands use the container names `up.sh` gives (they start with `harnessrouter-memories`, or with your `HR_MEMORIES_NAME`).

| Engine | What stays after a memory is deleted | Where |
|---|---|---|
| Mem0 | A history log of every fact it added, changed or deleted, with the words; the last ten messages of each memory's conversations; the names and topics it linked to the facts | `history.db` on the `mem0-history` volume; the `memories_entities` table in Postgres |
| ReMe | The conversation each record was drawn from; a request that failed is written to its log, conversation included | `session/dialog/` on the `reme` volume; the container's log |
| Graphiti | Nothing: the memory's file goes, with its log | |
| Hindsight | Nothing: the memory's documents, facts, entities and model requests go | |

Mem0's history of deleted facts, the messages it keeps for its next extraction, and the names of memories that hold no facts any more:

```sh
docker exec harnessrouter-memories-mem0-1 python -c "import sqlite3; c = sqlite3.connect('/app/history/history.db'); h = c.execute(\"DELETE FROM history WHERE memory_id IN (SELECT memory_id FROM history WHERE event = 'DELETE')\").rowcount; m = c.execute('DELETE FROM messages').rowcount; c.commit(); c.execute('VACUUM'); print(h, 'history rows and', m, 'messages removed')"
docker exec -u postgres harnessrouter-memories-postgres-1 psql -d postgres -c "DELETE FROM memories_entities e WHERE NOT EXISTS (SELECT 1 FROM memories m WHERE m.payload->>'user_id' = e.payload->>'user_id')" -c "VACUUM"
```

The history of facts that still exist stays, since a record's earlier versions are read from it. The next extraction of each memory starts without its earlier messages.

ReMe's conversations of memories that no longer exist:

```sh
docker exec harnessrouter-memories-reme-1 sh -c 'cd /data && for f in session/dialog/*.jsonl; do [ -e "$f" ] || continue; m=$(basename "$f" | cut -d_ -f1-2); [ -d "digest/$m" ] || rm -f "$f"; done'
```

ReMe's log goes when its container is recreated: `./up.sh --down`, then `./up.sh`.

Erasing one record, rather than deleting the memory, can leave its words in what it was drawn from (a Graphiti conversation, a Hindsight document); the console says so when it does. Postgres takes deleted rows out of its files at its next vacuum. Copies in your backups, and what was sent to your model provider, are outside all of this. The Mem0 Platform keeps a deleted memory's history on its side, under Mem0's terms.

## Worth knowing

- **Forgetting a fact closes the conversation that taught it.** Its words are in that conversation too. What else the conversation taught stays.
- **A turn that corrects memory isn't recorded.** When an agent revises or forgets something, that conversation is left out, whichever engine it is. Otherwise an engine would learn the forgotten thing again from the request to forget it. Whatever else the agent wants kept from that turn, it has to remember itself.
- **Graphiti keeps its graph in [LadybugDB](https://github.com/LadybugDB/ladybug) (MIT), inside its server.** Each memory is one file on the `graphiti` volume, so that's what to back up, and erasing a memory removes its file. The eight used most recently stay open, about 60 MB each, and the rest open when they're next used. `GRAPHITI_OPEN_MAX` changes that.
- **Graphiti's driver for this store is marked deprecated upstream.** It was written for Kuzu, which LadybugDB continues. It's pinned here with the store (`deploy/memories/graphiti/Dockerfile`), so run the suites again if you move either one.
- **After a hard stop, a memory's search by words is rebuilt** the next time it's opened. A store that stopped cleanly doesn't need that.
- **Mem0 and history.** Its server records only text changes, so an earlier version can't keep the time it was true. It doesn't declare facts that hold one value, and the answer says so.
- **ReMe's search is shared.** Its search has no folder scope, so HarnessRouter checks every result against the memory's folder.
- **ReMe searches words alone by default.** `deploy/memories/reme/config.yaml` turns on search by meaning. If you run ReMe with its own defaults, it's declared as words only, and an answer says so when a search by meaning ran on words.
- **ReMe's search is a few seconds behind.** It indexes about six seconds after a write. What was just written is matched directly until then.
- **Hindsight's single facts.** It can't delete one derived fact, only the document it came from, so erasing one takes it out of search and reports that it's still stored.
- **Hindsight downloads its search model on its first start** (a local reranker, into the `hindsight-cache` volume), so its first start takes a few minutes longer than the others.

Scores these projects publish are their own, on their own setups, and aren't comparable. We make no claim about which is best.
