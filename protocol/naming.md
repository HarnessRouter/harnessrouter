# The Naming of the Unified Harness Protocol

**How HarnessRouter named the harness-running layer, the nine names weighed along the way, and why Unified holds the contract together.**

## The short answer

The Unified Harness Protocol (UHP) defines a shared contract for running agent harnesses through one interface. An agent harness is the runtime that turns a model into a working agent: it plans, calls tools, and iterates until a task is done. HarnessRouter named this layer, the harness-running layer, and initiated it as a category; UHP defines its public boundary. It is the public, versioned contract that makes running a harness portable, inspectable, and independently testable, so a caller reaches any harness a conformant server exposes through one interface, without changing its integration.

"Unified" is the important word, and it is a claim about completeness. Running a harness is not a single call. It is a whole lifecycle: sessions, streaming, files, artifacts, cancellation, and failure handling. Every other name we weighed captured only one part of that lifecycle, or one property we wanted the contract to keep. UHP is the one contract that holds all of them, so an application talks to a harness through a single interface instead of stitching several together. This page is the record of that decision: nine names, weighed and resolved into one protocol.

## The problem: one harness, many surfaces

When you set out to standardize the harness-running layer, you find there is no single seam to standardize. Running a harness through a contract means covering several surfaces at once: how you open and resume a session, how progress and events stream back (including the tool calls the harness makes as it works), how files go in and artifacts come out, how work is cancelled, and how failures are reported. Beyond those surfaces are two qualities you want the whole contract to keep no matter what it covers: that it stays vendor-neutral, and that it stays open.

Each surface naturally suggests its own protocol name. Follow that instinct and the space fragments into a family of neighboring acronyms, each with its own schema and governance, before a single implementation ships. The stakes are industry-wide: without one contract, every product that wants agents rebuilds the same integrations, one per harness, and every harness builder rebuilds the same product seams in reverse. So the real question was never the acronym. It was architectural, and it decides how the whole field sees this layer: are these separate protocols, or parts of one contract? We chose one contract.

## Nine names, one protocol (UHP)

We weighed nine names, and the finding is architectural: none of them names a separate protocol. Every one resolves to UHP, as a surface of the contract, a property of it, a capability of it, or a pattern you build on it. Seven appear below, seven names across six rows, since two share both a role and an abbreviation. The last two were candidates for the name itself, and the decision between them follows the table.

| Name | Abbr | Kind | What it captured |
| --- | --- | --- | --- |
| Application Harness Protocol | AHP | surface of UHP | Integration: how a product embeds and drives a harness. |
| Harness Application Protocol | HAP | surface of UHP | The same integration seam, named from the harness side. |
| Harness Communication Protocol and Harness Client Protocol | HCP | surface of UHP | The client and harness conversation: the message wire and the client or SDK that consumes it. |
| Meta Harness Protocol | MHP | capability of UHP | Running many harnesses under one contract, so their runs are directly comparable; the caller applies its own metrics. An optimizer that rewrites one harness is one more client of the contract. |
| Open Harness Protocol | OHP | property of UHP | Openness: a public, no lock-in spec, a value rather than a request path. |
| Harness-to-Harness | H2H | a UHP pattern | Harnesses delegating to harnesses, built from repeated UHP calls: a harness delegates through a tool that runs another, or a caller orchestrates several runs directly. |

Read the table as a map. AHP and HAP are one integration seam seen from two sides. The two HCP names are one conversation described at two depths, the wire it travels on and the client that consumes it; fittingly, they landed on the same abbreviation. OHP is not a surface but a value we wanted the contract to keep.

