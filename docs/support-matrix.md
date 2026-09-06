# Harness support matrix

The run's notes, per column, are in [support-matrix-notes.md](support-matrix-notes.md).

Scenarios: first turn, follow-up in the same session, switch model mid-session, artifact (a file the task must produce), recycle (the sandbox is let go on purpose, then a follow-up must recall the first message). pass = ran and answered as asked, FAIL = failed (reason in the notes), n/a = not run.

## Provider: anthropic

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Notes |
|---|---|---|---|---|---|---|---|
| claude-code | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| claude-code | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| claude-code | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| claude-code | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| claude-code | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass |  |
| claude-code | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| claude-code | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| cline | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| cline | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| cline | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| cline | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| cline | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| cline | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| cline | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| dsh | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| dsh | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| dsh | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| dsh | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| dsh | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass |  |
| dsh | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| dsh | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| hermes | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| hermes | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| hermes | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| hermes | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| hermes | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass |  |
| hermes | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| hermes | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| opencode | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| opencode | claude-haiku-4.5 | FAIL | n/a | n/a | n/a | n/a | first: answered without M1-claude-haiku-4.5:  debugging, or refactoring code Exploring and understanding your codebase Solving technical problems A ; re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| opencode | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| opencode | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| opencode | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| opencode | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| opencode | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| pi | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| pi | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| pi | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| pi | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| pi | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass |  |
| pi | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| pi | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| qwen | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass | re-run with the Anthropic base carrying /v1 (0.13.9) ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-claude-fable-5: What exact word did I ask you to reply with  |
| qwen | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass | re-run with the Anthropic base carrying /v1 (0.13.9) ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-claude-haiku-4.5: What exact word did I ask you to reply wit |
| qwen | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass | re-run with the Anthropic base carrying /v1 (0.13.9) ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-claude-opus-4.7: What exact word did I ask you to reply with |
| qwen | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass | re-run with the Anthropic base carrying /v1 (0.13.9) ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-claude-opus-4.8: What exact word did I ask you to reply with |
| qwen | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass | re-run with the Anthropic base carrying /v1 (0.13.9) ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-claude-opus-5: What exact word did I ask you to reply with i |
| qwen | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | re-run with the Anthropic base carrying /v1 (0.13.9) ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-claude-sonnet-4.6: What exact word did I ask you to reply wi |
| qwen | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass | re-run with the Anthropic base carrying /v1 (0.13.9) ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-claude-sonnet-5: What exact word did I ask you to reply with |

49 pairs, 240 of 241 scenario runs passed.

## Provider: azure-e2

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Notes |
|---|---|---|---|---|---|---|---|
| cline | gpt-5.2 | pass | pass | pass (gpt-5.4) | pass | pass | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| cline | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| cline | gpt-5.4-mini | pass | pass | pass (gpt-5.4) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| cline | gpt-5.5 | pass | pass | pass (gpt-5.4) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| cline | gpt-5.6-luna | pass | pass | pass (gpt-5.4) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| cline | gpt-5.6-sol | pass | pass | pass (gpt-5.4) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| cline | gpt-5.6-terra | pass | pass | pass (gpt-5.4) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| codex | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-5.3-codex | pass | pass | pass (gpt-5.5) | FAIL | FAIL | artifact: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.5: its tools are not available there. Start a new task for gpt-5.3-code ; recycle: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.5: its tools are not available there. Start a new task for gpt-5.3-code ; re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | FAIL | recycle: answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in my very first message of this task? Reply with just that wo ; re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| dsh | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-5.3-codex | pass | pass | pass (gpt-5.5) | pass | pass | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| hermes | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-5.3-codex | pass | pass | pass (gpt-5.5) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| opencode | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-5.3-codex | pass | pass | pass (gpt-5.5) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| pi | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-5.3-codex | pass | pass | pass (gpt-5.5) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| qwen | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-gpt-5.2: What exact word did I ask you to reply with in my v |
| qwen | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-gpt-5.4: What exact word did I ask you to reply with in my v |
| qwen | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-gpt-5.4-mini: What exact word did I ask you to reply with in |
| qwen | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-gpt-5.5: What exact word did I ask you to reply with in my v |
| qwen | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in |
| qwen | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-gpt-5.6-sol: What exact word did I ask you to reply with in  |
| qwen | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run with the E2 base carrying /openai/v1 ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-gpt-5.6-terra: What exact word did I ask you to reply with i |

