# Memory engines

Four open source memory engines to run beside your HarnessRouter, started and connected with one command. Once they run, every new agent remembers, with the engine that suits it.

```sh
./up.sh
```

That's all. It finds your HarnessRouter container (or set `HR_CONTAINER=<name>`), starts Mem0, Graphiti, Hindsight and ReMe, puts HarnessRouter on their network, waits until each one answers and connects each one. Name some to start only those, as in `./up.sh mem0 hindsight`. Run it again at any time: it keeps what works and repairs what doesn't. `./up.sh --down` stops them and keeps what they remember.

No clone needed: the image carries this folder, so `docker cp harnessrouter:/app/deploy/memories .` copies it out.

**No second key.** The engines read and search with HarnessRouter's own model keys. `up.sh` asks HarnessRouter for a credential for each engine, which reaches only HarnessRouter's model relay, only for that engine's two models, and which HarnessRouter can withdraw. It's kept in `.env` here, with every other secret the engines need, at mode 600. Connect a model provider that serves `gpt-4o-mini` and `text-embedding-3-small` first (OpenAI, Azure OpenAI, Vercel AI Gateway and OpenRouter do), or choose others in `.env`.

**Keep HarnessRouter on their network.** When you recreate the HarnessRouter container, add `--network harnessrouter-memories` to its `docker run`, then run `./up.sh` again.

| Engine | Licence | A memory is |
|---|---|---|
| [Mem0](https://github.com/mem0ai/mem0) | Apache-2.0 | Short facts drawn from what was said |
| [Graphiti](https://github.com/getzep/graphiti) | Apache-2.0 | A graph of things and how they relate, over time |
| [Hindsight](https://github.com/vectorize-io/hindsight) | MIT | Facts and the things they involve, consolidated in the background |
| [ReMe](https://github.com/agentscope-ai/ReMe) | Apache-2.0 | Markdown files in folders, with links |

Each is its own project under its own licence. This folder runs their published images or builds from their source, and ships none of their code. The small server in `graphiti/` is ours, because Graphiti is a library and its own server doesn't accept types.

What each engine does, its addresses, schemas, files and backups, and how to run them by hand: [docs/memories-engines.md](https://github.com/HarnessRouter/harnessrouter/blob/main/docs/memories-engines.md).
