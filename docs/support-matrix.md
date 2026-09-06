# Harness support matrix

The run's notes, per column, are in [support-matrix-notes.md](support-matrix-notes.md).

Scenarios: first turn, follow-up in the same session, switch model mid-session, artifact (a file the task must produce), recycle (the sandbox is let go on purpose, then a follow-up must recall the first message). pass = ran and answered as asked, FAIL = failed (reason in the notes), n/a = not run.

## Provider: anthropic

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| claude-code | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| claude-code | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| claude-code | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| claude-code | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| claude-code | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic |  |
| claude-code | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| claude-code | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| cline | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| cline | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| cline | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| cline | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| cline | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| cline | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| cline | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| dsh | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| dsh | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| dsh | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| dsh | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| dsh | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic |  |
| dsh | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| dsh | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| hermes | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| hermes | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| hermes | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| hermes | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| hermes | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic |  |
| hermes | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| hermes | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| opencode | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| opencode | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | the model answered the first turn with a capabilities blurb instead of the word; one more try ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| opencode | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| opencode | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| opencode | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| opencode | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| opencode | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| pi | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| pi | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| pi | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| pi | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| pi | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic |  |
| pi | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| pi | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| qwen | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run with the Anthropic base carrying /v1 (0.13.9) ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-claude-fable-5: What exact word did I ask you to reply with  |
| qwen | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run with the Anthropic base carrying /v1 (0.13.9) ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-claude-haiku-4.5: What exact word did I ask you to reply wit |
| qwen | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run with the Anthropic base carrying /v1 (0.13.9) ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-claude-opus-4.7: What exact word did I ask you to reply with |
| qwen | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run with the Anthropic base carrying /v1 (0.13.9) ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-claude-opus-4.8: What exact word did I ask you to reply with |
| qwen | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic | re-run with the Anthropic base carrying /v1 (0.13.9) ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-claude-opus-5: What exact word did I ask you to reply with i |
| qwen | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run with the Anthropic base carrying /v1 (0.13.9) ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-claude-sonnet-4.6: What exact word did I ask you to reply wi |
| qwen | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run with the Anthropic base carrying /v1 (0.13.9) ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-claude-sonnet-5: What exact word did I ask you to reply with |

49 pairs, 245 of 245 scenario runs passed.

## Provider: azure-e2

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| cline | gpt-5.2 | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI E2 | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| cline | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| cline | gpt-5.4-mini | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| cline | gpt-5.5 | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| cline | gpt-5.6-luna | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| cline | gpt-5.6-sol | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| cline | gpt-5.6-terra | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| codex | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-5.3-codex | pass | pass | pass (gpt-5.5) | FAIL | FAIL | Azure OpenAI E2 | artifact: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.5: its tools are not available there. Start a new task for gpt-5.3-code ; recycle: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.5: its tools are not available there. Start a new task for gpt-5.3-code ; re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | FAIL | Azure OpenAI E2 | recycle: answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in my very first message of this task? Reply with just that wo ; re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Azure OpenAI E2 | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| dsh | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-5.3-codex | pass | pass | pass (gpt-5.5) | pass | pass | Azure OpenAI E2 | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| hermes | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-5.3-codex | pass | pass | pass (gpt-5.5) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| opencode | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-5.3-codex | pass | pass | pass (gpt-5.5) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| pi | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-5.3-codex | pass | pass | pass (gpt-5.5) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| qwen | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-gpt-5.2: What exact word did I ask you to reply with in my v |
| qwen | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-gpt-5.4: What exact word did I ask you to reply with in my v |
| qwen | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-gpt-5.4-mini: What exact word did I ask you to reply with in |
| qwen | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-gpt-5.5: What exact word did I ask you to reply with in my v |
| qwen | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in |
| qwen | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-gpt-5.6-sol: What exact word did I ask you to reply with in  |
| qwen | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-gpt-5.6-terra: What exact word did I ask you to reply with i |

54 pairs, 267 of 270 scenario runs passed.

