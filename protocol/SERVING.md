# Implement a server

How an open-source or closed-source agent harness becomes UHP compliant: choose a serving
path, implement the contract, and publish evidence from the conformance suite. The protocol's
precise claim is `UHP <version> conformant (<class>)`. This guide is the practical companion
to the [specification](versions/2026-10-19/index.md); where the two disagree, the specification wins.

## Choose a serving path

UHP conformance describes the **server interface that drives a harness**, not the availability
of the harness's source code. Open-source and closed-source implementations face the same
wire contract and the same conformance classes. Publishing source does not establish conformance;
keeping the harness proprietary does not prevent it.

| Path | Open-source harness | Closed-source harness | What is tested |
|---|---|---|---|
| **Native UHP server** | Add a UHP HTTP surface to the harness's own service. | The vendor implements UHP in its proprietary service without publishing the internal agent loop. | The native server endpoint driving the named harness and model. |
| **Adapter in a runner** | Add an adapter that invokes the existing CLI, SDK or runtime in a UHP server, such as the self-hosted reference implementation. | Use an available CLI, SDK or API to wrap the proprietary harness without modifying or publishing its internals. | The runner's UHP endpoint with that adapter and configured harness explicitly selected. |
| **UHP facade for a remote service** | A UHP server forwards work to a separately deployed harness service. | A UHP server maps a vendor's remote API to UHP while the vendor operates the harness. | The facade and actual remote service together, including progress, sessions, cancellation, artifacts and failure mapping. |

The remote facade is a deployment of the adapter path, not a separate conformance class. An
adapter is sufficient only when it preserves the required behaviour. For example, an upstream
API that cannot cancel work needs a real implementation solution or a documented conformance
gap; returning a successful cancellation response does not make the work stop.

A server can run wholly on your own infrastructure and provider keys. UHP does not require a
HarnessRouter Cloud account or registration. Conformance does not grant rights to redistribute
an upstream harness or use a vendor API outside its terms. An open adapter can wrap a proprietary
harness without making that harness open source; this repository's contribution policy and
Apache-2.0 license apply to contributions here, not as a requirement to publish every independent
implementation's source.

