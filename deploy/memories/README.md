# Memory vendors

HarnessRouter keeps no memory of its own. A memory lives with a vendor you connect, and agents reach it through the same tools whichever one it is. These are four open source ones to run yourself, each with a different idea of what a memory is.

| Vendor | Licence | A memory is | Search | Schema |
|---|---|---|---|---|
| [Mem0](https://github.com/mem0ai/mem0) | Apache-2.0 | Short facts drawn from what was said | By meaning | None |
| [Graphiti](https://github.com/getzep/graphiti), the open engine behind Zep | Apache-2.0 | A graph of things and how they relate, over time | Meaning and words | Types, properties and relations |
| [Hindsight](https://github.com/vectorize-io/hindsight) | MIT | Facts and the things they involve, consolidated in the background | Meaning and words | Labels on facts |
| [ReMe](https://github.com/agentscope-ai/ReMe) | Apache-2.0 | Markdown files in folders, with links | Meaning and words here, words alone on its defaults | None |

Each is its own project under its own licence. This folder runs their published images or builds from their source, and ships none of their code. The small server in `graphiti/` is ours, because Graphiti is a library and its own server doesn't accept types.

## Run them

```sh
cp .env.example .env     # then fill it in
docker compose --profile graphiti up -d
docker network connect harnessrouter-memories <your HarnessRouter container>
```

Use any of the profiles `mem0`, `graphiti`, `hindsight` and `reme`, one or several. Then in the console, go to **Memories**, connect the vendor, and give it its address:

| Vendor | Address | Key |
|---|---|---|
| Mem0 | `http://mem0:8000` | `MEM0_ADMIN_API_KEY` |
| Graphiti | `http://graphiti:8000` | `GRAPHITI_API_KEY`, if you set one |
| Hindsight | `http://hindsight:8888` | None |
| ReMe | `http://reme:2333` | None |

The Mem0 Platform also works: connect it with its key and no address.

Nothing here publishes a port, and most of these servers take no key, so keep them on this network. A connection is tried before it's kept, so a wrong address or key is refused then, with the reason.

## Does a memory need a schema?

A schema is only worth having where something reads it. So what you can set follows what the vendor does, and the console offers only that.

**Graphiti reads a whole schema when it extracts.** We measured what it does with one:

- Types work for things with a name, like people, companies and products. Concepts such as an issue or a fix were not picked up as things, even with a type for them.
- Properties fill in: a `seats` property came back as 40 and 12 on the right companies.
- A relation you name replaces the word Graphiti would have chosen, so "uses" came back as `BUYS`. A fact that fits none may come back as `RELATES_TO`, with its sentence kept. Name every kind you care about.
- With types and no relations, its own words stay, such as `SIGNED_UP_FOR` and `REPORTS_TO`. Leaving relations out is a fair choice.

**Hindsight reads labels.** They classify a fact and not a thing, and a search can be scoped to one. It applies them only to what it extracts from a conversation. A record you state is kept word for word, with no extraction.

**Mem0 and ReMe read none.** Mem0 keeps free text, and in ReMe the folders, frontmatter and links are the structure. Setting a schema on either is refused, because it would look like it was doing something.

## Worth knowing

- **A turn that corrects memory isn't recorded.** When an agent revises or forgets something, that conversation is left out, whichever vendor it is. Otherwise a vendor would learn the forgotten thing again from the request to forget it. Whatever else the agent wants kept from that turn, it has to remember itself.
- **Mem0 and history.** Its server records only text changes, so an earlier version can't keep the time it was true. It doesn't declare facts that hold one value, and the answer says so.
- **ReMe's search is shared.** Its search has no folder scope, so HarnessRouter checks every result against the memory's folder.
- **ReMe searches words alone by default.** `reme/config.yaml` here turns on search by meaning. If you run ReMe with its own defaults, it's declared as words only, and an answer says so when a search by meaning ran on words.
- **ReMe's search is a few seconds behind.** It indexes about six seconds after a write. What was just written is matched directly until then.
- **Hindsight's single facts.** It can't delete one derived fact, only the document it came from, so erasing one takes it out of search and reports that it's still stored.

Scores these projects publish are their own, on their own setups, and aren't comparable. We make no claim about which is best.
