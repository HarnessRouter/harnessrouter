# Contributing

Contributions are welcome, and so are questions.

## Where things go

- Proposals and bug reports: GitHub Issues.
- Discussion: the HarnessRouter Discord community, https://discord.gg/nPcbwqVPb2
- Security vulnerabilities: privately, per [SECURITY.md](SECURITY.md). Not in a public issue.

## Substantial changes: describe before you build

For anything beyond a small fix, open an issue first. Describe the problem you are solving, the change you propose, and its expected impact, before writing the implementation. Once a maintainer agrees on the direction, either you or a maintainer implements it.

Small, obvious fixes such as typos or a clear bug with an equally clear fix can go straight to a pull request.

## Changes to the protocol

The Unified Harness Protocol has a stricter process, because a specification, a reference implementation, and a conformance suite have to stay in step. If your change touches the protocol, follow [protocol/GOVERNANCE.md](protocol/GOVERNANCE.md): open a UHP Enhancement Proposal (UEP) as an issue labelled `uep` with Problem, Proposal, Compatibility, and Alternatives. Maintainers respond within 10 working days. An accepted UEP ships as one pull request that updates the specification, the schema, the reference implementation, a conformance test, and the changelog together.

## License

By contributing, you agree that your contribution is licensed under the Apache License 2.0, the same license as this repository.
