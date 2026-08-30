# Governance and change process

UHP is maintained in the [HarnessRouter repository](https://github.com/HarnessRouter/harnessrouter)
under a maintainer-led, proposal-first model. This document defines how it changes.

## Principles

1. **Prose before code.** A change starts as a description of the problem, not a pull request. A
   patch is an answer; the proposal has to establish the question first.
2. **Three artifacts move together.** No change lands unless the specification, the reference
   implementation and the conformance suite are updated in the same change. A specification sentence
   that nothing enforces is a wish.
3. **Compatibility is a feature.** A change that breaks conformant clients requires a new version and
   a migration path, not a note in a changelog.
4. **The bar is a working implementation.** A proposal is not accepted on elegance. Something has to
   run it.

## The process

### 1. Propose

Open a **UHP Enhancement Proposal (UEP)** as a GitHub issue labelled `uep`, containing:

- **Problem** — what a developer cannot do today, concretely.
- **Proposal** — the change, in enough detail to be argued with.
- **Compatibility** — what breaks, and what a client written against the current version experiences.
- **Alternatives** — what else was considered and why it is worse.

Prose is enough. A UEP does not need a patch, and one is not a substitute for the above.

### 2. Discuss

Maintainers respond within 10 working days with one of: **accepted in principle**, **needs work**,
or **declined with reasons**. Declines are recorded, with the reasoning, so the same proposal is not
re-litigated from scratch.

### 3. Implement

An accepted UEP is implemented as one pull request containing all three artifacts:

- [ ] Specification chapter(s) updated
- [ ] `schema/` OpenAPI + JSON Schema updated
- [ ] Reference implementation updated
- [ ] Conformance test added that fails before the change and passes after
- [ ] `CHANGELOG.md` entry

A pull request missing any of these is not ready, however good the code is.

### 4. Release

Additive changes ship into the current version. Breaking changes accumulate into a new dated version
per [VERSIONING.md](VERSIONING.md), published with a migration note.

## Roles

- **Maintainers** — merge rights; responsible for consistency across the three artifacts and for
  responding to UEPs.
- **Contributors** — anyone who opens a UEP, a pull request, or an issue.
- **Implementers** — anyone shipping a UHP server or client. Implementer feedback outranks
  theoretical elegance in every design argument.

## A declined field is not a pending one

An implementation may choose not to carry a field. That choice is a **decision**, and it should be
recorded as one — not left on a list that reads as work nobody has got to yet.

The distinction matters because the two look identical from outside. A field an implementation
intends to support later and a field it has decided never to support both show up the same way: as
something the request asked for and did not get. Left unstated, the second quietly becomes the
first, and a question that was actually settled gets re-opened by every new reader, every new
implementer, and every issue triage.

So:

- **Say which it is.** A declined field is closed. Say why, once, somewhere durable, and stop
  carrying it as an open item.
- **Declining is about implementation, never about validation.** [Tasks
  §1.1](versions/2026-08-11/tasks.md#11-request-fields) requires ignore-don't-reject, so a declined
  field is still accepted, and a request carrying it still runs.
- **Tell the caller.** A field that was dropped is named in `metadata.ignored_fields`. A silently
  ignored field is indistinguishable from an honoured one, and the caller cannot tell which they
  got. This is the same principle as reporting model substitution in [Tasks
  §1.3](versions/2026-08-11/tasks.md#13-model-selection-and-substitution).

This applies to the specification too, and `tools` and `include` are the worked example: rather than
leaving them under-specified and letting each implementer guess, they are declared reserved and
ignored in [Tasks §1.4](versions/2026-08-11/tasks.md#14-reserved-fields-tools-and-include), with the
reason written down.

The framing, and the phrase, are due to @aenawi in [#42](https://github.com/HarnessRouter/harnessrouter/issues/42),
from ADR-0007 of an independent UHP implementation.

## Reporting problems

- **Specification bugs** — ambiguity, a rule that cannot be implemented, disagreement between the
  spec and the suite: open an issue labelled `spec-bug`. These are treated as defects.
- **Bugs in the reference implementation** — GitHub Issues.
- **Security vulnerabilities** — private disclosure, not a public issue. See the repository's
  security policy.

## Conformance claims

"UHP 2026-08-11 conformant (class)" means the conformance suite passes at that class. Publishing the
report alongside the claim is expected. There is no certification body, no fee, and no logo
programme — the suite is the authority, it is in this repository, and anyone can run it against
anyone's server.

## Naming and conformance

The canonical name of this standard is the Unified Harness Protocol (UHP). Its site is https://unifiedharnessprotocol.org.

Apache-2.0 grants rights to the code and the specification under its terms. It does not grant rights to the protocol name. "Unified Harness Protocol" and "UHP" are marks of HarnessRouter.

An implementation may describe itself as "UHP-compatible" or say it "implements UHP" only if it passes the conformance suite in [`conformance/`](conformance/). Passing that suite is the definition of conformant for this project. Non-conformant implementations, partial implementations, and modified forks must not use the name in a way that implies compatibility. Stating factually that a product "works with" or "connects to" UHP is fine.

Trademark and compatibility-claim questions can be sent to contact@harnessrouter.ai.
