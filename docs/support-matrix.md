# Harness support matrix

Scenarios: first turn, follow-up in the same session, switch model mid-session, artifact (a file the task must produce), recycle (the sandbox is let go on purpose, then a follow-up must recall the first message). pass = ran and answered as asked, FAIL = failed (reason in the notes), n/a = not run.

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
| codex | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| codex | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | FAIL | FAIL | artifact: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-sol: its tools are not available there. Start a new task for gpt-5.3- ; recycle: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-sol: its tools are not available there. Start a new task for gpt-5.3- |
| codex | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| codex | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| codex | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| codex | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| codex | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| codex | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| dsh | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| dsh | gpt-5.3-codex | pass | pass | n/a | pass | pass |  |
| dsh | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| dsh | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| dsh | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| dsh | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| dsh | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| dsh | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.3-codex | pass | pass | n/a | pass | pass |  |
| hermes | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| hermes | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.3-codex | pass | pass | n/a | pass | pass |  |
| opencode | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
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
| qwen | gpt-5.3-codex | pass | pass | n/a | FAIL | FAIL | artifact: no file card (files: none); Create a file named hello-qwen.txt containing exactly the word HELLO, then reply DONE. QWEN CODE [API Error: 400 ; recycle: answered without M1-gpt-5.3-codex: What exact word did I ask you to reply with in my very first message of this task? Reply with just that w |
| qwen | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| qwen | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| qwen | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| qwen | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| qwen | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| qwen | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |

55 pairs, 267 of 271 scenario runs passed.

## Provider: openai

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Notes |
|---|---|---|---|---|---|---|---|
| hermes | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| hermes | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | FAIL | pass | artifact: no file card (files: none); Create a file named hello-opencode.txt containing exactly the word HELLO, then reply DONE. OPENCODE Used a tool  |
| opencode | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| opencode | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass |  |
| pi | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |

12 pairs, 59 of 60 scenario runs passed.

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
| codex | gpt-5.3-codex | pass | pass | pass (gpt-5.6-luna) | FAIL | FAIL | artifact: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-luna: its tools are not available there. Start a new task for gpt-5.3 ; recycle: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-luna: its tools are not available there. Start a new task for gpt-5.3 |
| codex | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| codex | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| codex | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| codex | gpt-5.6-luna | pass | pass | FAIL (gpt-5.3-codex) | pass | pass | switch: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-luna: its tools are not available there. Start a new task for gpt-5.3 |
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
| opencode | claude-opus-5 | pass | pass | FAIL (gemini-3.6-flash) | pass | pass | switch: [{"connection": "integration:My TokenRouter", "status": "failed", "error": "Invalid JSON payload received. Unknown name \"$schema\" at 'tool |
| opencode | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| opencode | gemini-3.6-flash | FAIL | n/a | n/a | n/a | n/a | first: [{"connection": "integration:My TokenRouter", "status": "failed", "error": "Invalid JSON payload received. Unknown name \"$schema\" at 'tool |
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
| pi | claude-opus-5 | pass | pass | pass (glm-5.3-flash) | pass | pass |  |
| pi | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | gemini-3.6-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| pi | glm-5.3-flash | pass | pass | FAIL (claude-opus-5) | pass | pass | switch: Your tokenrouter key was refused: The model refused to complete the request |
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
| qwen | gpt-5.3-codex | pass | pass | n/a | FAIL | FAIL | artifact: no file card (files: none);  word HELLO, then reply DONE. QWEN CODE [API Error: 404 This model is not supported in the v1/chat/completions e ; recycle: answered without M1-gpt-5.3-codex: ith in my very first message of this task? Reply with just that word. QWEN CODE [API Error: 404 This mode |
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
| codex | gpt-5.3-codex | pass | pass | n/a | pass | pass |  |
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
| dsh | gpt-5.6-sol | pass | pass | n/a | pass | pass |  |
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
| hermes | kimi-k2.7-code | FAIL | n/a | n/a | n/a | n/a | first: [{"connection": "integration:Vercel AI Gateway", "status": "failed", "error": "hermes -z: agent failed: Model moonshotai/kimi-k2.7-code has  |
| hermes | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass |  |
| hermes | ling-3.0-flash | FAIL | n/a | n/a | n/a | n/a | first: [{"connection": "integration:Vercel AI Gateway", "status": "failed", "error": "hermes -z: agent failed: Model inclusionai/ling-3.0-flash has |
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
| qwen | claude-opus-5 | pass | pass | n/a | pass | pass |  |
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

