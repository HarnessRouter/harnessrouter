# Contributing to HarnessRouter

Thank you for helping improve HarnessRouter.

HarnessRouter has two connected open-source layers:

- **Unified Harness Protocol (UHP)** is an open standard for how products work with agent harnesses.
- **HarnessRouter Community Edition** is a working implementation of UHP that provides the unified API, gateway, runner, and console.

HarnessRouter leads the project and maintains the standard in public. Community contributions can improve the protocol, the Community Edition, harness support, conformance tests, documentation, and examples.

UHP can be implemented independently of HarnessRouter Cloud. The specification and conformance suite define interoperability, HarnessRouter Community Edition provides working software, and HarnessRouter Cloud provides managed production infrastructure through the same interface.

## Start with the problem

For a substantial change, please open a GitHub Issue before writing a large patch. You do not need to arrive with complete code. A short, human-reviewed explanation in your own words is the best starting point.

Please include:

- the problem you want to solve;
- who encounters it and in what workflow;
- the behavior you propose;
- any compatibility or migration considerations;
- how the change could be tested.

This proposal-first process lets contributors and maintainers align on scope before implementation work begins. Small bug fixes and documentation corrections can go directly to a pull request when the intent is clear.

## Ways to contribute

Contributions are welcome across:

- UHP specification changes and clarifications;
- conformance tests and compatibility fixtures;
- support for additional agent harnesses;
- Community Edition gateway, runner, and console improvements;
- API documentation, examples, and integration guidance;
- bug reports and reproducible test cases.

Use GitHub Issues for concrete problems and proposals. Use the [HarnessRouter Discord community](https://discord.gg/nPcbwqVPb2) for early questions, implementation discussion, and help narrowing an idea before filing an issue.

## Changes to UHP

UHP is an open standard, not a product-specific extension point. A protocol change should solve a general interoperability problem for products and agent harnesses.

A UHP proposal should explain:

- the interaction or lifecycle behavior being standardized;
- the expected request, response, event, error, session, or file behavior;
- backward compatibility and versioning impact;
- how independent implementations can conform;
- the conformance coverage required to validate the change.

When a protocol change is accepted, the specification, machine-readable definitions, conformance suite, documentation, and Community Edition implementation should remain aligned wherever the change applies. Maintainers coordinate protocol versions and decide when a proposal is ready to enter the standard.

## Pull requests

Keep each pull request focused on one accepted problem or clearly scoped improvement.

Before requesting review:

1. Explain the problem and the chosen approach.
2. Link the relevant Issue when one exists.
3. Add or update tests for behavior changes.
4. Update documentation when the public API, protocol, configuration, or user workflow changes.
5. Call out compatibility, migration, security, or licensing implications.
6. Confirm that no credentials, private data, generated dependencies, or unrelated files are included.

HarnessRouter maintainers coordinate implementation, testing, review, and release decisions. A proposal may be revised or declined when it conflicts with protocol compatibility, project scope, security, or maintainability.

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

For gateway tests:

```bash
python -m pytest gateway/tests
```

For container-level changes, build and exercise the documented self-hosted flow before requesting review.

## Licensing

HarnessRouter is licensed under the Apache License 2.0. By submitting a contribution, you agree that your contribution may be distributed under the same license. Third-party code, assets, and agent harnesses must retain their own applicable licenses and notices.
