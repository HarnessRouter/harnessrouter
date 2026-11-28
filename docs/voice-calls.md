# Voice calls on a harness

A voice call is a spoken conversation with a harness: the caller's browser speaks to a
speech-to-speech model, and the model answers with the harness's own instructions and its plug
tools. This page is the design of record for the self-hosted server.

**Status.** The three routes are in the gateway and are off until the operator turns them on.
Calls have been placed through them on a live Azure resource with a Microsoft Entra sign-in, driven
by a script in typed text. A spoken call from a browser has not, and the console has no page that
places one: a client is written against the routes below. See
[What is verified, and what is not](#what-is-verified-and-what-is-not).

## What the gateway does, and what it does not

```
browser ── POST /v1/harnesses/{id}/realtime/sessions ──▶ gateway ── client_secrets ──▶ Azure OpenAI
browser ◀── client secret, WebRTC address ───────────── gateway
browser ══ audio and events, WebRTC ════════════════════════════════════════════════▶ Azure OpenAI
browser ── POST /v1/realtime/sessions/{sid}/tool-calls ─▶ gateway ──▶ the harness's plugs
browser ── POST /v1/realtime/sessions/{sid}/end ────────▶ gateway (the call is metered)
```

The gateway's part is three things (`gateway/realtime_plane.py`):

1. **It starts the call.** It asks the provider for a client secret that starts one call, set up
   with the harness's instructions and tools, and hands the secret to the caller once. The
   connection's own credential never leaves the gateway.
2. **It runs the call's tools.** The model asks for a tool over the call; the browser passes the
   request to the gateway, which runs it on the harness's plugs and answers.
3. **It meters the call**, as a session of the harness.

Audio never passes through the gateway. The browser speaks WebRTC to the provider directly.

The provider is Azure OpenAI's realtime API. It sits behind an interface of three calls (`mint`,
`end`, `usage`), so a second provider replaces one class.

## Turning it on

Set `HR_REALTIME=1` on the container. Without it, placing a call and running a tool answer
`403 realtime_not_enabled`, and the task that ends calls nobody hung up is not started. Ending a
call is never closed by the switch: a call that started is ended and metered whatever the switch
says by then.

A call also needs, on the **Integrations** page, an **Azure OpenAI** connection that:

- is enabled, and has an endpoint on one of Azure's hosts (`*.openai.azure.com`,
  `*.cognitiveservices.azure.com`, `*.services.ai.azure.com`) over https;