See [Architecture: roles and classes](versions/2026-10-19/architecture.md#1-roles) for the
client/server/harness boundary. A client that merely calls a UHP server fills the client role;
that integration alone does not establish server or harness conformance.

## Implement the contract

Choose the version and class your server will target. Classes are cumulative:

| Class | Required surface |
|---|---|
| **Core** | Capability and harness discovery, streaming and non-streaming tasks, session continuation, cancellation, and the error model. |
| **Extended** | Core plus file input, artifact retrieval, and session listing and inspection. |
| **Full** | Extended plus harness lifecycle management and session sharing. |

The [architecture chapter](versions/2026-10-19/architecture.md#2-conformance-classes) defines the
classes; the [conformance suite](conformance/README.md#what-it-checks) describes their executable
checks, including checks for optional capabilities. Advertise capabilities truthfully. Do not
label an unsupported feature as supported to reach a higher class.

Build in this order, using the versioned chapters for exact requests and responses:

1. **Discovery:** advertise the harnesses, models and capabilities the server actually supports.
   [Lifecycle](versions/2026-10-19/lifecycle.md) and [Harnesses](versions/2026-10-19/harnesses.md).
2. **Tasks:** accept work and return its result through `POST /v1/responses`.
   [Tasks](versions/2026-10-19/tasks.md).
3. **Streaming:** deliver progressive events and support the documented replay behaviour.
   [Streaming](versions/2026-10-19/streaming.md).
4. **Sessions:** continue the same conversation and workspace.
   [Sessions](versions/2026-10-19/sessions.md).
5. **Files:** accept inputs and return downloadable artifacts where required by the class.
   [Files](versions/2026-10-19/files.md).
6. **Cancellation and errors:** stop running work and map failures to the documented taxonomy.
   [Sessions](versions/2026-10-19/sessions.md) and [Errors](versions/2026-10-19/errors.md).

Generate types from the selected version's [OpenAPI and JSON Schema](versions/2026-10-19/schema.md).
Schema validation checks structure; lifecycle, streaming and cancellation also need runtime tests.

## Use the right tests

There is no weaker closed-source test track. The difference is how maintainers can exercise
internals and how another person can reproduce the observed result.

| Test layer | Open-source implementation | Closed-source implementation | What the result establishes |
|---|---|---|---|
| **Implementation and adapter tests** | Run repository tests with fixtures and mocks for event mapping, session IDs, failures and cleanup. | Run equivalent private tests against the vendor's code or adapter. External reviewers can test only exposed surfaces. | Local correctness and regression coverage. Mock results alone do not establish UHP conformance. |
| **Live UHP conformance suite** | Start the published release locally or in CI and run the suite against its endpoint. | Run the same suite against a deployed service or a privately installed release with authorized test access. | Observed protocol behaviour for the selected endpoint, harness, model, class and suite revision. Source access is unnecessary. |
| **Runtime and deployment checks** | Exercise actual processes, tools, workspace recovery and the deployed proxy; inspect internals where available. | Use private runtime tests plus externally observable checks and vendor-provided evidence for internal guarantees. | Guarantees the public suite cannot fully establish, such as tool restriction enforcement or recovery after a real restart. |
| **Task quality and performance evals** | Evaluate representative workloads, model choices, latency and cost. | Evaluate the same workload through the available service interface. | Fitness for a workload. This is separate from protocol conformance. |

In particular, the suite tests that `disabledTools` persists, not that a runtime enforces a hard
block. It also cannot force an arbitrary remote server to restart. See
[what the checks do not establish](conformance/README.md#what-these-checks-do-not-establish)
and the suite's resume checks for these limits. A passing report is not a general security audit,
a quality benchmark, or a production reliability guarantee.

## Run against the actual harness

From a checkout of the release or commit you want to use for measurement:

```bash
pip install -e protocol/conformance

# Set UHP_API_KEY in your test environment. Use a disposable test workspace.
uhp-conformance \
  --base-url https://your-uhp-server \
  --harness-id "$HARNESS_ID" \
  --model "$MODEL_ID" \
  --class core \
  --label "My harness 1.2.0 via My adapter 0.4.0" \
  --plain \
  --json report.json
```

`--base-url` is the server root; the suite appends `/v1/...`. `--harness-id` is the configured
harness's ID, not its display name. Name the model explicitly so results can be reproduced.
Run again with `--class extended` or `--class full` for the class you intend to claim. A passing
run for one adapter is not evidence for every harness in a multi-harness server: repeat the run
for each configuration and model combination you intend the evidence to cover.

The suite runs real agent tasks and can create and delete test resources. Use a dedicated test
environment with model access. For plugin and step-budget checks, make the suite's MCP fixture
reachable from the executing agent; use `--plugin-mcp-url` for a fixture on your own network.
A bring-your-own-key service can receive its required provider header via `--header`. Keep keys
in the authorized test environment, never in public issues, PRs, reports or screenshots. See the
[CLI options and fixture instructions](conformance/README.md#running-it).

During development, `--only` reruns selected checks. Before publishing a class claim, run the
whole requested class and read the JSON report, not only the process exit code:

- `conformant: true` means every required check ran and passed, with no skips.
- `conformant_with_skips` does not turn a skip into a pass. Read `skipped_not_verified` and disclose
  what was not verified. A partial `--only` run does not establish the requested class.
- `coverage` records missing or duplicate results. `highest_class_passed` credits only a fully
  covered and passing class.
- `protocol_version` is the version the server actually served; `suite_protocol_version` and
  `suite_version` identify the suite. Do not promote an older server to the suite's newer version
  in the wording of a claim.

The CLI can exit successfully when checks skip. Use the report's strict verdict and coverage
fields for a release gate. [Report semantics](conformance/README.md#outcomes) are identical for
open-source and proprietary implementations.

## Publish reproducible evidence

Publish the report with enough context to repeat the measurement: implementation release or
commit (or vendor build identifier), adapter revision if any, selected harness ID and its
configuration, model, suite revision, command without secrets, deployment conditions and run date.
Record configuration alongside the report because the report does not capture every runtime
setting. Review artifacts before publishing and remove credentials or private workload data;
if sensitive evidence cannot be published, state that limitation rather than implying public
reproducibility.

For open-source servers, link the release and install/start commands. For closed-source servers,
link the product/version and document how a measurer can obtain authorized access to the test
endpoint or installable build. Arrange credentials privately with the measurer; do not paste them
into an issue or listing PR. The underlying proprietary source need not be published.

A report can support the scoped wording `UHP <served version> conformant (<fully passed class>)`.
Identify the measured implementation and configuration next to the claim. For a wrapped harness,
attribute the result to the named adapter/server deployment rather than claiming that the unwrapped
upstream product implements UHP natively. Re-measure after relevant server, adapter, harness,
configuration or suite changes.

To request a listing, follow [Examples: listing criteria](IMPLEMENTATIONS.md).
A listing is not certification. The protocol site's measured level and badge come from reports
produced by the repository's `conformance-measure` workflow and merged under
`conformance/reports/<slug>/`; a maintainer arranges the measurement for either source model.
See [measured implementations](conformance/README.md#measured-implementations).

Questions the specification does not answer belong in
[GitHub discussions](https://github.com/HarnessRouter/harnessrouter/discussions);
protocol changes follow [governance](GOVERNANCE.md), prose first.