## Provider: azure-openai

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| cline | gpt-5.2 | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI |  |
| cline | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| cline | gpt-5.4-mini | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI |  |
| cline | gpt-5.5 | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI |  |
| cline | gpt-5.6-luna | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI |  |
| cline | gpt-5.6-sol | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI |  |
| cline | gpt-5.6-terra | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI |  |
| codex | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI | re-run on 0.13.7 (a Codex history is kept whole under the same account) ; retested once; first try:  |
| codex | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | FAIL | FAIL | Azure OpenAI | artifact: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-sol: its tools are not available there. Start a new task for gpt-5.3- ; recycle: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-sol: its tools are not available there. Start a new task for gpt-5.3- ; deployment gpt-5.3-codex added to the resource 2026-09-06, then re-run ; retested once; first try: first [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "Reconn |
| codex | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI | re-run on 0.13.7 (a Codex history is kept whole under the same account) ; retested once; first try: switch [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "{\n  \; artifact [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "Error ; recycle [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "Error  |
| codex | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI | re-run on 0.13.7 (a Codex history is kept whole under the same account) ; retested once; first try: switch [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "{\n  \; artifact [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "Error ; recycle [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "Error  |
| codex | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI | re-run on 0.13.7 (a Codex history is kept whole under the same account) ; retested once; first try:  |
| codex | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI | re-run on 0.13.7 (a Codex history is kept whole under the same account) ; retested once; first try: recycle answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in |
| codex | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Azure OpenAI | re-run on 0.13.7 (a Codex history is kept whole under the same account) ; retested once; first try:  |
| codex | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI | re-run on 0.13.7 (a Codex history is kept whole under the same account) ; retested once; first try:  |
| dsh | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| dsh | gpt-5.3-codex | pass | pass | n/a | pass | pass | Azure OpenAI | deployment gpt-5.3-codex added to the resource 2026-09-06, then re-run ; retested once; first try: first [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "OpenAI |
| dsh | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| dsh | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| dsh | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| dsh | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| dsh | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Azure OpenAI |  |
| dsh | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| hermes | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| hermes | gpt-5.3-codex | pass | pass | n/a | pass | pass | Azure OpenAI | deployment gpt-5.3-codex added to the resource 2026-09-06, then re-run ; retested once; first try: first [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "HTTP 4 |
| hermes | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| hermes | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| hermes | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| hermes | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| hermes | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Azure OpenAI |  |
| hermes | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| opencode | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| opencode | gpt-5.3-codex | pass | pass | n/a | pass | pass | Azure OpenAI | deployment gpt-5.3-codex added to the resource 2026-09-06, then re-run ; retested once; first try: first [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "The AP |
| opencode | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| opencode | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| opencode | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| opencode | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| opencode | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Azure OpenAI |  |
| opencode | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| pi | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| pi | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI | deployment gpt-5.3-codex added to the resource 2026-09-06, then re-run ; retested once; first try: first [{"connection": "integration:Azure OpenAI", "status": "failed", "error": "OpenAI |
| pi | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| pi | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| pi | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| pi | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| pi | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Azure OpenAI |  |
| pi | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| qwen | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| qwen | gpt-5.3-codex | pass | pass | n/a | FAIL | FAIL | Azure OpenAI | artifact: no file card (files: none); Create a file named hello-qwen.txt containing exactly the word HELLO, then reply DONE. QWEN CODE [API Error: 400 ; recycle: answered without M1-gpt-5.3-codex: What exact word did I ask you to reply with in my very first message of this task? Reply with just that w ; deployment gpt-5.3-codex added to the resource 2026-09-06, then re-run ; retested once; first try: artifact no file card (files: none); PI Error: 404 The API deployment for this resource d; recycle answered without M1-gpt-5.3-codex:  Reply with just that word. QWEN CODE [API Er |
| qwen | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| qwen | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| qwen | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| qwen | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |
| qwen | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Azure OpenAI |  |
| qwen | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI |  |

55 pairs, 267 of 271 scenario runs passed.

## Provider: gemini-cli

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| gemini | gemini-2.5-flash | pass | pass | pass (gemini-3.5-flash) | pass | pass | Google AI Studio | served as gemini-3.5-flash (finding below) |
| gemini | gemini-2.5-flash-lite | pass | pass | pass (gemini-3.5-flash) | pass | pass | Google AI Studio |  |
| gemini | gemini-2.5-pro | pass | pass | pass (gemini-3.5-flash) | pass | pass | Google AI Studio |  |
| gemini | gemini-3-flash-preview | pass | pass | pass (gemini-3.5-flash) | pass | pass | Google AI Studio |  |
| gemini | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.5-flash) | pass | pass | Google AI Studio |  |
| gemini | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.5-flash) | pass | pass | Google AI Studio |  |
| gemini | gemini-3.5-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| gemini | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.5-flash) | pass | pass | Google AI Studio |  |
| gemini | gemini-3.6-flash | pass | pass | pass (gemini-3.5-flash) | pass | pass | Google AI Studio | served as gemini-3.5-flash (finding below) |
| gemini | gemini-3.7-flash | pass | pass | pass (gemini-3.5-flash) | pass | pass | Google AI Studio | served as gemini-3.5-flash (finding below) |
| gemini | gemini-3.8-flash | pass | pass | pass (gemini-3.5-flash) | pass | pass | Google AI Studio | served as gemini-3.5-flash (finding below) |

11 pairs, 35 of 35 scenario runs passed; 4 pairs served by another connection or as another model are findings, not counted.

Findings, pairs served by a connection other than the one under test or as a model other than the id asked for:

- gemini x gemini-2.5-flash: served as gemini-3.5-flash (the CLI reports the model it ran)
- gemini x gemini-3.6-flash: served as gemini-3.5-flash (the CLI reports the model it ran)
- gemini x gemini-3.7-flash: served as gemini-3.5-flash (the CLI reports the model it ran)
- gemini x gemini-3.8-flash: served as gemini-3.5-flash (the CLI reports the model it ran)

## Provider: gemini-google

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| cline | gemini-2.5-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| cline | gemini-2.5-flash-lite | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| cline | gemini-2.5-pro | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio | retested once; first try: recycle answered without M1-gemini-2.5-pro: irst message of this task? Reply with just t |
| cline | gemini-3-flash-preview | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| cline | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| cline | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| cline | gemini-3.5-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| cline | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| cline | gemini-3.7-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| cline | gemini-3.8-flash | pass | pass | pass (gemini-3.7-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-2.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-2.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-2.5-pro | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| hermes | gemini-2.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| hermes | gemini-2.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| hermes | gemini-2.5-pro | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| hermes | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| hermes | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| hermes | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| hermes | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| hermes | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio | retested once; first try: followup [{"connection": "integration:Google AI Studio", "status": "failed", "error": "\u |
| hermes | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| hermes | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| hermes | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| opencode | gemini-2.5-flash | pass | pass | pass (gemini-3.6-flash) | FAIL | FAIL | Google AI Studio | artifact: no file card (files: none); Create a file named hello-opencode.txt containing exactly the word HELLO, then reply DONE. OPENCODE ; recycle: answered without M1-gemini-2.5-flash: What exact word did I ask you to reply with in my very first message of this task? Reply with just tha ; opencode rows re-run on 0.13.20 (opencode rides the loopback relay, #97) ; retested once; first try: artifact no file card (files: none); Create a file named hello-opencode.txt containing ex; recycle answered without M1-gemini-2.5-flash: What exact word did I ask you to reply wit |
| opencode | gemini-2.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio | opencode rows re-run on 0.13.20 (opencode rides the loopback relay, #97) ; retested once; first try:  |
| opencode | gemini-2.5-pro | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio | opencode rows re-run on 0.13.20 (opencode rides the loopback relay, #97) ; retested once; first try: recycle answered without M1-gemini-2.5-pro: exact word did I ask you to reply with in my |
| opencode | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio | opencode rows re-run on 0.13.20 (opencode rides the loopback relay, #97) ; retested once; first try: artifact [{"connection": "integration:Google AI Studio", "status": "failed", "error": "Ba |
| opencode | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio | opencode rows re-run on 0.13.20 (opencode rides the loopback relay, #97) ; retested once; first try: artifact [{"connection": "integration:Google AI Studio", "status": "failed", "error": "Ba |
| opencode | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio | opencode rows re-run on 0.13.20 (opencode rides the loopback relay, #97) ; retested once; first try: artifact [{"connection": "integration:Google AI Studio", "status": "failed", "error": "Ba |
| opencode | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio | opencode rows re-run on 0.13.20 (opencode rides the loopback relay, #97) ; retested once; first try: artifact [{"connection": "integration:Google AI Studio", "status": "failed", "error": "Ba |
| opencode | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio | opencode rows re-run on 0.13.20 (opencode rides the loopback relay, #97) ; retested once; first try: artifact [{"connection": "integration:Google AI Studio", "status": "failed", "error": "Ba |
| opencode | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio | opencode rows re-run on 0.13.20 (opencode rides the loopback relay, #97) ; retested once; first try: artifact [{"connection": "integration:Google AI Studio", "status": "failed", "error": "Ba |
| opencode | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio | opencode rows re-run on 0.13.20 (opencode rides the loopback relay, #97) ; retested once; first try: artifact [{"connection": "integration:Google AI Studio", "status": "failed", "error": "Ba |
| opencode | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio | opencode rows re-run on 0.13.20 (opencode rides the loopback relay, #97) ; retested once; first try: artifact [{"connection": "integration:Google AI Studio", "status": "failed", "error": "Ba |
| pi | gemini-2.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| pi | gemini-2.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| pi | gemini-2.5-pro | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| pi | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| pi | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| pi | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| pi | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| pi | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| pi | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| pi | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| pi | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| qwen | gemini-2.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| qwen | gemini-2.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| qwen | gemini-2.5-pro | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| qwen | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| qwen | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| qwen | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| qwen | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| qwen | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| qwen | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| qwen | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| qwen | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |

65 pairs, 323 of 325 scenario runs passed.

## Provider: gemini-openrouter

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| cline | gemini-2.5-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| cline | gemini-2.5-flash-lite | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| cline | gemini-2.5-pro | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| cline | gemini-3-flash-preview | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| cline | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| cline | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| cline | gemini-3.5-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| cline | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| cline | gemini-3.7-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| cline | gemini-3.8-flash | pass | pass | pass (gemini-3.7-flash) | pass | pass | OpenRouter |  |
| dsh | gemini-2.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| dsh | gemini-2.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| dsh | gemini-2.5-pro | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| dsh | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| dsh | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| dsh | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| dsh | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| dsh | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| dsh | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| dsh | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| dsh | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| hermes | gemini-2.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| hermes | gemini-2.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | FAIL | OpenRouter | recycle: answered without M1-gemini-2.5-flash-lite: What exact word did I ask you to reply with in my very first message of this task? Reply with jus ; retested once; first try: recycle answered without M1-gemini-2.5-flash-lite: What exact word did I ask you to repl |
| hermes | gemini-2.5-pro | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| hermes | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| hermes | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| hermes | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| hermes | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| hermes | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| hermes | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| hermes | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| hermes | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| opencode | gemini-2.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| opencode | gemini-2.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| opencode | gemini-2.5-pro | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| opencode | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| opencode | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| opencode | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| opencode | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| opencode | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| opencode | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| opencode | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| opencode | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| pi | gemini-2.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| pi | gemini-2.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| pi | gemini-2.5-pro | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| pi | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| pi | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| pi | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| pi | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| pi | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| pi | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| pi | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| pi | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| qwen | gemini-2.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| qwen | gemini-2.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter | retested once; first try: followup answered without M2-gemini-2.5-flash-lite: rks) What is the desired visual aesth |
| qwen | gemini-2.5-pro | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| qwen | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| qwen | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| qwen | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| qwen | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| qwen | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| qwen | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| qwen | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| qwen | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |

65 pairs, 324 of 325 scenario runs passed.

## Provider: gemini-tokenrouter

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| cline | gemini-3-flash-preview | pass | pass | pass (gemini-3.8-flash) | pass | pass | My TokenRouter | cline rows re-run on 0.13.22 (no anyOf leaves the normaliser, #104) ; retested once; first try:  |
| cline | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.8-flash) | pass | pass | My TokenRouter | cline rows re-run on 0.13.22 (no anyOf leaves the normaliser, #104) ; retested once; first try:  |
| cline | gemini-3.5-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | My TokenRouter | cline rows re-run on 0.13.22 (no anyOf leaves the normaliser, #104) ; retested once; first try:  |
| cline | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.8-flash) | pass | pass | My TokenRouter | cline rows re-run on 0.13.22 (no anyOf leaves the normaliser, #104) ; retested once; first try:  |
| cline | gemini-3.7-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | My TokenRouter | cline rows re-run on 0.13.22 (no anyOf leaves the normaliser, #104) ; retested once; first try:  |
| cline | gemini-3.8-flash | pass | pass | pass (gemini-3.7-flash) | pass | pass | My TokenRouter | cline rows re-run on 0.13.22 (no anyOf leaves the normaliser, #104) ; retested once; first try:  |
| dsh | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| dsh | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| dsh | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| dsh | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| dsh | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | My TokenRouter |  |
| dsh | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| dsh | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| hermes | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| hermes | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| hermes | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| hermes | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| hermes | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | My TokenRouter |  |
| hermes | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| hermes | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| opencode | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| opencode | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| opencode | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| opencode | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| opencode | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | My TokenRouter |  |
| opencode | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| opencode | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| pi | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| pi | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| pi | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| pi | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| pi | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | My TokenRouter |  |
| pi | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| pi | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter |  |
| qwen | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter | qwen rows re-run on 0.13.22 (no anyOf leaves the normaliser, #104) ; retested once; first try:  |
| qwen | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter | qwen rows re-run on 0.13.22 (no anyOf leaves the normaliser, #104) ; retested once; first try: artifact no file card (files: none); claration parameters.fork_turns schema specified oth; recycle answered without M1-gemini-3.1-pro-preview:  submit request because agent functi |
| qwen | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter | qwen rows re-run on 0.13.22 (no anyOf leaves the normaliser, #104) ; retested once; first try: artifact no file card (files: none); claration parameters.fork_turns schema specified oth; recycle answered without M1-gemini-3.5-flash:  submit request because agent functionDecl |
| qwen | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter | qwen rows re-run on 0.13.22 (no anyOf leaves the normaliser, #104) ; retested once; first try: artifact no file card (files: none); claration parameters.fork_turns schema specified oth; recycle answered without M1-gemini-3.5-flash-lite:  submit request because agent functio |
| qwen | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | My TokenRouter | qwen rows re-run on 0.13.22 (no anyOf leaves the normaliser, #104) ; retested once; first try: artifact no file card (files: none); claration parameters.fork_turns schema specified oth; recycle answered without M1-gemini-3.6-flash:  submit request because agent functionDecl |
| qwen | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter | qwen rows re-run on 0.13.22 (no anyOf leaves the normaliser, #104) ; retested once; first try:  |
| qwen | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | My TokenRouter | qwen rows re-run on 0.13.22 (no anyOf leaves the normaliser, #104) ; retested once; first try: artifact no file card (files: none); claration parameters.fork_turns schema specified oth; recycle answered without M1-gemini-3.8-flash:  submit request because agent functionDecl |

41 pairs, 205 of 205 scenario runs passed.

## Provider: gemini-vercel

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| cline | gemini-2.5-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| cline | gemini-2.5-flash-lite | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| cline | gemini-2.5-pro | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| cline | gemini-3-flash-preview | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| cline | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| cline | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| cline | gemini-3.5-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| cline | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| cline | gemini-3.7-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| cline | gemini-3.8-flash | pass | pass | pass (gemini-3.7-flash) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-2.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-2.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | FAIL | pass | Vercel AI Gateway | artifact: no file card (files: none); word HELLO, then reply DONE. DEEPSEEK HARNESS Used a tool I am sorry, I cannot fulfill this request. The availab ; retested once; first try: artifact no file card (files: none); O, then reply DONE. DEEPSEEK HARNESS Used a tool I a |
| dsh | gemini-2.5-pro | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| hermes | gemini-2.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| hermes | gemini-2.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway | retested once; first try: recycle answered without M1-gemini-2.5-flash-lite: What exact word did I ask you to repl |
| hermes | gemini-2.5-pro | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| hermes | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| hermes | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| hermes | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| hermes | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| hermes | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| hermes | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | FAIL | Vercel AI Gateway | recycle: answered without M1-gemini-3.6-flash: What exact word did I ask you to reply with in my very first message of this task? Reply with just tha ; retested once; first try: recycle answered without M1-gemini-3.6-flash: What exact word did I ask you to reply wit |
| hermes | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| hermes | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| opencode | gemini-2.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| opencode | gemini-2.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| opencode | gemini-2.5-pro | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| opencode | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| opencode | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| opencode | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| opencode | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| opencode | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| opencode | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| opencode | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| opencode | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| pi | gemini-2.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| pi | gemini-2.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| pi | gemini-2.5-pro | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| pi | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| pi | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| pi | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| pi | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| pi | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| pi | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| pi | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| pi | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| qwen | gemini-2.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| qwen | gemini-2.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway | retested once; first try: first answered without M1-gemini-2.5-flash-lite: ation creation process. To begin, ple |
| qwen | gemini-2.5-pro | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| qwen | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| qwen | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| qwen | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| qwen | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| qwen | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| qwen | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| qwen | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| qwen | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |

65 pairs, 323 of 325 scenario runs passed.

## Provider: google

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| dsh | gemini-3.6-flash | n/a | n/a | n/a | n/a | n/a | ? | re-run on the sponsored Tier 3 key and 0.13.14 (the relays drop the field Google refuses); first try on the Free-tier ke ; retested once; first try: first [{"connection": "integration:Google AI Studio", "status": "failed", "error": "40 |
| hermes | gemini-3.6-flash | n/a | n/a | n/a | n/a | n/a | ? | re-run on the sponsored Tier 3 key and 0.13.14 (the relays drop the field Google refuses); first try on the Free-tier ke ; retested once; first try: first Your openai-api key was refused: API call failed after 3 retries: HTTP 429: [{
  |
| opencode | gemini-3.6-flash | pass | pass | n/a | FAIL | pass | Google AI Studio | artifact: [{"connection": "integration:Google AI Studio", "status": "failed", "error": "Bad Request: [{\n  \"error\": {\n    \"code\": 400,\n    \"mes ; re-run on the sponsored Tier 3 key and 0.13.14 (the relays drop the field Google refuses); first try on the Free-tier ke ; retested once; first try: followup [{"connection": "integration:Google AI Studio", "status": "failed", "error": "To; artifact [{"connection": "integration:Google AI Studio", "status": "failed", "error": "To; recycle [{"connection": "integration:Google AI Studio", "status": "failed", "error": "To |
| pi | gemini-3.6-flash | n/a | n/a | n/a | n/a | n/a | ? | re-run on the sponsored Tier 3 key and 0.13.14 (the relays drop the field Google refuses); first try on the Free-tier ke ; retested once; first try: first [{"connection": "integration:Google AI Studio", "status": "failed", "error": "40 |
| qwen | gemini-3.6-flash | pass | pass | n/a | FAIL | pass | Google AI Studio | artifact: no file card (files: none); he word HELLO, then reply DONE. QWEN CODE I will check if hello-qwen.txt exists and then write "HELLO" to it. Us ; re-run on the sponsored Tier 3 key and 0.13.14 (the relays drop the field Google refuses); first try on the Free-tier ke ; retested once; first try: first Reply with exactly: M1-gemini-3.6-flash QWEN CODE M1-gemini-3.6-flash Working… |

5 pairs, 6 of 8 scenario runs passed.

## Provider: openai

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| cline | gpt-5.2 | pass | pass | pass (gpt-5.4) | pass | pass | OpenAI |  |
| cline | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| cline | gpt-5.4-mini | pass | pass | pass (gpt-5.4) | pass | pass | OpenAI |  |
| cline | gpt-5.5 | pass | pass | pass (gpt-5.4) | pass | pass | OpenAI |  |
| cline | gpt-5.6-luna | pass | pass | pass (gpt-5.4) | pass | pass | OpenAI |  |
| cline | gpt-5.6-sol | pass | pass | pass (gpt-5.4) | pass | pass | OpenAI |  |
| cline | gpt-5.6-terra | pass | pass | pass (gpt-5.4) | pass | pass | OpenAI |  |
| codex | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| codex | gpt-5.3-codex | pass | pass | pass (gpt-5.6-luna) | FAIL | FAIL | OpenAI | artifact: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-luna: its tools are not available there. Start a new task for gpt-5.3 ; recycle: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-luna: its tools are not available there. Start a new task for gpt-5.3 ; retested once; first try: artifact Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-sol: its ; recycle Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-sol: its  |
| codex | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| codex | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| codex | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| codex | gpt-5.6-luna | pass | pass | FAIL (gpt-5.3-codex) | pass | FAIL | OpenAI | switch: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-luna: its tools are not available there. Start a new task for gpt-5.3 ; recycle: answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in my very first message of this task? Reply with just that wo ; retested once; first try: recycle answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in |
| codex | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | OpenAI |  |
| codex | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| dsh | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| dsh | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| dsh | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| dsh | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| dsh | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| dsh | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| dsh | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | OpenAI |  |
| dsh | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| hermes | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| hermes | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| hermes | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| hermes | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| hermes | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| hermes | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| hermes | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | OpenAI |  |
| hermes | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| opencode | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| opencode | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| opencode | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| opencode | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| opencode | gpt-5.5 | pass | pass | n/a | pass | pass | OpenAI | retested once; first try: artifact no file card (files: none); Create a file named hello-opencode.txt containing ex |
| opencode | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| opencode | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | OpenAI |  |
| opencode | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| pi | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| pi | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| pi | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| pi | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| pi | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| pi | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| pi | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | OpenAI |  |
| pi | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| qwen | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| qwen | gpt-5.3-codex | pass | pass | n/a | FAIL | FAIL | OpenAI | artifact: no file card (files: none);  word HELLO, then reply DONE. QWEN CODE [API Error: 404 This model is not supported in the v1/chat/completions e ; recycle: answered without M1-gpt-5.3-codex: ith in my very first message of this task? Reply with just that word. QWEN CODE [API Error: 404 This mode ; retested once; first try: artifact no file card (files: none);  word HELLO, then reply DONE. QWEN CODE [API Error: ; recycle answered without M1-gpt-5.3-codex: ith in my very first message of this task? Re |
| qwen | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| qwen | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| qwen | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| qwen | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| qwen | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | OpenAI |  |
| qwen | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |

55 pairs, 267 of 273 scenario runs passed.

## Provider: openrouter

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| dsh | claude-fable-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | claude-haiku-4.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | claude-opus-4.7 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | claude-opus-4.8 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | claude-opus-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | claude-sonnet-4.6 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | claude-sonnet-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | deepseek-v4-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | deepseek-v4-pro | pass | pass | pass (deepseek-v4-flash) | pass | pass | OpenRouter |  |
| dsh | gemini-3.6-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | glm-5.3 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | glm-5.3-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gpt-5.2 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gpt-5.3-codex | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gpt-5.4 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gpt-5.4-mini | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gpt-5.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gpt-5.6-luna | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gpt-5.6-sol | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gpt-5.6-terra | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | kimi-k2.7-code | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | kimi-k3 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | mistral-medium-3.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | qwen3.7-max | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | qwen3.8-max | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | step-3.7-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| hermes | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | claude-opus-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | gemini-3.6-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | glm-5.3-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | OpenRouter |  |
| hermes | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | hunyuan-3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | ling-3.0-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | minimax-m3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | nemotron-3-ultra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | qwen3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | claude-opus-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | gemini-3.6-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | glm-5.3-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | OpenRouter |  |
| opencode | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| pi | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | claude-opus-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| pi | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | gemini-3.6-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | glm-5.3-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| pi | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| pi | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| pi | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| pi | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| pi | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| pi | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | OpenRouter |  |
| pi | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| pi | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| qwen | claude-fable-5 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | claude-haiku-4.5 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | claude-opus-4.7 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | claude-opus-4.8 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | claude-opus-5 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | claude-sonnet-4.6 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | claude-sonnet-5 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | deepseek-v4-flash | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | deepseek-v4-pro | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | gemini-3.6-flash | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | glm-5.3 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | glm-5.3-flash | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | gpt-5.2 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | gpt-5.4 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | gpt-5.4-mini | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | gpt-5.5 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | gpt-5.6-luna | pass | pass | pass (qwen3.7-max) | pass | FAIL | OpenRouter | recycle: answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in my very first message of this task? Reply with just that wo ; retested once; first try: recycle answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in |
| qwen | gpt-5.6-sol | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | gpt-5.6-terra | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | kimi-k2.7-code | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | kimi-k3 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | mistral-medium-3.5 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | qwen3.7-max | pass | pass | pass (qwen3.8-max) | pass | pass | OpenRouter |  |
| qwen | qwen3.8-max | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | step-3.7-flash | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |

134 pairs, 669 of 670 scenario runs passed.

## Provider: tokenrouter

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| claude-code | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass | My TokenRouter |  |
| claude-code | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass | My TokenRouter |  |
| claude-code | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass | My TokenRouter |  |
| claude-code | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass | My TokenRouter |  |
| claude-code | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass | My TokenRouter |  |
| claude-code | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | My TokenRouter |  |
| claude-code | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass | My TokenRouter |  |
| cline | claude-fable-5 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | claude-haiku-4.5 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | claude-opus-4.7 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | claude-opus-4.8 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | claude-opus-5 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | claude-sonnet-4.6 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | claude-sonnet-5 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | deepseek-v4-flash | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | deepseek-v4-pro | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | glm-5.3 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | glm-5.3-flash | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | gpt-5.2 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| cline | gpt-5.4-mini | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | gpt-5.5 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | gpt-5.6-luna | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | gpt-5.6-sol | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | gpt-5.6-terra | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | kimi-k2.7-code | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | kimi-k3 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | mistral-medium-3.5 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | qwen3.7-max | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | qwen3.8-max | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | step-3.7-flash | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| codex | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| codex | gpt-5.3-codex | pass | pass | pass (gpt-5.6-luna) | FAIL | FAIL | My TokenRouter | artifact: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-luna: its tools are not available there. Start a new task for gpt-5.3 ; recycle: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-luna: its tools are not available there. Start a new task for gpt-5.3 ; retested once; first try: artifact Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-sol: its ; recycle Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-sol: its  |
| codex | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| codex | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| codex | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| codex | gpt-5.6-luna | pass | pass | FAIL (gpt-5.3-codex) | pass | pass | My TokenRouter | switch: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-luna: its tools are not available there. Start a new task for gpt-5.3 ; retested once; first try: recycle answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in |
| codex | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | My TokenRouter |  |
| codex | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| dsh | claude-fable-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | claude-haiku-4.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | claude-opus-4.7 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | claude-opus-4.8 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | claude-opus-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | claude-sonnet-4.6 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | claude-sonnet-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | deepseek-v4-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | deepseek-v4-pro | pass | pass | pass (deepseek-v4-flash) | pass | pass | My TokenRouter |  |
| dsh | gemini-3.6-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | glm-5.3 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | glm-5.3-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gpt-5.2 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gpt-5.3-codex | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gpt-5.4 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gpt-5.4-mini | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gpt-5.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gpt-5.6-luna | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gpt-5.6-sol | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gpt-5.6-terra | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | kimi-k2.7-code | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | kimi-k3 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | mistral-medium-3.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | qwen3.7-max | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | qwen3.8-max | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | step-3.7-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| hermes | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | claude-opus-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | gemini-3.6-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | glm-5.3-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | My TokenRouter |  |
| hermes | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| hermes | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | claude-opus-5 | pass | pass | FAIL (gemini-3.6-flash) | pass | pass | My TokenRouter | switch: [{"connection": "integration:My TokenRouter", "status": "failed", "error": "Invalid JSON payload received. Unknown name \"$schema\" at 'tool ; retested once; first try: followup Reply with exactly: M2-claude-opus-5 OPENCODE Working… |
| opencode | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | gemini-3.6-flash | FAIL | n/a | n/a | n/a | n/a | My TokenRouter | first: [{"connection": "integration:My TokenRouter", "status": "failed", "error": "Invalid JSON payload received. Unknown name \"$schema\" at 'tool ; retested once; first try: first [{"connection": "integration:My TokenRouter", "status": "failed", "error": "Inva |
| opencode | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | glm-5.3-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | My TokenRouter |  |
| opencode | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| opencode | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | claude-opus-5 | pass | pass | pass (glm-5.3-flash) | pass | pass | My TokenRouter | retested once; first try: first [{"connection": "integration:My TokenRouter", "status": "failed", "error": "M1-c |
| pi | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | gemini-3.6-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | glm-5.3-flash | pass | pass | FAIL (claude-opus-5) | pass | pass | My TokenRouter | switch: Your tokenrouter key was refused: The model refused to complete the request ; retested once; first try: artifact no file card (files: none); Create a file named hello-pi.txt containing exactly  |
| pi | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | My TokenRouter |  |
| pi | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| pi | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| qwen | claude-fable-5 | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | claude-haiku-4.5 | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | claude-opus-4.7 | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | claude-opus-4.8 | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | claude-opus-5 | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | claude-sonnet-4.6 | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | claude-sonnet-5 | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | deepseek-v4-flash | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | deepseek-v4-pro | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | gemini-3.6-flash | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | glm-5.3 | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | glm-5.3-flash | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | gpt-5.2 | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | gpt-5.3-codex | pass | pass | n/a | FAIL | FAIL | My TokenRouter | artifact: no file card (files: none);  word HELLO, then reply DONE. QWEN CODE [API Error: 404 This model is not supported in the v1/chat/completions e ; recycle: answered without M1-gpt-5.3-codex: ith in my very first message of this task? Reply with just that word. QWEN CODE [API Error: 404 This mode ; retested once; first try: artifact no file card (files: none);  word HELLO, then reply DONE. QWEN CODE [API Error: ; recycle answered without M1-gpt-5.3-codex: ith in my very first message of this task? Re |
| qwen | gpt-5.4 | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | gpt-5.4-mini | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | gpt-5.5 | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | gpt-5.6-luna | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | gpt-5.6-sol | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | gpt-5.6-terra | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | kimi-k2.7-code | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | kimi-k3 | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | mistral-medium-3.5 | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | qwen3.7-max | pass | pass | pass (qwen3.8-max) | pass | pass | My TokenRouter |  |
| qwen | qwen3.8-max | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |
| qwen | step-3.7-flash | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |

169 pairs, 832 of 840 scenario runs passed.

## Provider: vercel

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| claude-code | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass | Vercel AI Gateway |  |
| claude-code | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass | Vercel AI Gateway |  |
| claude-code | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass | Vercel AI Gateway |  |
| claude-code | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass | Vercel AI Gateway |  |
| claude-code | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass | Vercel AI Gateway |  |
| claude-code | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | Vercel AI Gateway |  |
| claude-code | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass | Vercel AI Gateway |  |
| cline | claude-fable-5 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | claude-haiku-4.5 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | claude-opus-4.7 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | claude-opus-4.8 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | claude-opus-5 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | claude-sonnet-4.6 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | claude-sonnet-5 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | deepseek-v4-flash | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | deepseek-v4-pro | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | glm-5.3 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | glm-5.3-flash | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | gpt-5.2 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| cline | gpt-5.4-mini | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | gpt-5.5 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | gpt-5.6-luna | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | gpt-5.6-sol | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | gpt-5.6-terra | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | kimi-k2.7-code | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | kimi-k3 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | mistral-medium-3.5 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | qwen3.7-max | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | qwen3.8-max | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | step-3.7-flash | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| codex | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| codex | gpt-5.3-codex | pass | pass | n/a | pass | pass | Vercel AI Gateway | retested once; first try: artifact Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-sol: its ; recycle Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-sol: its  |
| codex | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| codex | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| codex | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| codex | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| codex | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Vercel AI Gateway |  |
| codex | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| dsh | claude-fable-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | claude-haiku-4.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | claude-opus-4.7 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | claude-opus-4.8 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | claude-opus-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | claude-sonnet-4.6 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | claude-sonnet-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | deepseek-v4-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | deepseek-v4-pro | pass | pass | pass (deepseek-v4-flash) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.6-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | glm-5.3 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | glm-5.3-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gpt-5.2 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gpt-5.3-codex | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gpt-5.4 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gpt-5.4-mini | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gpt-5.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gpt-5.6-luna | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gpt-5.6-sol | pass | pass | n/a | pass | pass | Vercel AI Gateway | retested once; first try: first the message was not taken: the session never opened a turn in 120 s |
| dsh | gpt-5.6-terra | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | kimi-k2.7-code | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | kimi-k3 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | mistral-medium-3.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | qwen3.7-max | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | qwen3.8-max | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | step-3.7-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| hermes | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | claude-opus-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | gemini-3.6-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | glm-5.3-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Vercel AI Gateway |  |
| hermes | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | hunyuan-3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | kimi-k2.7-code | FAIL | n/a | n/a | n/a | n/a | Vercel AI Gateway | first: [{"connection": "integration:Vercel AI Gateway", "status": "failed", "error": "hermes -z: agent failed: Model moonshotai/kimi-k2.7-code has  ; retested once; first try: first [{"connection": "integration:Vercel AI Gateway", "status": "failed", "error": "h |
| hermes | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | ling-3.0-flash | FAIL | n/a | n/a | n/a | n/a | Vercel AI Gateway | first: [{"connection": "integration:Vercel AI Gateway", "status": "failed", "error": "hermes -z: agent failed: Model inclusionai/ling-3.0-flash has ; retested once; first try: first [{"connection": "integration:Vercel AI Gateway", "status": "failed", "error": "h |
| hermes | minimax-m3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | nemotron-3-ultra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | qwen3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | claude-opus-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | gemini-3.6-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | glm-5.3-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Vercel AI Gateway |  |
| opencode | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| opencode | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | claude-opus-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | gemini-3.6-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | glm-5.3-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Vercel AI Gateway |  |
| pi | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| pi | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| qwen | claude-fable-5 | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | claude-haiku-4.5 | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | claude-opus-4.7 | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | claude-opus-4.8 | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | claude-opus-5 | pass | pass | n/a | pass | pass | Vercel AI Gateway | retested once; first try: first the message was not taken: the session never opened a turn in 120 s |
| qwen | claude-sonnet-4.6 | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | claude-sonnet-5 | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | deepseek-v4-flash | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | deepseek-v4-pro | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | gemini-3.6-flash | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | glm-5.3 | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | glm-5.3-flash | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | gpt-5.2 | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | gpt-5.3-codex | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | gpt-5.4 | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | gpt-5.4-mini | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | gpt-5.5 | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | gpt-5.6-luna | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | gpt-5.6-sol | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | gpt-5.6-terra | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | kimi-k2.7-code | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | kimi-k3 | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | mistral-medium-3.5 | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | qwen3.7-max | pass | pass | pass (qwen3.8-max) | pass | pass | Vercel AI Gateway |  |
| qwen | qwen3.8-max | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |
| qwen | step-3.7-flash | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway |  |

174 pairs, 857 of 859 scenario runs passed.

