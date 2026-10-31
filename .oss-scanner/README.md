# Opt-in open-source vulnerability scanning

This directory prepares the Community Edition for the [OSS Scanner
program](https://red.anthropic.com/oss-scanner/). Committing these files does not
enroll the project, start a scan, or grant access to a model API.

The audit image keeps the full source tree in `/src`, installs dependencies at
build time, and builds the self-hosted UI. It does not start the application,
authenticate to providers, or run the product's first-boot CLI installer.

## Maintainer review and enrollment

1. Review this configuration, the public contact address, the build and offline
   test results, the [OSS Scanner Agreement](https://red.anthropic.com/oss-scanner/terms/),
   and the upstream [contribution and CLA requirements](https://github.com/anthropics/oss-scanner/blob/main/CONTRIBUTING.md).
   Enrollment must be submitted by a core maintainer who is, or is authorized by,
   the lead maintainer, with organizational permission when acting as an employee.
   Do not sign on another person's behalf. Acceptance is at the program's discretion.
2. Merge the reviewed environment into this repository's `main` branch first.
   The enrollment points to that branch, so its referenced files must exist there
   before the external application can build successfully.
3. Fork [anthropics/oss-scanner](https://github.com/anthropics/oss-scanner).
   Copy **only** `enrollment/project.yaml` from this directory to
   `projects/harnessrouter/project.yaml` in that fork. Keep the `dockerfile` and
   `threat_model` fields: they reference the files in this repository, rather
   than adjacent files in the enrollment repository.
4. Run the upstream configuration validator and build check described below,
   then open one enrollment pull request. The first PR requires its author to
   complete the CLA process. Maintainers must review the actual terms before
   signing or submitting; this preparation does not accept them.

`primary_contact` is already published in `SECURITY.md`. Its value, and any future
CC addresses, will also be public in the enrollment PR. Do not add credentials,
private user data, or private deployment information.
For encrypted reports, follow upstream's `pgp` configuration; it cannot be
combined with `auto_ccs`.

## Validate the enrollment and build

These commands are run from the fork of the upstream scanner repository after
copying the enrollment file. The build needs git, Docker, Python, and PyYAML.

```bash
python3 tools/validate.py
python3 tools/check harnessrouter
```

The second command anonymously clones the configured branch, builds the audit
image and the scanner's additional tooling layer, and opens a shell with network
access disabled. In that shell, run:

```bash
bash /src/.oss-scanner/check-offline.sh
```

Do not use real provider keys or mount local credential directories. Perform
checks in a clean checkout. For this repository-hosted Dockerfile, the upstream
check retains the root `.dockerignore`. The adjacent `Dockerfile.dockerignore`
overrides that product file so audit sources, documentation, and `SECURITY.md`
remain available while local environment files, data, and caches are excluded.
This is not a substitute for using a clean checkout without credentials.
`check-offline.sh` runs the same suites as `.github/workflows/tests.yml`. A green
run means a patch can be tested offline in the image, not that the code is secure.

The `oss-scanner environment` workflow does the same without a person:

- It validates the proposed enrollment with the pinned upstream validator.
- On a pull request that changes what the image installs, it builds this image
  from the pull request.
- On `main`, after such a merge and weekly, it runs
  `tools/check harnessrouter --no-shell`. That is the upstream build above,
  including the program's own layer, from an anonymous clone of `main`.
- Either way it then runs `check-offline.sh` with `--network none` on 2 CPUs and
  8 GB, the size of the scanner's agent machine.

It checks the environment only; it does not submit an enrollment or invoke a
model scan.

## What enrollment provides

Accepted projects receive free periodic scans. Frequency is determined by the
program, not this configuration. Findings are model-generated and require
maintainer validation; patches are suggestions for review. Initial automated
reports are not subject to a mandatory 90-day disclosure period. If a report is
later manually validated under the coordinated disclosure program, that program's
policy and notice apply. Check the current [FAQ](https://red.anthropic.com/oss-scanner/)
and agreement for the full requirements.

Reports and build failures go to the configured contact. Reports are confidential
under the agreement; share them only with authorized maintainers for assessment
and remediation, and protect unpatched findings as required by its terms.
Pause participation by changing the
upstream enrollment to `disabled: true`, or withdraw by removing it. This program
does not replace dependency scanning, branch checks, runtime monitoring, or the
maintainers' vulnerability response process.
