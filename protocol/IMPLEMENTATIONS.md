# Examples

Example implementations of the Unified Harness Protocol, grouped by the
[role](versions/2026-08-11/architecture.md#1-roles) each fills. Listings are
community-maintained by pull request and **do not imply endorsement or
certification** — the only conformance claim that means anything is
[passing the conformance suite](conformance/README.md).

<div class="impl-actions">
<a class="impl-cta" href="#listing-criteria">Add an implementation</a>
<a class="impl-crit" href="#listing-criteria">Listing criteria</a>
</div>

## Example servers

A server runs one or more harnesses behind the contract. Guide: [Implement a server](SERVING.md).

<div class="impl-list">

<div class="impl-card">
<div class="impl-head"><a href="https://github.com/HarnessRouter/harnessrouter"><b>HarnessRouter Community Edition</b></a><span class="role role-server">Server</span></div>
<p>Open-source runner that puts existing harnesses — Codex, Claude Code, Hermes — behind the UHP contract. HarnessRouter · Apache-2.0.</p>
<p class="impl-meta">UHP 2026-08-11</p>
</div>

</div>

## Example clients

A client drives a UHP server. Guide: [Implement a client](CONNECTING.md).

<div class="impl-list">

<div class="impl-card">
<div class="impl-head"><a href="https://github.com/SuperagenticAI/superqode"><b>SuperQode</b></a><span class="role role-client">Client</span></div>
<p>Harness-engineering framework that connects to a UHP server via <code>superqode connect uhp</code>. SuperagenticAI · Apache-2.0.</p>
<p class="impl-meta">UHP 2026-08-11</p>
</div>

</div>

## Listing criteria

A listing is a factual row, not a certification. Open a pull request against
this file in the [repository](https://github.com/HarnessRouter/harnessrouter)
adding one card. To merge, an entry needs:

1. A public, usable release — a repository or a product page, not an announcement.
2. The UHP version the implementation targets.
3. A maintainer contact reachable from the linked page.
4. The role it fills: **Server** (runs harnesses behind the contract), **Client**
   (drives a UHP server), **SDK** (a library for building either), or a
   combination.

A conformance level appears on a listing only once UHP publishes reproducible
test evidence for that implementation; until then, absence of a level is
expected, not a mark against the entry.

Building an implementation? Start with [Implement a server](SERVING.md) or
[Implement a client](CONNECTING.md).
