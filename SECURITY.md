# Security Policy

HarnessRouter Community Edition runs agent CLIs with your own provider keys and executes their work in local workspaces with bash, git, and a filesystem. Treat any instance as capable of running code with the credentials you give it, and keep it off public networks unless you have set a password and put TLS in front of it.

## Reporting a vulnerability

Please report security issues privately. Do not open a public GitHub issue for a vulnerability.

Two private channels:

- GitHub private vulnerability reporting: use the "Report a vulnerability" button under this repository's Security tab.
- Email: contact@harnessrouter.ai

Include what is needed to reproduce it: affected version or commit, environment, steps, expected impact, and a proof of concept if you have one.

We aim to acknowledge a report within 10 working days, agree on a fix and a disclosure timeline with you, and credit you when the fix ships if you want the credit.

## Scope

In scope: the gateway, runner, console, adapters, and the protocol implementation in this repository.

Out of scope: the agent CLIs themselves (Codex, Claude Code, Hermes), installed on first run under their own licenses and with their own security contacts; and issues that require an already-compromised host or a credential you supplied to the instance.
