# Contributing

Contributions are welcome, and so are questions.

This project is two connected open-source layers: the Unified Harness Protocol (UHP), an open
standard for how products work with agent harnesses, and this repository, a working implementation
of it. Both take contributions — the specification, the conformance suite, harness support, the
implementation, and the documentation.

## Verifying a harness

A harness that answers is not a harness that works. Before a change to harness support ships, it is
measured: five scenarios per harness and model, plus a custom harness carrying its own skill and
tool policy, judged by rules that are enforced in code rather than by eye.
[docs/harness-verification.md](docs/harness-verification.md) says what must be proven, how each
claim is measured, and where the rule lives. Read it before adding a harness or changing how one
routes, and check a change against it rather than against a green turn.

## Where things go

- A bug you have a fix for: a pull request, with no issue needed first. See
  [Bug fixes](#bug-fixes-straight-to-a-pull-request).
- A bug you have found and not fixed, and proposals: GitHub Issues.
- Discussion: the HarnessRouter Discord community, https://discord.gg/nPcbwqVPb2
- Security vulnerabilities: privately, per [SECURITY.md](SECURITY.md). Not in a public issue.

## Bug fixes: straight to a pull request

A bug fix does not need an issue first. Open the pull request and make its description the report,
under these four headings:

```markdown
## The bug
What goes wrong and how to see it: the version, the steps or the input, and what comes back.

## Expected behavior
What should happen instead.

## The fix
What the cause is and what you changed.

## Verification
The steps you ran and what each one showed, written so a reviewer can repeat them: the test you
added, the commands, and the result before and after the fix.
```

A reviewer reads the description before the diff, and repeats the verification before merging. A
fix whose description is missing one of the four is asked for it before it is reviewed. A test
that fails without the fix and passes with it is the strongest verification there is; where a test
is not possible, say what you ran by hand and what you saw.

This covers a defect in the implementation, the conformance suite's code, or the documentation.
Two kinds of defect keep their own route: a security vulnerability is reported privately, per
[SECURITY.md](SECURITY.md), and a defect in the specification's text is an issue labelled
`spec-bug`, per [protocol/GOVERNANCE.md](protocol/GOVERNANCE.md).

## Substantial changes: describe before you build

For anything that changes behavior on purpose (a feature, a new harness, a redesign), open an
issue first. Describe the problem you are solving, the change you propose, and its expected
impact, before writing the implementation. Once a maintainer agrees on the direction, either you
or a maintainer implements it.

A typo or a correction of that size can go straight to a pull request with a line saying what it
corrects.

## Changes to the protocol

The Unified Harness Protocol has a stricter process, because a specification, a reference
implementation, and a conformance suite have to stay in step. If your change touches the protocol,
follow [protocol/GOVERNANCE.md](protocol/GOVERNANCE.md): open a UHP Enhancement Proposal (UEP) as
an issue labelled `uep` with Problem, Proposal, Compatibility, and Alternatives. Maintainers
respond within 10 working days. An accepted UEP ships as one pull request that updates the
specification, the schema, the reference implementation, a conformance test, and the changelog
together.

## Pull requests

Keep each pull request to one problem. A bug fix is described as
[above](#bug-fixes-straight-to-a-pull-request). Before requesting review: link the issue when one exists;
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

## How changes land on main

`main` takes pull requests only: one approval, every check green, no bypass for anyone, admins
included. A pull request cannot be approved by its own author, so an agent working through a
maintainer's account opens its pull requests with the `open-pr` workflow instead, which creates
them as `github-actions[bot]`; the maintainer then reviews and approves like any other change.

```bash
gh workflow run open-pr.yml -f branch=<branch> -f title="<title>" -f body="<body>"
git commit --allow-empty -m "ci: start checks" && git push   # a bot-opened PR needs one push to run CI
```
