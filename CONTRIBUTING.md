# Contributing

Contributions are welcome, and so are questions.

This project is two connected open-source layers: the Unified Harness Protocol (UHP), an open
standard for how products work with agent harnesses, and this repository, a working implementation
of it. Both take contributions — the specification, the conformance suite, harness support, the
implementation, and the documentation.

## Where things go

- Proposals and bug reports: GitHub Issues.
- Discussion: the HarnessRouter Discord community, https://discord.gg/nPcbwqVPb2
- Security vulnerabilities: privately, per [SECURITY.md](SECURITY.md). Not in a public issue.

## Substantial changes: describe before you build

For anything beyond a small fix, open an issue first. Describe the problem you are solving, the
change you propose, and its expected impact, before writing the implementation. Once a maintainer
agrees on the direction, either you or a maintainer implements it.

Small, obvious fixes such as typos or a clear bug with an equally clear fix can go straight to a
pull request.

## Changes to the protocol

The Unified Harness Protocol has a stricter process, because a specification, a reference
implementation, and a conformance suite have to stay in step. If your change touches the protocol,
follow [protocol/GOVERNANCE.md](protocol/GOVERNANCE.md): open a UHP Enhancement Proposal (UEP) as
an issue labelled `uep` with Problem, Proposal, Compatibility, and Alternatives. Maintainers
respond within 10 working days. An accepted UEP ships as one pull request that updates the
specification, the schema, the reference implementation, a conformance test, and the changelog
together.

## Pull requests

Keep each pull request to one problem. Before requesting review: link the issue when one exists;
add or update tests for behavior changes; update the documentation when the public API, protocol,
configuration, or user workflow changes; call out compatibility, security, or licensing
implications; and check that no credentials, generated dependencies, or unrelated files ride
along.

## Development checks

Run the checks that match the area you changed.

For the console:

```bash
cd ui
npm ci
npm run type-check
npm test
npm run build
```

For the gateway:

```bash
python -m pytest gateway/tests
```

For container-level changes, build the image and walk the documented self-hosted flow before
requesting review.

## License

By contributing, you agree that your contribution is licensed under the Apache License 2.0, the
same license as this repository.