54 pairs, 267 of 270 scenario runs passed.

## Provider: azure-openai

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Notes |
|---|---|---|---|---|---|---|---|
| cline | gpt-5.2 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| cline | gpt-5.4-mini | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.5 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.6-luna | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.6-sol | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.6-terra | pass | pass | pass (gpt-5.4) | pass | pass |  |
| codex | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run on 0.13.7 (a Codex history is kept whole under the same account) ; retested once; first try:  |
| codex | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | FAIL | FAIL | artifact: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-sol: its tools are not available there. Start a new task for gpt-5.3- ; recycle: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-sol: its tools are not available there. Start a new task for gpt-5.3- ; deployment gpt-5.3-codex added to the resource 2026-09-06, then re-run ; retested once; first try: first [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "Reconn |
| codex | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run on 0.13.7 (a Codex history is kept whole under the same account) ; retested once; first try: switch [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "{\n  \; artifact [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "Error ; recycle [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "Error  |
| codex | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run on 0.13.7 (a Codex history is kept whole under the same account) ; retested once; first try: switch [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "{\n  \; artifact [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "Error ; recycle [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "Error  |
| codex | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run on 0.13.7 (a Codex history is kept whole under the same account) ; retested once; first try:  |
| codex | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run on 0.13.7 (a Codex history is kept whole under the same account) ; retested once; first try: recycle answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in |
| codex | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | re-run on 0.13.7 (a Codex history is kept whole under the same account) ; retested once; first try:  |
| codex | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | re-run on 0.13.7 (a Codex history is kept whole under the same account) ; retested once; first try:  |
| dsh | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| dsh | gpt-5.3-codex | pass | pass | n/a | pass | pass | deployment gpt-5.3-codex added to the resource 2026-09-06, then re-run ; retested once; first try: first [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "OpenAI |
| dsh | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| dsh | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| dsh | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| dsh | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| dsh | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| dsh | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.3-codex | pass | pass | n/a | pass | pass | deployment gpt-5.3-codex added to the resource 2026-09-06, then re-run ; retested once; first try: first [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "HTTP 4 |
| hermes | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| hermes | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.3-codex | pass | pass | n/a | pass | pass | deployment gpt-5.3-codex added to the resource 2026-09-06, then re-run ; retested once; first try: first [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "The AP |
| opencode | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| opencode | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass | deployment gpt-5.3-codex added to the resource 2026-09-06, then re-run ; retested once; first try: first [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "OpenAI |
| pi | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| pi | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| qwen | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| qwen | gpt-5.3-codex | pass | pass | n/a | FAIL | FAIL | artifact: no file card (files: none); Create a file named hello-qwen.txt containing exactly the word HELLO, then reply DONE. QWEN CODE [API Error: 400 ; recycle: answered without M1-gpt-5.3-codex: What exact word did I ask you to reply with in my very first message of this task? Reply with just that w ; deployment gpt-5.3-codex added to the resource 2026-09-06, then re-run ; retested once; first try: artifact no file card (files: none); PI Error: 404 The API deployment for this resource d; recycle answered without M1-gpt-5.3-codex:  Reply with just that word. QWEN CODE [API Er |
| qwen | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| qwen | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| qwen | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| qwen | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| qwen | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| qwen | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |

55 pairs, 267 of 271 scenario runs passed.

## Provider: google

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Notes |
|---|---|---|---|---|---|---|---|
| dsh | gemini-3.6-flash | FAIL | n/a | n/a | n/a | n/a | first: [{"connection": "integration:Google AI Studio", "status": "failed", "error": "400 status code (no body)"}] |
| hermes | gemini-3.6-flash | FAIL | n/a | n/a | n/a | n/a | first: Your openai-api key was refused: API call failed after 3 retries: HTTP 429: [{
  "error": {
    "code": 429,
    "message": "You exceeded yo |
| opencode | gemini-3.6-flash | FAIL | n/a | n/a | n/a | n/a | first: [{"connection": "integration:Google AI Studio", "status": "failed", "error": "Too Many Requests: [{\n  \"error\": {\n    \"code\": 429,\n    ; retested once; first try: followup [{"connection": "integration:Google AI Studio", "status": "failed", "error": "To; artifact [{"connection": "integration:Google AI Studio", "status": "failed", "error": "To; recycle [{"connection": "integration:Google AI Studio", "status": "failed", "error": "To |
| pi | gemini-3.6-flash | FAIL | n/a | n/a | n/a | n/a | first: [{"connection": "integration:Google AI Studio", "status": "failed", "error": "400 status code (no body)"}] |
| qwen | gemini-3.6-flash | FAIL | n/a | n/a | n/a | n/a | first: Reply with exactly: M1-gemini-3.6-flash QWEN CODE Working… ; retested once; first try: first Reply with exactly: M1-gemini-3.6-flash QWEN CODE M1-gemini-3.6-flash Working… |

5 pairs, 0 of 5 scenario runs passed.

## Provider: openai

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Notes |
|---|---|---|---|---|---|---|---|
| cline | gpt-5.2 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| cline | gpt-5.4-mini | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.5 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.6-luna | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.6-sol | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.6-terra | pass | pass | pass (gpt-5.4) | pass | pass |  |
| codex | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| codex | gpt-5.3-codex | pass | pass | pass (gpt-5.6-luna) | FAIL | FAIL | artifact: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-luna: its tools are not available there. Start a new task for gpt-5.3 ; recycle: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-luna: its tools are not available there. Start a new task for gpt-5.3 ; retested once; first try: artifact Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-sol: its ; recycle Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-sol: its  |
| codex | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| codex | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| codex | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| codex | gpt-5.6-luna | pass | pass | FAIL (gpt-5.3-codex) | pass | FAIL | switch: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-luna: its tools are not available there. Start a new task for gpt-5.3 ; recycle: answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in my very first message of this task? Reply with just that wo ; retested once; first try: recycle answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in |
| codex | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| codex | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| dsh | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| dsh | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| dsh | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| dsh | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| dsh | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| dsh | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| dsh | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| dsh | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| hermes | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.5 | pass | pass | n/a | pass | pass | retested once; first try: artifact no file card (files: none); Create a file named hello-opencode.txt containing ex |
| opencode | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| opencode | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| pi | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| qwen | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| qwen | gpt-5.3-codex | pass | pass | n/a | FAIL | FAIL | artifact: no file card (files: none);  word HELLO, then reply DONE. QWEN CODE [API Error: 404 This model is not supported in the v1/chat/completions e ; recycle: answered without M1-gpt-5.3-codex: ith in my very first message of this task? Reply with just that word. QWEN CODE [API Error: 404 This mode ; retested once; first try: artifact no file card (files: none);  word HELLO, then reply DONE. QWEN CODE [API Error: ; recycle answered without M1-gpt-5.3-codex: ith in my very first message of this task? Re |
| qwen | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| qwen | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| qwen | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| qwen | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| qwen | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| qwen | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |

55 pairs, 267 of 273 scenario runs passed.

## Provider: openrouter

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Notes |
|---|---|---|---|---|---|---|---|
| dsh | claude-fable-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | claude-haiku-4.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | claude-opus-4.7 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | claude-opus-4.8 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | claude-opus-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | claude-sonnet-4.6 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | claude-sonnet-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | deepseek-v4-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | deepseek-v4-pro | pass | pass | pass (deepseek-v4-flash) | pass | pass |  |
| dsh | gemini-3.6-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | glm-5.3 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | glm-5.3-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.2 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.3-codex | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.4 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.4-mini | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.6-luna | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.6-sol | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.6-terra | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | kimi-k2.7-code | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | kimi-k3 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | mistral-medium-3.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | qwen3.7-max | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | qwen3.8-max | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | step-3.7-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| hermes | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | claude-opus-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gemini-3.6-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | glm-5.3-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| hermes | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | hunyuan-3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | ling-3.0-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | minimax-m3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | nemotron-3-ultra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | qwen3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | claude-opus-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gemini-3.6-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | glm-5.3-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| opencode | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try:  |
| pi | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try:  |
| pi | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try:  |
| pi | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try:  |
| pi | claude-opus-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try:  |
| pi | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try:  |
| pi | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try:  |
| pi | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try:  |
| pi | gemini-3.6-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try:  |
| pi | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try:  |
| pi | glm-5.3-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try:  |
| pi | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| pi | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try:  |
| pi | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try:  |
| pi | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try:  |
| pi | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try:  |
| pi | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try:  |
| pi | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | retested once; first try:  |
| qwen | claude-fable-5 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | claude-haiku-4.5 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | claude-opus-4.7 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | claude-opus-4.8 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | claude-opus-5 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | claude-sonnet-4.6 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | claude-sonnet-5 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | deepseek-v4-flash | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | deepseek-v4-pro | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gemini-3.6-flash | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | glm-5.3 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | glm-5.3-flash | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gpt-5.2 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gpt-5.4 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gpt-5.4-mini | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gpt-5.5 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gpt-5.6-luna | pass | pass | pass (qwen3.7-max) | pass | FAIL | recycle: answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in my very first message of this task? Reply with just that wo ; retested once; first try: recycle answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in |
| qwen | gpt-5.6-sol | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gpt-5.6-terra | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | kimi-k2.7-code | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | kimi-k3 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | mistral-medium-3.5 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | qwen3.7-max | pass | pass | pass (qwen3.8-max) | pass | pass |  |
| qwen | qwen3.8-max | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | step-3.7-flash | pass | pass | pass (qwen3.7-max) | pass | pass |  |

134 pairs, 669 of 670 scenario runs passed.

## Provider: tokenrouter

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Notes |
|---|---|---|---|---|---|---|---|
| claude-code | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| claude-code | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| claude-code | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| claude-code | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| claude-code | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass |  |
| claude-code | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| claude-code | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| cline | claude-fable-5 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | claude-haiku-4.5 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | claude-opus-4.7 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | claude-opus-4.8 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | claude-opus-5 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | claude-sonnet-4.6 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | claude-sonnet-5 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | deepseek-v4-flash | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | deepseek-v4-pro | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | glm-5.3 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | glm-5.3-flash | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.2 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| cline | gpt-5.4-mini | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.5 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.6-luna | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.6-sol | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.6-terra | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | kimi-k2.7-code | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | kimi-k3 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | mistral-medium-3.5 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | qwen3.7-max | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | qwen3.8-max | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | step-3.7-flash | pass | pass | pass (gpt-5.4) | pass | pass |  |
| codex | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| codex | gpt-5.3-codex | pass | pass | pass (gpt-5.6-luna) | FAIL | FAIL | artifact: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-luna: its tools are not available there. Start a new task for gpt-5.3 ; recycle: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-luna: its tools are not available there. Start a new task for gpt-5.3 ; retested once; first try: artifact Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-sol: its ; recycle Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-sol: its  |
| codex | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| codex | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| codex | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| codex | gpt-5.6-luna | pass | pass | FAIL (gpt-5.3-codex) | pass | pass | switch: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-luna: its tools are not available there. Start a new task for gpt-5.3 ; retested once; first try: recycle answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in |
| codex | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| codex | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| dsh | claude-fable-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | claude-haiku-4.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | claude-opus-4.7 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | claude-opus-4.8 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | claude-opus-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | claude-sonnet-4.6 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | claude-sonnet-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | deepseek-v4-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | deepseek-v4-pro | pass | pass | pass (deepseek-v4-flash) | pass | pass |  |
| dsh | gemini-3.6-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | glm-5.3 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | glm-5.3-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.2 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.3-codex | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.4 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.4-mini | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.6-luna | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.6-sol | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.6-terra | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | kimi-k2.7-code | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | kimi-k3 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | mistral-medium-3.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | qwen3.7-max | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | qwen3.8-max | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | step-3.7-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| hermes | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | claude-opus-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gemini-3.6-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | glm-5.3-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| hermes | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | claude-opus-5 | pass | pass | FAIL (gemini-3.6-flash) | pass | pass | switch: [{"connection": "integration:My TokenRouter", "status": "failed", "error": "Invalid JSON payload received. Unknown name \"$schema\" at 'tool ; retested once; first try: followup Reply with exactly: M2-claude-opus-5 OPENCODE Working… |
| opencode | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gemini-3.6-flash | FAIL | n/a | n/a | n/a | n/a | first: [{"connection": "integration:My TokenRouter", "status": "failed", "error": "Invalid JSON payload received. Unknown name \"$schema\" at 'tool ; retested once; first try: first [{"connection": "integration:My TokenRouter", "status": "failed", "error": "Inva |
| opencode | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | glm-5.3-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| opencode | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | claude-opus-5 | pass | pass | pass (glm-5.3-flash) | pass | pass | retested once; first try: first [{"connection": "integration:My TokenRouter", "status": "failed", "error": "M1-c |
| pi | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gemini-3.6-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | glm-5.3-flash | pass | pass | FAIL (claude-opus-5) | pass | pass | switch: Your tokenrouter key was refused: The model refused to complete the request ; retested once; first try: artifact no file card (files: none); Create a file named hello-pi.txt containing exactly  |
| pi | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| pi | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| qwen | claude-fable-5 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | claude-haiku-4.5 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | claude-opus-4.7 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | claude-opus-4.8 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | claude-opus-5 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | claude-sonnet-4.6 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | claude-sonnet-5 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | deepseek-v4-flash | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | deepseek-v4-pro | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gemini-3.6-flash | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | glm-5.3 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | glm-5.3-flash | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gpt-5.2 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gpt-5.3-codex | pass | pass | n/a | FAIL | FAIL | artifact: no file card (files: none);  word HELLO, then reply DONE. QWEN CODE [API Error: 404 This model is not supported in the v1/chat/completions e ; recycle: answered without M1-gpt-5.3-codex: ith in my very first message of this task? Reply with just that word. QWEN CODE [API Error: 404 This mode ; retested once; first try: artifact no file card (files: none);  word HELLO, then reply DONE. QWEN CODE [API Error: ; recycle answered without M1-gpt-5.3-codex: ith in my very first message of this task? Re |
| qwen | gpt-5.4 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gpt-5.4-mini | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gpt-5.5 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gpt-5.6-luna | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gpt-5.6-sol | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gpt-5.6-terra | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | kimi-k2.7-code | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | kimi-k3 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | mistral-medium-3.5 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | qwen3.7-max | pass | pass | pass (qwen3.8-max) | pass | pass |  |
| qwen | qwen3.8-max | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | step-3.7-flash | pass | pass | pass (qwen3.7-max) | pass | pass |  |

169 pairs, 832 of 840 scenario runs passed.

## Provider: vercel

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Notes |
|---|---|---|---|---|---|---|---|
| claude-code | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| claude-code | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| claude-code | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| claude-code | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| claude-code | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass |  |
| claude-code | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| claude-code | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass |  |
| cline | claude-fable-5 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | claude-haiku-4.5 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | claude-opus-4.7 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | claude-opus-4.8 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | claude-opus-5 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | claude-sonnet-4.6 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | claude-sonnet-5 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | deepseek-v4-flash | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | deepseek-v4-pro | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | glm-5.3 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | glm-5.3-flash | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.2 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| cline | gpt-5.4-mini | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.5 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.6-luna | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.6-sol | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | gpt-5.6-terra | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | kimi-k2.7-code | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | kimi-k3 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | mistral-medium-3.5 | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | qwen3.7-max | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | qwen3.8-max | pass | pass | pass (gpt-5.4) | pass | pass |  |
| cline | step-3.7-flash | pass | pass | pass (gpt-5.4) | pass | pass |  |
| codex | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| codex | gpt-5.3-codex | pass | pass | n/a | pass | pass | retested once; first try: artifact Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-sol: its ; recycle Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-sol: its  |
| codex | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| codex | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| codex | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| codex | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| codex | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| codex | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| dsh | claude-fable-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | claude-haiku-4.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | claude-opus-4.7 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | claude-opus-4.8 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | claude-opus-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | claude-sonnet-4.6 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | claude-sonnet-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | deepseek-v4-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | deepseek-v4-pro | pass | pass | pass (deepseek-v4-flash) | pass | pass |  |
| dsh | gemini-3.6-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | glm-5.3 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | glm-5.3-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.2 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.3-codex | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.4 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.4-mini | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.6-luna | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | gpt-5.6-sol | pass | pass | n/a | pass | pass | retested once; first try: first the message was not taken: the session never opened a turn in 120 s |
| dsh | gpt-5.6-terra | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | kimi-k2.7-code | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | kimi-k3 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | mistral-medium-3.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | qwen3.7-max | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | qwen3.8-max | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| dsh | step-3.7-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass |  |
| hermes | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | claude-opus-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gemini-3.6-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | glm-5.3-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| hermes | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | hunyuan-3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | kimi-k2.7-code | FAIL | n/a | n/a | n/a | n/a | first: [{"connection": "integration:Vercel AI Gateway", "status": "failed", "error": "hermes -z: agent failed: Model moonshotai/kimi-k2.7-code has  ; retested once; first try: first [{"connection": "integration:Vercel AI Gateway", "status": "failed", "error": "h |
| hermes | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | ling-3.0-flash | FAIL | n/a | n/a | n/a | n/a | first: [{"connection": "integration:Vercel AI Gateway", "status": "failed", "error": "hermes -z: agent failed: Model inclusionai/ling-3.0-flash has ; retested once; first try: first [{"connection": "integration:Vercel AI Gateway", "status": "failed", "error": "h |
| hermes | minimax-m3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | nemotron-3-ultra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | qwen3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | claude-opus-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gemini-3.6-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | glm-5.3-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| opencode | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | claude-opus-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gemini-3.6-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | glm-5.3-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| pi | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| qwen | claude-fable-5 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | claude-haiku-4.5 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | claude-opus-4.7 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | claude-opus-4.8 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | claude-opus-5 | pass | pass | n/a | pass | pass | retested once; first try: first the message was not taken: the session never opened a turn in 120 s |
| qwen | claude-sonnet-4.6 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | claude-sonnet-5 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | deepseek-v4-flash | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | deepseek-v4-pro | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gemini-3.6-flash | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | glm-5.3 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | glm-5.3-flash | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gpt-5.2 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gpt-5.3-codex | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gpt-5.4 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gpt-5.4-mini | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gpt-5.5 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gpt-5.6-luna | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gpt-5.6-sol | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | gpt-5.6-terra | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | kimi-k2.7-code | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | kimi-k3 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | mistral-medium-3.5 | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | qwen3.7-max | pass | pass | pass (qwen3.8-max) | pass | pass |  |
| qwen | qwen3.8-max | pass | pass | pass (qwen3.7-max) | pass | pass |  |
| qwen | step-3.7-flash | pass | pass | pass (qwen3.7-max) | pass | pass |  |

174 pairs, 857 of 859 scenario runs passed.