- has a credential: an API key, or a Microsoft Entra sign-in (the self-hosting guide, "An Azure
  connection without an API key");
- reaches a realtime deployment on that resource.

The first connection that fits is used. `HR_REALTIME_INTEGRATION` names one when there are several.
A connection given through the environment (`HR_SECRET_GLOBAL_HARNESS_CONN_*`) is not read: only
connections saved on the Integrations page are.

With no such connection, placing a call answers `503 provider_error` and says so.

### The deployment's name

A deployment is named by whoever made the resource, so the gateway reads its name from the first of
these that says one:

1. the connection's own model row for the call's model (`HR_REALTIME_MODEL`, default
   `gpt-realtime-2.1`): a row that pairs that model with the deployment's name;
2. `HR_REALTIME_DEPLOYMENT`;
3. the model's name itself.

### Microsoft Entra

A connection that signs in with Microsoft Entra holds no key. The gateway signs in as the
connection's application, with the function every other model call on such a connection uses, and
sends the token in the key's place. A key left on such a connection is not sent. When the sign-in
is refused, placing a call answers with Entra's own reason and no call is started.

## The routes

All three take the caller's usual credential (a sign-in or an API key) and are not part of the
published protocol.

### `POST /v1/harnesses/{harness_id}/realtime/sessions`

Places a call. The harness is checked as a turn on it is: it belongs to the caller's organization,
is not deleted, and is in a workspace the caller reaches. A built-in base has no record, so it
takes no call.

| Field | Default | |
|---|---|---|
| `voice` | `HR_REALTIME_VOICE` (`marin`) | One of `alloy`, `ash`, `ballad`, `coral`, `echo`, `sage`, `shimmer`, `verse`, `marin`, `cedar`. |
| `max_minutes` | 10 | At least 1; more than 30 is read as 30. |
| `max_cost_usd` | none | The most the call is metered at. |
| `metadata.task_ref` | none | Kept on the session, up to 120 characters. |
| `client_tools` | none | Up to 8 function tools the caller's own page runs, each named `page_…`. See [Tools](#tools). |

Answers `201`:

```json
{"session_id": "hrrt_…", "client_secret": "…", "expires_at": "2026-11-27T10:02:00Z",
 "webrtc_url": "https://<resource>.openai.azure.com/openai/v1/realtime/calls",
 "deployment": "…", "voice": "marin", "tools": ["github__list_pull_requests"],
 "client_tools": [], "max_minutes": 10}
```

`client_secret` is returned once and is stored and logged nowhere. It starts a call for a short
time only (`HR_REALTIME_SECRET_TTL_S`, default 120 seconds); the call then lasts until it is ended
or reaches `max_minutes`.

The session's record is written before the provider is asked, so no call is started that nothing
would meter. If the provider refuses, the record is closed as not started and nothing is billed.

| Answer | When |
|---|---|
| `403 realtime_not_enabled` | The switch is off. |
| `404` | The harness is not one the caller may use. |
| `422 invalid_input` | A field is out of range; `param` names it. |
| `503 provider_error` | No connection fits, the sign-in was refused, or Azure refused the request (its HTTP status and error code are in the message, never its body). |
| `502 provider_error` | Azure could not be reached, answered 5xx or 429, or answered without a secret. |
| `503 server_error` | The session's record could not be written, so the call was not started. |

### `POST /v1/realtime/sessions/{sid}/tool-calls`

Runs one tool the model asked for. Body: `{"call_id", "name", "arguments"}`, the three values of
the model's function call (`arguments` as the JSON string the model sent, or an object).

It answers `200` with one of:

```json
{"status": "done", "output": "…"}
{"status": "refused", "detail": "…"}
```

`output` and `detail` are text for the model to speak from, at most 16,000 characters. A call is
refused, in words, when the call has ended or passed its `max_minutes`, the tool is not one of the
call's, the arguments are not a JSON object, or the plugs server refused it. A `call_id` sent twice
is answered from the first answer and the tool is not run again (on the replica that ran it).

The contract has a third answer, `held`, for a tool that waits for a person's approval. This
gateway's plugs server has no such step, so it is never given here.

### `POST /v1/realtime/sessions/{sid}/end`

Ends the call and meters it. Answers `{"minutes": 1.5, "spend_usd": 0.15}`. Asked again, it answers
the same figures and meters nothing more. A call another request is ending at that moment answers
`409 session_ending`.

Both session routes answer `404 session_not_found` for a session that is not a call, is not the
caller's, or is deleted.

## The browser's part

The exchange with Azure is Azure's own and is described in Microsoft's
[realtime audio over WebRTC](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/realtime-audio-webrtc)
guide (read 2026-11-27). What a client of these routes does:

1. Place the call (the first route).
2. Create a peer connection with the microphone's track and a data channel, and `POST` the SDP
   offer to `webrtc_url` with `Authorization: Bearer <client_secret>` and
   `Content-Type: application/sdp`. The answer is the SDP answer.
3. When the model's function call arrives on the data channel, send its `call_id`, `name` and
   `arguments` to the tool calls route, then hand the answer back to the model as that call's
   output and ask it to respond. A tool named `page_…` is the page's own: run it in the page.
4. End the call (the third route) when the caller hangs up, and close the peer connection.

Microsoft's sample adds `?webrtcfilter=on` to the offer's address, which limits what Azure sends
the browser over the data channel. Its list of the events that remain has no function call events,
so a client that runs tools does not use it.

## Tools

A call's tools are the harness's plugs. They are listed and run through the plugs server itself,
with the credential a text turn's agent is given for it, so a tool is listed, refused, recorded and
run exactly as on a text turn. A harness with no plugs has a call with no tools. At most 128 tools
reach the model, and a description is cut to 1,024 characters.

A harness's MCP servers other than plugs, its skills and its files are not part of a call.

`client_tools` are tools of the caller's own page, for a page that lets a call act on it. They are
put in the call's tools beside the harness's, and the gateway never runs one: the tool calls route
runs only the tools recorded for the call when it started.

**What the browser can change.** The browser holds the client secret, and the provider lets it
send `session.update` for its own call: it can replace the instructions and the tool list the model
sees. Neither Azure nor OpenAI offers a setting that forbids this. What the gateway runs does not
move with it: only the harness's own tools, under the plugs server's own checks. So a caller can
make the model say other things, and cannot make the gateway run anything the harness could not.

## Metering

A call is metered by the clock: the minutes it was open, never more than its `max_minutes`, times
`HR_REALTIME_USD_PER_MIN` (default `0.10`), never more than its `max_cost_usd`. The default is
OpenAI's list price for `gpt-realtime-2.1` with both directions speaking the whole minute, rounded
up; set your own if your resource is priced differently. The rate is fixed on the call when it
starts.

The figure is posted once as usage of the harness (`media.usd`) and written on the session as its
spend. The session shows in the harness's and the organization's session lists as "Voice call".

A call is ended once, by whichever comes first:

- its caller (the end route);
- a tool call that arrives after `max_minutes`;
- the sweep, which runs every minute and ends a call past its `max_minutes` that nobody ended,
  metered at `max_minutes`;
- the deletion of its session, which meters the call before the session's record is reduced.

Across replicas one of them meters a call, decided by a lock; the others read the figures it wrote.

Two limits follow from the provider, not from this gateway:

- **The gateway cannot hang up.** Azure addresses a call by an id it gives the browser, which the
  gateway never sees. After `max_minutes` the gateway stops metering and runs no more tools, but a
  browser that keeps the connection keeps talking to the model on the resource's account.
- **The cost is an estimate.** Azure reports a call's tokens on the call's own channel, which the
  gateway does not read.

This gateway has no spend limit per organization for calls. `max_minutes` and `max_cost_usd` bound
one call each.

## A call relayed by a Realtime Harness

Everything above describes a **direct** call: the browser and Azure, with nothing between them. Its
two limits come from that. `HR_REALTIME_PROVIDER=harness` places calls on a
[Realtime Harness](https://github.com/HarnessRouter/RealtimeHarness) instead, which **relays** them:

```
device ══ audio and events, WebSocket ══▶ Realtime Harness ══ the provider's wire ══▶ Azure OpenAI
                                              │  ▲
              the call's tools, over MCP      │  │  a provider credential per connection
                                              ▼  │
                                            gateway (places the call, ends it, meters it, keeps what was said)
```

| | Direct | Relayed |
|---|---|---|
| Who can change the call's instructions and tools | The browser, with `session.update` | Nobody: the harness keeps what the gateway handed it, and a device can only mute, cancel an answer and hang up |
| Ending a call | The record and the meter stop; the gateway cannot hang up | The gateway tells the harness, and the device's connection closes |
| Tools | The browser passes each call to the tool calls route | The harness runs them at the plugs server; the tool calls route runs nothing |
| Billed by | The clock | The tokens the provider reported for each turn; the clock when it reported none |
| What was said | Not kept | Kept in the session's conversation |
| Page tools (`client_tools`) | Yes | Refused with `422` |
| The device connects over | WebRTC, to Azure | WebSocket, to the harness |

**Placing the call.** The first route is the same, with the same checks. The gateway creates the
call on the harness with the call's own configuration: the gateway harness's instructions and voice,
`max_minutes`, and the plugs server's address with the credential a text turn's agent is given for
it. The answer's `transport` is `websocket`, `connect_url` is where the device opens its socket, and
`client_secret` is the harness's connect token, good for one connection within about a minute.
(A direct call answers `transport: "webrtc"`, and `webrtc_url` beside `connect_url`.) What the device
sends and receives on that socket is the harness's device protocol, in its README.

**The provider key stays here.** The harness holds no key and no harness of its own. Each time it
opens a connection to Azure, it asks `POST /v1/realtime/upstream` for a short-lived credential, with
a token the gateway made for that one call. The token names the call, opens that route only, and is
worth nothing at the model broker or the plugs server. A call is given at most four credentials: its
first connection, and the harness's replacements when the provider drops.

**Billing.** A relayed call's turns each carry the provider's own usage. The gateway prices those
tokens at OpenAI's published prices for `gpt-realtime-2.1` (read 2026-11-27; Azure's page listed no
figure that day), per million: text in $4, audio in $32, cached input $0.40, text out $24, audio
out $64. Usage says how many input tokens were cached, not how many of those were audio, so the
cached ones are counted against the text first. The figure is therefore never under what the
provider charges for the same tokens, and can be over it. It is still capped by `max_cost_usd`.

Three cases are told apart at the end of a relayed call. The harness's record holds turns: their
tokens are billed. The record is read and holds no turn, because nobody spoke and the model
generated nothing: the call is billed nothing. The record cannot be read, or no turn in it reported
usage: the clock bills it, as a direct call, so a call is never free because a read failed. The line
that logs a call's end says which (`billed_by=tokens` or `billed_by=clock`).

**What was said.** When the call ends, each turn is written as one of the session's response
records: the person's words, the model's, and each tool call with its answer. Audio is never kept.
A turn the hang-up cut off reads as cancelled. A session that is being deleted has its call metered
and its words not written.

**Running the harness.** The harness is a second process, started with the operator key and nothing
else (`rth serve`, in its README). It needs RealtimeHarness's operator support
(HarnessRouter/RealtimeHarness#4). Three addresses matter:

- the gateway reaches the harness at `HR_REALTIME_HARNESS_URL` (`http://127.0.0.1:8790` beside it);
- the harness reaches the gateway where a runner beside it does, for the plugs server and the
  credential route;
- a person's device reaches the harness at `HR_REALTIME_HARNESS_PUBLIC_URL`, a `ws://` or `wss://`
  address. The console's own port carries no WebSocket, so the harness's port is published on its
  own (`-p 8790:8790`), behind TLS wherever the console is.

This image does not start the harness yet. And the harness's other transport, WebRTC, is not used:
its media library's wheels bundle GPL codecs.

## Settings

| Variable | Default | |
|---|---|---|
| `HR_REALTIME` | off | `1` serves voice calls. |
| `HR_REALTIME_INTEGRATION` | the first that fits | The name of the Azure OpenAI connection calls are placed on. |
| `HR_REALTIME_MODEL` | `gpt-realtime-2.1` | The model a call is recorded as, and the model row a deployment's name is read from. |
| `HR_REALTIME_DEPLOYMENT` | none | The deployment's name, when the connection has no row for the model. |
| `HR_REALTIME_TRANSCRIBE_DEPLOYMENT` | none | A transcription deployment on the same resource (`gpt-4o-transcribe`, for one). Without it the provider does not transcribe the caller's speech. |
| `HR_REALTIME_VOICE` | `marin` | The voice of a call that names none. |
| `HR_REALTIME_USD_PER_MIN` | `0.10` | What a minute of call is metered at. |
| `HR_REALTIME_PROVIDER` | `azure` | `harness` relays calls through a Realtime Harness. |
| `HR_REALTIME_HARNESS_URL` | none | Where the gateway reaches the harness. |
| `HR_REALTIME_HARNESS_PUBLIC_URL` | none | Where a device reaches it: `ws://` or `wss://`. |
| `HR_REALTIME_HARNESS_KEY` | none | The operator key the gateway calls the harness with. A secret: give it from your secret store, as you give the harness its `RTH_OPERATOR_KEYS`. |
| `HR_REALTIME_SECRET_TTL_S` | `120` | How long a client secret may start a call, 10 to 7200 seconds. Azure has opened a call a few seconds past it, so it is not an exact window. |

## What is verified, and what is not

Run on 2026-11-27 against a live Azure OpenAI resource that takes only a Microsoft Entra sign-in
(deployment `gpt-realtime-2-1`), on an instance built from this change, by a script and with no
browser. The call itself was held over a WebSocket opened with the call's client secret, in typed
text:

- With no Azure connection, placing a call answers `503` and says why.
- A call is minted with the Entra sign-in. The scope the gateway uses for every Azure model call
  (`https://cognitiveservices.azure.com/.default`) is accepted on the client secret request;
  Microsoft's sample uses `https://ai.azure.com/.default`, which was not needed.
- The session Azure made holds the harness's instructions and the call's own line, and the model
  answered from the instructions.
- A tool that is not the call's is refused in words.
- Ending the call meters it by the clock (6 seconds: 0.103 minutes, $0.0103), ending it again
  answers the same figures, and the session reads as an ended voice call with its spend.
- A call whose session is deleted while it is open is metered at that moment.
- A call nobody ended is ended by the sweep, metered at its `max_minutes`, 110 seconds after a
  one-minute call started.
- The gateway's log holds no client secret and no Entra secret.

Not verified:

- **A relayed call, anywhere but in tests.** The gateway's side is tested against a stand-in for
  the harness, and the harness's side against a stand-in for the gateway. The two have not run
  against each other, and no relayed call has reached a real provider. The token figure has not been
  compared with a provider's bill.
- **A spoken call over WebRTC.** The script used a WebSocket and text, so the SDP exchange, the
  audio and a browser were not part of it.
- **A tool run on a live call.** The harness in the run had no plugs, so a call's tool was listed
  and run only in the tests, with the plugs server stood in.
- **A browser client.** None ships here; "The browser's part" is written from Microsoft's guide and
  the routes, not from a client run against them.
- The measurements quoted in `gateway/realtime_plane.py` (what `session.update` changes, the
  secret's lifetime) were taken on Azure with the same code in the hosted service, not here.
