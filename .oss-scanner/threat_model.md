# Community Edition security review

## Scope

Review only the public code in this repository: `gateway/`, `runner/`, `ui/`,
`protocol/`, including adapters in those components, and their integration and
packaging. This is the self-hosted
Community Edition. Do not contact a hosted service, use a real provider account,
or test deployments belonging to other people.

Third-party agent CLIs, SDKs, and dependencies have their own maintainers. Their
implementation is outside this enrollment. Integration mistakes in our code
remain in scope. The audit image does not install or authenticate provider CLIs.

## How an instance is laid out

One container runs three processes (`Dockerfile`, `docker/entrypoint.sh`):

- The console listens on port 3000, the only port the image publishes. `ui/src/middleware.ts`
  admits a request without the operator's login only for the sign-in page, the protocol
  discovery documents, share links (the token is the credential), static assets baked into the
  image, and API calls bearing a key, which the gateway checks itself. The console relays
  `/api/harness/` to the gateway and adds its internal trust header only for a signed-in caller.
- The gateway listens on loopback inside the container and runs as an unprivileged user. It
  keeps the databases and the encrypted secret store on the data volume.
- The runner listens on loopback too. It runs as root only so that each agent session runs as its
  own uid, and its environment carries neither the login nor the secret store key.

The published default password and `HR_AUTH_DISABLED=1` are the operator's choices, and the
startup log warns about both. The boundaries that matter most are reaching the gateway or the
runner past that gate; one agent session reaching another session's workspace, the gateway's
data, the login or the secret store; and agent output (files, previews, messages) acting as the
signed-in operator in the console.

## Intended behavior and trust boundaries

The instance operator deliberately grants agents the ability to execute commands
and edit their task workspace. A task running its authorized command is expected
behavior; demonstrate a crossed boundary before treating execution as a flaw.
An already-compromised host is outside this application's threat model.

Prioritize these boundaries and distinguish proven behavior from assumptions:

- Untrusted request bodies, identifiers, paths, filenames, archives, uploaded
  content, and streamed events entering the gateway or runner.
- Authentication and access checks before reading credentials, changing an
  instance's configuration, or operating on another session's resources.
- File containment, traversal, symlinks, and generated artifact access. Identify
  which principal controls the path and which files the deployment exposes.
- Credential forwarding, logs, errors, subprocess environments, and proxy
  destinations. Use synthetic sentinel values, never production credentials.
- The distinction between an agent's intended workspace authority and access to
  unrelated sessions, instance configuration, or host resources.
- UI rendering of untrusted files and agent output, plus browser-to-backend
  authorization and request-origin checks.
- Cancellation, session deletion, and resource handling under adversarial input.

The service is intended for an operator-controlled installation. Do not assume
that it implements a hosted multi-tenant product's policies. State all relevant
deployment and attacker preconditions for each finding; consult `SECURITY.md`.

## Offline environment and tests

The audit Dockerfile builds the self-hosted UI and installs the Python
dependencies, the test tooling, the protocol conformance package and the driver
packages the runner's tests use, as `.github/workflows/tests.yml` does. Sources
live in `/src`. It does not run the product's first-boot entrypoint or install
the agent CLIs, so a turn cannot run end to end; the drivers' tests use stubs.

`bash /src/.oss-scanner/check-offline.sh` runs every suite (gateway, benchmark,
runner, conformance, console) with networking disabled. The suites assume an
unprivileged user, as in CI: as root, the runner's environment tests take the
real account and group paths their stubs stand in for, and fail. Run them as
the image's `audit` user, which owns `/src`, for example
`runuser -u audit -- python -m pytest runner/tests -q`; the script does this
itself. A test that is skipped says why. Report skips and missing coverage
explicitly. Do not install packages, call public endpoints, or use live
accounts to make offline tests pass.

## Findings and patches

For each finding, provide the affected commit and files, attacker prerequisites,
the reachable entry point, a minimal local reproducer with synthetic data,
demonstrated impact, and a focused patch with a regression check where feasible.
Prefer deterministic reproduction over speculative severity. Check whether an
existing authorization or deployment control prevents the proposed attack.

Critical findings require a demonstrated severe impact such as unauthenticated
credential disclosure or execution across a protected boundary. High findings
include proven authorization bypasses or sensitive file/credential exposure
under stated realistic preconditions. Explain constraints on denial of service
and lower-impact issues. Do not rate intended agent command execution as
critical merely because a shell is involved.

Use the private reporting channels in `SECURITY.md`. Do not open public issues
or publish unpatched findings. Maintainers will validate reports and review
patches before applying changes.