"Meta-harness" splits two ways. Running many harnesses and comparing them is a capability the unified contract carries: because every run goes through one contract, the runs are directly comparable, and the caller applies the metrics that matter to it. The searching, tuning, and winner-picking belong to the caller, by design. Improving a single harness is a different thing: an outer loop that rewrites a harness from its own execution records, the shape described in [Stanford's Meta-Harness work](https://arxiv.org/abs/2603.28052), a 2026 arXiv preprint. That kind of optimizer is a consumer of runs, not a protocol; the runs it feeds on are the ones UHP produces and makes comparable. Either way, meta-harness is a capability of UHP: running and comparing many harnesses is what the one contract makes possible, and improving one builds on the runs it produces.

H2H is the same story one step over. A harness plans and calls tools, so give it a tool that runs another harness through the same contract, and delegation and fan-out are built from repeated UHP calls. A session preserves one configured harness from start to finish, so the coordination lives in the caller; that is not a limit on the pattern but the design that makes it composable, because the contract underneath every call stays identical. It is also why UHP complements Agent2Agent (A2A) rather than competing with it. A2A is the peer protocol for agents that discover and message each other directly; UHP is the contract a caller uses to run each harness it coordinates. None of the names was wrong. Each resolves to UHP, seen from one side.

## The decision: why Unified won the letters UHP

The last two names never entered the table, because both were candidates for the name itself, not for anything the name covers. Both are adjectives, and both wanted the same three letters: the Universal Harness Protocol and the Unified Harness Protocol.

Universal is a claim about reach: it says the protocol works across every vendor. That is a goal worth holding, but reach is a property a protocol earns, not its shape, and it leaves the real question open: coverage of what?

Unified answers that. It says the whole running contract is one protocol rather than a scattering of them. Universal describes what a protocol touches; Unified describes what the protocol is. So UHP means Unified, and universality lives inside it as one of the things one contract delivers.

## Open by design

A contract for this layer is only worth unifying if no one can own it. UHP is open by construction, so openness did not need to be the name: the specification is public, anyone can implement it, and a conformance suite runs locally, grading implementations into conformance classes. Conformance applies to the server that exposes harnesses, so interoperability is an independently verifiable property rather than a promise. It is a versioned HTTP contract defined with OpenAPI 3.1 and JSON Schema 2020-12, published at unifiedharnessprotocol.org, and it grows as one contract: UHP negotiates versions and advertises capabilities, so a client discovers exactly what a harness supports without a new protocol appearing at every step.

## The one thing UHP leaves alone by design

"Unified" is a claim about the contract for running a harness, and it stops at one deliberate line: the harness's own reasoning, how it plans, decides, and iterates toward a result. That judgment is what makes one harness worth choosing over another, so UHP standardizes the contract around a harness, not the way a harness thinks.

Everything up to that line runs through one interface, and it runs on both sides of the harness. On one side, UHP unifies how a harness plugs into a product: a product integrates once and drives any harness a conformant server exposes the same way. On the other, it unifies how capabilities plug into a harness: tools and skills (whether provided by MCP servers or bundled in agent plugins) attach through one configuration, so wiring a capability in is identical no matter which harness runs underneath.

Every integration seam around a harness runs through UHP, which is the whole point of a unified interface: one contract for every seam, whatever harness sits behind it.

And the contract is built to carry the ecosystem rather than compete with it: MCP standardizes how a capability is exposed, Agent Plugins standardizes how skills and MCP server definitions are packaged, and UHP brings both under one configuration, so the field's open standards meet in one interface instead of fragmenting across many.

## The reference implementation

HarnessRouter is the world's first unified interface for agent harnesses.

The unified interface is the full running contract: sessions, streaming, files, artifacts, cancellation, and failure handling, reached through one API. UHP is the open standard HarnessRouter initiated and leads, and its open-source Community Edition, licensed under Apache 2.0, ships a reference implementation anyone can run: a conformant server holding a Full-class report against the suite's checks (currently 52).

That is what "Unified" finally means: not that every harness is the same, but that one contract runs every harness a conformant server exposes, in the open. A category becomes durable when products and harnesses can evolve independently above a boundary no one has to reinvent. HarnessRouter named that category and drew its boundary; UHP is the public contract an ecosystem can build on.
