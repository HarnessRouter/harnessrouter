# Harness support matrix

The run's notes, per column, are in [support-matrix-notes.md](support-matrix-notes.md).

Scenarios: first turn, follow-up in the same session, switch model mid-session, artifact (a file the task must produce), recycle (the sandbox is let go on purpose, then a follow-up must recall the first message). pass = ran and answered as asked, FAIL = failed (reason in the notes), n/a = not run.

## Provider: agentzero-default

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| agentzero | claude-fable-5 | FAIL | n/a | n/a | n/a | n/a | My TokenRouter | first: The turn failed: the provider declined the request (finish_reason content_filter) ; retested once; first try: first The turn failed: the provider declined the request (finish_reason content_filter ; cache 0% of input |
| agentzero | claude-fable-5-1 | FAIL | n/a | n/a | n/a | n/a | My TokenRouter | first: The turn failed: the provider declined the request (finish_reason content_filter) ; retested once; first try: first The turn failed: the provider declined the request (finish_reason content_filter ; cache 0% of input |
| agentzero | claude-haiku-4.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Anthropic, OpenRouter | no prompt cache reads (finding below) ; served as claude-haiku-4-5-20251001 (the provider's alias of the same model) |
| agentzero | claude-opus-4.7 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | no prompt cache reads (finding below) ; served as claude-opus-4-7 (the provider's alias of the same model) |
| agentzero | claude-opus-4.8 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | no prompt cache reads (finding below) ; served as claude-opus-4-8 (the provider's alias of the same model) |
| agentzero | claude-opus-5 | pass | pass | pass (gpt-6.1-sol) | FAIL | FAIL | My TokenRouter, OpenRouter | artifact: The turn failed: the provider declined the request (finish_reason content_filter) ; recycle: The turn failed: the provider declined the request (finish_reason content_filter) ; retested once; first try: artifact The turn failed: the provider declined the request (finish_reason content_filter; recycle The turn failed: the provider declined the request (finish_reason content_filter ; cache 0% of input |
| agentzero | claude-opus-5.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | no prompt cache reads (finding below) ; served as anthropic/claude-opus-5.5 (the provider's alias of the same model) |
| agentzero | claude-sonnet-4.6 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Anthropic, OpenRouter | no prompt cache reads (finding below) ; served as claude-sonnet-4-6 (the provider's alias of the same model) |
| agentzero | claude-sonnet-5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | no prompt cache reads (finding below) |
| agentzero | claude-sonnet-5.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | no prompt cache reads (finding below) ; served as claude-sonnet-5-5 (the provider's alias of the same model) |
| agentzero | claude-sonnet-5.5-direct | pass | pass | pass (gpt-6.1-sol) | pass | pass | Anthropic, OpenRouter | no prompt cache reads (finding below) ; served as claude-sonnet-5-5 (finding below) |
| agentzero | deepseek-v4-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as deepseek-v4.1-flash (finding below) ; cache 63% of input |
| agentzero | deepseek-v4-pro | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 59% of input |
| agentzero | deepseek-v4.1-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 63% of input |
| agentzero | gemini-3-flash-preview | pass | pass | pass (gpt-6.1-sol) | pass | FAIL | My TokenRouter, OpenRouter | recycle: answered without M1-gemini-3-flash-preview: What exact word did I ask you to reply with in my very first message of this task? Reply with ju ; retested once; first try: recycle answered without M1-gemini-3-flash-preview: What exact word did I ask you to rep ; cache 29% of input |
| agentzero | gemini-3.1-flash-lite | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as google/gemini-3.1-flash-lite (the provider's alias of the same model) ; cache 44% of input |
| agentzero | gemini-3.1-pro-preview | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 29% of input |
| agentzero | gemini-3.5-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 44% of input |
| agentzero | gemini-3.5-flash-lite | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 44% of input |
| agentzero | gemini-3.6-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 19% of input |
| agentzero | gemini-3.7-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 29% of input |
| agentzero | gemini-3.8-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 29% of input |
| agentzero | glm-5.3 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 71% of input |
| agentzero | glm-5.3-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 46% of input |
| agentzero | gpt-5.2 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Custom OpenAI Chat, OpenRouter | served as gpt-5.2-2025-12-11 (the provider's alias of the same model) ; cache 60% of input |
| agentzero | gpt-5.4 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as gpt-5.4-2026-03-05 (the provider's alias of the same model) ; cache 58% of input |
| agentzero | gpt-5.4-mini | pass | pass | pass (gpt-6.1-sol) | pass | pass | Custom OpenAI Chat, OpenRouter | served as gpt-5.4-mini-2026-03-17 (the provider's alias of the same model) ; cache 58% of input |
| agentzero | gpt-5.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Azure OpenAI E2, OpenRouter | served as gpt-5.5-2026-04-24 (the provider's alias of the same model) ; cache 56% of input |
| agentzero | gpt-5.6-luna | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 61% of input |
| agentzero | gpt-5.6-sol | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 62% of input |
| agentzero | gpt-5.6-terra | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 66% of input |
| agentzero | gpt-6-luna | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 61% of input |
| agentzero | gpt-6-sol | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 66% of input |
| agentzero | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter, My TokenRouter | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 62% of input |
| agentzero | grok-4.20 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as x-ai/grok-4.20 (the provider's alias of the same model) ; cache 47% of input |
| agentzero | grok-4.3 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as x-ai/grok-4.3 (the provider's alias of the same model) ; cache 17% of input |
| agentzero | grok-4.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 34% of input |
| agentzero | grok-4.6 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 6% of input |
| agentzero | grok-build-0.1 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as x-ai/grok-build-0.1 (the provider's alias of the same model) ; cache 32% of input |
| agentzero | hunyuan-4-preview | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as tencent/hy4-preview (the provider's alias of the same model) ; cache 55% of input |
| agentzero | kimi-k2.7-code | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 62% of input |
| agentzero | kimi-k3 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 0% of input |
| agentzero | llama-3.3-70b | pass | pass | pass (gpt-6.1-sol) | pass | pass | OpenRouter | served as meta-llama/llama-3.3-70b-instruct (the provider's alias of the same model) ; cache 32% of input |
| agentzero | mistral-medium-3.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as mistralai/mistral-medium-3-5 (the provider's alias of the same model) ; cache 63% of input |
| agentzero | muse-glimmer-30b | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as meta/muse-glimmer-30b (the provider's alias of the same model) ; retested once; first try: artifact The turn failed: HandledException: Agent stopped after 5 consecutive unusable mo ; cache 60% of input |
| agentzero | muse-spark-1.1 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as meta/muse-spark-1.1 (the provider's alias of the same model) ; cache 66% of input |
| agentzero | muse-spark-1.2 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as meta/muse-spark-1.2 (the provider's alias of the same model) ; cache 67% of input |
| agentzero | muse-spark-1.3 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as meta/muse-spark-1.3 (the provider's alias of the same model) ; cache 0% of input |
| agentzero | nemotron-3-super | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as nvidia/nemotron-3-super-120b-a12b (the provider's alias of the same model) ; cache 0% of input |
| agentzero | nemotron-3.5-lightning | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as nvidia/nemotron-3.5-lightning (the provider's alias of the same model) ; cache 15% of input |
| agentzero | qwen3.7-max | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 57% of input |
| agentzero | qwen3.7-plus | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 47% of input |
| agentzero | qwen3.8-27b | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as alibaba/qwen3.8-27b (the provider's alias of the same model) ; cache 51% of input |
| agentzero | qwen3.8-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 64% of input |
| agentzero | qwen3.8-max | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 62% of input |
| agentzero | step-3.7-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as stepfun/step-3.7-flash (the provider's alias of the same model) ; cache 60% of input |

56 pairs, 257 of 262 scenario runs passed; 2 pairs served by another connection or as another model are findings, not counted.

Findings, pairs served by a connection other than the one under test or as a model other than the id asked for:

- agentzero x claude-haiku-4.5: no prompt cache reads over 42994 input tokens (every call paid full price)
- agentzero x claude-opus-4.7: no prompt cache reads over 55588 input tokens (every call paid full price)
- agentzero x claude-opus-4.8: no prompt cache reads over 55260 input tokens (every call paid full price)
- agentzero x claude-opus-5.5: no prompt cache reads over 55502 input tokens (every call paid full price)
- agentzero x claude-sonnet-4.6: no prompt cache reads over 42617 input tokens (every call paid full price)
- agentzero x claude-sonnet-5: no prompt cache reads over 55459 input tokens (every call paid full price)
- agentzero x claude-sonnet-5.5: no prompt cache reads over 55454 input tokens (every call paid full price)
- agentzero x claude-sonnet-5.5-direct: served as claude-sonnet-5-5 (the CLI reports the model it ran)
- agentzero x claude-sonnet-5.5-direct: no prompt cache reads over 55461 input tokens (every call paid full price)
- agentzero x deepseek-v4-flash: served as deepseek-v4.1-flash (the CLI reports the model it ran)

## Provider: anthropic

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| agentzero | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Anthropic | no prompt cache reads (finding below) ; served as claude-haiku-5-5 (the provider's alias of the same model) |
| aider | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | FAIL | Anthropic | no prompt cache reads (finding below) ; served as claude-haiku-5-5 (the provider's alias of the same model) ; recycle: answered without M1-claude-haiku-5.5: What exact word did I ask you to reply with in my very first message of this task? Reply with just tha |
| claude-code | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| claude-code | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| claude-code | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Anthropic | served as claude-haiku-5-5 (the provider's alias of the same model) ; cache 100% of input |
| claude-code | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| claude-code | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| claude-code | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic |  |
| claude-code | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| claude-code | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| cline | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| cline | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| cline | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Anthropic | no prompt cache reads (finding below) ; 4 turn(s) unlabelled (finding below) |
| cline | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| cline | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| cline | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| cline | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| cline | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| dsh | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| dsh | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| dsh | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Anthropic | 4 turn(s) unlabelled (finding below) ; cache 100% of input |
| dsh | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| dsh | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| dsh | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic |  |
| dsh | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| dsh | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| goose | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Anthropic | served as claude-haiku-5-5 (the provider's alias of the same model) ; cache 64% of input |
| grok | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Anthropic | no prompt cache reads (finding below) ; served as claude-haiku-5-5 (the provider's alias of the same model) |
| hermes | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| hermes | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| hermes | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Anthropic | served as claude-haiku-5-5 (the provider's alias of the same model) ; cache 100% of input |
| hermes | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| hermes | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| hermes | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic |  |
| hermes | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| hermes | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| kilo | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Anthropic | served as claude-haiku-5-5 (the provider's alias of the same model) ; cache 99% of input |
| kimi | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Anthropic | no prompt cache reads (finding below) ; served as claude-haiku-5-5 (the provider's alias of the same model) |
| minimax | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Anthropic | no prompt cache reads (finding below) ; served as claude-haiku-5-5 (the provider's alias of the same model) |
| omp | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Anthropic | served as claude-haiku-5-5 (the provider's alias of the same model) ; cache 100% of input |
| opencode | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| opencode | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | the model answered the first turn with a capabilities blurb instead of the word; one more try ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| opencode | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Anthropic | served as claude-haiku-5-5 (the provider's alias of the same model) ; cache 100% of input |
| opencode | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| opencode | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| opencode | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| opencode | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| opencode | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run on the bare base, partner inside the column ; retested once; first try: first [{"connection": "integration:Anthropic", "status": "failed", "error": "Not Found |
| openhands | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Anthropic | served as claude-haiku-5-5 (the provider's alias of the same model) ; cache 99% of input |
| pi | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| pi | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| pi | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Anthropic | served as claude-haiku-5-5 (the provider's alias of the same model) ; cache 83% of input |
| pi | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| pi | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| pi | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic |  |
| pi | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| pi | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| qwen | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run with the Anthropic base carrying /v1 (0.13.9) ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-claude-fable-5: What exact word did I ask you to reply with  |
| qwen | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run with the Anthropic base carrying /v1 (0.13.9) ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-claude-haiku-4.5: What exact word did I ask you to reply wit |
| qwen | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Anthropic | no prompt cache reads (finding below) ; served as claude-haiku-5-5 (the provider's alias of the same model) |
| qwen | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run with the Anthropic base carrying /v1 (0.13.9) ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-claude-opus-4.7: What exact word did I ask you to reply with |
| qwen | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run with the Anthropic base carrying /v1 (0.13.9) ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-claude-opus-4.8: What exact word did I ask you to reply with |
| qwen | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic | re-run with the Anthropic base carrying /v1 (0.13.9) ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-claude-opus-5: What exact word did I ask you to reply with i |
| qwen | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run with the Anthropic base carrying /v1 (0.13.9) ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-claude-sonnet-4.6: What exact word did I ask you to reply wi |
| qwen | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | re-run with the Anthropic base carrying /v1 (0.13.9) ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-claude-sonnet-5: What exact word did I ask you to reply with |

65 pairs, 314 of 315 scenario runs passed; 2 pairs served by another connection or as another model are findings, not counted.

Findings, pairs served by a connection other than the one under test or as a model other than the id asked for:

- agentzero x claude-haiku-5.5: no prompt cache reads over 56589 input tokens (every call paid full price)
- aider x claude-haiku-5.5: no prompt cache reads over 24331 input tokens (every call paid full price)
- cline x claude-haiku-5.5: 4 turn(s) report no served model, so rule 2 could not judge them
- cline x claude-haiku-5.5: no prompt cache reads over 51690 input tokens (every call paid full price)
- dsh x claude-haiku-5.5: 4 turn(s) report no served model, so rule 2 could not judge them
- grok x claude-haiku-5.5: no prompt cache reads over 95190 input tokens (every call paid full price)
- kimi x claude-haiku-5.5: no prompt cache reads over 184580 input tokens (every call paid full price)
- minimax x claude-haiku-5.5: no prompt cache reads over 83845 input tokens (every call paid full price)
- qwen x claude-haiku-5.5: no prompt cache reads over 570021 input tokens (every call paid full price)

Not run in this column, 111 pairs the provider serves that the harness did not run, with the reason:

- agentzero x claude-fable-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- agentzero x claude-fable-5-1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- agentzero x claude-haiku-4.5: not run, not run in this column
- agentzero x claude-opus-4.7: not run, not run in this column
- agentzero x claude-opus-4.8: not run, not run in this column
- agentzero x claude-opus-5: not run, not run in this column
- agentzero x claude-opus-5.5: not run, not run in this column
- agentzero x claude-sonnet-4.6: not run, not run in this column
- agentzero x claude-sonnet-5: not run, not run in this column
- agentzero x claude-sonnet-5.5: not run, not run in this column
- aider x claude-fable-5: not run, not run in this column
- aider x claude-fable-5-1: not run, not run in this column
- aider x claude-haiku-4.5: not run, not run in this column
- aider x claude-opus-4.7: not run, not run in this column
- aider x claude-opus-4.8: not run, not run in this column
- aider x claude-opus-5: not run, not run in this column
- aider x claude-opus-5.5: not run, not run in this column
- aider x claude-sonnet-4.6: not run, not run in this column
- aider x claude-sonnet-5: not run, not run in this column
- aider x claude-sonnet-5.5: not run, not run in this column
- claude-code x claude-fable-5-1: not run, not run in this column
- claude-code x claude-opus-5.5: not run, not run in this column
- claude-code x claude-sonnet-5.5: not run, not run in this column
- cline x claude-fable-5-1: not run, not run in this column
- cline x claude-opus-5.5: not run, not run in this column
- cline x claude-sonnet-5.5: not run, not run in this column
- dsh x claude-fable-5-1: not run, not run in this column
- dsh x claude-opus-5.5: not run, not run in this column
- dsh x claude-sonnet-5.5: not run, not run in this column
- goose x claude-fable-5: not run, not run in this column
- goose x claude-fable-5-1: not run, not run in this column
- goose x claude-haiku-4.5: not run, not run in this column
- goose x claude-opus-4.7: not run, not run in this column
- goose x claude-opus-4.8: not run, not run in this column
- goose x claude-opus-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x claude-opus-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x claude-sonnet-4.6: not run, not run in this column
- goose x claude-sonnet-5: not run, not run in this column
- goose x claude-sonnet-5.5: not run, not run in this column
- grok x claude-fable-5: not run, not run in this column
- grok x claude-fable-5-1: not run, not run in this column
- grok x claude-haiku-4.5: not run, not run in this column
- grok x claude-opus-4.7: not run, not run in this column
- grok x claude-opus-4.8: not run, not run in this column
- grok x claude-opus-5: not run, not run in this column
- grok x claude-opus-5.5: not run, not run in this column
- grok x claude-sonnet-4.6: not run, not run in this column
- grok x claude-sonnet-5: not run, not run in this column
- grok x claude-sonnet-5.5: not run, not run in this column
- hermes x claude-fable-5-1: not run, not run in this column
- hermes x claude-opus-5.5: not run, not run in this column
- hermes x claude-sonnet-5.5: not run, not run in this column
- kilo x claude-fable-5: not run, not run in this column
- kilo x claude-fable-5-1: not run, not run in this column
- kilo x claude-haiku-4.5: not run, not run in this column
- kilo x claude-opus-4.7: not run, not run in this column
- kilo x claude-opus-4.8: not run, not run in this column
- kilo x claude-opus-5: not run, not run in this column
- kilo x claude-opus-5.5: not run, not run in this column
- kilo x claude-sonnet-4.6: not run, not run in this column
- kilo x claude-sonnet-5: not run, not run in this column
- kilo x claude-sonnet-5.5: not run, not run in this column
- kimi x claude-fable-5: not run, not run in this column
- kimi x claude-fable-5-1: not run, not run in this column
- kimi x claude-haiku-4.5: not run, not run in this column
- kimi x claude-opus-4.7: not run, not run in this column
- kimi x claude-opus-4.8: not run, not run in this column
- kimi x claude-opus-5: not run, not run in this column
- kimi x claude-opus-5.5: not run, not run in this column
- kimi x claude-sonnet-4.6: not run, not run in this column
- kimi x claude-sonnet-5: not run, not run in this column
- kimi x claude-sonnet-5.5: not run, not run in this column
- minimax x claude-fable-5: not run, not run in this column
- minimax x claude-fable-5-1: not run, not run in this column
- minimax x claude-haiku-4.5: not run, not run in this column
- minimax x claude-opus-4.7: not run, not run in this column
- minimax x claude-opus-4.8: not run, not run in this column
- minimax x claude-opus-5: not run, not run in this column
- minimax x claude-opus-5.5: not run, not run in this column
- minimax x claude-sonnet-4.6: not run, not run in this column
- minimax x claude-sonnet-5: not run, not run in this column
- minimax x claude-sonnet-5.5: not run, not run in this column
- omp x claude-fable-5: not run, not run in this column
- omp x claude-fable-5-1: not run, not run in this column
- omp x claude-haiku-4.5: not run, not run in this column
- omp x claude-opus-4.7: not run, not run in this column
- omp x claude-opus-4.8: not run, not run in this column
- omp x claude-opus-5: not run, not run in this column
- omp x claude-opus-5.5: not run, not run in this column
- omp x claude-sonnet-4.6: not run, not run in this column
- omp x claude-sonnet-5: not run, not run in this column
- omp x claude-sonnet-5.5: not run, not run in this column
- opencode x claude-fable-5-1: not run, not run in this column
- opencode x claude-opus-5.5: not run, not run in this column
- opencode x claude-sonnet-5.5: not run, not run in this column
- openhands x claude-fable-5: not run, not run in this column
- openhands x claude-fable-5-1: not run, not run in this column
- openhands x claude-haiku-4.5: not run, not run in this column
- openhands x claude-opus-4.7: not run, not run in this column
- openhands x claude-opus-4.8: not run, not run in this column
- openhands x claude-opus-5: not run, not run in this column
- openhands x claude-opus-5.5: not run, not run in this column
- openhands x claude-sonnet-4.6: not run, not run in this column
- openhands x claude-sonnet-5: not run, not run in this column
- openhands x claude-sonnet-5.5: not run, not run in this column
- pi x claude-fable-5-1: not run, not run in this column
- pi x claude-opus-5.5: not run, not run in this column
- pi x claude-sonnet-5.5: not run, not run in this column
- qwen x claude-fable-5-1: not run, not run in this column
- qwen x claude-opus-5.5: not run, not run in this column
- qwen x claude-sonnet-5.5: not run, not run in this column

## Provider: azure-e2

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| aider | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | FAIL | Azure OpenAI E2 | recycle: answered without M1-gpt-6-luna: What exact word did I ask you to reply with in my very first message of this task? Reply with just that word ; served as gpt-6-luna-2026-09-22 (the provider's alias of the same model) ; recycle: answered without M1-gpt-6-luna: What |
| aider | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | Azure OpenAI E2 | served as gpt-6-sol-2026-09-22 (the provider's alias of the same model) |
| aider | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Azure OpenAI E2 | served as gpt-6.1-sol-2026-09-29 (the provider's alias of the same model) ; cache 50% of input |
| cline | gpt-5.2 | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI E2 | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| cline | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| cline | gpt-5.4-mini | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| cline | gpt-5.5 | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| cline | gpt-5.6-luna | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| cline | gpt-5.6-sol | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| cline | gpt-5.6-terra | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| cline | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | Azure OpenAI E2 |  |
| cline | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | Azure OpenAI E2 |  |
| cline | gpt-6.1-sol | FAIL | n/a | n/a | n/a | n/a | Azure OpenAI E2 | 1 turn(s) unlabelled (finding below) ; first: The turn failed: Unsupported value: 'reasoning_effort' does not support 'none' with this model. Supported values are: 'low', 'medium', 'high |
| codex | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-5.3-codex | pass | pass | pass (gpt-5.5) | FAIL | FAIL | Azure OpenAI E2 | artifact: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.5: its tools are not available there. Start a new task for gpt-5.3-code ; recycle: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.5: its tools are not available there. Start a new task for gpt-5.3-code ; re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | FAIL | Azure OpenAI E2 | recycle: answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in my very first message of this task? Reply with just that wo ; re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Azure OpenAI E2 | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Rec |
| codex | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | Azure OpenAI E2 |  |
| codex | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| codex | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| codex | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Azure OpenAI E2 | 4 turn(s) unlabelled (finding below) ; cache 50% of input |
| dsh | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-5.3-codex | pass | pass | pass (gpt-5.5) | pass | pass | Azure OpenAI E2 | retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| dsh | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | Azure OpenAI E2 |  |
| dsh | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| dsh | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| dsh | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Azure OpenAI E2 | 4 turn(s) unlabelled (finding below) ; cache 100% of input |
| goose | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Azure OpenAI E2 | cache 52% of input |
| hermes | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-5.3-codex | pass | pass | pass (gpt-5.5) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "API |
| hermes | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | Azure OpenAI E2 |  |
| hermes | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| hermes | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| hermes | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Azure OpenAI E2 | 4 turn(s) unlabelled (finding below) ; cache 0% of input |
| kimi | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | Azure OpenAI E2 | served as gpt-6-luna-2026-09-22 (the provider's alias of the same model) |
| kimi | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | Azure OpenAI E2 | served as gpt-6-sol-2026-09-22 (the provider's alias of the same model) |
| kimi | gpt-6.1-sol | FAIL | n/a | n/a | n/a | n/a | Azure OpenAI E2 | 1 turn(s) unlabelled (finding below) ; first: The turn failed: error: failed to run prompt: provider.api_error: 400 Unsupported value: 'reasoning_effort' does not support 'none' with thi |
| omp | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | Azure OpenAI E2 |  |
| omp | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| omp | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| omp | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Azure OpenAI E2 | 1 turn(s) unlabelled (finding below) ; cache 100% of input |
| opencode | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-5.3-codex | pass | pass | pass (gpt-5.5) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Res |
| opencode | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | Azure OpenAI E2 |  |
| opencode | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| opencode | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| opencode | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Azure OpenAI E2 | cache 100% of input |
| openhands | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | Azure OpenAI E2 |  |
| openhands | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | Azure OpenAI E2 |  |
| openhands | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Azure OpenAI E2 | cache 0% of input |
| pi | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-5.3-codex | pass | pass | pass (gpt-5.5) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: first [{"connection": "integration:Azure OpenAI E2", "status": "failed", "error": "Ope |
| pi | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | Azure OpenAI E2 |  |
| pi | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| pi | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| pi | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Azure OpenAI E2 | cache 100% of input |
| qwen | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-gpt-5.2: What exact word did I ask you to reply with in my v |
| qwen | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-gpt-5.4: What exact word did I ask you to reply with in my v |
| qwen | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-gpt-5.4-mini: What exact word did I ask you to reply with in |
| qwen | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-gpt-5.5: What exact word did I ask you to reply with in my v |
| qwen | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in |
| qwen | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-gpt-5.6-sol: What exact word did I ask you to reply with in  |
| qwen | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 | re-run with the E2 base carrying /openai/v1 ; retested once; first try: artifact no file card (files: none); Create a file named hello-qwen.txt containing exactl; recycle answered without M1-gpt-5.6-terra: What exact word did I ask you to reply with i |
| qwen | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | Azure OpenAI E2 | served as gpt-6-luna-2026-09-22 (the provider's alias of the same model) |
| qwen | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | Azure OpenAI E2 | served as gpt-6-sol-2026-09-22 (the provider's alias of the same model) |
| qwen | gpt-6.1-sol | FAIL | n/a | n/a | n/a | n/a | Azure OpenAI E2 | 1 turn(s) unlabelled (finding below) ; first: The turn failed: API Error: 400 Unsupported value: 'reasoning_effort' does not support 'none' with this model. Supported values are: 'low',  |

94 pairs, 431 of 435 scenario runs passed; 7 pairs served by another connection or as another model are findings, not counted.

Findings, pairs served by a connection other than the one under test or as a model other than the id asked for:

- cline x gpt-6.1-sol: 1 turn(s) report no served model, so rule 2 could not judge them
- codex x gpt-6.1-sol: 4 turn(s) report no served model, so rule 2 could not judge them
- dsh x gpt-6.1-sol: 4 turn(s) report no served model, so rule 2 could not judge them
- hermes x gpt-6.1-sol: 4 turn(s) report no served model, so rule 2 could not judge them
- kimi x gpt-6.1-sol: 1 turn(s) report no served model, so rule 2 could not judge them
- omp x gpt-6.1-sol: 1 turn(s) report no served model, so rule 2 could not judge them
- qwen x gpt-6.1-sol: 1 turn(s) report no served model, so rule 2 could not judge them

Not run in this column, 50 pairs the provider serves that the harness did not run, with the reason:

- aider x gpt-5.2: not run, not run in this column
- aider x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- aider x gpt-5.4: not run, not run in this column
- aider x gpt-5.4-mini: not run, not run in this column
- aider x gpt-5.5: not run, not run in this column
- aider x gpt-5.6-luna: not run, not run in this column
- aider x gpt-5.6-sol: not run, not run in this column
- aider x gpt-5.6-terra: not run, not run in this column
- aider x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cline x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cline x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-5.2: not run, not run in this column
- goose x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-5.4: not run, not run in this column
- goose x gpt-5.4-mini: not run, not run in this column
- goose x gpt-5.5: not run, not run in this column
- goose x gpt-5.6-luna: not run, not run in this column
- goose x gpt-5.6-sol: not run, not run in this column
- goose x gpt-5.6-terra: not run, not run in this column
- goose x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-6-luna: not run, not run in this column
- goose x gpt-6-sol: not run, not run in this column
- kimi x gpt-5.2: not run, not run in this column
- kimi x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- kimi x gpt-5.4: not run, not run in this column
- kimi x gpt-5.4-mini: not run, not run in this column
- kimi x gpt-5.5: not run, not run in this column
- kimi x gpt-5.6-luna: not run, not run in this column
- kimi x gpt-5.6-sol: not run, not run in this column
- kimi x gpt-5.6-terra: not run, not run in this column
- kimi x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- omp x gpt-5.2: not run, not run in this column
- omp x gpt-5.3-codex: not run, not run in this column
- omp x gpt-5.4: not run, not run in this column
- omp x gpt-5.4-mini: not run, not run in this column
- omp x gpt-5.5: not run, not run in this column
- omp x gpt-5.6-luna: not run, not run in this column
- omp x gpt-5.6-sol: not run, not run in this column
- omp x gpt-5.6-terra: not run, not run in this column
- openhands x gpt-5.2: not run, not run in this column
- openhands x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- openhands x gpt-5.4: not run, not run in this column
- openhands x gpt-5.4-mini: not run, not run in this column
- openhands x gpt-5.5: not run, not run in this column
- openhands x gpt-5.6-luna: not run, not run in this column
- openhands x gpt-5.6-sol: not run, not run in this column
- openhands x gpt-5.6-terra: not run, not run in this column
- openhands x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- qwen x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- qwen x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only

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

Not run in this column, 29 pairs the provider serves that the harness did not run, with the reason:

- cline x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cline x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cline x gpt-6-luna: not run, not run in this column
- cline x gpt-6-sol: not run, not run in this column
- cline x gpt-6.1-sol: not run, not run in this column
- codex x gpt-6-astra: not run, not run in this column
- codex x gpt-6-luna: not run, not run in this column
- codex x gpt-6-sol: not run, not run in this column
- codex x gpt-6.1-sol: not run, not run in this column
- dsh x gpt-6-astra: not run, not run in this column
- dsh x gpt-6-luna: not run, not run in this column
- dsh x gpt-6-sol: not run, not run in this column
- dsh x gpt-6.1-sol: not run, not run in this column
- hermes x gpt-6-astra: not run, not run in this column
- hermes x gpt-6-luna: not run, not run in this column
- hermes x gpt-6-sol: not run, not run in this column
- hermes x gpt-6.1-sol: not run, not run in this column
- opencode x gpt-6-astra: not run, not run in this column
- opencode x gpt-6-luna: not run, not run in this column
- opencode x gpt-6-sol: not run, not run in this column
- opencode x gpt-6.1-sol: not run, not run in this column
- pi x gpt-6-astra: not run, not run in this column
- pi x gpt-6-luna: not run, not run in this column
- pi x gpt-6-sol: not run, not run in this column
- pi x gpt-6.1-sol: not run, not run in this column
- qwen x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- qwen x gpt-6-luna: not run, not run in this column
- qwen x gpt-6-sol: not run, not run in this column
- qwen x gpt-6.1-sol: not run, not run in this column

## Provider: cheetahclaws-tokenrouter

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| cheetahclaws | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| cheetahclaws | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as gpt-5.4-2026-03-05 (the provider's alias of the same model) |
| cheetahclaws | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Custom OpenAI Chat, My TokenRouter | served as gpt-5.4-mini-2026-03-17 (the provider's alias of the same model) |

3 pairs, 15 of 15 scenario runs passed.

## Provider: codex-azure-e2

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| codex | gpt-5.2 | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| codex | gpt-5.3-codex | pass | pass | n/a | pass | pass | Azure OpenAI E2 |  |
| codex | gpt-5.4 | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| codex | gpt-5.4-mini | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| codex | gpt-5.5 | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| codex | gpt-5.6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 | retested once; first try: recycle answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in |
| codex | gpt-5.6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| codex | gpt-5.6-terra | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| codex | gpt-6-astra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 |  |

9 pairs, 44 of 44 scenario runs passed.

Not run in this column, 3 pairs the provider serves that the harness did not run, with the reason:

- codex x gpt-6-luna: not run, not run in this column
- codex x gpt-6-sol: not run, not run in this column
- codex x gpt-6.1-sol: not run, not run in this column

## Provider: codex-openai

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| codex | gpt-5.2 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| codex | gpt-5.3-codex | pass | pass | n/a | pass | pass | OpenAI |  |
| codex | gpt-5.4 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| codex | gpt-5.4-mini | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| codex | gpt-5.5 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| codex | gpt-5.6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| codex | gpt-5.6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| codex | gpt-5.6-terra | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| codex | gpt-6-astra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |

9 pairs, 44 of 44 scenario runs passed.

Not run in this column, 3 pairs the provider serves that the harness did not run, with the reason:

- codex x gpt-6-luna: not run, not run in this column
- codex x gpt-6-sol: not run, not run in this column
- codex x gpt-6.1-sol: not run, not run in this column

## Provider: codex-openrouter

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| codex | gpt-5.2 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| codex | gpt-5.3-codex | pass | pass | n/a | pass | pass | OpenRouter |  |
| codex | gpt-5.4 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| codex | gpt-5.4-mini | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| codex | gpt-5.5 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| codex | gpt-5.6-luna | pass | pass | pass (gpt-6-astra) | pass | FAIL | OpenRouter | recycle: answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in my very first message of this task? Reply with just that wo ; retested once; first try: recycle answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in |
| codex | gpt-5.6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| codex | gpt-5.6-terra | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| codex | gpt-6-astra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |

9 pairs, 43 of 44 scenario runs passed.

Not run in this column, 57 pairs the provider serves that the harness did not run, with the reason:

- codex x claude-fable-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-fable-5-1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-haiku-4.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-haiku-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-4.7: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-4.8: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-sonnet-4.6: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-sonnet-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-sonnet-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x deepseek-v4-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x deepseek-v4-pro: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x deepseek-v4.1-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3-flash-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.1-flash-lite: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.1-pro-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.5-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.5-flash-lite: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.6-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.8-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x glm-5.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x glm-5.3-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gpt-6-luna: not run, not run in this column
- codex x gpt-6-sol: not run, not run in this column
- codex x gpt-6.1-sol: not run, not run in this column
- codex x grok-4.20: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-4.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-4.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-4.6: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-build-0.1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x hunyuan-4-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x kimi-k2.7-code: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x kimi-k3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x llama-3.3-70b: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x llama-4-maverick: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x mistral-medium-3.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x muse-glimmer-30b: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x muse-spark-1.1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x muse-spark-1.2: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x muse-spark-1.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x nemotron-3-super: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x nemotron-3.5-lightning: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.7-max: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.7-plus: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.8-27b: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.8-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.8-max: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x step-3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)

## Provider: codex-tokenrouter

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| codex | gpt-5.2 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| codex | gpt-5.3-codex | pass | pass | n/a | pass | pass | My TokenRouter |  |
| codex | gpt-5.4 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| codex | gpt-5.4-mini | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| codex | gpt-5.5 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| codex | gpt-5.6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| codex | gpt-5.6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| codex | gpt-5.6-terra | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| codex | gpt-6-astra | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |

9 pairs, 44 of 44 scenario runs passed.

Not run in this column, 41 pairs the provider serves that the harness did not run, with the reason:

- codex x claude-fable-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-fable-5-1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-haiku-4.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-4.7: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-4.8: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-sonnet-4.6: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-sonnet-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-sonnet-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x deepseek-v4-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x deepseek-v4-pro: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x deepseek-v4.1-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3-flash-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.1-pro-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.5-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.5-flash-lite: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.6-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.8-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x glm-5.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x glm-5.3-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gpt-6-luna: not run, not run in this column
- codex x gpt-6-sol: not run, not run in this column
- codex x gpt-6.1-sol: not run, not run in this column
- codex x grok-4.20: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-4.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-4.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-4.6: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-build-0.1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x hunyuan-4-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x kimi-k2.7-code: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x kimi-k3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x mistral-medium-3.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x nemotron-3-super: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x nemotron-3.5-lightning: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.7-max: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.7-plus: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.8-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.8-max: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x step-3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)

## Provider: codex-vercel

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| codex | gpt-5.2 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| codex | gpt-5.3-codex | pass | pass | n/a | pass | pass | Vercel AI Gateway |  |
| codex | gpt-5.4 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| codex | gpt-5.4-mini | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| codex | gpt-5.5 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| codex | gpt-5.6-luna | pass | pass | pass (gpt-6-astra) | pass | FAIL | Vercel AI Gateway | recycle: answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in my very first message of this task? Reply with just that wo ; retested once; first try: recycle answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in |
| codex | gpt-5.6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| codex | gpt-5.6-terra | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| codex | gpt-6-astra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |

9 pairs, 43 of 44 scenario runs passed.

Not run in this column, 53 pairs the provider serves that the harness did not run, with the reason:

- codex x claude-fable-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-fable-5-1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-haiku-4.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-haiku-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-4.7: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-4.8: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-sonnet-4.6: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-sonnet-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-sonnet-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x deepseek-v4-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x deepseek-v4-pro: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x deepseek-v4.1-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3-flash-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.1-flash-lite: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.1-pro-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.5-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.5-flash-lite: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.6-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.8-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x glm-5.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x glm-5.3-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gpt-6-luna: not run, not run in this column
- codex x gpt-6-sol: not run, not run in this column
- codex x gpt-6.1-sol: not run, not run in this column
- codex x grok-4.20: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-4.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-4.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-4.6: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-build-0.1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x hunyuan-4-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x kimi-k2.7-code: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x kimi-k3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x mistral-medium-3.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x muse-glimmer-30b: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x muse-spark-1.1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x muse-spark-1.2: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x muse-spark-1.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x nemotron-3-super: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x nemotron-3.5-lightning: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.7-max: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.7-plus: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.8-27b: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.8-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.8-max: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x step-3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)

## Provider: dsh-anthropic

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| dsh | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| dsh | claude-fable-5-1 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| dsh | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| dsh | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| dsh | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| dsh | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic |  |
| dsh | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| dsh | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |

8 pairs, 40 of 40 scenario runs passed.

Not run in this column, 3 pairs the provider serves that the harness did not run, with the reason:

- dsh x claude-haiku-5.5: not run, not run in this column
- dsh x claude-opus-5.5: not run, not run in this column
- dsh x claude-sonnet-5.5: not run, not run in this column

## Provider: dsh-azure-e2

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| dsh | gpt-5.2 | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| dsh | gpt-5.3-codex | pass | pass | n/a | pass | pass | Azure OpenAI E2 |  |
| dsh | gpt-5.4 | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| dsh | gpt-5.4-mini | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| dsh | gpt-5.5 | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| dsh | gpt-5.6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| dsh | gpt-5.6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| dsh | gpt-5.6-terra | pass | pass | pass (gpt-6-astra) | pass | pass | Azure OpenAI E2 |  |
| dsh | gpt-6-astra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 |  |

9 pairs, 44 of 44 scenario runs passed.

Not run in this column, 3 pairs the provider serves that the harness did not run, with the reason:

- dsh x gpt-6-luna: not run, not run in this column
- dsh x gpt-6-sol: not run, not run in this column
- dsh x gpt-6.1-sol: not run, not run in this column

## Provider: dsh-google

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| dsh | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |

8 pairs, 40 of 40 scenario runs passed.

## Provider: dsh-openai

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| dsh | gpt-5.2 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| dsh | gpt-5.3-codex | pass | pass | n/a | pass | pass | OpenAI |  |
| dsh | gpt-5.4 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| dsh | gpt-5.4-mini | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| dsh | gpt-5.5 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| dsh | gpt-5.6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| dsh | gpt-5.6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| dsh | gpt-5.6-terra | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| dsh | gpt-6-astra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |

9 pairs, 44 of 44 scenario runs passed.

Not run in this column, 3 pairs the provider serves that the harness did not run, with the reason:

- dsh x gpt-6-luna: not run, not run in this column
- dsh x gpt-6-sol: not run, not run in this column
- dsh x gpt-6.1-sol: not run, not run in this column

## Provider: dsh-openrouter

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| dsh | claude-fable-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | claude-fable-5-1 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | claude-haiku-4.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | claude-opus-4.7 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | claude-opus-4.8 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | claude-opus-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | claude-sonnet-4.6 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | claude-sonnet-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | deepseek-v4-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | deepseek-v4-pro | pass | pass | pass (deepseek-v4-flash) | pass | pass | OpenRouter |  |
| dsh | deepseek-v4.1-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gemini-3-flash-preview | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gemini-3.1-flash-lite | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gemini-3.1-pro-preview | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gemini-3.5-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gemini-3.5-flash-lite | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gemini-3.6-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gemini-3.7-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gemini-3.8-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | glm-5.3 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | glm-5.3-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gpt-5.2 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gpt-5.3-codex | pass | pass | n/a | pass | pass | OpenRouter |  |
| dsh | gpt-5.4 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gpt-5.4-mini | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gpt-5.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gpt-5.6-luna | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gpt-5.6-sol | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gpt-5.6-terra | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | gpt-6-astra | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | grok-4.20 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| dsh | grok-4.3 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| dsh | grok-4.5 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| dsh | grok-4.6 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| dsh | grok-build-0.1 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| dsh | hunyuan-4-preview | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | kimi-k2.7-code | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | kimi-k3 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | llama-3.3-70b | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| dsh | llama-4-maverick | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| dsh | mistral-medium-3.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | muse-glimmer-30b | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| dsh | muse-spark-1.1 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| dsh | muse-spark-1.2 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| dsh | muse-spark-1.3 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| dsh | nemotron-3-super | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | nemotron-3.5-lightning | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | qwen3.7-max | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | qwen3.7-plus | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | qwen3.8-27b | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | qwen3.8-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | qwen3.8-max | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | step-3.7-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |

53 pairs, 264 of 264 scenario runs passed.

Not run in this column, 13 pairs the provider serves that the harness did not run, with the reason:

- dsh x claude-haiku-5.5: not run, not run in this column
- dsh x claude-opus-5.5: not run, not run in this column
- dsh x claude-sonnet-5.5: not run, not run in this column
- dsh x gpt-6-luna: not run, not run in this column
- dsh x gpt-6-sol: not run, not run in this column
- dsh x gpt-6.1-sol: not run, not run in this column
- dsh x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)

## Provider: dsh-tokenrouter

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| dsh | claude-fable-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | claude-fable-5-1 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | claude-haiku-4.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | claude-opus-4.7 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | claude-opus-4.8 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | claude-opus-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | claude-sonnet-4.6 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | claude-sonnet-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | deepseek-v4-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | deepseek-v4-pro | pass | pass | pass (deepseek-v4-flash) | pass | pass | My TokenRouter |  |
| dsh | deepseek-v4.1-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gemini-3-flash-preview | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gemini-3.1-pro-preview | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gemini-3.5-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gemini-3.5-flash-lite | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gemini-3.6-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gemini-3.7-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gemini-3.8-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | glm-5.3 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | glm-5.3-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gpt-5.2 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gpt-5.3-codex | pass | pass | n/a | pass | pass | My TokenRouter |  |
| dsh | gpt-5.4 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gpt-5.4-mini | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gpt-5.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gpt-5.6-luna | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gpt-5.6-sol | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gpt-5.6-terra | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | gpt-6-astra | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | grok-4.20 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| dsh | grok-4.3 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| dsh | grok-4.5 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| dsh | grok-4.6 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| dsh | grok-build-0.1 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| dsh | hunyuan-4-preview | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | kimi-k2.7-code | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | kimi-k3 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | mistral-medium-3.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | nemotron-3-super | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | nemotron-3.5-lightning | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | qwen3.7-max | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | qwen3.7-plus | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | qwen3.8-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | qwen3.8-max | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |
| dsh | step-3.7-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | My TokenRouter |  |

45 pairs, 224 of 224 scenario runs passed.

Not run in this column, 5 pairs the provider serves that the harness did not run, with the reason:

- dsh x claude-opus-5.5: not run, not run in this column
- dsh x claude-sonnet-5.5: not run, not run in this column
- dsh x gpt-6-luna: not run, not run in this column
- dsh x gpt-6-sol: not run, not run in this column
- dsh x gpt-6.1-sol: not run, not run in this column

## Provider: dsh-vercel

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| dsh | claude-fable-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | claude-fable-5-1 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | claude-haiku-4.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | claude-opus-4.7 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | claude-opus-4.8 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | claude-opus-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | claude-sonnet-4.6 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | claude-sonnet-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | deepseek-v4-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | deepseek-v4-pro | pass | pass | pass (deepseek-v4-flash) | pass | pass | Vercel AI Gateway |  |
| dsh | deepseek-v4.1-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3-flash-preview | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.1-flash-lite | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.1-pro-preview | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.5-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.5-flash-lite | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.6-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.7-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.8-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | glm-5.3 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | glm-5.3-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gpt-5.2 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gpt-5.3-codex | pass | pass | n/a | pass | pass | Vercel AI Gateway |  |
| dsh | gpt-5.4 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gpt-5.4-mini | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gpt-5.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gpt-5.6-luna | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gpt-5.6-sol | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gpt-5.6-terra | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | gpt-6-astra | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | grok-4.1-fast | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| dsh | grok-4.20 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| dsh | grok-4.3 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| dsh | grok-4.5 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| dsh | grok-4.6 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| dsh | grok-build-0.1 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| dsh | hunyuan-4-preview | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | kimi-k2.7-code | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | kimi-k3 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | llama-3.3-70b | FAIL | n/a | n/a | n/a | n/a | Vercel AI Gateway | first: The turn failed: 400: {"message":"undefined: The maximum tokens you requested exceeds the model limit of 8192. Try again with a maximum toke |
| dsh | llama-4-maverick | FAIL | n/a | n/a | n/a | n/a | Vercel AI Gateway | first: The turn failed: 405: {"message":"Tool calling is not supported for model: meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8","type":"AI_API |
| dsh | llama-4-scout | pass | pass | pass (gpt-6-astra) | FAIL | FAIL | Vercel AI Gateway | artifact: The turn failed: model "meta/llama-4-scout" returned a completed response with no content ; recycle: answered without M1-llama-4-scout: ", "Create a file named hello-dsh.txt containing exactly the word HELLO, then reply DONE."] JSON {"type": |
| dsh | mistral-medium-3.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | muse-glimmer-30b | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| dsh | muse-spark-1.1 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| dsh | muse-spark-1.2 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| dsh | muse-spark-1.3 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| dsh | nemotron-3-super | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | nemotron-3.5-lightning | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | qwen3.7-max | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | qwen3.7-plus | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | qwen3.8-27b | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | qwen3.8-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | qwen3.8-max | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |
| dsh | step-3.7-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | Vercel AI Gateway |  |

55 pairs, 262 of 266 scenario runs passed.

Not run in this column, 11 pairs the provider serves that the harness did not run, with the reason:

- dsh x claude-haiku-5.5: not run, not run in this column
- dsh x claude-opus-5.5: not run, not run in this column
- dsh x claude-sonnet-5.5: not run, not run in this column
- dsh x gpt-6-luna: not run, not run in this column
- dsh x gpt-6-sol: not run, not run in this column
- dsh x gpt-6.1-sol: not run, not run in this column
- dsh x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)

## Provider: gemini-cli

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| gemini | gemini-3-flash-preview | pass | pass | pass (gemini-3.5-flash) | pass | pass | Google AI Studio |  |
| gemini | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.5-flash) | pass | pass | Google AI Studio |  |
| gemini | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.5-flash) | pass | pass | Google AI Studio |  |
| gemini | gemini-3.5-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| gemini | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.5-flash) | pass | pass | Google AI Studio |  |
| gemini | gemini-3.6-flash | pass | pass | pass (gemini-3.5-flash) | pass | pass | Google AI Studio |  |
| gemini | gemini-3.7-flash | pass | pass | pass (gemini-3.5-flash) | pass | pass | Google AI Studio |  |
| gemini | gemini-3.8-flash | pass | pass | pass (gemini-3.5-flash) | pass | pass | Google AI Studio |  |

8 pairs, 40 of 40 scenario runs passed.

## Provider: gemini-google

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| cline | gemini-3-flash-preview | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| cline | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| cline | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| cline | gemini-3.5-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| cline | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| cline | gemini-3.7-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| cline | gemini-3.8-flash | pass | pass | pass (gemini-3.7-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| dsh | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| hermes | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| hermes | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| hermes | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| hermes | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| hermes | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio | retested once; first try: followup [{"connection": "integration:Google AI Studio", "status": "failed", "error": "\u |
| hermes | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| hermes | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| hermes | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| opencode | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio | opencode rows re-run on 0.13.20 (opencode rides the loopback relay, #97) ; retested once; first try: artifact [{"connection": "integration:Google AI Studio", "status": "failed", "error": "Ba |
| opencode | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio | opencode rows re-run on 0.13.20 (opencode rides the loopback relay, #97) ; retested once; first try: artifact [{"connection": "integration:Google AI Studio", "status": "failed", "error": "Ba |
| opencode | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio | opencode rows re-run on 0.13.20 (opencode rides the loopback relay, #97) ; retested once; first try: artifact [{"connection": "integration:Google AI Studio", "status": "failed", "error": "Ba |
| opencode | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio | opencode rows re-run on 0.13.20 (opencode rides the loopback relay, #97) ; retested once; first try: artifact [{"connection": "integration:Google AI Studio", "status": "failed", "error": "Ba |
| opencode | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio | opencode rows re-run on 0.13.20 (opencode rides the loopback relay, #97) ; retested once; first try: artifact [{"connection": "integration:Google AI Studio", "status": "failed", "error": "Ba |
| opencode | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio | opencode rows re-run on 0.13.20 (opencode rides the loopback relay, #97) ; retested once; first try: artifact [{"connection": "integration:Google AI Studio", "status": "failed", "error": "Ba |
| opencode | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio | opencode rows re-run on 0.13.20 (opencode rides the loopback relay, #97) ; retested once; first try: artifact [{"connection": "integration:Google AI Studio", "status": "failed", "error": "Ba |
| opencode | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio | opencode rows re-run on 0.13.20 (opencode rides the loopback relay, #97) ; retested once; first try: artifact [{"connection": "integration:Google AI Studio", "status": "failed", "error": "Ba |
| pi | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| pi | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| pi | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| pi | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| pi | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| pi | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| pi | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| pi | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| qwen | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| qwen | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| qwen | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| qwen | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| qwen | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| qwen | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| qwen | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| qwen | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |

47 pairs, 235 of 235 scenario runs passed.

Not run in this column, 1 pairs the provider serves that the harness did not run, with the reason:

- cline x gemini-3.6-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)

## Provider: gemini-openrouter

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| cline | gemini-3-flash-preview | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| cline | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| cline | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| cline | gemini-3.5-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| cline | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| cline | gemini-3.7-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| cline | gemini-3.8-flash | pass | pass | pass (gemini-3.7-flash) | pass | pass | OpenRouter |  |
| dsh | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| dsh | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| dsh | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| dsh | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| dsh | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| dsh | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| dsh | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| dsh | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| hermes | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| hermes | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| hermes | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| hermes | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| hermes | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| hermes | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| hermes | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| hermes | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| opencode | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| opencode | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| opencode | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| opencode | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| opencode | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| opencode | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| opencode | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| opencode | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| pi | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| pi | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| pi | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| pi | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| pi | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| pi | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| pi | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| pi | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| qwen | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| qwen | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| qwen | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| qwen | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| qwen | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| qwen | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | OpenRouter |  |
| qwen | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |
| qwen | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | OpenRouter |  |

47 pairs, 235 of 235 scenario runs passed.

Not run in this column, 349 pairs the provider serves that the harness did not run, with the reason:

- cline x claude-fable-5: not run, not run in this column
- cline x claude-fable-5-1: not run, not run in this column
- cline x claude-haiku-4.5: not run, not run in this column
- cline x claude-haiku-5.5: not run, not run in this column
- cline x claude-opus-4.7: not run, not run in this column
- cline x claude-opus-4.8: not run, not run in this column
- cline x claude-opus-5: not run, not run in this column
- cline x claude-opus-5.5: not run, not run in this column
- cline x claude-sonnet-4.6: not run, not run in this column
- cline x claude-sonnet-5: not run, not run in this column
- cline x claude-sonnet-5.5: not run, not run in this column
- cline x deepseek-v4-flash: not run, not run in this column
- cline x deepseek-v4-pro: not run, not run in this column
- cline x deepseek-v4.1-flash: not run, not run in this column
- cline x gemini-3.6-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x glm-5.3: not run, not run in this column
- cline x glm-5.3-flash: not run, not run in this column
- cline x gpt-5.2: not run, not run in this column
- cline x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cline x gpt-5.4: not run, not run in this column
- cline x gpt-5.4-mini: not run, not run in this column
- cline x gpt-5.5: not run, not run in this column
- cline x gpt-5.6-luna: not run, not run in this column
- cline x gpt-5.6-sol: not run, not run in this column
- cline x gpt-5.6-terra: not run, not run in this column
- cline x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cline x gpt-6-luna: not run, not run in this column
- cline x gpt-6-sol: not run, not run in this column
- cline x gpt-6.1-sol: not run, not run in this column
- cline x grok-4.20: not run, not run in this column
- cline x grok-4.3: not run, not run in this column
- cline x grok-4.5: not run, not run in this column
- cline x grok-4.6: not run, not run in this column
- cline x grok-build-0.1: not run, not run in this column
- cline x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x hunyuan-4-preview: not run, not run in this column
- cline x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x kimi-k2.7-code: not run, not run in this column
- cline x kimi-k3: not run, not run in this column
- cline x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x llama-3.3-70b: not run, not run in this column
- cline x llama-4-maverick: not run, not run in this column
- cline x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x mistral-medium-3.5: not run, not run in this column
- cline x muse-glimmer-30b: not run, not run in this column
- cline x muse-spark-1.1: not run, not run in this column
- cline x muse-spark-1.2: not run, not run in this column
- cline x muse-spark-1.3: not run, not run in this column
- cline x nemotron-3-super: not run, not run in this column
- cline x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x nemotron-3.5-lightning: not run, not run in this column
- cline x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x qwen3.7-max: not run, not run in this column
- cline x qwen3.7-plus: not run, not run in this column
- cline x qwen3.8-27b: not run, not run in this column
- cline x qwen3.8-flash: not run, not run in this column
- cline x qwen3.8-max: not run, not run in this column
- cline x step-3.7-flash: not run, not run in this column
- dsh x claude-fable-5: not run, not run in this column
- dsh x claude-fable-5-1: not run, not run in this column
- dsh x claude-haiku-4.5: not run, not run in this column
- dsh x claude-haiku-5.5: not run, not run in this column
- dsh x claude-opus-4.7: not run, not run in this column
- dsh x claude-opus-4.8: not run, not run in this column
- dsh x claude-opus-5: not run, not run in this column
- dsh x claude-opus-5.5: not run, not run in this column
- dsh x claude-sonnet-4.6: not run, not run in this column
- dsh x claude-sonnet-5: not run, not run in this column
- dsh x claude-sonnet-5.5: not run, not run in this column
- dsh x deepseek-v4-flash: not run, not run in this column
- dsh x deepseek-v4-pro: not run, not run in this column
- dsh x deepseek-v4.1-flash: not run, not run in this column
- dsh x glm-5.3: not run, not run in this column
- dsh x glm-5.3-flash: not run, not run in this column
- dsh x gpt-5.2: not run, not run in this column
- dsh x gpt-5.3-codex: not run, not run in this column
- dsh x gpt-5.4: not run, not run in this column
- dsh x gpt-5.4-mini: not run, not run in this column
- dsh x gpt-5.5: not run, not run in this column
- dsh x gpt-5.6-luna: not run, not run in this column
- dsh x gpt-5.6-sol: not run, not run in this column
- dsh x gpt-5.6-terra: not run, not run in this column
- dsh x gpt-6-astra: not run, not run in this column
- dsh x gpt-6-luna: not run, not run in this column
- dsh x gpt-6-sol: not run, not run in this column
- dsh x gpt-6.1-sol: not run, not run in this column
- dsh x grok-4.20: not run, not run in this column
- dsh x grok-4.3: not run, not run in this column
- dsh x grok-4.5: not run, not run in this column
- dsh x grok-4.6: not run, not run in this column
- dsh x grok-build-0.1: not run, not run in this column
- dsh x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x hunyuan-4-preview: not run, not run in this column
- dsh x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x kimi-k2.7-code: not run, not run in this column
- dsh x kimi-k3: not run, not run in this column
- dsh x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x llama-3.3-70b: not run, not run in this column
- dsh x llama-4-maverick: not run, not run in this column
- dsh x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x mistral-medium-3.5: not run, not run in this column
- dsh x muse-glimmer-30b: not run, not run in this column
- dsh x muse-spark-1.1: not run, not run in this column
- dsh x muse-spark-1.2: not run, not run in this column
- dsh x muse-spark-1.3: not run, not run in this column
- dsh x nemotron-3-super: not run, not run in this column
- dsh x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x nemotron-3.5-lightning: not run, not run in this column
- dsh x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x qwen3.7-max: not run, not run in this column
- dsh x qwen3.7-plus: not run, not run in this column
- dsh x qwen3.8-27b: not run, not run in this column
- dsh x qwen3.8-flash: not run, not run in this column
- dsh x qwen3.8-max: not run, not run in this column
- dsh x step-3.7-flash: not run, not run in this column
- hermes x claude-fable-5: not run, not run in this column
- hermes x claude-fable-5-1: not run, not run in this column
- hermes x claude-haiku-4.5: not run, not run in this column
- hermes x claude-haiku-5.5: not run, not run in this column
- hermes x claude-opus-4.7: not run, not run in this column
- hermes x claude-opus-4.8: not run, not run in this column
- hermes x claude-opus-5: not run, not run in this column
- hermes x claude-opus-5.5: not run, not run in this column
- hermes x claude-sonnet-4.6: not run, not run in this column
- hermes x claude-sonnet-5: not run, not run in this column
- hermes x claude-sonnet-5.5: not run, not run in this column
- hermes x deepseek-v4-flash: not run, not run in this column
- hermes x deepseek-v4-pro: not run, not run in this column
- hermes x deepseek-v4.1-flash: not run, not run in this column
- hermes x glm-5.3: not run, not run in this column
- hermes x glm-5.3-flash: not run, not run in this column
- hermes x gpt-5.2: not run, not run in this column
- hermes x gpt-5.3-codex: not run, not run in this column
- hermes x gpt-5.4: not run, not run in this column
- hermes x gpt-5.4-mini: not run, not run in this column
- hermes x gpt-5.5: not run, not run in this column
- hermes x gpt-5.6-luna: not run, not run in this column
- hermes x gpt-5.6-sol: not run, not run in this column
- hermes x gpt-5.6-terra: not run, not run in this column
- hermes x gpt-6-astra: not run, not run in this column
- hermes x gpt-6-luna: not run, not run in this column
- hermes x gpt-6-sol: not run, not run in this column
- hermes x gpt-6.1-sol: not run, not run in this column
- hermes x grok-4.20: not run, not run in this column
- hermes x grok-4.3: not run, not run in this column
- hermes x grok-4.5: not run, not run in this column
- hermes x grok-4.6: not run, not run in this column
- hermes x grok-build-0.1: not run, not run in this column
- hermes x hunyuan-3: not run, not run in this column
- hermes x hunyuan-4-preview: not run, not run in this column
- hermes x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- hermes x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- hermes x kimi-k2.7-code: not run, not run in this column
- hermes x kimi-k3: not run, not run in this column
- hermes x ling-3.0-flash: not run, not run in this column
- hermes x llama-3.3-70b: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- hermes x llama-4-maverick: not run, not run in this column
- hermes x minimax-m3: not run, not run in this column
- hermes x mistral-medium-3.5: not run, not run in this column
- hermes x muse-glimmer-30b: not run, not run in this column
- hermes x muse-spark-1.1: not run, not run in this column
- hermes x muse-spark-1.2: not run, not run in this column
- hermes x muse-spark-1.3: not run, not run in this column
- hermes x nemotron-3-super: not run, not run in this column
- hermes x nemotron-3-ultra: not run, not run in this column
- hermes x nemotron-3.5-lightning: not run, not run in this column
- hermes x qwen3.7-flash: not run, not run in this column
- hermes x qwen3.7-max: not run, not run in this column
- hermes x qwen3.7-plus: not run, not run in this column
- hermes x qwen3.8-27b: not run, not run in this column
- hermes x qwen3.8-flash: not run, not run in this column
- hermes x qwen3.8-max: not run, not run in this column
- hermes x step-3.7-flash: not run, not run in this column
- opencode x claude-fable-5: not run, not run in this column
- opencode x claude-fable-5-1: not run, not run in this column
- opencode x claude-haiku-4.5: not run, not run in this column
- opencode x claude-haiku-5.5: not run, not run in this column
- opencode x claude-opus-4.7: not run, not run in this column
- opencode x claude-opus-4.8: not run, not run in this column
- opencode x claude-opus-5: not run, not run in this column
- opencode x claude-opus-5.5: not run, not run in this column
- opencode x claude-sonnet-4.6: not run, not run in this column
- opencode x claude-sonnet-5: not run, not run in this column
- opencode x claude-sonnet-5.5: not run, not run in this column
- opencode x deepseek-v4-flash: not run, not run in this column
- opencode x deepseek-v4-pro: not run, not run in this column
- opencode x deepseek-v4.1-flash: not run, not run in this column
- opencode x glm-5.3: not run, not run in this column
- opencode x glm-5.3-flash: not run, not run in this column
- opencode x gpt-5.2: not run, not run in this column
- opencode x gpt-5.3-codex: not run, not run in this column
- opencode x gpt-5.4: not run, not run in this column
- opencode x gpt-5.4-mini: not run, not run in this column
- opencode x gpt-5.5: not run, not run in this column
- opencode x gpt-5.6-luna: not run, not run in this column
- opencode x gpt-5.6-sol: not run, not run in this column
- opencode x gpt-5.6-terra: not run, not run in this column
- opencode x gpt-6-astra: not run, not run in this column
- opencode x gpt-6-luna: not run, not run in this column
- opencode x gpt-6-sol: not run, not run in this column
- opencode x gpt-6.1-sol: not run, not run in this column
- opencode x grok-4.20: not run, not run in this column
- opencode x grok-4.3: not run, not run in this column
- opencode x grok-4.5: not run, not run in this column
- opencode x grok-4.6: not run, not run in this column
- opencode x grok-build-0.1: not run, not run in this column
- opencode x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x hunyuan-4-preview: not run, not run in this column
- opencode x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x kimi-k2.7-code: not run, not run in this column
- opencode x kimi-k3: not run, not run in this column
- opencode x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x llama-3.3-70b: not run, not run in this column
- opencode x llama-4-maverick: not run, not run in this column
- opencode x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x mistral-medium-3.5: not run, not run in this column
- opencode x muse-glimmer-30b: not run, not run in this column
- opencode x muse-spark-1.1: not run, not run in this column
- opencode x muse-spark-1.2: not run, not run in this column
- opencode x muse-spark-1.3: not run, not run in this column
- opencode x nemotron-3-super: not run, not run in this column
- opencode x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x nemotron-3.5-lightning: not run, not run in this column
- opencode x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x qwen3.7-max: not run, not run in this column
- opencode x qwen3.7-plus: not run, not run in this column
- opencode x qwen3.8-27b: not run, not run in this column
- opencode x qwen3.8-flash: not run, not run in this column
- opencode x qwen3.8-max: not run, not run in this column
- opencode x step-3.7-flash: not run, not run in this column
- pi x claude-fable-5: not run, not run in this column
- pi x claude-fable-5-1: not run, not run in this column
- pi x claude-haiku-4.5: not run, not run in this column
- pi x claude-haiku-5.5: not run, not run in this column
- pi x claude-opus-4.7: not run, not run in this column
- pi x claude-opus-4.8: not run, not run in this column
- pi x claude-opus-5: not run, not run in this column
- pi x claude-opus-5.5: not run, not run in this column
- pi x claude-sonnet-4.6: not run, not run in this column
- pi x claude-sonnet-5: not run, not run in this column
- pi x claude-sonnet-5.5: not run, not run in this column
- pi x deepseek-v4-flash: not run, not run in this column
- pi x deepseek-v4-pro: not run, not run in this column
- pi x deepseek-v4.1-flash: not run, not run in this column
- pi x glm-5.3: not run, not run in this column
- pi x glm-5.3-flash: not run, not run in this column
- pi x gpt-5.2: not run, not run in this column
- pi x gpt-5.3-codex: not run, not run in this column
- pi x gpt-5.4: not run, not run in this column
- pi x gpt-5.4-mini: not run, not run in this column
- pi x gpt-5.5: not run, not run in this column
- pi x gpt-5.6-luna: not run, not run in this column
- pi x gpt-5.6-sol: not run, not run in this column
- pi x gpt-5.6-terra: not run, not run in this column
- pi x gpt-6-astra: not run, not run in this column
- pi x gpt-6-luna: not run, not run in this column
- pi x gpt-6-sol: not run, not run in this column
- pi x gpt-6.1-sol: not run, not run in this column
- pi x grok-4.20: not run, not run in this column
- pi x grok-4.3: not run, not run in this column
- pi x grok-4.5: not run, not run in this column
- pi x grok-4.6: not run, not run in this column
- pi x grok-build-0.1: not run, not run in this column
- pi x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x hunyuan-4-preview: not run, not run in this column
- pi x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x kimi-k2.7-code: not run, not run in this column
- pi x kimi-k3: not run, not run in this column
- pi x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x llama-3.3-70b: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x llama-4-maverick: not run, not run in this column
- pi x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x mistral-medium-3.5: not run, not run in this column
- pi x muse-glimmer-30b: not run, not run in this column
- pi x muse-spark-1.1: not run, not run in this column
- pi x muse-spark-1.2: not run, not run in this column
- pi x muse-spark-1.3: not run, not run in this column
- pi x nemotron-3-super: not run, not run in this column
- pi x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x nemotron-3.5-lightning: not run, not run in this column
- pi x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x qwen3.7-max: not run, not run in this column
- pi x qwen3.7-plus: not run, not run in this column
- pi x qwen3.8-27b: not run, not run in this column
- pi x qwen3.8-flash: not run, not run in this column
- pi x qwen3.8-max: not run, not run in this column
- pi x step-3.7-flash: not run, not run in this column
- qwen x claude-fable-5: not run, not run in this column
- qwen x claude-fable-5-1: not run, not run in this column
- qwen x claude-haiku-4.5: not run, not run in this column
- qwen x claude-haiku-5.5: not run, not run in this column
- qwen x claude-opus-4.7: not run, not run in this column
- qwen x claude-opus-4.8: not run, not run in this column
- qwen x claude-opus-5: not run, not run in this column
- qwen x claude-opus-5.5: not run, not run in this column
- qwen x claude-sonnet-4.6: not run, not run in this column
- qwen x claude-sonnet-5: not run, not run in this column
- qwen x claude-sonnet-5.5: not run, not run in this column
- qwen x deepseek-v4-flash: not run, not run in this column
- qwen x deepseek-v4-pro: not run, not run in this column
- qwen x deepseek-v4.1-flash: not run, not run in this column
- qwen x glm-5.3: not run, not run in this column
- qwen x glm-5.3-flash: not run, not run in this column
- qwen x gpt-5.2: not run, not run in this column
- qwen x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- qwen x gpt-5.4: not run, not run in this column
- qwen x gpt-5.4-mini: not run, not run in this column
- qwen x gpt-5.5: not run, not run in this column
- qwen x gpt-5.6-luna: not run, not run in this column
- qwen x gpt-5.6-sol: not run, not run in this column
- qwen x gpt-5.6-terra: not run, not run in this column
- qwen x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- qwen x gpt-6-luna: not run, not run in this column
- qwen x gpt-6-sol: not run, not run in this column
- qwen x gpt-6.1-sol: not run, not run in this column
- qwen x grok-4.20: not run, not run in this column
- qwen x grok-4.3: not run, not run in this column
- qwen x grok-4.5: not run, not run in this column
- qwen x grok-4.6: not run, not run in this column
- qwen x grok-build-0.1: not run, not run in this column
- qwen x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x hunyuan-4-preview: not run, not run in this column
- qwen x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x kimi-k2.7-code: not run, not run in this column
- qwen x kimi-k3: not run, not run in this column
- qwen x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x llama-3.3-70b: not run, not run in this column
- qwen x llama-4-maverick: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x mistral-medium-3.5: not run, not run in this column
- qwen x muse-glimmer-30b: not run, not run in this column
- qwen x muse-spark-1.1: not run, not run in this column
- qwen x muse-spark-1.2: not run, not run in this column
- qwen x muse-spark-1.3: not run, not run in this column
- qwen x nemotron-3-super: not run, not run in this column
- qwen x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x nemotron-3.5-lightning: not run, not run in this column
- qwen x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x qwen3.7-max: not run, not run in this column
- qwen x qwen3.7-plus: not run, not run in this column
- qwen x qwen3.8-27b: not run, not run in this column
- qwen x qwen3.8-flash: not run, not run in this column
- qwen x qwen3.8-max: not run, not run in this column
- qwen x step-3.7-flash: not run, not run in this column

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

Not run in this column, 259 pairs the provider serves that the harness did not run, with the reason:

- cline x claude-fable-5: not run, not run in this column
- cline x claude-fable-5-1: not run, not run in this column
- cline x claude-haiku-4.5: not run, not run in this column
- cline x claude-opus-4.7: not run, not run in this column
- cline x claude-opus-4.8: not run, not run in this column
- cline x claude-opus-5: not run, not run in this column
- cline x claude-opus-5.5: not run, not run in this column
- cline x claude-sonnet-4.6: not run, not run in this column
- cline x claude-sonnet-5: not run, not run in this column
- cline x claude-sonnet-5.5: not run, not run in this column
- cline x deepseek-v4-flash: not run, not run in this column
- cline x deepseek-v4-pro: not run, not run in this column
- cline x deepseek-v4.1-flash: not run, not run in this column
- cline x gemini-3.6-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x glm-5.3: not run, not run in this column
- cline x glm-5.3-flash: not run, not run in this column
- cline x gpt-5.2: not run, not run in this column
- cline x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cline x gpt-5.4: not run, not run in this column
- cline x gpt-5.4-mini: not run, not run in this column
- cline x gpt-5.5: not run, not run in this column
- cline x gpt-5.6-luna: not run, not run in this column
- cline x gpt-5.6-sol: not run, not run in this column
- cline x gpt-5.6-terra: not run, not run in this column
- cline x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cline x gpt-6-luna: not run, not run in this column
- cline x gpt-6-sol: not run, not run in this column
- cline x gpt-6.1-sol: not run, not run in this column
- cline x grok-4.20: not run, not run in this column
- cline x grok-4.3: not run, not run in this column
- cline x grok-4.5: not run, not run in this column
- cline x grok-4.6: not run, not run in this column
- cline x grok-build-0.1: not run, not run in this column
- cline x hunyuan-4-preview: not run, not run in this column
- cline x kimi-k2.7-code: not run, not run in this column
- cline x kimi-k3: not run, not run in this column
- cline x mistral-medium-3.5: not run, not run in this column
- cline x nemotron-3-super: not run, not run in this column
- cline x nemotron-3.5-lightning: not run, not run in this column
- cline x qwen3.7-max: not run, not run in this column
- cline x qwen3.7-plus: not run, not run in this column
- cline x qwen3.8-flash: not run, not run in this column
- cline x qwen3.8-max: not run, not run in this column
- cline x step-3.7-flash: not run, not run in this column
- dsh x claude-fable-5: not run, not run in this column
- dsh x claude-fable-5-1: not run, not run in this column
- dsh x claude-haiku-4.5: not run, not run in this column
- dsh x claude-opus-4.7: not run, not run in this column
- dsh x claude-opus-4.8: not run, not run in this column
- dsh x claude-opus-5: not run, not run in this column
- dsh x claude-opus-5.5: not run, not run in this column
- dsh x claude-sonnet-4.6: not run, not run in this column
- dsh x claude-sonnet-5: not run, not run in this column
- dsh x claude-sonnet-5.5: not run, not run in this column
- dsh x deepseek-v4-flash: not run, not run in this column
- dsh x deepseek-v4-pro: not run, not run in this column
- dsh x deepseek-v4.1-flash: not run, not run in this column
- dsh x glm-5.3: not run, not run in this column
- dsh x glm-5.3-flash: not run, not run in this column
- dsh x gpt-5.2: not run, not run in this column
- dsh x gpt-5.3-codex: not run, not run in this column
- dsh x gpt-5.4: not run, not run in this column
- dsh x gpt-5.4-mini: not run, not run in this column
- dsh x gpt-5.5: not run, not run in this column
- dsh x gpt-5.6-luna: not run, not run in this column
- dsh x gpt-5.6-sol: not run, not run in this column
- dsh x gpt-5.6-terra: not run, not run in this column
- dsh x gpt-6-astra: not run, not run in this column
- dsh x gpt-6-luna: not run, not run in this column
- dsh x gpt-6-sol: not run, not run in this column
- dsh x gpt-6.1-sol: not run, not run in this column
- dsh x grok-4.20: not run, not run in this column
- dsh x grok-4.3: not run, not run in this column
- dsh x grok-4.5: not run, not run in this column
- dsh x grok-4.6: not run, not run in this column
- dsh x grok-build-0.1: not run, not run in this column
- dsh x hunyuan-4-preview: not run, not run in this column
- dsh x kimi-k2.7-code: not run, not run in this column
- dsh x kimi-k3: not run, not run in this column
- dsh x mistral-medium-3.5: not run, not run in this column
- dsh x nemotron-3-super: not run, not run in this column
- dsh x nemotron-3.5-lightning: not run, not run in this column
- dsh x qwen3.7-max: not run, not run in this column
- dsh x qwen3.7-plus: not run, not run in this column
- dsh x qwen3.8-flash: not run, not run in this column
- dsh x qwen3.8-max: not run, not run in this column
- dsh x step-3.7-flash: not run, not run in this column
- hermes x claude-fable-5: not run, not run in this column
- hermes x claude-fable-5-1: not run, not run in this column
- hermes x claude-haiku-4.5: not run, not run in this column
- hermes x claude-opus-4.7: not run, not run in this column
- hermes x claude-opus-4.8: not run, not run in this column
- hermes x claude-opus-5: not run, not run in this column
- hermes x claude-opus-5.5: not run, not run in this column
- hermes x claude-sonnet-4.6: not run, not run in this column
- hermes x claude-sonnet-5: not run, not run in this column
- hermes x claude-sonnet-5.5: not run, not run in this column
- hermes x deepseek-v4-flash: not run, not run in this column
- hermes x deepseek-v4-pro: not run, not run in this column
- hermes x deepseek-v4.1-flash: not run, not run in this column
- hermes x glm-5.3: not run, not run in this column
- hermes x glm-5.3-flash: not run, not run in this column
- hermes x gpt-5.2: not run, not run in this column
- hermes x gpt-5.3-codex: not run, not run in this column
- hermes x gpt-5.4: not run, not run in this column
- hermes x gpt-5.4-mini: not run, not run in this column
- hermes x gpt-5.5: not run, not run in this column
- hermes x gpt-5.6-luna: not run, not run in this column
- hermes x gpt-5.6-sol: not run, not run in this column
- hermes x gpt-5.6-terra: not run, not run in this column
- hermes x gpt-6-astra: not run, not run in this column
- hermes x gpt-6-luna: not run, not run in this column
- hermes x gpt-6-sol: not run, not run in this column
- hermes x gpt-6.1-sol: not run, not run in this column
- hermes x grok-4.20: not run, not run in this column
- hermes x grok-4.3: not run, not run in this column
- hermes x grok-4.5: not run, not run in this column
- hermes x grok-4.6: not run, not run in this column
- hermes x grok-build-0.1: not run, not run in this column
- hermes x hunyuan-4-preview: not run, not run in this column
- hermes x kimi-k2.7-code: not run, not run in this column
- hermes x kimi-k3: not run, not run in this column
- hermes x mistral-medium-3.5: not run, not run in this column
- hermes x nemotron-3-super: not run, not run in this column
- hermes x nemotron-3.5-lightning: not run, not run in this column
- hermes x qwen3.7-max: not run, not run in this column
- hermes x qwen3.7-plus: not run, not run in this column
- hermes x qwen3.8-flash: not run, not run in this column
- hermes x qwen3.8-max: not run, not run in this column
- hermes x step-3.7-flash: not run, not run in this column
- opencode x claude-fable-5: not run, not run in this column
- opencode x claude-fable-5-1: not run, not run in this column
- opencode x claude-haiku-4.5: not run, not run in this column
- opencode x claude-opus-4.7: not run, not run in this column
- opencode x claude-opus-4.8: not run, not run in this column
- opencode x claude-opus-5: not run, not run in this column
- opencode x claude-opus-5.5: not run, not run in this column
- opencode x claude-sonnet-4.6: not run, not run in this column
- opencode x claude-sonnet-5: not run, not run in this column
- opencode x claude-sonnet-5.5: not run, not run in this column
- opencode x deepseek-v4-flash: not run, not run in this column
- opencode x deepseek-v4-pro: not run, not run in this column
- opencode x deepseek-v4.1-flash: not run, not run in this column
- opencode x glm-5.3: not run, not run in this column
- opencode x glm-5.3-flash: not run, not run in this column
- opencode x gpt-5.2: not run, not run in this column
- opencode x gpt-5.3-codex: not run, not run in this column
- opencode x gpt-5.4: not run, not run in this column
- opencode x gpt-5.4-mini: not run, not run in this column
- opencode x gpt-5.5: not run, not run in this column
- opencode x gpt-5.6-luna: not run, not run in this column
- opencode x gpt-5.6-sol: not run, not run in this column
- opencode x gpt-5.6-terra: not run, not run in this column
- opencode x gpt-6-astra: not run, not run in this column
- opencode x gpt-6-luna: not run, not run in this column
- opencode x gpt-6-sol: not run, not run in this column
- opencode x gpt-6.1-sol: not run, not run in this column
- opencode x grok-4.20: not run, not run in this column
- opencode x grok-4.3: not run, not run in this column
- opencode x grok-4.5: not run, not run in this column
- opencode x grok-4.6: not run, not run in this column
- opencode x grok-build-0.1: not run, not run in this column
- opencode x hunyuan-4-preview: not run, not run in this column
- opencode x kimi-k2.7-code: not run, not run in this column
- opencode x kimi-k3: not run, not run in this column
- opencode x mistral-medium-3.5: not run, not run in this column
- opencode x nemotron-3-super: not run, not run in this column
- opencode x nemotron-3.5-lightning: not run, not run in this column
- opencode x qwen3.7-max: not run, not run in this column
- opencode x qwen3.7-plus: not run, not run in this column
- opencode x qwen3.8-flash: not run, not run in this column
- opencode x qwen3.8-max: not run, not run in this column
- opencode x step-3.7-flash: not run, not run in this column
- pi x claude-fable-5: not run, not run in this column
- pi x claude-fable-5-1: not run, not run in this column
- pi x claude-haiku-4.5: not run, not run in this column
- pi x claude-opus-4.7: not run, not run in this column
- pi x claude-opus-4.8: not run, not run in this column
- pi x claude-opus-5: not run, not run in this column
- pi x claude-opus-5.5: not run, not run in this column
- pi x claude-sonnet-4.6: not run, not run in this column
- pi x claude-sonnet-5: not run, not run in this column
- pi x claude-sonnet-5.5: not run, not run in this column
- pi x deepseek-v4-flash: not run, not run in this column
- pi x deepseek-v4-pro: not run, not run in this column
- pi x deepseek-v4.1-flash: not run, not run in this column
- pi x glm-5.3: not run, not run in this column
- pi x glm-5.3-flash: not run, not run in this column
- pi x gpt-5.2: not run, not run in this column
- pi x gpt-5.3-codex: not run, not run in this column
- pi x gpt-5.4: not run, not run in this column
- pi x gpt-5.4-mini: not run, not run in this column
- pi x gpt-5.5: not run, not run in this column
- pi x gpt-5.6-luna: not run, not run in this column
- pi x gpt-5.6-sol: not run, not run in this column
- pi x gpt-5.6-terra: not run, not run in this column
- pi x gpt-6-astra: not run, not run in this column
- pi x gpt-6-luna: not run, not run in this column
- pi x gpt-6-sol: not run, not run in this column
- pi x gpt-6.1-sol: not run, not run in this column
- pi x grok-4.20: not run, not run in this column
- pi x grok-4.3: not run, not run in this column
- pi x grok-4.5: not run, not run in this column
- pi x grok-4.6: not run, not run in this column
- pi x grok-build-0.1: not run, not run in this column
- pi x hunyuan-4-preview: not run, not run in this column
- pi x kimi-k2.7-code: not run, not run in this column
- pi x kimi-k3: not run, not run in this column
- pi x mistral-medium-3.5: not run, not run in this column
- pi x nemotron-3-super: not run, not run in this column
- pi x nemotron-3.5-lightning: not run, not run in this column
- pi x qwen3.7-max: not run, not run in this column
- pi x qwen3.7-plus: not run, not run in this column
- pi x qwen3.8-flash: not run, not run in this column
- pi x qwen3.8-max: not run, not run in this column
- pi x step-3.7-flash: not run, not run in this column
- qwen x claude-fable-5: not run, not run in this column
- qwen x claude-fable-5-1: not run, not run in this column
- qwen x claude-haiku-4.5: not run, not run in this column
- qwen x claude-opus-4.7: not run, not run in this column
- qwen x claude-opus-4.8: not run, not run in this column
- qwen x claude-opus-5: not run, not run in this column
- qwen x claude-opus-5.5: not run, not run in this column
- qwen x claude-sonnet-4.6: not run, not run in this column
- qwen x claude-sonnet-5: not run, not run in this column
- qwen x claude-sonnet-5.5: not run, not run in this column
- qwen x deepseek-v4-flash: not run, not run in this column
- qwen x deepseek-v4-pro: not run, not run in this column
- qwen x deepseek-v4.1-flash: not run, not run in this column
- qwen x glm-5.3: not run, not run in this column
- qwen x glm-5.3-flash: not run, not run in this column
- qwen x gpt-5.2: not run, not run in this column
- qwen x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- qwen x gpt-5.4: not run, not run in this column
- qwen x gpt-5.4-mini: not run, not run in this column
- qwen x gpt-5.5: not run, not run in this column
- qwen x gpt-5.6-luna: not run, not run in this column
- qwen x gpt-5.6-sol: not run, not run in this column
- qwen x gpt-5.6-terra: not run, not run in this column
- qwen x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- qwen x gpt-6-luna: not run, not run in this column
- qwen x gpt-6-sol: not run, not run in this column
- qwen x gpt-6.1-sol: not run, not run in this column
- qwen x grok-4.20: not run, not run in this column
- qwen x grok-4.3: not run, not run in this column
- qwen x grok-4.5: not run, not run in this column
- qwen x grok-4.6: not run, not run in this column
- qwen x grok-build-0.1: not run, not run in this column
- qwen x hunyuan-4-preview: not run, not run in this column
- qwen x kimi-k2.7-code: not run, not run in this column
- qwen x kimi-k3: not run, not run in this column
- qwen x mistral-medium-3.5: not run, not run in this column
- qwen x nemotron-3-super: not run, not run in this column
- qwen x nemotron-3.5-lightning: not run, not run in this column
- qwen x qwen3.7-max: not run, not run in this column
- qwen x qwen3.7-plus: not run, not run in this column
- qwen x qwen3.8-flash: not run, not run in this column
- qwen x qwen3.8-max: not run, not run in this column
- qwen x step-3.7-flash: not run, not run in this column

## Provider: gemini-vercel

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| cline | gemini-3-flash-preview | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| cline | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| cline | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| cline | gemini-3.5-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| cline | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| cline | gemini-3.7-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| cline | gemini-3.8-flash | pass | pass | pass (gemini-3.7-flash) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| dsh | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| hermes | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| hermes | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| hermes | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| hermes | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| hermes | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| hermes | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | FAIL | Vercel AI Gateway | recycle: answered without M1-gemini-3.6-flash: What exact word did I ask you to reply with in my very first message of this task? Reply with just tha ; retested once; first try: recycle answered without M1-gemini-3.6-flash: What exact word did I ask you to reply wit |
| hermes | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| hermes | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| opencode | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| opencode | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| opencode | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| opencode | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| opencode | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| opencode | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| opencode | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| opencode | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| pi | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| pi | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| pi | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| pi | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| pi | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| pi | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| pi | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| pi | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| qwen | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| qwen | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| qwen | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| qwen | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| qwen | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| qwen | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Vercel AI Gateway |  |
| qwen | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |
| qwen | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Vercel AI Gateway |  |

47 pairs, 234 of 235 scenario runs passed.

Not run in this column, 325 pairs the provider serves that the harness did not run, with the reason:

- cline x claude-fable-5: not run, not run in this column
- cline x claude-fable-5-1: not run, not run in this column
- cline x claude-haiku-4.5: not run, not run in this column
- cline x claude-haiku-5.5: not run, not run in this column
- cline x claude-opus-4.7: not run, not run in this column
- cline x claude-opus-4.8: not run, not run in this column
- cline x claude-opus-5: not run, not run in this column
- cline x claude-opus-5.5: not run, not run in this column
- cline x claude-sonnet-4.6: not run, not run in this column
- cline x claude-sonnet-5: not run, not run in this column
- cline x claude-sonnet-5.5: not run, not run in this column
- cline x deepseek-v4-flash: not run, not run in this column
- cline x deepseek-v4-pro: not run, not run in this column
- cline x deepseek-v4.1-flash: not run, not run in this column
- cline x gemini-3.6-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x glm-5.3: not run, not run in this column
- cline x glm-5.3-flash: not run, not run in this column
- cline x gpt-5.2: not run, not run in this column
- cline x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cline x gpt-5.4: not run, not run in this column
- cline x gpt-5.4-mini: not run, not run in this column
- cline x gpt-5.5: not run, not run in this column
- cline x gpt-5.6-luna: not run, not run in this column
- cline x gpt-5.6-sol: not run, not run in this column
- cline x gpt-5.6-terra: not run, not run in this column
- cline x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cline x gpt-6-luna: not run, not run in this column
- cline x gpt-6-sol: not run, not run in this column
- cline x gpt-6.1-sol: not run, not run in this column
- cline x grok-4.20: not run, not run in this column
- cline x grok-4.3: not run, not run in this column
- cline x grok-4.5: not run, not run in this column
- cline x grok-4.6: not run, not run in this column
- cline x grok-build-0.1: not run, not run in this column
- cline x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x hunyuan-4-preview: not run, not run in this column
- cline x kimi-k2.7-code: not run, not run in this column
- cline x kimi-k3: not run, not run in this column
- cline x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x mistral-medium-3.5: not run, not run in this column
- cline x muse-glimmer-30b: not run, not run in this column
- cline x muse-spark-1.1: not run, not run in this column
- cline x muse-spark-1.2: not run, not run in this column
- cline x muse-spark-1.3: not run, not run in this column
- cline x nemotron-3-super: not run, not run in this column
- cline x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x nemotron-3.5-lightning: not run, not run in this column
- cline x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x qwen3.7-max: not run, not run in this column
- cline x qwen3.7-plus: not run, not run in this column
- cline x qwen3.8-27b: not run, not run in this column
- cline x qwen3.8-flash: not run, not run in this column
- cline x qwen3.8-max: not run, not run in this column
- cline x step-3.7-flash: not run, not run in this column
- dsh x claude-fable-5: not run, not run in this column
- dsh x claude-fable-5-1: not run, not run in this column
- dsh x claude-haiku-4.5: not run, not run in this column
- dsh x claude-haiku-5.5: not run, not run in this column
- dsh x claude-opus-4.7: not run, not run in this column
- dsh x claude-opus-4.8: not run, not run in this column
- dsh x claude-opus-5: not run, not run in this column
- dsh x claude-opus-5.5: not run, not run in this column
- dsh x claude-sonnet-4.6: not run, not run in this column
- dsh x claude-sonnet-5: not run, not run in this column
- dsh x claude-sonnet-5.5: not run, not run in this column
- dsh x deepseek-v4-flash: not run, not run in this column
- dsh x deepseek-v4-pro: not run, not run in this column
- dsh x deepseek-v4.1-flash: not run, not run in this column
- dsh x glm-5.3: not run, not run in this column
- dsh x glm-5.3-flash: not run, not run in this column
- dsh x gpt-5.2: not run, not run in this column
- dsh x gpt-5.3-codex: not run, not run in this column
- dsh x gpt-5.4: not run, not run in this column
- dsh x gpt-5.4-mini: not run, not run in this column
- dsh x gpt-5.5: not run, not run in this column
- dsh x gpt-5.6-luna: not run, not run in this column
- dsh x gpt-5.6-sol: not run, not run in this column
- dsh x gpt-5.6-terra: not run, not run in this column
- dsh x gpt-6-astra: not run, not run in this column
- dsh x gpt-6-luna: not run, not run in this column
- dsh x gpt-6-sol: not run, not run in this column
- dsh x gpt-6.1-sol: not run, not run in this column
- dsh x grok-4.20: not run, not run in this column
- dsh x grok-4.3: not run, not run in this column
- dsh x grok-4.5: not run, not run in this column
- dsh x grok-4.6: not run, not run in this column
- dsh x grok-build-0.1: not run, not run in this column
- dsh x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x hunyuan-4-preview: not run, not run in this column
- dsh x kimi-k2.7-code: not run, not run in this column
- dsh x kimi-k3: not run, not run in this column
- dsh x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x mistral-medium-3.5: not run, not run in this column
- dsh x muse-glimmer-30b: not run, not run in this column
- dsh x muse-spark-1.1: not run, not run in this column
- dsh x muse-spark-1.2: not run, not run in this column
- dsh x muse-spark-1.3: not run, not run in this column
- dsh x nemotron-3-super: not run, not run in this column
- dsh x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x nemotron-3.5-lightning: not run, not run in this column
- dsh x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x qwen3.7-max: not run, not run in this column
- dsh x qwen3.7-plus: not run, not run in this column
- dsh x qwen3.8-27b: not run, not run in this column
- dsh x qwen3.8-flash: not run, not run in this column
- dsh x qwen3.8-max: not run, not run in this column
- dsh x step-3.7-flash: not run, not run in this column
- hermes x claude-fable-5: not run, not run in this column
- hermes x claude-fable-5-1: not run, not run in this column
- hermes x claude-haiku-4.5: not run, not run in this column
- hermes x claude-haiku-5.5: not run, not run in this column
- hermes x claude-opus-4.7: not run, not run in this column
- hermes x claude-opus-4.8: not run, not run in this column
- hermes x claude-opus-5: not run, not run in this column
- hermes x claude-opus-5.5: not run, not run in this column
- hermes x claude-sonnet-4.6: not run, not run in this column
- hermes x claude-sonnet-5: not run, not run in this column
- hermes x claude-sonnet-5.5: not run, not run in this column
- hermes x deepseek-v4-flash: not run, not run in this column
- hermes x deepseek-v4-pro: not run, not run in this column
- hermes x deepseek-v4.1-flash: not run, not run in this column
- hermes x glm-5.3: not run, not run in this column
- hermes x glm-5.3-flash: not run, not run in this column
- hermes x gpt-5.2: not run, not run in this column
- hermes x gpt-5.3-codex: not run, not run in this column
- hermes x gpt-5.4: not run, not run in this column
- hermes x gpt-5.4-mini: not run, not run in this column
- hermes x gpt-5.5: not run, not run in this column
- hermes x gpt-5.6-luna: not run, not run in this column
- hermes x gpt-5.6-sol: not run, not run in this column
- hermes x gpt-5.6-terra: not run, not run in this column
- hermes x gpt-6-astra: not run, not run in this column
- hermes x gpt-6-luna: not run, not run in this column
- hermes x gpt-6-sol: not run, not run in this column
- hermes x gpt-6.1-sol: not run, not run in this column
- hermes x grok-4.20: not run, not run in this column
- hermes x grok-4.3: not run, not run in this column
- hermes x grok-4.5: not run, not run in this column
- hermes x grok-4.6: not run, not run in this column
- hermes x grok-build-0.1: not run, not run in this column
- hermes x hunyuan-3: not run, not run in this column
- hermes x hunyuan-4-preview: not run, not run in this column
- hermes x kimi-k2.7-code: not run, not run in this column
- hermes x kimi-k3: not run, not run in this column
- hermes x ling-3.0-flash: not run, not run in this column
- hermes x minimax-m3: not run, not run in this column
- hermes x mistral-medium-3.5: not run, not run in this column
- hermes x muse-glimmer-30b: not run, not run in this column
- hermes x muse-spark-1.1: not run, not run in this column
- hermes x muse-spark-1.2: not run, not run in this column
- hermes x muse-spark-1.3: not run, not run in this column
- hermes x nemotron-3-super: not run, not run in this column
- hermes x nemotron-3-ultra: not run, not run in this column
- hermes x nemotron-3.5-lightning: not run, not run in this column
- hermes x qwen3.7-flash: not run, not run in this column
- hermes x qwen3.7-max: not run, not run in this column
- hermes x qwen3.7-plus: not run, not run in this column
- hermes x qwen3.8-27b: not run, not run in this column
- hermes x qwen3.8-flash: not run, not run in this column
- hermes x qwen3.8-max: not run, not run in this column
- hermes x step-3.7-flash: not run, not run in this column
- opencode x claude-fable-5: not run, not run in this column
- opencode x claude-fable-5-1: not run, not run in this column
- opencode x claude-haiku-4.5: not run, not run in this column
- opencode x claude-haiku-5.5: not run, not run in this column
- opencode x claude-opus-4.7: not run, not run in this column
- opencode x claude-opus-4.8: not run, not run in this column
- opencode x claude-opus-5: not run, not run in this column
- opencode x claude-opus-5.5: not run, not run in this column
- opencode x claude-sonnet-4.6: not run, not run in this column
- opencode x claude-sonnet-5: not run, not run in this column
- opencode x claude-sonnet-5.5: not run, not run in this column
- opencode x deepseek-v4-flash: not run, not run in this column
- opencode x deepseek-v4-pro: not run, not run in this column
- opencode x deepseek-v4.1-flash: not run, not run in this column
- opencode x glm-5.3: not run, not run in this column
- opencode x glm-5.3-flash: not run, not run in this column
- opencode x gpt-5.2: not run, not run in this column
- opencode x gpt-5.3-codex: not run, not run in this column
- opencode x gpt-5.4: not run, not run in this column
- opencode x gpt-5.4-mini: not run, not run in this column
- opencode x gpt-5.5: not run, not run in this column
- opencode x gpt-5.6-luna: not run, not run in this column
- opencode x gpt-5.6-sol: not run, not run in this column
- opencode x gpt-5.6-terra: not run, not run in this column
- opencode x gpt-6-astra: not run, not run in this column
- opencode x gpt-6-luna: not run, not run in this column
- opencode x gpt-6-sol: not run, not run in this column
- opencode x gpt-6.1-sol: not run, not run in this column
- opencode x grok-4.20: not run, not run in this column
- opencode x grok-4.3: not run, not run in this column
- opencode x grok-4.5: not run, not run in this column
- opencode x grok-4.6: not run, not run in this column
- opencode x grok-build-0.1: not run, not run in this column
- opencode x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x hunyuan-4-preview: not run, not run in this column
- opencode x kimi-k2.7-code: not run, not run in this column
- opencode x kimi-k3: not run, not run in this column
- opencode x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x mistral-medium-3.5: not run, not run in this column
- opencode x muse-glimmer-30b: not run, not run in this column
- opencode x muse-spark-1.1: not run, not run in this column
- opencode x muse-spark-1.2: not run, not run in this column
- opencode x muse-spark-1.3: not run, not run in this column
- opencode x nemotron-3-super: not run, not run in this column
- opencode x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x nemotron-3.5-lightning: not run, not run in this column
- opencode x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x qwen3.7-max: not run, not run in this column
- opencode x qwen3.7-plus: not run, not run in this column
- opencode x qwen3.8-27b: not run, not run in this column
- opencode x qwen3.8-flash: not run, not run in this column
- opencode x qwen3.8-max: not run, not run in this column
- opencode x step-3.7-flash: not run, not run in this column
- pi x claude-fable-5: not run, not run in this column
- pi x claude-fable-5-1: not run, not run in this column
- pi x claude-haiku-4.5: not run, not run in this column
- pi x claude-haiku-5.5: not run, not run in this column
- pi x claude-opus-4.7: not run, not run in this column
- pi x claude-opus-4.8: not run, not run in this column
- pi x claude-opus-5: not run, not run in this column
- pi x claude-opus-5.5: not run, not run in this column
- pi x claude-sonnet-4.6: not run, not run in this column
- pi x claude-sonnet-5: not run, not run in this column
- pi x claude-sonnet-5.5: not run, not run in this column
- pi x deepseek-v4-flash: not run, not run in this column
- pi x deepseek-v4-pro: not run, not run in this column
- pi x deepseek-v4.1-flash: not run, not run in this column
- pi x glm-5.3: not run, not run in this column
- pi x glm-5.3-flash: not run, not run in this column
- pi x gpt-5.2: not run, not run in this column
- pi x gpt-5.3-codex: not run, not run in this column
- pi x gpt-5.4: not run, not run in this column
- pi x gpt-5.4-mini: not run, not run in this column
- pi x gpt-5.5: not run, not run in this column
- pi x gpt-5.6-luna: not run, not run in this column
- pi x gpt-5.6-sol: not run, not run in this column
- pi x gpt-5.6-terra: not run, not run in this column
- pi x gpt-6-astra: not run, not run in this column
- pi x gpt-6-luna: not run, not run in this column
- pi x gpt-6-sol: not run, not run in this column
- pi x gpt-6.1-sol: not run, not run in this column
- pi x grok-4.20: not run, not run in this column
- pi x grok-4.3: not run, not run in this column
- pi x grok-4.5: not run, not run in this column
- pi x grok-4.6: not run, not run in this column
- pi x grok-build-0.1: not run, not run in this column
- pi x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x hunyuan-4-preview: not run, not run in this column
- pi x kimi-k2.7-code: not run, not run in this column
- pi x kimi-k3: not run, not run in this column
- pi x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x mistral-medium-3.5: not run, not run in this column
- pi x muse-glimmer-30b: not run, not run in this column
- pi x muse-spark-1.1: not run, not run in this column
- pi x muse-spark-1.2: not run, not run in this column
- pi x muse-spark-1.3: not run, not run in this column
- pi x nemotron-3-super: not run, not run in this column
- pi x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x nemotron-3.5-lightning: not run, not run in this column
- pi x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x qwen3.7-max: not run, not run in this column
- pi x qwen3.7-plus: not run, not run in this column
- pi x qwen3.8-27b: not run, not run in this column
- pi x qwen3.8-flash: not run, not run in this column
- pi x qwen3.8-max: not run, not run in this column
- pi x step-3.7-flash: not run, not run in this column
- qwen x claude-fable-5: not run, not run in this column
- qwen x claude-fable-5-1: not run, not run in this column
- qwen x claude-haiku-4.5: not run, not run in this column
- qwen x claude-haiku-5.5: not run, not run in this column
- qwen x claude-opus-4.7: not run, not run in this column
- qwen x claude-opus-4.8: not run, not run in this column
- qwen x claude-opus-5: not run, not run in this column
- qwen x claude-opus-5.5: not run, not run in this column
- qwen x claude-sonnet-4.6: not run, not run in this column
- qwen x claude-sonnet-5: not run, not run in this column
- qwen x claude-sonnet-5.5: not run, not run in this column
- qwen x deepseek-v4-flash: not run, not run in this column
- qwen x deepseek-v4-pro: not run, not run in this column
- qwen x deepseek-v4.1-flash: not run, not run in this column
- qwen x glm-5.3: not run, not run in this column
- qwen x glm-5.3-flash: not run, not run in this column
- qwen x gpt-5.2: not run, not run in this column
- qwen x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- qwen x gpt-5.4: not run, not run in this column
- qwen x gpt-5.4-mini: not run, not run in this column
- qwen x gpt-5.5: not run, not run in this column
- qwen x gpt-5.6-luna: not run, not run in this column
- qwen x gpt-5.6-sol: not run, not run in this column
- qwen x gpt-5.6-terra: not run, not run in this column
- qwen x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- qwen x gpt-6-luna: not run, not run in this column
- qwen x gpt-6-sol: not run, not run in this column
- qwen x gpt-6.1-sol: not run, not run in this column
- qwen x grok-4.20: not run, not run in this column
- qwen x grok-4.3: not run, not run in this column
- qwen x grok-4.5: not run, not run in this column
- qwen x grok-4.6: not run, not run in this column
- qwen x grok-build-0.1: not run, not run in this column
- qwen x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x hunyuan-4-preview: not run, not run in this column
- qwen x kimi-k2.7-code: not run, not run in this column
- qwen x kimi-k3: not run, not run in this column
- qwen x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x mistral-medium-3.5: not run, not run in this column
- qwen x muse-glimmer-30b: not run, not run in this column
- qwen x muse-spark-1.1: not run, not run in this column
- qwen x muse-spark-1.2: not run, not run in this column
- qwen x muse-spark-1.3: not run, not run in this column
- qwen x nemotron-3-super: not run, not run in this column
- qwen x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x nemotron-3.5-lightning: not run, not run in this column
- qwen x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x qwen3.7-max: not run, not run in this column
- qwen x qwen3.7-plus: not run, not run in this column
- qwen x qwen3.8-27b: not run, not run in this column
- qwen x qwen3.8-flash: not run, not run in this column
- qwen x qwen3.8-max: not run, not run in this column
- qwen x step-3.7-flash: not run, not run in this column

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

Not run in this column, 35 pairs the provider serves that the harness did not run, with the reason:

- dsh x gemini-3-flash-preview: not run, not run in this column
- dsh x gemini-3.1-flash-lite: not run, not run in this column
- dsh x gemini-3.1-pro-preview: not run, not run in this column
- dsh x gemini-3.5-flash: not run, not run in this column
- dsh x gemini-3.5-flash-lite: not run, not run in this column
- dsh x gemini-3.7-flash: not run, not run in this column
- dsh x gemini-3.8-flash: not run, not run in this column
- hermes x gemini-3-flash-preview: not run, not run in this column
- hermes x gemini-3.1-flash-lite: not run, not run in this column
- hermes x gemini-3.1-pro-preview: not run, not run in this column
- hermes x gemini-3.5-flash: not run, not run in this column
- hermes x gemini-3.5-flash-lite: not run, not run in this column
- hermes x gemini-3.7-flash: not run, not run in this column
- hermes x gemini-3.8-flash: not run, not run in this column
- opencode x gemini-3-flash-preview: not run, not run in this column
- opencode x gemini-3.1-flash-lite: not run, not run in this column
- opencode x gemini-3.1-pro-preview: not run, not run in this column
- opencode x gemini-3.5-flash: not run, not run in this column
- opencode x gemini-3.5-flash-lite: not run, not run in this column
- opencode x gemini-3.7-flash: not run, not run in this column
- opencode x gemini-3.8-flash: not run, not run in this column
- pi x gemini-3-flash-preview: not run, not run in this column
- pi x gemini-3.1-flash-lite: not run, not run in this column
- pi x gemini-3.1-pro-preview: not run, not run in this column
- pi x gemini-3.5-flash: not run, not run in this column
- pi x gemini-3.5-flash-lite: not run, not run in this column
- pi x gemini-3.7-flash: not run, not run in this column
- pi x gemini-3.8-flash: not run, not run in this column
- qwen x gemini-3-flash-preview: not run, not run in this column
- qwen x gemini-3.1-flash-lite: not run, not run in this column
- qwen x gemini-3.1-pro-preview: not run, not run in this column
- qwen x gemini-3.5-flash: not run, not run in this column
- qwen x gemini-3.5-flash-lite: not run, not run in this column
- qwen x gemini-3.7-flash: not run, not run in this column
- qwen x gemini-3.8-flash: not run, not run in this column

## Provider: goose-anthropic

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| goose | claude-fable-5 | pass | pass | pass (claude-fable-5-1) | pass | pass | Anthropic |  |
| goose | claude-fable-5-1 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic |  |
| goose | claude-haiku-4.5 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic | served as claude-haiku-4-5-20251001 (the provider's alias of the same model) |
| goose | claude-opus-4.7 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic | served as claude-opus-4-7 (the provider's alias of the same model) |
| goose | claude-opus-4.8 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic | served as claude-opus-4-8 (the provider's alias of the same model) |
| goose | claude-sonnet-4.6 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic | served as claude-sonnet-4-6 (the provider's alias of the same model) |
| goose | claude-sonnet-5 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic |  |

7 pairs, 35 of 35 scenario runs passed.

Not run in this column, 4 pairs the provider serves that the harness did not run, with the reason:

- goose x claude-haiku-5.5: not run, not run in this column
- goose x claude-opus-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x claude-opus-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x claude-sonnet-5.5: not run, not run in this column

## Provider: goose-azure-e2

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| goose | gpt-5.2 | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI E2 |  |
| goose | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 |  |
| goose | gpt-5.4-mini | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI E2 |  |
| goose | gpt-5.5 | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI E2 |  |
| goose | gpt-5.6-luna | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI E2 |  |
| goose | gpt-5.6-sol | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI E2 |  |
| goose | gpt-5.6-terra | pass | pass | pass (gpt-5.4) | pass | pass | Azure OpenAI E2 |  |

7 pairs, 35 of 35 scenario runs passed.

Not run in this column, 5 pairs the provider serves that the harness did not run, with the reason:

- goose x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-6-luna: not run, not run in this column
- goose x gpt-6-sol: not run, not run in this column
- goose x gpt-6.1-sol: not run, not run in this column

## Provider: goose-harnessrouter

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| goose | claude-fable-5 | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 |  |
| goose | claude-fable-5-1 | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 |  |
| goose | claude-haiku-4.5 | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 | served as claude-haiku-4-5-20251001 (the provider's alias of the same model) |
| goose | claude-opus-4.7 | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 | served as claude-opus-4-7 (the provider's alias of the same model) |
| goose | claude-opus-4.8 | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 | served as claude-opus-4-8 (the provider's alias of the same model) |
| goose | claude-sonnet-4.6 | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 | served as claude-sonnet-4-6 (the provider's alias of the same model) |
| goose | claude-sonnet-5 | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 |  |
| goose | deepseek-v4-flash | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 |  |
| goose | deepseek-v4-pro | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 |  |
| goose | gemini-3-flash-preview | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 | served as google/gemini-3-flash-preview (the provider's alias of the same model) |
| goose | gemini-3.1-pro-preview | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 |  |
| goose | gemini-3.5-flash | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 |  |
| goose | gemini-3.5-flash-lite | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 |  |
| goose | gemini-3.6-flash | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 |  |
| goose | gemini-3.7-flash | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 | served as google/gemini-3.7-flash (the provider's alias of the same model) |
| goose | gemini-3.8-flash | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 |  |
| goose | glm-5.3 | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 |  |
| goose | glm-5.3-flash | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 |  |
| goose | gpt-5.2 | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 | served as gpt-5.2-2025-12-11 (the provider's alias of the same model) |
| goose | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | HarnessRouter API  test 1 |  |
| goose | gpt-5.4-mini | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 | served as gpt-5.4-mini-2026-03-17 (the provider's alias of the same model) |
| goose | gpt-5.5 | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 | served as gpt-5.5-2026-04-23 (the provider's alias of the same model) |
| goose | gpt-5.6-luna | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 |  |
| goose | gpt-5.6-sol | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 |  |
| goose | gpt-5.6-terra | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 |  |
| goose | kimi-k2.7-code | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 |  |
| goose | kimi-k3 | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 |  |
| goose | mistral-medium-3.5 | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 | served as mistralai/mistral-medium-3-5 (the provider's alias of the same model) |
| goose | qwen3.7-max | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 |  |
| goose | qwen3.8-max | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 |  |
| goose | step-3.7-flash | pass | pass | pass (gpt-5.4) | pass | pass | HarnessRouter API  test 1 | served as stepfun/step-3.7-flash (the provider's alias of the same model) |

31 pairs, 155 of 155 scenario runs passed.

Not run in this column, 19 pairs the provider serves that the harness did not run, with the reason:

- goose x claude-opus-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x claude-opus-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x claude-sonnet-5.5: not run, not run in this column
- goose x deepseek-v4.1-flash: not run, not run in this column
- goose x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-6-luna: not run, not run in this column
- goose x gpt-6-sol: not run, not run in this column
- goose x gpt-6.1-sol: not run, not run in this column
- goose x grok-4.20: not run, not run in this column
- goose x grok-4.3: not run, not run in this column
- goose x grok-4.5: not run, not run in this column
- goose x grok-4.6: not run, not run in this column
- goose x grok-build-0.1: not run, not run in this column
- goose x hunyuan-4-preview: not run, not run in this column
- goose x nemotron-3-super: not run, not run in this column
- goose x nemotron-3.5-lightning: not run, not run in this column
- goose x qwen3.7-plus: not run, not run in this column
- goose x qwen3.8-flash: not run, not run in this column

## Provider: goose-openai

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| goose | gpt-5.2 | pass | pass | pass (gpt-5.4) | pass | pass | OpenAI | served as gpt-5.2-2025-12-11 (the provider's alias of the same model) |
| goose | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI | served as gpt-5.4-2026-03-05 (the provider's alias of the same model) |
| goose | gpt-5.4-mini | pass | pass | pass (gpt-5.4) | pass | pass | OpenAI | served as gpt-5.4-mini-2026-03-17 (the provider's alias of the same model) |
| goose | gpt-5.5 | pass | pass | pass (gpt-5.4) | pass | pass | OpenAI | served as gpt-5.5-2026-04-23 (the provider's alias of the same model) |
| goose | gpt-5.6-luna | pass | pass | pass (gpt-5.4) | pass | pass | OpenAI |  |
| goose | gpt-5.6-sol | pass | pass | pass (gpt-5.4) | pass | pass | OpenAI |  |
| goose | gpt-5.6-terra | pass | pass | pass (gpt-5.4) | pass | pass | OpenAI |  |

7 pairs, 35 of 35 scenario runs passed.

Not run in this column, 5 pairs the provider serves that the harness did not run, with the reason:

- goose x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-6-luna: not run, not run in this column
- goose x gpt-6-sol: not run, not run in this column
- goose x gpt-6.1-sol: not run, not run in this column

## Provider: goose-openrouter

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| goose | claude-fable-5 | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as anthropic/claude-fable-5 (the provider's alias of the same model) |
| goose | claude-fable-5-1 | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as anthropic/claude-fable-5.1 (the provider's alias of the same model) |
| goose | claude-haiku-4.5 | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as anthropic/claude-haiku-4.5 (the provider's alias of the same model) |
| goose | claude-opus-4.7 | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as anthropic/claude-opus-4.7 (the provider's alias of the same model) |
| goose | claude-opus-4.8 | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as anthropic/claude-opus-4.8 (the provider's alias of the same model) |
| goose | claude-sonnet-4.6 | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as anthropic/claude-sonnet-4.6 (the provider's alias of the same model) |
| goose | claude-sonnet-5 | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as anthropic/claude-sonnet-5 (the provider's alias of the same model) |
| goose | deepseek-v4-flash | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as deepseek/deepseek-v4-flash (the provider's alias of the same model) |
| goose | deepseek-v4-pro | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as deepseek/deepseek-v4-pro (the provider's alias of the same model) |
| goose | deepseek-v4.1-flash | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as deepseek/deepseek-v4.1-flash (the provider's alias of the same model) |
| goose | gemini-3-flash-preview | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as google/gemini-3-flash-preview (the provider's alias of the same model) |
| goose | gemini-3.1-flash-lite | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as google/gemini-3.1-flash-lite (the provider's alias of the same model) |
| goose | gemini-3.1-pro-preview | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as google/gemini-3.1-pro-preview (the provider's alias of the same model) |
| goose | gemini-3.5-flash | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as google/gemini-3.5-flash (the provider's alias of the same model) |
| goose | gemini-3.5-flash-lite | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as google/gemini-3.5-flash-lite (the provider's alias of the same model) |
| goose | gemini-3.6-flash | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as google/gemini-3.6-flash (the provider's alias of the same model) |
| goose | gemini-3.7-flash | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as google/gemini-3.7-flash (the provider's alias of the same model) |
| goose | gemini-3.8-flash | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as google/gemini-3.8-flash (the provider's alias of the same model) |
| goose | glm-5.3 | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as z-ai/glm-5.3 (the provider's alias of the same model) |
| goose | glm-5.3-flash | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as z-ai/glm-5.3-flash (the provider's alias of the same model) |
| goose | gpt-5.2 | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as openai/gpt-5.2 (the provider's alias of the same model) |
| goose | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as openai/gpt-5.4 (the provider's alias of the same model) |
| goose | gpt-5.4-mini | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as openai/gpt-5.4-mini (the provider's alias of the same model) |
| goose | gpt-5.5 | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as openai/gpt-5.5 (the provider's alias of the same model) |
| goose | gpt-5.6-luna | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as openai/gpt-5.6-luna (the provider's alias of the same model) |
| goose | gpt-5.6-sol | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as openai/gpt-5.6-sol (the provider's alias of the same model) |
| goose | gpt-5.6-terra | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as openai/gpt-5.6-terra (the provider's alias of the same model) |
| goose | grok-4.20 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as x-ai/grok-4.20 (the provider's alias of the same model) |
| goose | grok-4.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as x-ai/grok-4.3 (the provider's alias of the same model) |
| goose | grok-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as x-ai/grok-4.5 (the provider's alias of the same model) |
| goose | grok-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as x-ai/grok-4.6 (the provider's alias of the same model) |
| goose | grok-build-0.1 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as x-ai/grok-build-0.1 (the provider's alias of the same model) |
| goose | hunyuan-3 | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as tencent/hy3 (the provider's alias of the same model) |
| goose | hunyuan-4-preview | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as tencent/hy4-preview (the provider's alias of the same model) |
| goose | kimi-k2.7-code | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as moonshotai/kimi-k2.7-code (the provider's alias of the same model) |
| goose | kimi-k3 | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as moonshotai/kimi-k3 (the provider's alias of the same model) |
| goose | ling-3.0-flash | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as inclusionai/ling-3.0-flash (the provider's alias of the same model) |
| goose | llama-3.3-70b | pass | pass | pass (gpt-5.6-sol) | pass | FAIL | OpenRouter | served as meta-llama/llama-3.3-70b-instruct (the provider's alias of the same model) ; recycle: answered without M1-llama-3.3-70b: What exact word did I ask you to reply with in my very first message of this task? Reply with just that w |
| goose | llama-4-maverick | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as meta-llama/llama-4-maverick (the provider's alias of the same model) |
| goose | minimax-m3 | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as minimax/minimax-m3 (the provider's alias of the same model) |
| goose | mistral-medium-3.5 | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as mistralai/mistral-medium-3-5 (the provider's alias of the same model) |
| goose | muse-glimmer-30b | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as meta/muse-glimmer-30b (the provider's alias of the same model) |
| goose | muse-spark-1.1 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as meta/muse-spark-1.1 (the provider's alias of the same model) |
| goose | muse-spark-1.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as meta/muse-spark-1.2 (the provider's alias of the same model) |
| goose | muse-spark-1.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as meta/muse-spark-1.3 (the provider's alias of the same model) |
| goose | nemotron-3-super | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as nvidia/nemotron-3-super-120b-a12b (the provider's alias of the same model) |
| goose | nemotron-3-ultra | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as nvidia/nemotron-3-ultra-550b-a55b (the provider's alias of the same model) |
| goose | nemotron-3.5-lightning | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as nvidia/nemotron-3.5-lightning (the provider's alias of the same model) |
| goose | qwen3.7-flash | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as qwen/qwen3.7-flash (the provider's alias of the same model) |
| goose | qwen3.7-max | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as qwen/qwen3.7-max (the provider's alias of the same model) |
| goose | qwen3.7-plus | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as qwen/qwen3.7-plus (the provider's alias of the same model) |
| goose | qwen3.8-27b | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as qwen/qwen3.8-27b (the provider's alias of the same model) |
| goose | qwen3.8-flash | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as qwen/qwen3.8-flash (the provider's alias of the same model) |
| goose | qwen3.8-max | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as qwen/qwen3.8-max-0902 (the provider's alias of the same model) |
| goose | step-3.7-flash | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter | served as stepfun/step-3.7-flash (the provider's alias of the same model) |

55 pairs, 274 of 275 scenario runs passed.

Not run in this column, 11 pairs the provider serves that the harness did not run, with the reason:

- goose x claude-haiku-5.5: not run, not run in this column
- goose x claude-opus-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x claude-opus-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x claude-sonnet-5.5: not run, not run in this column
- goose x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-6-luna: not run, not run in this column
- goose x gpt-6-sol: not run, not run in this column
- goose x gpt-6.1-sol: not run, not run in this column
- goose x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)

## Provider: goose-tokenrouter

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| goose | claude-fable-5 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| goose | claude-fable-5-1 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| goose | claude-haiku-4.5 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter | served as claude-haiku-4-5-20251001 (the provider's alias of the same model) |
| goose | claude-opus-4.7 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter | served as claude-opus-4-7 (the provider's alias of the same model) |
| goose | claude-opus-4.8 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter | served as claude-opus-4-8 (the provider's alias of the same model) |
| goose | claude-sonnet-4.6 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter | served as claude-sonnet-4-6 (the provider's alias of the same model) |
| goose | claude-sonnet-5 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| goose | deepseek-v4-flash | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| goose | deepseek-v4-pro | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| goose | deepseek-v4.1-flash | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter | served as deepseek-flash (the provider's alias of the same model) |
| goose | gemini-3-flash-preview | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter | served as google/gemini-3-flash-preview (the provider's alias of the same model) |
| goose | gemini-3.1-pro-preview | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| goose | gemini-3.5-flash | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| goose | gemini-3.5-flash-lite | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| goose | gemini-3.6-flash | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| goose | gemini-3.7-flash | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter | served as google/gemini-3.7-flash (the provider's alias of the same model) |
| goose | gemini-3.8-flash | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| goose | glm-5.3 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| goose | glm-5.3-flash | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| goose | gpt-5.2 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter | served as gpt-5.2-2025-12-11 (the provider's alias of the same model) |
| goose | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| goose | gpt-5.4-mini | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter | served as gpt-5.4-mini-2026-03-17 (the provider's alias of the same model) |
| goose | gpt-5.5 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter | served as gpt-5.5-2026-04-23 (the provider's alias of the same model) |
| goose | gpt-5.6-luna | pass | pass | pass (gpt-5.4) | pass | FAIL | My TokenRouter | recycle: answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in my very first message of this task? Reply with just that wo |
| goose | gpt-5.6-sol | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| goose | gpt-5.6-terra | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| goose | grok-4.20 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as x-ai/grok-4.20 (the provider's alias of the same model) |
| goose | grok-4.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as x-ai/grok-4.3 (the provider's alias of the same model) |
| goose | grok-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| goose | grok-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| goose | grok-build-0.1 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as x-ai/grok-build-0.1 (the provider's alias of the same model) |
| goose | hunyuan-4-preview | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter | served as tencent/hy4-preview (the provider's alias of the same model) |
| goose | kimi-k2.7-code | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| goose | kimi-k3 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| goose | mistral-medium-3.5 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter | served as mistralai/mistral-medium-3-5 (the provider's alias of the same model) |
| goose | nemotron-3-super | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter | served as nvidia/nemotron-3-super-120b-a12b (the provider's alias of the same model) |
| goose | nemotron-3.5-lightning | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter | served as nvidia/nemotron-3.5-lightning (the provider's alias of the same model) |
| goose | qwen3.7-max | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| goose | qwen3.7-plus | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter | served as qwen/qwen3.7-plus (the provider's alias of the same model) |
| goose | qwen3.8-flash | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| goose | qwen3.8-max | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| goose | step-3.7-flash | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter | served as stepfun/step-3.7-flash (the provider's alias of the same model) |

42 pairs, 209 of 210 scenario runs passed.

Not run in this column, 8 pairs the provider serves that the harness did not run, with the reason:

- goose x claude-opus-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x claude-opus-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x claude-sonnet-5.5: not run, not run in this column
- goose x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-6-luna: not run, not run in this column
- goose x gpt-6-sol: not run, not run in this column
- goose x gpt-6.1-sol: not run, not run in this column

## Provider: goose-vercel

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| goose | claude-fable-5 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as anthropic/claude-fable-5 (the provider's alias of the same model) |
| goose | claude-fable-5-1 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as anthropic/claude-fable-5.1 (the provider's alias of the same model) |
| goose | claude-haiku-4.5 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as anthropic/claude-haiku-4.5 (the provider's alias of the same model) |
| goose | claude-opus-4.7 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as anthropic/claude-opus-4.7 (the provider's alias of the same model) |
| goose | claude-opus-4.8 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as anthropic/claude-opus-4.8 (the provider's alias of the same model) |
| goose | claude-sonnet-4.6 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as anthropic/claude-sonnet-4.6 (the provider's alias of the same model) |
| goose | claude-sonnet-5 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as anthropic/claude-sonnet-5 (the provider's alias of the same model) |
| goose | deepseek-v4-flash | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as deepseek/deepseek-v4-flash (the provider's alias of the same model) |
| goose | deepseek-v4-pro | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as deepseek/deepseek-v4-pro (the provider's alias of the same model) |
| goose | deepseek-v4.1-flash | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as deepseek/deepseek-v4.1-flash (the provider's alias of the same model) |
| goose | gemini-3-flash-preview | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as google/gemini-3-flash (the provider's alias of the same model) |
| goose | gemini-3.1-flash-lite | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as google/gemini-3.1-flash-lite (the provider's alias of the same model) |
| goose | gemini-3.1-pro-preview | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as google/gemini-3.1-pro-preview (the provider's alias of the same model) |
| goose | gemini-3.5-flash | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as google/gemini-3.5-flash (the provider's alias of the same model) |
| goose | gemini-3.5-flash-lite | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as google/gemini-3.5-flash-lite (the provider's alias of the same model) |
| goose | gemini-3.6-flash | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as google/gemini-3.6-flash (the provider's alias of the same model) |
| goose | gemini-3.7-flash | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as google/gemini-3.7-flash (the provider's alias of the same model) |
| goose | gemini-3.8-flash | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as google/gemini-3.8-flash (the provider's alias of the same model) |
| goose | glm-5.3 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as zai/glm-5.3 (the provider's alias of the same model) |
| goose | glm-5.3-flash | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as zai/glm-5.3-flash (the provider's alias of the same model) |
| goose | gpt-5.2 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as openai/gpt-5.2 (the provider's alias of the same model) |
| goose | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-5.4 (the provider's alias of the same model) |
| goose | gpt-5.4-mini | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as openai/gpt-5.4-mini (the provider's alias of the same model) |
| goose | gpt-5.5 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as openai/gpt-5.5 (the provider's alias of the same model) |
| goose | gpt-5.6-luna | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as openai/gpt-5.6-luna (the provider's alias of the same model) |
| goose | gpt-5.6-sol | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as openai/gpt-5.6-sol (the provider's alias of the same model) |
| goose | gpt-5.6-terra | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as openai/gpt-5.6-terra (the provider's alias of the same model) |
| goose | grok-4.1-fast | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.1-fast-reasoning (finding below) |
| goose | grok-4.20 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.20-reasoning (the provider's alias of the same model) |
| goose | grok-4.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.3 (the provider's alias of the same model) |
| goose | grok-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.5 (the provider's alias of the same model) |
| goose | grok-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.6 (the provider's alias of the same model) |
| goose | grok-build-0.1 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as spacexai/grok-build-0.1 (the provider's alias of the same model) |
| goose | hunyuan-3 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as tencent/hy3 (the provider's alias of the same model) |
| goose | hunyuan-4-preview | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as tencent/hy4-preview (the provider's alias of the same model) |
| goose | kimi-k2.7-code | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as moonshotai/kimi-k2.7-code (the provider's alias of the same model) |
| goose | kimi-k3 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as moonshotai/kimi-k3 (the provider's alias of the same model) |
| goose | ling-3.0-flash | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as inclusionai/ling-3.0-flash (the provider's alias of the same model) |
| goose | llama-3.3-70b | FAIL | n/a | n/a | n/a | n/a | Vercel AI Gateway | first: The turn failed: Ran into this error: Request failed: Bad request (400): undefined: This model doesn't support tool use in streaming mode..  |
| goose | llama-4-maverick | FAIL | n/a | n/a | n/a | n/a | Vercel AI Gateway | first: The turn failed: Ran into this error: Request failed: Request failed with status 405 Method Not Allowed at http://127.0.0.1:39571/v1/chat/co |
| goose | llama-4-scout | pass | pass | pass (gpt-5.6-sol) | FAIL | pass | Vercel AI Gateway | served as meta/llama-4-scout (the provider's alias of the same model) ; artifact: no file card (files: none); le named hello-goose.txt containing exactly the word HELLO, then reply DONE. GOOSE The model returned an empty r |
| goose | minimax-m3 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as minimax/minimax-m3 (the provider's alias of the same model) |
| goose | mistral-medium-3.5 | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as mistral/mistral-medium-3.5 (the provider's alias of the same model) |
| goose | muse-glimmer-30b | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as meta/muse-glimmer-30b (the provider's alias of the same model) |
| goose | muse-spark-1.1 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as meta/muse-spark-1.1 (the provider's alias of the same model) |
| goose | muse-spark-1.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as meta/muse-spark-1.2 (the provider's alias of the same model) |
| goose | muse-spark-1.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as meta/muse-spark-1.3 (the provider's alias of the same model) |
| goose | nemotron-3-super | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as nvidia/nemotron-3-super-120b-a12b (the provider's alias of the same model) |
| goose | nemotron-3-ultra | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as nvidia/nemotron-3-ultra-550b-a55b (the provider's alias of the same model) |
| goose | nemotron-3.5-lightning | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as nvidia/nemotron-3.5-lightning (the provider's alias of the same model) |
| goose | qwen3.7-flash | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as alibaba/qwen3.7-flash (the provider's alias of the same model) |
| goose | qwen3.7-max | pass | pass | pass (gpt-5.4) | FAIL | pass | Vercel AI Gateway | served as alibaba/qwen3.7-max (the provider's alias of the same model) ; artifact: The turn failed: Ran into this error: Server error: Upstream stream ended before terminal chunk.

Please retry if you think this is a transi |
| goose | qwen3.7-plus | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as alibaba/qwen3.7-plus (the provider's alias of the same model) |
| goose | qwen3.8-27b | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as alibaba/qwen3.8-27b (the provider's alias of the same model) |
| goose | qwen3.8-flash | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as alibaba/qwen3.8-flash (the provider's alias of the same model) |
| goose | qwen3.8-max | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as alibaba/qwen3.8-max (the provider's alias of the same model) |
| goose | step-3.7-flash | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway | served as stepfun/step-3.7-flash (the provider's alias of the same model) |

57 pairs, 268 of 272 scenario runs passed; 1 pairs served by another connection or as another model are findings, not counted.

Findings, pairs served by a connection other than the one under test or as a model other than the id asked for:

- goose x grok-4.1-fast: served as spacexai/grok-4.1-fast-reasoning (the CLI reports the model it ran)

Not run in this column, 9 pairs the provider serves that the harness did not run, with the reason:

- goose x claude-haiku-5.5: not run, not run in this column
- goose x claude-opus-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x claude-opus-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x claude-sonnet-5.5: not run, not run in this column
- goose x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-6-luna: not run, not run in this column
- goose x gpt-6-sol: not run, not run in this column
- goose x gpt-6.1-sol: not run, not run in this column

## Provider: grok-default

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| grok | claude-fable-5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 8% of input |
| grok | claude-fable-5-1 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 8% of input |
| grok | claude-haiku-4.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Anthropic, OpenRouter | served as claude-haiku-4-5-20251001 (the provider's alias of the same model) ; cache 10% of input |
| grok | claude-opus-4.7 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as claude-opus-4-7 (the provider's alias of the same model) ; cache 8% of input |
| grok | claude-opus-4.8 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as claude-opus-4-8 (the provider's alias of the same model) ; cache 8% of input |
| grok | claude-opus-5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 8% of input |
| grok | claude-opus-5.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as anthropic/claude-opus-5.5 (the provider's alias of the same model) ; cache 8% of input |
| grok | claude-sonnet-4.6 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Anthropic, OpenRouter | served as claude-sonnet-4-6 (the provider's alias of the same model) ; cache 10% of input |
| grok | claude-sonnet-5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 6% of input |
| grok | claude-sonnet-5.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as claude-sonnet-5-5 (the provider's alias of the same model) ; cache 8% of input |
| grok | claude-sonnet-5.5-direct | pass | pass | pass (gpt-6.1-sol) | pass | pass | Anthropic, OpenRouter | served as claude-sonnet-5-5 (finding below) ; cache 8% of input |
| grok | deepseek-v4-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as deepseek-v4.1-flash (finding below) ; cache 78% of input |
| grok | deepseek-v4-pro | pass | pass | pass (gpt-6.1-sol) | FAIL | pass | My TokenRouter, OpenRouter | artifact: The turn failed: Internal error: { "message": "empty response from model (reasoning_only)", "promptUsage": { "inputTokens": 71225, "outputTo ; retested once; first try: artifact The turn failed: Internal error: { "message": "empty response from model (reason ; cache 82% of input |
| grok | deepseek-v4.1-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 79% of input |
| grok | gemini-3-flash-preview | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 65% of input |
| grok | gemini-3.1-flash-lite | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as google/gemini-3.1-flash-lite (the provider's alias of the same model) ; cache 56% of input |
| grok | gemini-3.1-pro-preview | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 65% of input |
| grok | gemini-3.5-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 78% of input |
| grok | gemini-3.5-flash-lite | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 78% of input |
| grok | gemini-3.6-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 52% of input |
| grok | gemini-3.7-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 52% of input |
| grok | gemini-3.8-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 39% of input |
| grok | glm-5.3 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 79% of input |
| grok | glm-5.3-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 79% of input |
| grok | gpt-5.2 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Custom OpenAI Chat, OpenRouter | served as gpt-5.2-2025-12-11 (the provider's alias of the same model) ; cache 76% of input |
| grok | gpt-5.4 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as gpt-5.4-2026-03-05 (the provider's alias of the same model) ; cache 62% of input |
| grok | gpt-5.4-mini | pass | pass | pass (gpt-6.1-sol) | pass | pass | Custom OpenAI Chat, OpenRouter | served as gpt-5.4-mini-2026-03-17 (the provider's alias of the same model) ; cache 77% of input |
| grok | gpt-5.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Azure OpenAI E2, OpenRouter | served as gpt-5.5-2026-04-24 (the provider's alias of the same model) ; cache 77% of input |
| grok | gpt-5.6-luna | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 79% of input |
| grok | gpt-5.6-sol | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 79% of input |
| grok | gpt-5.6-terra | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 79% of input |
| grok | gpt-6-luna | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 80% of input |
| grok | gpt-6-sol | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 93% of input |
| grok | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter, My TokenRouter | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 66% of input |
| grok | grok-4.20 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as x-ai/grok-4.20 (the provider's alias of the same model) ; cache 63% of input |
| grok | grok-4.3 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as x-ai/grok-4.3 (the provider's alias of the same model) ; cache 80% of input |
| grok | grok-4.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 64% of input |
| grok | grok-4.6 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 83% of input |
| grok | grok-build-0.1 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as x-ai/grok-build-0.1 (the provider's alias of the same model) ; cache 83% of input |
| grok | hunyuan-4-preview | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as tencent/hy4-preview (the provider's alias of the same model) ; cache 82% of input |
| grok | kimi-k2.7-code | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | retested once; first try: artifact no file card (files: none); Create a file named hello-grok.txt containing exactl ; cache 79% of input |
| grok | kimi-k3 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | retested once; first try: first The turn failed: Internal error: "serialization error: invalid type: null, expec ; cache 79% of input |
| grok | llama-3.3-70b | pass | pass | pass (gpt-6.1-sol) | pass | pass | OpenRouter | served as meta-llama/llama-3.3-70b-instruct (the provider's alias of the same model) ; cache 62% of input |
| grok | mistral-medium-3.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as mistralai/mistral-medium-3-5 (the provider's alias of the same model) ; cache 79% of input |
| grok | muse-glimmer-30b | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as meta/muse-glimmer-30b (the provider's alias of the same model) ; cache 62% of input |
| grok | muse-spark-1.1 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as meta/muse-spark-1.1 (the provider's alias of the same model) ; cache 45% of input |
| grok | muse-spark-1.2 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as meta/muse-spark-1.2 (the provider's alias of the same model) ; cache 68% of input |
| grok | muse-spark-1.3 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as meta/muse-spark-1.3 (the provider's alias of the same model) ; cache 28% of input |
| grok | nemotron-3-super | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as nvidia/nemotron-3-super-120b-a12b (the provider's alias of the same model) ; cache 10% of input |
| grok | nemotron-3.5-lightning | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as nvidia/nemotron-3.5-lightning (the provider's alias of the same model) ; cache 55% of input |
| grok | qwen3.7-max | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 73% of input |
| grok | qwen3.7-plus | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 76% of input |
| grok | qwen3.8-27b | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as alibaba/qwen3.8-27b (the provider's alias of the same model) ; cache 71% of input |
| grok | qwen3.8-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 80% of input |
| grok | qwen3.8-max | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 79% of input |
| grok | step-3.7-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as stepfun/step-3.7-flash (the provider's alias of the same model) ; cache 78% of input |

56 pairs, 269 of 270 scenario runs passed; 2 pairs served by another connection or as another model are findings, not counted.

Findings, pairs served by a connection other than the one under test or as a model other than the id asked for:

- grok x claude-sonnet-5.5-direct: served as claude-sonnet-5-5 (the CLI reports the model it ran)
- grok x deepseek-v4-flash: served as deepseek-v4.1-flash (the CLI reports the model it ran)

## Provider: hermes-azure-e2

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| hermes | gpt-6-astra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 |  |

1 pairs, 5 of 5 scenario runs passed.

Not run in this column, 11 pairs the provider serves that the harness did not run, with the reason:

- hermes x gpt-5.2: not run, not run in this column
- hermes x gpt-5.3-codex: not run, not run in this column
- hermes x gpt-5.4: not run, not run in this column
- hermes x gpt-5.4-mini: not run, not run in this column
- hermes x gpt-5.5: not run, not run in this column
- hermes x gpt-5.6-luna: not run, not run in this column
- hermes x gpt-5.6-sol: not run, not run in this column
- hermes x gpt-5.6-terra: not run, not run in this column
- hermes x gpt-6-luna: not run, not run in this column
- hermes x gpt-6-sol: not run, not run in this column
- hermes x gpt-6.1-sol: not run, not run in this column

## Provider: kilo-default

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| kilo | claude-fable-5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | no prompt cache reads (finding below) |
| kilo | claude-fable-5-1 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | no prompt cache reads (finding below) |
| kilo | claude-haiku-4.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Custom Anthropic, OpenRouter | served as claude-haiku-4-5-20251001 (the provider's alias of the same model) ; retested once; first try:  ; cache 99% of input |
| kilo | claude-opus-4.7 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | no prompt cache reads (finding below) ; served as claude-opus-4-7 (the provider's alias of the same model) |
| kilo | claude-opus-4.8 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | no prompt cache reads (finding below) ; served as claude-opus-4-8 (the provider's alias of the same model) ; retested once; first try:  |
| kilo | claude-opus-5 | pass | pass | pass (gpt-6.1-sol) | FAIL | FAIL | My TokenRouter, OpenRouter | artifact: The turn failed: the provider declined the request (finish_reason content_filter) ; recycle: The turn failed: the provider declined the request (finish_reason content_filter) ; retested once; first try: artifact The turn failed: the provider declined the request (finish_reason content_filter; recycle The turn failed: the provider declined the request (finish_reason content_filter ; cache 0% of input |
| kilo | claude-opus-5.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as anthropic/claude-opus-5.5 (the provider's alias of the same model) ; cache 79% of input |
| kilo | claude-sonnet-4.6 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Custom Anthropic, OpenRouter | served as claude-sonnet-4-6 (the provider's alias of the same model) ; retested once; first try:  ; cache 99% of input |
| kilo | claude-sonnet-5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | no prompt cache reads (finding below) |
| kilo | claude-sonnet-5.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | no prompt cache reads (finding below) ; served as claude-sonnet-5-5 (the provider's alias of the same model) |
| kilo | claude-sonnet-5.5-direct | pass | pass | pass (gpt-6.1-sol) | pass | pass | Anthropic, OpenRouter | served as claude-sonnet-5-5 (finding below) ; retested once; first try:  ; cache 99% of input |
| kilo | deepseek-v4-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as deepseek-v4.1-flash (finding below) ; cache 77% of input |
| kilo | deepseek-v4-pro | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 76% of input |
| kilo | deepseek-v4.1-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 82% of input |
| kilo | gemini-3-flash-preview | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 64% of input |
| kilo | gemini-3.1-flash-lite | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as google/gemini-3.1-flash-lite (the provider's alias of the same model) ; cache 38% of input |
| kilo | gemini-3.1-pro-preview | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 48% of input |
| kilo | gemini-3.5-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 74% of input |
| kilo | gemini-3.5-flash-lite | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 37% of input |
| kilo | gemini-3.6-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 66% of input |
| kilo | gemini-3.7-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 64% of input |
| kilo | gemini-3.8-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 48% of input |
| kilo | glm-5.3 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 80% of input |
| kilo | glm-5.3-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 79% of input |
| kilo | gpt-5.2 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Custom OpenAI Chat, OpenRouter | served as gpt-5.2-2025-12-11 (the provider's alias of the same model) ; cache 78% of input |
| kilo | gpt-5.3-codex | pass | pass | n/a | pass | pass | Azure OpenAI E2 | cache 78% of input |
| kilo | gpt-5.4 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 79% of input |
| kilo | gpt-5.4-mini | pass | pass | pass (gpt-6.1-sol) | pass | pass | Custom OpenAI Chat, OpenRouter | served as gpt-5.4-mini-2026-03-17 (the provider's alias of the same model) ; cache 77% of input |
| kilo | gpt-5.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Azure OpenAI E2, OpenRouter | cache 78% of input |
| kilo | gpt-5.6-luna | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 100% of input |
| kilo | gpt-5.6-sol | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 100% of input |
| kilo | gpt-5.6-terra | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 100% of input |
| kilo | gpt-6-astra | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 100% of input |
| kilo | gpt-6-luna | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 100% of input |
| kilo | gpt-6-sol | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 100% of input |
| kilo | gpt-6.1-sol | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter, My TokenRouter | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 100% of input |
| kilo | grok-4.20 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as x-ai/grok-4.20 (the provider's alias of the same model) ; cache 80% of input |
| kilo | grok-4.3 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as x-ai/grok-4.3 (the provider's alias of the same model) ; cache 80% of input |
| kilo | grok-4.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 60% of input |
| kilo | grok-4.6 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 80% of input |
| kilo | grok-build-0.1 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as x-ai/grok-build-0.1 (the provider's alias of the same model) ; cache 69% of input |
| kilo | hunyuan-4-preview | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as tencent/hy4-preview (the provider's alias of the same model) ; cache 79% of input |
| kilo | kimi-k2.7-code | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 79% of input |
| kilo | kimi-k3 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 59% of input |
| kilo | llama-3.3-70b | pass | pass | pass (gpt-6.1-sol) | FAIL | pass | OpenRouter | served as meta-llama/llama-3.3-70b-instruct (the provider's alias of the same model) ; artifact: no file card (files: none); xactly the word HELLO, then reply DONE. KILO CODE write.write(content="HELLO", filePath="/data/workspaces/hsesse ; retested once; first try: first etch Webfetch Webfetch Webfetch Webfetch Webfetch Webfetch Webfetch Webfetch Web ; cache 60% of input |
| kilo | llama-4-maverick | pass | pass | pass (gpt-6.1-sol) | pass | pass | OpenRouter | served as meta-llama/llama-4-maverick (the provider's alias of the same model) ; cache 80% of input |
| kilo | mistral-medium-3.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as mistralai/mistral-medium-3-5 (the provider's alias of the same model) ; cache 79% of input |
| kilo | muse-glimmer-30b | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as meta/muse-glimmer-30b (the provider's alias of the same model) ; cache 60% of input |
| kilo | muse-spark-1.1 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as meta/muse-spark-1.1 (the provider's alias of the same model) ; cache 59% of input |
| kilo | muse-spark-1.2 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as meta/muse-spark-1.2 (the provider's alias of the same model) ; cache 79% of input |
| kilo | muse-spark-1.3 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as meta/muse-spark-1.3 (the provider's alias of the same model) ; cache 20% of input |
| kilo | nemotron-3-super | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as nvidia/nemotron-3-super-120b-a12b (the provider's alias of the same model) ; cache 0% of input |
| kilo | nemotron-3.5-lightning | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as nvidia/nemotron-3.5-lightning (the provider's alias of the same model) ; cache 54% of input |
| kilo | qwen3.7-max | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 76% of input |
| kilo | qwen3.7-plus | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 77% of input |
| kilo | qwen3.8-27b | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as alibaba/qwen3.8-27b (the provider's alias of the same model) ; cache 73% of input |
| kilo | qwen3.8-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 76% of input |
| kilo | qwen3.8-max | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 76% of input |
| kilo | step-3.7-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as stepfun/step-3.7-flash (the provider's alias of the same model) ; cache 81% of input |

59 pairs, 281 of 284 scenario runs passed; 2 pairs served by another connection or as another model are findings, not counted.

Findings, pairs served by a connection other than the one under test or as a model other than the id asked for:

- kilo x claude-fable-5: no prompt cache reads over 100948 input tokens (every call paid full price)
- kilo x claude-fable-5-1: no prompt cache reads over 100755 input tokens (every call paid full price)
- kilo x claude-opus-4.7: no prompt cache reads over 102906 input tokens (every call paid full price)
- kilo x claude-opus-4.8: no prompt cache reads over 101079 input tokens (every call paid full price)
- kilo x claude-sonnet-5: no prompt cache reads over 100846 input tokens (every call paid full price)
- kilo x claude-sonnet-5.5: no prompt cache reads over 100807 input tokens (every call paid full price)
- kilo x claude-sonnet-5.5-direct: served as claude-sonnet-5-5 (the CLI reports the model it ran)
- kilo x deepseek-v4-flash: served as deepseek-v4.1-flash (the CLI reports the model it ran)

## Provider: minimax-default

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| minimax | claude-fable-5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | no prompt cache reads (finding below) |
| minimax | claude-fable-5-1 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | no prompt cache reads (finding below) |
| minimax | claude-haiku-4.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Anthropic, OpenRouter | no prompt cache reads (finding below) ; served as claude-haiku-4-5-20251001 (the provider's alias of the same model) |
| minimax | claude-opus-4.7 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | no prompt cache reads (finding below) ; served as claude-opus-4-7 (the provider's alias of the same model) |
| minimax | claude-opus-4.8 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | no prompt cache reads (finding below) ; served as claude-opus-4-8 (the provider's alias of the same model) |
| minimax | claude-opus-5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | no prompt cache reads (finding below) |
| minimax | claude-opus-5.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | no prompt cache reads (finding below) ; served as anthropic/claude-opus-5.5 (the provider's alias of the same model) |
| minimax | claude-sonnet-4.6 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Anthropic, OpenRouter | no prompt cache reads (finding below) ; served as claude-sonnet-4-6 (the provider's alias of the same model) |
| minimax | claude-sonnet-5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | no prompt cache reads (finding below) |
| minimax | claude-sonnet-5.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | no prompt cache reads (finding below) ; served as claude-sonnet-5-5 (the provider's alias of the same model) |
| minimax | claude-sonnet-5.5-direct | pass | pass | pass (gpt-6.1-sol) | pass | pass | Anthropic, OpenRouter | no prompt cache reads (finding below) ; served as claude-sonnet-5-5 (finding below) |
| minimax | deepseek-v4-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as deepseek-v4.1-flash (finding below) ; cache 61% of input |
| minimax | deepseek-v4-pro | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 64% of input |
| minimax | deepseek-v4.1-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 72% of input |
| minimax | gemini-3-flash-preview | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 57% of input |
| minimax | gemini-3.1-flash-lite | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as google/gemini-3.1-flash-lite (the provider's alias of the same model) ; cache 57% of input |
| minimax | gemini-3.1-pro-preview | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 28% of input |
| minimax | gemini-3.5-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 57% of input |
| minimax | gemini-3.5-flash-lite | pass | pass | pass (gpt-6.1-sol) | FAIL | pass | My TokenRouter, OpenRouter | artifact: The turn failed: Conversation history could not be safely updated. Please retry. ; retested once; first try: artifact The turn failed: Conversation history could not be safely updated. Please retry. ; cache 43% of input |
| minimax | gemini-3.6-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 32% of input |
| minimax | gemini-3.7-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 21% of input |
| minimax | gemini-3.8-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 29% of input |
| minimax | glm-5.3 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 68% of input |
| minimax | glm-5.3-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 67% of input |
| minimax | gpt-5.2 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Custom OpenAI Chat, OpenRouter | served as gpt-5.2-2025-12-11 (the provider's alias of the same model) ; cache 66% of input |
| minimax | gpt-5.4 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as gpt-5.4-2026-03-05 (the provider's alias of the same model) ; cache 66% of input |
| minimax | gpt-5.4-mini | pass | pass | pass (gpt-6.1-sol) | pass | pass | Custom OpenAI Chat, OpenRouter | served as gpt-5.4-mini-2026-03-17 (the provider's alias of the same model) ; cache 70% of input |
| minimax | gpt-5.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Azure OpenAI E2, OpenRouter | served as gpt-5.5-2026-04-24 (the provider's alias of the same model) ; cache 65% of input |
| minimax | gpt-5.6-luna | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 71% of input |
| minimax | gpt-5.6-sol | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 71% of input |
| minimax | gpt-5.6-terra | pass | pass | pass (gpt-6.1-sol) | FAIL | pass | My TokenRouter, OpenRouter | artifact: no file card (files: none); Create a file named hello-minimax.txt containing exactly the word HELLO, then reply DONE. MINIMAX CODE DONE ; retested once; first try: artifact no file card (files: none); Create a file named hello-minimax.txt containing exa ; cache 59% of input |
| minimax | gpt-6-luna | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 71% of input |
| minimax | gpt-6-sol | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 71% of input |
| minimax | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter, My TokenRouter | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 66% of input |
| minimax | grok-4.20 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as x-ai/grok-4.20 (the provider's alias of the same model) ; cache 58% of input |
| minimax | grok-4.3 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as x-ai/grok-4.3 (the provider's alias of the same model) ; cache 68% of input |
| minimax | grok-4.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 68% of input |
| minimax | grok-4.6 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 47% of input |
| minimax | grok-build-0.1 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as x-ai/grok-build-0.1 (the provider's alias of the same model) ; cache 72% of input |
| minimax | hunyuan-4-preview | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as tencent/hy4-preview (the provider's alias of the same model) ; cache 67% of input |
| minimax | kimi-k2.7-code | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 66% of input |
| minimax | kimi-k3 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 77% of input |
| minimax | llama-3.3-70b | pass | pass | pass (gpt-6.1-sol) | pass | pass | OpenRouter | served as meta-llama/llama-3.3-70b-instruct (the provider's alias of the same model) ; retested once; first try: artifact the cards do not match the record: cards [model.txt,model.txt,hello-minimax.txt] ; cache 63% of input |
| minimax | minimax-m3 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as minimax/minimax-m3 (the provider's alias of the same model) ; cache 68% of input |
| minimax | mistral-medium-3.5 | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as mistralai/mistral-medium-3-5 (the provider's alias of the same model) ; cache 68% of input |
| minimax | muse-glimmer-30b | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as meta/muse-glimmer-30b (the provider's alias of the same model) ; cache 50% of input |
| minimax | muse-spark-1.1 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as meta/muse-spark-1.1 (the provider's alias of the same model) ; cache 50% of input |
| minimax | muse-spark-1.2 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as meta/muse-spark-1.2 (the provider's alias of the same model) ; cache 51% of input |
| minimax | muse-spark-1.3 | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as meta/muse-spark-1.3 (the provider's alias of the same model) ; cache 0% of input |
| minimax | nemotron-3-super | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as nvidia/nemotron-3-super-120b-a12b (the provider's alias of the same model) ; cache 0% of input |
| minimax | nemotron-3.5-lightning | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as nvidia/nemotron-3.5-lightning (the provider's alias of the same model) ; cache 49% of input |
| minimax | qwen3.7-max | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 63% of input |
| minimax | qwen3.7-plus | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 68% of input |
| minimax | qwen3.8-27b | pass | pass | pass (gpt-6.1-sol) | pass | pass | Vercel AI Gateway, OpenRouter | served as alibaba/qwen3.8-27b (the provider's alias of the same model) ; cache 60% of input |
| minimax | qwen3.8-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 69% of input |
| minimax | qwen3.8-max | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | cache 66% of input |
| minimax | step-3.7-flash | pass | pass | pass (gpt-6.1-sol) | pass | pass | My TokenRouter, OpenRouter | served as stepfun/step-3.7-flash (the provider's alias of the same model) ; cache 65% of input |

57 pairs, 273 of 275 scenario runs passed; 2 pairs served by another connection or as another model are findings, not counted.

Findings, pairs served by a connection other than the one under test or as a model other than the id asked for:

- minimax x claude-fable-5: no prompt cache reads over 81472 input tokens (every call paid full price)
- minimax x claude-fable-5-1: no prompt cache reads over 81293 input tokens (every call paid full price)
- minimax x claude-haiku-4.5: no prompt cache reads over 62761 input tokens (every call paid full price)
- minimax x claude-opus-4.7: no prompt cache reads over 83407 input tokens (every call paid full price)
- minimax x claude-opus-4.8: no prompt cache reads over 81281 input tokens (every call paid full price)
- minimax x claude-opus-5: no prompt cache reads over 81303 input tokens (every call paid full price)
- minimax x claude-opus-5.5: no prompt cache reads over 81338 input tokens (every call paid full price)
- minimax x claude-sonnet-4.6: no prompt cache reads over 62404 input tokens (every call paid full price)
- minimax x claude-sonnet-5: no prompt cache reads over 81655 input tokens (every call paid full price)
- minimax x claude-sonnet-5.5: no prompt cache reads over 81476 input tokens (every call paid full price)
- minimax x claude-sonnet-5.5-direct: served as claude-sonnet-5-5 (the CLI reports the model it ran)
- minimax x claude-sonnet-5.5-direct: no prompt cache reads over 81403 input tokens (every call paid full price)
- minimax x deepseek-v4-flash: served as deepseek-v4.1-flash (the CLI reports the model it ran)

## Provider: omp-anthropic

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| omp | claude-fable-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| omp | claude-fable-5-1 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |
| omp | claude-haiku-4.5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | served as claude-haiku-4-5-20251001 (the provider's alias of the same model) |
| omp | claude-opus-4.7 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | served as claude-opus-4-7 (the provider's alias of the same model) |
| omp | claude-opus-4.8 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | served as claude-opus-4-8 (the provider's alias of the same model) |
| omp | claude-opus-5 | pass | pass | pass (claude-fable-5) | pass | pass | Anthropic |  |
| omp | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic | served as claude-sonnet-4-6 (the provider's alias of the same model) |
| omp | claude-sonnet-5 | pass | pass | pass (claude-opus-5) | pass | pass | Anthropic |  |

8 pairs, 40 of 40 scenario runs passed.

Not run in this column, 3 pairs the provider serves that the harness did not run, with the reason:

- omp x claude-haiku-5.5: not run, not run in this column
- omp x claude-opus-5.5: not run, not run in this column
- omp x claude-sonnet-5.5: not run, not run in this column

## Provider: omp-azure-e2

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| omp | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 |  |
| omp | gpt-5.3-codex | pass | pass | n/a | pass | pass | Azure OpenAI E2 |  |
| omp | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 |  |
| omp | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 |  |
| omp | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 |  |
| omp | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 |  |
| omp | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Azure OpenAI E2 |  |
| omp | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Azure OpenAI E2 |  |

8 pairs, 39 of 39 scenario runs passed.

Not run in this column, 4 pairs the provider serves that the harness did not run, with the reason:

- omp x gpt-6-astra: not run, not run in this column
- omp x gpt-6-luna: not run, not run in this column
- omp x gpt-6-sol: not run, not run in this column
- omp x gpt-6.1-sol: not run, not run in this column

## Provider: omp-google

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| omp | gemini-3-flash-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| omp | gemini-3.1-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| omp | gemini-3.1-pro-preview | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| omp | gemini-3.5-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| omp | gemini-3.5-flash-lite | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| omp | gemini-3.6-flash | pass | pass | pass (gemini-3.8-flash) | pass | pass | Google AI Studio |  |
| omp | gemini-3.7-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |
| omp | gemini-3.8-flash | pass | pass | pass (gemini-3.6-flash) | pass | pass | Google AI Studio |  |

8 pairs, 40 of 40 scenario runs passed.

## Provider: omp-openai

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| omp | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| omp | gpt-5.3-codex | pass | pass | n/a | pass | pass | OpenAI |  |
| omp | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| omp | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| omp | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| omp | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| omp | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | OpenAI |  |
| omp | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |

8 pairs, 39 of 39 scenario runs passed.

Not run in this column, 4 pairs the provider serves that the harness did not run, with the reason:

- omp x gpt-6-astra: not run, not run in this column
- omp x gpt-6-luna: not run, not run in this column
- omp x gpt-6-sol: not run, not run in this column
- omp x gpt-6.1-sol: not run, not run in this column

## Provider: omp-openrouter

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| omp | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as anthropic/claude-fable-5 (the provider's alias of the same model) |
| omp | claude-fable-5-1 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as anthropic/claude-fable-5.1 (the provider's alias of the same model) |
| omp | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as anthropic/claude-haiku-4.5 (the provider's alias of the same model) |
| omp | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as anthropic/claude-opus-4.7 (the provider's alias of the same model) |
| omp | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as anthropic/claude-opus-4.8 (the provider's alias of the same model) |
| omp | claude-opus-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as anthropic/claude-opus-5 (the provider's alias of the same model) |
| omp | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as anthropic/claude-sonnet-4.6 (the provider's alias of the same model) |
| omp | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as anthropic/claude-sonnet-5 (the provider's alias of the same model) |
| omp | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as deepseek/deepseek-v4-flash (the provider's alias of the same model) |
| omp | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as deepseek/deepseek-v4-pro (the provider's alias of the same model) |
| omp | deepseek-v4.1-flash | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as deepseek/deepseek-v4.1-flash (the provider's alias of the same model) |
| omp | gemini-3-flash-preview | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as google/gemini-3-flash-preview (the provider's alias of the same model) |
| omp | gemini-3.1-flash-lite | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as google/gemini-3.1-flash-lite (the provider's alias of the same model) |
| omp | gemini-3.1-pro-preview | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as google/gemini-3.1-pro-preview (the provider's alias of the same model) |
| omp | gemini-3.5-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as google/gemini-3.5-flash (the provider's alias of the same model) |
| omp | gemini-3.5-flash-lite | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as google/gemini-3.5-flash-lite (the provider's alias of the same model) |
| omp | gemini-3.6-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as google/gemini-3.6-flash (the provider's alias of the same model) |
| omp | gemini-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as google/gemini-3.7-flash (the provider's alias of the same model) |
| omp | gemini-3.8-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as google/gemini-3.8-flash (the provider's alias of the same model) |
| omp | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as z-ai/glm-5.3 (the provider's alias of the same model) |
| omp | glm-5.3-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as z-ai/glm-5.3-flash (the provider's alias of the same model) |
| omp | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as openai/gpt-5.2 (the provider's alias of the same model) |
| omp | gpt-5.3-codex | pass | pass | n/a | pass | pass | OpenRouter | served as openai/gpt-5.3-codex (the provider's alias of the same model) |
| omp | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as openai/gpt-5.4 (the provider's alias of the same model) |
| omp | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as openai/gpt-5.4-mini (the provider's alias of the same model) |
| omp | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as openai/gpt-5.5 (the provider's alias of the same model) |
| omp | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as openai/gpt-5.6-luna (the provider's alias of the same model) |
| omp | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | OpenRouter | served as openai/gpt-5.6-sol (the provider's alias of the same model) |
| omp | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as openai/gpt-5.6-terra (the provider's alias of the same model) |
| omp | grok-4.20 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as x-ai/grok-4.20 (the provider's alias of the same model) |
| omp | grok-4.3 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as x-ai/grok-4.3 (the provider's alias of the same model) |
| omp | grok-4.5 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as x-ai/grok-4.5 (the provider's alias of the same model) |
| omp | grok-4.6 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as x-ai/grok-4.6 (the provider's alias of the same model) |
| omp | grok-build-0.1 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as x-ai/grok-build-0.1 (the provider's alias of the same model) |
| omp | hunyuan-4-preview | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as tencent/hy4-preview (the provider's alias of the same model) |
| omp | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as moonshotai/kimi-k2.7-code (the provider's alias of the same model) |
| omp | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as moonshotai/kimi-k3 (the provider's alias of the same model) |
| omp | llama-3.3-70b | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as meta-llama/llama-3.3-70b-instruct (the provider's alias of the same model) |
| omp | llama-4-maverick | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as meta-llama/llama-4-maverick (the provider's alias of the same model) |
| omp | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as mistralai/mistral-medium-3-5 (the provider's alias of the same model) |
| omp | muse-glimmer-30b | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as meta/muse-glimmer-30b (the provider's alias of the same model) |
| omp | muse-spark-1.1 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as meta/muse-spark-1.1 (the provider's alias of the same model) |
| omp | muse-spark-1.2 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as meta/muse-spark-1.2 (the provider's alias of the same model) |
| omp | muse-spark-1.3 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as meta/muse-spark-1.3 (the provider's alias of the same model) |
| omp | nemotron-3-super | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as nvidia/nemotron-3-super-120b-a12b (the provider's alias of the same model) |
| omp | nemotron-3.5-lightning | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as nvidia/nemotron-3.5-lightning (the provider's alias of the same model) |
| omp | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as qwen/qwen3.7-max (the provider's alias of the same model) |
| omp | qwen3.7-plus | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as qwen/qwen3.7-plus (the provider's alias of the same model) |
| omp | qwen3.8-27b | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as qwen/qwen3.8-27b (the provider's alias of the same model) |
| omp | qwen3.8-flash | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as qwen/qwen3.8-flash (the provider's alias of the same model) |
| omp | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as qwen/qwen3.8-max-0902 (the provider's alias of the same model) |
| omp | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as stepfun/step-3.7-flash (the provider's alias of the same model) |

52 pairs, 259 of 259 scenario runs passed.

Not run in this column, 14 pairs the provider serves that the harness did not run, with the reason:

- omp x claude-haiku-5.5: not run, not run in this column
- omp x claude-opus-5.5: not run, not run in this column
- omp x claude-sonnet-5.5: not run, not run in this column
- omp x gpt-6-astra: not run, not run in this column
- omp x gpt-6-luna: not run, not run in this column
- omp x gpt-6-sol: not run, not run in this column
- omp x gpt-6.1-sol: not run, not run in this column
- omp x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)

## Provider: omp-tokenrouter

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| omp | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as anthropic/claude-fable-5 (the provider's alias of the same model) |
| omp | claude-fable-5-1 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as anthropic/claude-fable-5.1 (the provider's alias of the same model) |
| omp | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as anthropic/claude-haiku-4.5 (the provider's alias of the same model) |
| omp | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as anthropic/claude-opus-4.7 (the provider's alias of the same model) |
| omp | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as anthropic/claude-opus-4.8 (the provider's alias of the same model) |
| omp | claude-opus-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as anthropic/claude-opus-5 (the provider's alias of the same model) |
| omp | claude-sonnet-4.6 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as anthropic/claude-sonnet-4.6 (the provider's alias of the same model) |
| omp | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as anthropic/claude-sonnet-5 (the provider's alias of the same model) |
| omp | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as deepseek/deepseek-v4-flash (the provider's alias of the same model) |
| omp | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as deepseek/deepseek-v4-pro (the provider's alias of the same model) |
| omp | deepseek-v4.1-flash | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as deepseek/deepseek-v4.1-flash (the provider's alias of the same model) |
| omp | gemini-3-flash-preview | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as google/gemini-3-flash-preview (the provider's alias of the same model) |
| omp | gemini-3.1-pro-preview | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as google/gemini-3.1-pro-preview (the provider's alias of the same model) |
| omp | gemini-3.5-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as google/gemini-3.5-flash (the provider's alias of the same model) |
| omp | gemini-3.5-flash-lite | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as google/gemini-3.5-flash-lite (the provider's alias of the same model) |
| omp | gemini-3.6-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as google/gemini-3.6-flash (the provider's alias of the same model) |
| omp | gemini-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as google/gemini-3.7-flash (the provider's alias of the same model) |
| omp | gemini-3.8-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as google/gemini-3.8-flash (the provider's alias of the same model) |
| omp | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as z-ai/glm-5.3 (the provider's alias of the same model) |
| omp | glm-5.3-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as z-ai/glm-5.3-flash (the provider's alias of the same model) |
| omp | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as openai/gpt-5.2 (the provider's alias of the same model) |
| omp | gpt-5.3-codex | pass | pass | n/a | pass | pass | My TokenRouter | served as openai/gpt-5.3-codex (the provider's alias of the same model) |
| omp | gpt-5.4 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as openai/gpt-5.4 (the provider's alias of the same model) |
| omp | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as openai/gpt-5.4-mini (the provider's alias of the same model) |
| omp | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as openai/gpt-5.5 (the provider's alias of the same model) |
| omp | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as openai/gpt-5.6-luna (the provider's alias of the same model) |
| omp | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | My TokenRouter | served as openai/gpt-5.6-sol (the provider's alias of the same model) |
| omp | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as openai/gpt-5.6-terra (the provider's alias of the same model) |
| omp | grok-4.20 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as x-ai/grok-4.20-beta (the provider's alias of the same model) |
| omp | grok-4.3 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as x-ai/grok-4.3 (the provider's alias of the same model) |
| omp | grok-4.5 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as x-ai/grok-4.5 (the provider's alias of the same model) |
| omp | grok-4.6 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as x-ai/grok-4.6 (the provider's alias of the same model) |
| omp | grok-build-0.1 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as x-ai/grok-build-0.1 (the provider's alias of the same model) |
| omp | hunyuan-4-preview | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as tencent/hy4-preview (the provider's alias of the same model) |
| omp | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as moonshotai/kimi-k2.7-code (the provider's alias of the same model) |
| omp | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as moonshotai/kimi-k3 (the provider's alias of the same model) |
| omp | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as mistralai/mistral-medium-3-5 (the provider's alias of the same model) |
| omp | nemotron-3-super | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as nvidia/nemotron-3-super-120b-a12b (the provider's alias of the same model) |
| omp | nemotron-3.5-lightning | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as nvidia/nemotron-3.5-lightning (the provider's alias of the same model) |
| omp | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as qwen/qwen3.7-max (the provider's alias of the same model) |
| omp | qwen3.7-plus | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as qwen/qwen3.7-plus (the provider's alias of the same model) |
| omp | qwen3.8-flash | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as qwen/qwen3.8-flash (the provider's alias of the same model) |
| omp | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as qwen/qwen3.8-max (the provider's alias of the same model) |
| omp | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as stepfun/step-3.7-flash (the provider's alias of the same model) |

44 pairs, 219 of 219 scenario runs passed.

Not run in this column, 6 pairs the provider serves that the harness did not run, with the reason:

- omp x claude-opus-5.5: not run, not run in this column
- omp x claude-sonnet-5.5: not run, not run in this column
- omp x gpt-6-astra: not run, not run in this column
- omp x gpt-6-luna: not run, not run in this column
- omp x gpt-6-sol: not run, not run in this column
- omp x gpt-6.1-sol: not run, not run in this column

## Provider: omp-vercel

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| omp | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as anthropic/claude-fable-5 (the provider's alias of the same model) |
| omp | claude-fable-5-1 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as anthropic/claude-fable-5.1 (the provider's alias of the same model) |
| omp | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as anthropic/claude-haiku-4.5 (the provider's alias of the same model) |
| omp | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as anthropic/claude-opus-4.7 (the provider's alias of the same model) |
| omp | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as anthropic/claude-opus-4.8 (the provider's alias of the same model) |
| omp | claude-opus-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as anthropic/claude-opus-5 (the provider's alias of the same model) |
| omp | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as anthropic/claude-sonnet-4.6 (the provider's alias of the same model) |
| omp | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as anthropic/claude-sonnet-5 (the provider's alias of the same model) |
| omp | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as deepseek/deepseek-v4-flash (the provider's alias of the same model) |
| omp | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as deepseek/deepseek-v4-pro (the provider's alias of the same model) |
| omp | deepseek-v4.1-flash | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as deepseek/deepseek-v4.1-flash (the provider's alias of the same model) |
| omp | gemini-3-flash-preview | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as google/gemini-3-flash (the provider's alias of the same model) |
| omp | gemini-3.1-flash-lite | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as google/gemini-3.1-flash-lite (the provider's alias of the same model) |
| omp | gemini-3.1-pro-preview | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as google/gemini-3.1-pro-preview (the provider's alias of the same model) |
| omp | gemini-3.5-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as google/gemini-3.5-flash (the provider's alias of the same model) |
| omp | gemini-3.5-flash-lite | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as google/gemini-3.5-flash-lite (the provider's alias of the same model) |
| omp | gemini-3.6-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as google/gemini-3.6-flash (the provider's alias of the same model) |
| omp | gemini-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as google/gemini-3.7-flash (the provider's alias of the same model) |
| omp | gemini-3.8-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as google/gemini-3.8-flash (the provider's alias of the same model) |
| omp | glm-5.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as zai/glm-5.3 (the provider's alias of the same model) |
| omp | glm-5.3-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as zai/glm-5.3-flash (the provider's alias of the same model) |
| omp | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-5.2 (the provider's alias of the same model) |
| omp | gpt-5.3-codex | pass | pass | n/a | pass | pass | Vercel AI Gateway | served as openai/gpt-5.3-codex (the provider's alias of the same model) |
| omp | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-5.4 (the provider's alias of the same model) |
| omp | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-5.4-mini (the provider's alias of the same model) |
| omp | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-5.5 (the provider's alias of the same model) |
| omp | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-5.6-luna (the provider's alias of the same model) |
| omp | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | Vercel AI Gateway | served as openai/gpt-5.6-sol (the provider's alias of the same model) |
| omp | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-5.6-terra (the provider's alias of the same model) |
| omp | grok-4.1-fast | FAIL | n/a | n/a | n/a | n/a | Vercel AI Gateway | served as spacexai/grok-4.1-fast-reasoning (finding below) ; first: The turn failed: Stream error occurred |
| omp | grok-4.20 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.20-reasoning (the provider's alias of the same model) |
| omp | grok-4.3 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.3 (the provider's alias of the same model) |
| omp | grok-4.5 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.5 (the provider's alias of the same model) |
| omp | grok-4.6 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.6 (the provider's alias of the same model) |
| omp | grok-build-0.1 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as spacexai/grok-build-0.1 (the provider's alias of the same model) |
| omp | hunyuan-4-preview | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as tencent/hy4-preview (the provider's alias of the same model) |
| omp | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as moonshotai/kimi-k2.7-code (the provider's alias of the same model) |
| omp | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as moonshotai/kimi-k3 (the provider's alias of the same model) |
| omp | llama-3.3-70b | FAIL | n/a | n/a | n/a | n/a | Vercel AI Gateway | served as meta/llama-3.3-70b (the provider's alias of the same model) ; first: The turn failed: 400 undefined: The maximum tokens you requested exceeds the model limit of 8192. Try again with a maximum tokens value that |
| omp | llama-4-maverick | FAIL | n/a | n/a | n/a | n/a | Vercel AI Gateway | served as meta/llama-4-maverick (the provider's alias of the same model) ; first: The turn failed: 405 Tool calling is not supported for model: meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8
Tool calling is not supporte |
| omp | llama-4-scout | pass | pass | pass (gpt-6-astra) | FAIL | FAIL | Vercel AI Gateway | served as meta/llama-4-scout (the provider's alias of the same model) ; artifact: no file card (files: none); Create a file named hello-omp.txt containing exactly the word HELLO, then reply DONE. OH MY PI WRITE { "path": " ; recycle: answered without M1-llama-4-scout: What exact word did I ask you to reply with in my very first message of this task? Reply with just that w |
| omp | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as mistral/mistral-medium-3.5 (the provider's alias of the same model) |
| omp | muse-glimmer-30b | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as meta/muse-glimmer-30b (the provider's alias of the same model) |
| omp | muse-spark-1.1 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as meta/muse-spark-1.1 (the provider's alias of the same model) |
| omp | muse-spark-1.2 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as meta/muse-spark-1.2 (the provider's alias of the same model) |
| omp | muse-spark-1.3 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as meta/muse-spark-1.3 (the provider's alias of the same model) |
| omp | nemotron-3-super | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as nvidia/nemotron-3-super-120b-a12b (the provider's alias of the same model) |
| omp | nemotron-3.5-lightning | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as nvidia/nemotron-3.5-lightning (the provider's alias of the same model) |
| omp | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as alibaba/qwen3.7-max (the provider's alias of the same model) |
| omp | qwen3.7-plus | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as alibaba/qwen3.7-plus (the provider's alias of the same model) |
| omp | qwen3.8-27b | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as alibaba/qwen3.8-27b (the provider's alias of the same model) |
| omp | qwen3.8-flash | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as alibaba/qwen3.8-flash (the provider's alias of the same model) |
| omp | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as alibaba/qwen3.8-max (the provider's alias of the same model) |
| omp | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as stepfun/step-3.7-flash (the provider's alias of the same model) |

54 pairs, 252 of 256 scenario runs passed; 1 pairs served by another connection or as another model are findings, not counted.

Findings, pairs served by a connection other than the one under test or as a model other than the id asked for:

- omp x grok-4.1-fast: served as spacexai/grok-4.1-fast-reasoning (the CLI reports the model it ran)

Not run in this column, 12 pairs the provider serves that the harness did not run, with the reason:

- omp x claude-haiku-5.5: not run, not run in this column
- omp x claude-opus-5.5: not run, not run in this column
- omp x claude-sonnet-5.5: not run, not run in this column
- omp x gpt-6-astra: not run, not run in this column
- omp x gpt-6-luna: not run, not run in this column
- omp x gpt-6-sol: not run, not run in this column
- omp x gpt-6.1-sol: not run, not run in this column
- omp x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)

## Provider: openai

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| aider | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | OpenAI |  |
| aider | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | OpenAI |  |
| aider | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenAI | cache 45% of input |
| cline | gpt-5.2 | pass | pass | pass (gpt-5.4) | pass | pass | OpenAI |  |
| cline | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| cline | gpt-5.4-mini | pass | pass | pass (gpt-5.4) | pass | pass | OpenAI |  |
| cline | gpt-5.5 | pass | pass | pass (gpt-5.4) | pass | pass | OpenAI |  |
| cline | gpt-5.6-luna | pass | pass | pass (gpt-5.4) | pass | pass | OpenAI |  |
| cline | gpt-5.6-sol | pass | pass | pass (gpt-5.4) | pass | pass | OpenAI |  |
| cline | gpt-5.6-terra | pass | pass | pass (gpt-5.4) | pass | pass | OpenAI |  |
| cline | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | OpenAI |  |
| cline | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | OpenAI |  |
| cline | gpt-6.1-sol | FAIL | n/a | n/a | n/a | n/a | OpenAI | 1 turn(s) unlabelled (finding below) ; first: The turn failed: Unsupported value: 'reasoning_effort' does not support 'none' with this model. Supported values are: 'low', 'medium', 'high |
| codex | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| codex | gpt-5.3-codex | pass | pass | pass (gpt-5.6-luna) | FAIL | FAIL | OpenAI | artifact: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-luna: its tools are not available there. Start a new task for gpt-5.3 ; recycle: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-luna: its tools are not available there. Start a new task for gpt-5.3 ; retested once; first try: artifact Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-sol: its ; recycle Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-sol: its  |
| codex | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| codex | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| codex | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| codex | gpt-5.6-luna | pass | pass | FAIL (gpt-5.3-codex) | pass | FAIL | OpenAI | switch: Codex cannot run gpt-5.3-codex in a task that has already used gpt-5.6-luna: its tools are not available there. Start a new task for gpt-5.3 ; recycle: answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in my very first message of this task? Reply with just that wo ; retested once; first try: recycle answered without M1-gpt-5.6-luna: What exact word did I ask you to reply with in |
| codex | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | OpenAI |  |
| codex | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| codex | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | OpenAI |  |
| codex | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | FAIL | OpenAI | recycle: answered without M1-gpt-6-luna: What exact word did I ask you to reply with in my very first message of this task? Reply with just that word ; recycle: answered without M1-gpt-6-luna: What exact word did I ask you to reply with in my very first message of this ta |
| codex | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| codex | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenAI | 4 turn(s) unlabelled (finding below) ; cache 58% of input |
| dsh | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| dsh | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| dsh | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| dsh | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| dsh | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| dsh | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| dsh | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | OpenAI |  |
| dsh | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| dsh | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | OpenAI |  |
| dsh | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| dsh | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| dsh | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenAI | 4 turn(s) unlabelled (finding below) ; cache 100% of input |
| goose | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenAI | cache 52% of input |
| hermes | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| hermes | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| hermes | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| hermes | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| hermes | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| hermes | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| hermes | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | OpenAI |  |
| hermes | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| hermes | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | OpenAI |  |
| hermes | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| hermes | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| hermes | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenAI | cache 0% of input |
| kimi | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | OpenAI |  |
| kimi | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | OpenAI |  |
| kimi | gpt-6.1-sol | FAIL | n/a | n/a | n/a | n/a | OpenAI | 1 turn(s) unlabelled (finding below) ; first: The turn failed: error: failed to run prompt: provider.api_error: 400 Unsupported value: 'reasoning_effort' does not support 'none' with thi |
| omp | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | OpenAI |  |
| omp | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| omp | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| omp | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenAI | 1 turn(s) unlabelled (finding below) ; cache 100% of input |
| opencode | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| opencode | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| opencode | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| opencode | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| opencode | gpt-5.5 | pass | pass | n/a | pass | pass | OpenAI | retested once; first try: artifact no file card (files: none); Create a file named hello-opencode.txt containing ex |
| opencode | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| opencode | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | OpenAI |  |
| opencode | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| opencode | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | OpenAI |  |
| opencode | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| opencode | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| opencode | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenAI | cache 100% of input |
| openhands | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | OpenAI |  |
| openhands | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | OpenAI |  |
| openhands | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenAI | cache 0% of input |
| pi | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| pi | gpt-5.3-codex | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| pi | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| pi | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| pi | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| pi | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| pi | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | OpenAI |  |
| pi | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| pi | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | OpenAI |  |
| pi | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| pi | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | OpenAI |  |
| pi | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenAI | cache 100% of input |
| qwen | gpt-5.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| qwen | gpt-5.3-codex | pass | pass | n/a | FAIL | FAIL | OpenAI | artifact: no file card (files: none);  word HELLO, then reply DONE. QWEN CODE [API Error: 404 This model is not supported in the v1/chat/completions e ; recycle: answered without M1-gpt-5.3-codex: ith in my very first message of this task? Reply with just that word. QWEN CODE [API Error: 404 This mode ; retested once; first try: artifact no file card (files: none);  word HELLO, then reply DONE. QWEN CODE [API Error: ; recycle answered without M1-gpt-5.3-codex: ith in my very first message of this task? Re |
| qwen | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| qwen | gpt-5.4-mini | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| qwen | gpt-5.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| qwen | gpt-5.6-luna | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| qwen | gpt-5.6-sol | pass | pass | pass (gpt-5.6-terra) | pass | pass | OpenAI |  |
| qwen | gpt-5.6-terra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenAI |  |
| qwen | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | OpenAI |  |
| qwen | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | OpenAI |  |
| qwen | gpt-6.1-sol | FAIL | n/a | n/a | n/a | n/a | OpenAI | 1 turn(s) unlabelled (finding below) ; first: The turn failed: API Error: 400 Unsupported value: 'reasoning_effort' does not support 'none' with this model. Supported values are: 'low',  |

95 pairs, 436 of 443 scenario runs passed; 6 pairs served by another connection or as another model are findings, not counted.

Findings, pairs served by a connection other than the one under test or as a model other than the id asked for:

- cline x gpt-6.1-sol: 1 turn(s) report no served model, so rule 2 could not judge them
- codex x gpt-6.1-sol: 4 turn(s) report no served model, so rule 2 could not judge them
- dsh x gpt-6.1-sol: 4 turn(s) report no served model, so rule 2 could not judge them
- kimi x gpt-6.1-sol: 1 turn(s) report no served model, so rule 2 could not judge them
- omp x gpt-6.1-sol: 1 turn(s) report no served model, so rule 2 could not judge them
- qwen x gpt-6.1-sol: 1 turn(s) report no served model, so rule 2 could not judge them

Not run in this column, 49 pairs the provider serves that the harness did not run, with the reason:

- aider x gpt-5.2: not run, not run in this column
- aider x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- aider x gpt-5.4: not run, not run in this column
- aider x gpt-5.4-mini: not run, not run in this column
- aider x gpt-5.5: not run, not run in this column
- aider x gpt-5.6-luna: not run, not run in this column
- aider x gpt-5.6-sol: not run, not run in this column
- aider x gpt-5.6-terra: not run, not run in this column
- aider x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cline x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cline x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-5.2: not run, not run in this column
- goose x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-5.4: not run, not run in this column
- goose x gpt-5.4-mini: not run, not run in this column
- goose x gpt-5.5: not run, not run in this column
- goose x gpt-5.6-luna: not run, not run in this column
- goose x gpt-5.6-sol: not run, not run in this column
- goose x gpt-5.6-terra: not run, not run in this column
- goose x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-6-luna: not run, not run in this column
- goose x gpt-6-sol: not run, not run in this column
- kimi x gpt-5.2: not run, not run in this column
- kimi x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- kimi x gpt-5.4: not run, not run in this column
- kimi x gpt-5.4-mini: not run, not run in this column
- kimi x gpt-5.5: not run, not run in this column
- kimi x gpt-5.6-luna: not run, not run in this column
- kimi x gpt-5.6-sol: not run, not run in this column
- kimi x gpt-5.6-terra: not run, not run in this column
- kimi x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- omp x gpt-5.2: not run, not run in this column
- omp x gpt-5.3-codex: not run, not run in this column
- omp x gpt-5.4: not run, not run in this column
- omp x gpt-5.4-mini: not run, not run in this column
- omp x gpt-5.5: not run, not run in this column
- omp x gpt-5.6-luna: not run, not run in this column
- omp x gpt-5.6-sol: not run, not run in this column
- omp x gpt-5.6-terra: not run, not run in this column
- openhands x gpt-5.2: not run, not run in this column
- openhands x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- openhands x gpt-5.4: not run, not run in this column
- openhands x gpt-5.4-mini: not run, not run in this column
- openhands x gpt-5.5: not run, not run in this column
- openhands x gpt-5.6-luna: not run, not run in this column
- openhands x gpt-5.6-sol: not run, not run in this column
- openhands x gpt-5.6-terra: not run, not run in this column
- openhands x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- qwen x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only

## Provider: openrouter

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| agentzero | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | OpenRouter | no prompt cache reads (finding below) ; served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) |
| aider | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | OpenRouter | no prompt cache reads (finding below) ; served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) |
| aider | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter | served as openai/gpt-6-luna (the provider's alias of the same model) |
| aider | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | FAIL | OpenRouter | recycle: answered without M1-gpt-6-sol: What exact word did I ask you to reply with in my very first message of this task? Reply with just that word. ; served as openai/gpt-6-sol (the provider's alias of the same model) ; recycle: answered without M1-gpt-6-sol: What exact |
| aider | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 51% of input |
| cheetahclaws | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | OpenRouter | no prompt cache reads (finding below) ; served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) |
| cheetahclaws | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter | served as openai/gpt-6-luna (the provider's alias of the same model) |
| cheetahclaws | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | OpenRouter | served as openai/gpt-6-sol (the provider's alias of the same model) |
| cheetahclaws | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 17% of input |
| cline | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | OpenRouter | no prompt cache reads (finding below) ; 4 turn(s) unlabelled (finding below) |
| cline | deepseek-v4.1-flash | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter |  |
| cline | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter |  |
| cline | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | OpenRouter |  |
| cline | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter | 4 turn(s) unlabelled (finding below) ; cache 65% of input |
| cline | grok-4.20 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| cline | grok-4.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| cline | grok-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| cline | grok-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| cline | grok-build-0.1 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| cline | hunyuan-4-preview | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter |  |
| cline | llama-3.3-70b | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| cline | llama-4-maverick | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| cline | muse-glimmer-30b | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| cline | muse-spark-1.1 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| cline | muse-spark-1.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| cline | muse-spark-1.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| cline | nemotron-3-super | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter |  |
| cline | nemotron-3.5-lightning | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter |  |
| cline | qwen3.7-plus | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter |  |
| cline | qwen3.8-27b | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter |  |
| cline | qwen3.8-flash | pass | pass | pass (gpt-5.4) | pass | pass | OpenRouter |  |
| codex | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter |  |
| codex | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| codex | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| codex | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter | 4 turn(s) unlabelled (finding below) ; cache 50% of input |
| dsh | claude-fable-5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | claude-haiku-4.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | OpenRouter | 4 turn(s) unlabelled (finding below) ; cache 100% of input |
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
| dsh | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter |  |
| dsh | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| dsh | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| dsh | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter | 4 turn(s) unlabelled (finding below) ; cache 100% of input |
| dsh | kimi-k2.7-code | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | kimi-k3 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | mistral-medium-3.5 | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | qwen3.7-max | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | qwen3.8-max | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| dsh | step-3.7-flash | pass | pass | pass (deepseek-v4-pro) | pass | pass | OpenRouter |  |
| goose | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | OpenRouter | no prompt cache reads (finding below) ; served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) |
| goose | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 52% of input |
| grok | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | OpenRouter | no prompt cache reads (finding below) ; served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) |
| hermes | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | OpenRouter | no prompt cache reads (finding below) ; served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) |
| hermes | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | claude-opus-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | deepseek-v4.1-flash | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
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
| hermes | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter |  |
| hermes | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| hermes | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| hermes | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter | 4 turn(s) unlabelled (finding below) ; cache 0% of input |
| hermes | grok-4.20 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| hermes | grok-4.3 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| hermes | grok-4.5 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| hermes | grok-4.6 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| hermes | grok-build-0.1 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| hermes | hunyuan-3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | hunyuan-4-preview | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| hermes | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | ling-3.0-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | llama-3.3-70b | pass | pass | FAIL (gpt-6-astra) | pass | pass | OpenRouter | switch: The turn failed: ↻ Resumed session 20260913_060549_70cbeb (2 user messages, 4 total messages)

session_id: 20260913_060549_70cbeb |
| hermes | llama-4-maverick | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| hermes | minimax-m3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | muse-glimmer-30b | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| hermes | muse-spark-1.1 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| hermes | muse-spark-1.2 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| hermes | muse-spark-1.3 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| hermes | nemotron-3-super | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| hermes | nemotron-3-ultra | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | nemotron-3.5-lightning | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| hermes | qwen3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | qwen3.7-plus | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| hermes | qwen3.8-27b | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| hermes | qwen3.8-flash | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter |  |
| hermes | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| hermes | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| kilo | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | OpenRouter | served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) ; cache 69% of input |
| kimi | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | OpenRouter | no prompt cache reads (finding below) ; served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) |
| kimi | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter | served as openai/gpt-6-luna (the provider's alias of the same model) |
| kimi | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | OpenRouter | served as openai/gpt-6-sol (the provider's alias of the same model) |
| kimi | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 50% of input |
| minimax | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | OpenRouter | no prompt cache reads (finding below) ; served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) |
| omp | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | OpenRouter | no prompt cache reads (finding below) ; served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) |
| omp | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter | served as openai/gpt-6-astra (the provider's alias of the same model) |
| omp | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as openai/gpt-6-luna (the provider's alias of the same model) |
| omp | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as openai/gpt-6-sol (the provider's alias of the same model) |
| omp | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter | 1 turn(s) unlabelled (finding below) ; served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 100% of input |
| opencode | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | OpenRouter | served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) ; cache 68% of input |
| opencode | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | claude-opus-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | deepseek-v4.1-flash | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as deepseek/deepseek-v4.1-flash (the provider's alias of the same model) |
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
| opencode | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter | served as openai/gpt-6-astra (the provider's alias of the same model) |
| opencode | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as openai/gpt-6-luna (the provider's alias of the same model) |
| opencode | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as openai/gpt-6-sol (the provider's alias of the same model) |
| opencode | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 100% of input |
| opencode | grok-4.20 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as x-ai/grok-4.20 (the provider's alias of the same model) |
| opencode | grok-4.3 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as x-ai/grok-4.3 (the provider's alias of the same model) |
| opencode | grok-4.5 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as x-ai/grok-4.5 (the provider's alias of the same model) |
| opencode | grok-4.6 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as x-ai/grok-4.6 (the provider's alias of the same model) |
| opencode | grok-build-0.1 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as x-ai/grok-build-0.1 (the provider's alias of the same model) |
| opencode | hunyuan-4-preview | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as tencent/hy4-preview (the provider's alias of the same model) |
| opencode | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | llama-3.3-70b | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as meta-llama/llama-3.3-70b-instruct (the provider's alias of the same model) |
| opencode | llama-4-maverick | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as meta-llama/llama-4-maverick (the provider's alias of the same model) |
| opencode | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | muse-glimmer-30b | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as meta/muse-glimmer-30b (the provider's alias of the same model) |
| opencode | muse-spark-1.1 | pass | pass | pass (gpt-6-astra) | pass | FAIL | OpenRouter | served as meta/muse-spark-1.1 (the provider's alias of the same model) ; recycle: answered without M1-muse-spark-1.1: What exact word did I ask you to reply with in my very first message of this task? Reply with just that  |
| opencode | muse-spark-1.2 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as meta/muse-spark-1.2 (the provider's alias of the same model) |
| opencode | muse-spark-1.3 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as meta/muse-spark-1.3 (the provider's alias of the same model) |
| opencode | nemotron-3-super | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as nvidia/nemotron-3-super-120b-a12b (the provider's alias of the same model) |
| opencode | nemotron-3.5-lightning | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as nvidia/nemotron-3.5-lightning (the provider's alias of the same model) |
| opencode | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | qwen3.7-plus | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as qwen/qwen3.7-plus (the provider's alias of the same model) |
| opencode | qwen3.8-27b | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as qwen/qwen3.8-27b (the provider's alias of the same model) |
| opencode | qwen3.8-flash | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as qwen/qwen3.8-flash (the provider's alias of the same model) |
| opencode | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| opencode | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| openhands | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | OpenRouter | served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) ; cache 69% of input |
| openhands | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter | served as openai/gpt-6-luna (the provider's alias of the same model) |
| openhands | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | OpenRouter | served as openai/gpt-6-sol (the provider's alias of the same model) |
| openhands | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 66% of input |
| pi | claude-fable-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | claude-haiku-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | OpenRouter | no prompt cache reads (finding below) ; served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) |
| pi | claude-opus-4.7 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | claude-opus-4.8 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | claude-opus-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter |  |
| pi | claude-sonnet-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | claude-sonnet-5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | deepseek-v4-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | deepseek-v4-pro | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | deepseek-v4.1-flash | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as deepseek/deepseek-v4.1-flash (the provider's alias of the same model) |
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
| pi | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter | served as openai/gpt-6-astra (the provider's alias of the same model) |
| pi | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as openai/gpt-6-luna (the provider's alias of the same model) |
| pi | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as openai/gpt-6-sol (the provider's alias of the same model) |
| pi | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 100% of input |
| pi | grok-4.20 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as x-ai/grok-4.20 (the provider's alias of the same model) |
| pi | grok-4.3 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as x-ai/grok-4.3 (the provider's alias of the same model) |
| pi | grok-4.5 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as x-ai/grok-4.5 (the provider's alias of the same model) |
| pi | grok-4.6 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as x-ai/grok-4.6 (the provider's alias of the same model) |
| pi | grok-build-0.1 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as x-ai/grok-build-0.1 (the provider's alias of the same model) |
| pi | hunyuan-4-preview | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as tencent/hy4-preview (the provider's alias of the same model) |
| pi | kimi-k2.7-code | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | kimi-k3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | llama-3.3-70b | pass | pass | pass (gpt-6-astra) | FAIL | pass | OpenRouter | served as meta-llama/llama-3.3-70b-instruct (the provider's alias of the same model) ; artifact: no file card (files: output.txt,output.txt); Create a file named hello-pi.txt containing exactly the word HELLO, then reply DONE. PI write(" |
| pi | llama-4-maverick | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as meta-llama/llama-4-maverick (the provider's alias of the same model) |
| pi | mistral-medium-3.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | muse-glimmer-30b | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as meta/muse-glimmer-30b (the provider's alias of the same model) |
| pi | muse-spark-1.1 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as meta/muse-spark-1.1 (the provider's alias of the same model) |
| pi | muse-spark-1.2 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as meta/muse-spark-1.2 (the provider's alias of the same model) |
| pi | muse-spark-1.3 | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as meta/muse-spark-1.3 (the provider's alias of the same model) |
| pi | nemotron-3-super | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as nvidia/nemotron-3-super-120b-a12b (the provider's alias of the same model) |
| pi | nemotron-3.5-lightning | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as nvidia/nemotron-3.5-lightning (the provider's alias of the same model) |
| pi | qwen3.7-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | qwen3.7-plus | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as qwen/qwen3.7-plus (the provider's alias of the same model) |
| pi | qwen3.8-27b | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as qwen/qwen3.8-27b (the provider's alias of the same model) |
| pi | qwen3.8-flash | pass | pass | pass (gpt-6-astra) | pass | pass | OpenRouter | served as qwen/qwen3.8-flash (the provider's alias of the same model) |
| pi | qwen3.8-max | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| pi | step-3.7-flash | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | retested once; first try:  |
| qwen | claude-fable-5 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | claude-haiku-4.5 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | OpenRouter | no prompt cache reads (finding below) ; served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) |
| qwen | claude-opus-4.7 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | claude-opus-4.8 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | claude-opus-5 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | claude-sonnet-4.6 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | claude-sonnet-5 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | deepseek-v4-flash | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | deepseek-v4-pro | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | deepseek-v4.1-flash | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter | served as deepseek/deepseek-v4.1-flash (the provider's alias of the same model) |
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
| qwen | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter | served as openai/gpt-6-luna (the provider's alias of the same model) |
| qwen | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | OpenRouter | served as openai/gpt-6-sol (the provider's alias of the same model) |
| qwen | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | OpenRouter | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 25% of input |
| qwen | grok-4.20 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as x-ai/grok-4.20 (the provider's alias of the same model) |
| qwen | grok-4.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as x-ai/grok-4.3 (the provider's alias of the same model) |
| qwen | grok-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as x-ai/grok-4.5 (the provider's alias of the same model) |
| qwen | grok-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as x-ai/grok-4.6 (the provider's alias of the same model) |
| qwen | grok-build-0.1 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as x-ai/grok-build-0.1 (the provider's alias of the same model) |
| qwen | hunyuan-4-preview | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter | served as tencent/hy4-preview (the provider's alias of the same model) |
| qwen | kimi-k2.7-code | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | kimi-k3 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | llama-3.3-70b | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as meta-llama/llama-3.3-70b-instruct (the provider's alias of the same model) |
| qwen | llama-4-maverick | pass | pass | pass (gpt-5.6-sol) | FAIL | pass | OpenRouter | served as meta-llama/llama-4-maverick (the provider's alias of the same model) ; artifact: no file card (files: none); create 'hello-qwen.txt'. [tool_call: write_file for file_path '/data/workspaces/hsess77f149599a1d465fb237581431a |
| qwen | mistral-medium-3.5 | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | muse-glimmer-30b | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as meta/muse-glimmer-30b (the provider's alias of the same model) |
| qwen | muse-spark-1.1 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as meta/muse-spark-1.1 (the provider's alias of the same model) |
| qwen | muse-spark-1.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as meta/muse-spark-1.2 (the provider's alias of the same model) |
| qwen | muse-spark-1.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | OpenRouter | served as meta/muse-spark-1.3 (the provider's alias of the same model) |
| qwen | nemotron-3-super | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter | served as nvidia/nemotron-3-super-120b-a12b (the provider's alias of the same model) |
| qwen | nemotron-3.5-lightning | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter | served as nvidia/nemotron-3.5-lightning (the provider's alias of the same model) |
| qwen | qwen3.7-max | pass | pass | pass (qwen3.8-max) | pass | pass | OpenRouter |  |
| qwen | qwen3.7-plus | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter | served as qwen/qwen3.7-plus (the provider's alias of the same model) |
| qwen | qwen3.8-27b | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter | served as qwen/qwen3.8-27b (the provider's alias of the same model) |
| qwen | qwen3.8-flash | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter | served as qwen/qwen3.8-flash (the provider's alias of the same model) |
| qwen | qwen3.8-max | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |
| qwen | step-3.7-flash | pass | pass | pass (qwen3.7-max) | pass | pass | OpenRouter |  |

283 pairs, 1374 of 1380 scenario runs passed; 7 pairs served by another connection or as another model are findings, not counted.

Findings, pairs served by a connection other than the one under test or as a model other than the id asked for:

- agentzero x claude-haiku-5.5: no prompt cache reads over 56612 input tokens (every call paid full price)
- aider x claude-haiku-5.5: no prompt cache reads over 24403 input tokens (every call paid full price)
- cheetahclaws x claude-haiku-5.5: no prompt cache reads over 75368 input tokens (every call paid full price)
- cline x claude-haiku-5.5: 4 turn(s) report no served model, so rule 2 could not judge them
- cline x claude-haiku-5.5: no prompt cache reads over 51682 input tokens (every call paid full price)
- cline x gpt-6.1-sol: 4 turn(s) report no served model, so rule 2 could not judge them
- codex x gpt-6.1-sol: 4 turn(s) report no served model, so rule 2 could not judge them
- dsh x claude-haiku-5.5: 4 turn(s) report no served model, so rule 2 could not judge them
- dsh x gpt-6.1-sol: 4 turn(s) report no served model, so rule 2 could not judge them
- goose x claude-haiku-5.5: no prompt cache reads over 179206 input tokens (every call paid full price)
- grok x claude-haiku-5.5: no prompt cache reads over 95095 input tokens (every call paid full price)
- hermes x claude-haiku-5.5: no prompt cache reads over 124046 input tokens (every call paid full price)
- hermes x gpt-6.1-sol: 4 turn(s) report no served model, so rule 2 could not judge them
- kimi x claude-haiku-5.5: no prompt cache reads over 184668 input tokens (every call paid full price)
- minimax x claude-haiku-5.5: no prompt cache reads over 83953 input tokens (every call paid full price)
- omp x claude-haiku-5.5: no prompt cache reads over 169082 input tokens (every call paid full price)
- omp x gpt-6.1-sol: 1 turn(s) report no served model, so rule 2 could not judge them
- pi x claude-haiku-5.5: no prompt cache reads over 25529 input tokens (every call paid full price)
- qwen x claude-haiku-5.5: no prompt cache reads over 570679 input tokens (every call paid full price)

Not run in this column, 839 pairs the provider serves that the harness did not run, with the reason:

- agentzero x claude-fable-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- agentzero x claude-fable-5-1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- agentzero x claude-haiku-4.5: not run, not run in this column
- agentzero x claude-opus-4.7: not run, not run in this column
- agentzero x claude-opus-4.8: not run, not run in this column
- agentzero x claude-opus-5: not run, not run in this column
- agentzero x claude-opus-5.5: not run, not run in this column
- agentzero x claude-sonnet-4.6: not run, not run in this column
- agentzero x claude-sonnet-5: not run, not run in this column
- agentzero x claude-sonnet-5.5: not run, not run in this column
- agentzero x deepseek-v4-flash: not run, not run in this column
- agentzero x deepseek-v4-pro: not run, not run in this column
- agentzero x deepseek-v4.1-flash: not run, not run in this column
- agentzero x gemini-3-flash-preview: not run, not run in this column
- agentzero x gemini-3.1-flash-lite: not run, not run in this column
- agentzero x gemini-3.1-pro-preview: not run, not run in this column
- agentzero x gemini-3.5-flash: not run, not run in this column
- agentzero x gemini-3.5-flash-lite: not run, not run in this column
- agentzero x gemini-3.6-flash: not run, not run in this column
- agentzero x gemini-3.7-flash: not run, not run in this column
- agentzero x gemini-3.8-flash: not run, not run in this column
- agentzero x glm-5.3: not run, not run in this column
- agentzero x glm-5.3-flash: not run, not run in this column
- agentzero x gpt-5.2: not run, not run in this column
- agentzero x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- agentzero x gpt-5.4: not run, not run in this column
- agentzero x gpt-5.4-mini: not run, not run in this column
- agentzero x gpt-5.5: not run, not run in this column
- agentzero x gpt-5.6-luna: not run, not run in this column
- agentzero x gpt-5.6-sol: not run, not run in this column
- agentzero x gpt-5.6-terra: not run, not run in this column
- agentzero x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- agentzero x gpt-6-luna: not run, not run in this column
- agentzero x gpt-6-sol: not run, not run in this column
- agentzero x gpt-6.1-sol: not run, not run in this column
- agentzero x grok-4.20: not run, not run in this column
- agentzero x grok-4.3: not run, not run in this column
- agentzero x grok-4.5: not run, not run in this column
- agentzero x grok-4.6: not run, not run in this column
- agentzero x grok-build-0.1: not run, not run in this column
- agentzero x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- agentzero x hunyuan-4-preview: not run, not run in this column
- agentzero x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- agentzero x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- agentzero x kimi-k2.7-code: not run, not run in this column
- agentzero x kimi-k3: not run, not run in this column
- agentzero x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- agentzero x llama-3.3-70b: not run, not run in this column
- agentzero x llama-4-maverick: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- agentzero x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- agentzero x mistral-medium-3.5: not run, not run in this column
- agentzero x muse-glimmer-30b: not run, not run in this column
- agentzero x muse-spark-1.1: not run, not run in this column
- agentzero x muse-spark-1.2: not run, not run in this column
- agentzero x muse-spark-1.3: not run, not run in this column
- agentzero x nemotron-3-super: not run, not run in this column
- agentzero x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- agentzero x nemotron-3.5-lightning: not run, not run in this column
- agentzero x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- agentzero x qwen3.7-max: not run, not run in this column
- agentzero x qwen3.7-plus: not run, not run in this column
- agentzero x qwen3.8-27b: not run, not run in this column
- agentzero x qwen3.8-flash: not run, not run in this column
- agentzero x qwen3.8-max: not run, not run in this column
- agentzero x step-3.7-flash: not run, not run in this column
- aider x claude-fable-5: not run, not run in this column
- aider x claude-fable-5-1: not run, not run in this column
- aider x claude-haiku-4.5: not run, not run in this column
- aider x claude-opus-4.7: not run, not run in this column
- aider x claude-opus-4.8: not run, not run in this column
- aider x claude-opus-5: not run, not run in this column
- aider x claude-opus-5.5: not run, not run in this column
- aider x claude-sonnet-4.6: not run, not run in this column
- aider x claude-sonnet-5: not run, not run in this column
- aider x claude-sonnet-5.5: not run, not run in this column
- aider x deepseek-v4-flash: not run, not run in this column
- aider x deepseek-v4-pro: not run, not run in this column
- aider x deepseek-v4.1-flash: not run, not run in this column
- aider x gemini-3-flash-preview: not run, not run in this column
- aider x gemini-3.1-flash-lite: not run, not run in this column
- aider x gemini-3.1-pro-preview: not run, not run in this column
- aider x gemini-3.5-flash: not run, not run in this column
- aider x gemini-3.5-flash-lite: not run, not run in this column
- aider x gemini-3.6-flash: not run, not run in this column
- aider x gemini-3.7-flash: not run, not run in this column
- aider x gemini-3.8-flash: not run, not run in this column
- aider x glm-5.3: not run, not run in this column
- aider x glm-5.3-flash: not run, not run in this column
- aider x gpt-5.2: not run, not run in this column
- aider x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- aider x gpt-5.4: not run, not run in this column
- aider x gpt-5.4-mini: not run, not run in this column
- aider x gpt-5.5: not run, not run in this column
- aider x gpt-5.6-luna: not run, not run in this column
- aider x gpt-5.6-sol: not run, not run in this column
- aider x gpt-5.6-terra: not run, not run in this column
- aider x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- aider x grok-4.20: not run, not run in this column
- aider x grok-4.3: not run, not run in this column
- aider x grok-4.5: not run, not run in this column
- aider x grok-4.6: not run, not run in this column
- aider x grok-build-0.1: not run, not run in this column
- aider x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- aider x hunyuan-4-preview: not run, not run in this column
- aider x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- aider x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- aider x kimi-k2.7-code: not run, not run in this column
- aider x kimi-k3: not run, not run in this column
- aider x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- aider x llama-3.3-70b: not run, not run in this column
- aider x llama-4-maverick: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- aider x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- aider x mistral-medium-3.5: not run, not run in this column
- aider x muse-glimmer-30b: not run, not run in this column
- aider x muse-spark-1.1: not run, not run in this column
- aider x muse-spark-1.2: not run, not run in this column
- aider x muse-spark-1.3: not run, not run in this column
- aider x nemotron-3-super: not run, not run in this column
- aider x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- aider x nemotron-3.5-lightning: not run, not run in this column
- aider x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- aider x qwen3.7-max: not run, not run in this column
- aider x qwen3.7-plus: not run, not run in this column
- aider x qwen3.8-27b: not run, not run in this column
- aider x qwen3.8-flash: not run, not run in this column
- aider x qwen3.8-max: not run, not run in this column
- aider x step-3.7-flash: not run, not run in this column
- cheetahclaws x claude-fable-5: not run, not run in this column
- cheetahclaws x claude-fable-5-1: not run, not run in this column
- cheetahclaws x claude-haiku-4.5: not run, not run in this column
- cheetahclaws x claude-opus-4.7: not run, not run in this column
- cheetahclaws x claude-opus-4.8: not run, not run in this column
- cheetahclaws x claude-opus-5: not run, not run in this column
- cheetahclaws x claude-opus-5.5: not run, not run in this column
- cheetahclaws x claude-sonnet-4.6: not run, not run in this column
- cheetahclaws x claude-sonnet-5: not run, not run in this column
- cheetahclaws x claude-sonnet-5.5: not run, not run in this column
- cheetahclaws x deepseek-v4-flash: not run, not run in this column
- cheetahclaws x deepseek-v4-pro: not run, not run in this column
- cheetahclaws x deepseek-v4.1-flash: not run, not run in this column
- cheetahclaws x gemini-3-flash-preview: not run, not run in this column
- cheetahclaws x gemini-3.1-flash-lite: not run, not run in this column
- cheetahclaws x gemini-3.1-pro-preview: not run, not run in this column
- cheetahclaws x gemini-3.5-flash: not run, not run in this column
- cheetahclaws x gemini-3.5-flash-lite: not run, not run in this column
- cheetahclaws x gemini-3.6-flash: not run, not run in this column
- cheetahclaws x gemini-3.7-flash: not run, not run in this column
- cheetahclaws x gemini-3.8-flash: not run, not run in this column
- cheetahclaws x glm-5.3: not run, not run in this column
- cheetahclaws x glm-5.3-flash: not run, not run in this column
- cheetahclaws x gpt-5.2: not run, not run in this column
- cheetahclaws x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cheetahclaws x gpt-5.4: not run, not run in this column
- cheetahclaws x gpt-5.4-mini: not run, not run in this column
- cheetahclaws x gpt-5.5: not run, not run in this column
- cheetahclaws x gpt-5.6-luna: not run, not run in this column
- cheetahclaws x gpt-5.6-sol: not run, not run in this column
- cheetahclaws x gpt-5.6-terra: not run, not run in this column
- cheetahclaws x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cheetahclaws x grok-4.20: not run, not run in this column
- cheetahclaws x grok-4.3: not run, not run in this column
- cheetahclaws x grok-4.5: not run, not run in this column
- cheetahclaws x grok-4.6: not run, not run in this column
- cheetahclaws x grok-build-0.1: not run, not run in this column
- cheetahclaws x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cheetahclaws x hunyuan-4-preview: not run, not run in this column
- cheetahclaws x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cheetahclaws x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cheetahclaws x kimi-k2.7-code: not run, not run in this column
- cheetahclaws x kimi-k3: not run, not run in this column
- cheetahclaws x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cheetahclaws x llama-3.3-70b: not run, not run in this column
- cheetahclaws x llama-4-maverick: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cheetahclaws x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cheetahclaws x mistral-medium-3.5: not run, not run in this column
- cheetahclaws x muse-glimmer-30b: not run, not run in this column
- cheetahclaws x muse-spark-1.1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cheetahclaws x muse-spark-1.2: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cheetahclaws x muse-spark-1.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cheetahclaws x nemotron-3-super: not run, not run in this column
- cheetahclaws x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cheetahclaws x nemotron-3.5-lightning: not run, not run in this column
- cheetahclaws x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cheetahclaws x qwen3.7-max: not run, not run in this column
- cheetahclaws x qwen3.7-plus: not run, not run in this column
- cheetahclaws x qwen3.8-27b: not run, not run in this column
- cheetahclaws x qwen3.8-flash: not run, not run in this column
- cheetahclaws x qwen3.8-max: not run, not run in this column
- cheetahclaws x step-3.7-flash: not run, not run in this column
- cline x claude-fable-5: not run, not run in this column
- cline x claude-fable-5-1: not run, not run in this column
- cline x claude-haiku-4.5: not run, not run in this column
- cline x claude-opus-4.7: not run, not run in this column
- cline x claude-opus-4.8: not run, not run in this column
- cline x claude-opus-5: not run, not run in this column
- cline x claude-opus-5.5: not run, not run in this column
- cline x claude-sonnet-4.6: not run, not run in this column
- cline x claude-sonnet-5: not run, not run in this column
- cline x claude-sonnet-5.5: not run, not run in this column
- cline x deepseek-v4-flash: not run, not run in this column
- cline x deepseek-v4-pro: not run, not run in this column
- cline x gemini-3-flash-preview: not run, not run in this column
- cline x gemini-3.1-flash-lite: not run, not run in this column
- cline x gemini-3.1-pro-preview: not run, not run in this column
- cline x gemini-3.5-flash: not run, not run in this column
- cline x gemini-3.5-flash-lite: not run, not run in this column
- cline x gemini-3.6-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x gemini-3.7-flash: not run, not run in this column
- cline x gemini-3.8-flash: not run, not run in this column
- cline x glm-5.3: not run, not run in this column
- cline x glm-5.3-flash: not run, not run in this column
- cline x gpt-5.2: not run, not run in this column
- cline x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cline x gpt-5.4: not run, not run in this column
- cline x gpt-5.4-mini: not run, not run in this column
- cline x gpt-5.5: not run, not run in this column
- cline x gpt-5.6-luna: not run, not run in this column
- cline x gpt-5.6-sol: not run, not run in this column
- cline x gpt-5.6-terra: not run, not run in this column
- cline x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cline x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x kimi-k2.7-code: not run, not run in this column
- cline x kimi-k3: not run, not run in this column
- cline x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x mistral-medium-3.5: not run, not run in this column
- cline x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x qwen3.7-max: not run, not run in this column
- cline x qwen3.8-max: not run, not run in this column
- cline x step-3.7-flash: not run, not run in this column
- codex x claude-fable-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-fable-5-1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-haiku-4.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-haiku-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-4.7: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-4.8: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-sonnet-4.6: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-sonnet-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-sonnet-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x deepseek-v4-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x deepseek-v4-pro: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x deepseek-v4.1-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3-flash-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.1-flash-lite: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.1-pro-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.5-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.5-flash-lite: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.6-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.8-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x glm-5.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x glm-5.3-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gpt-5.2: not run, not run in this column
- codex x gpt-5.3-codex: not run, not run in this column
- codex x gpt-5.4: not run, not run in this column
- codex x gpt-5.4-mini: not run, not run in this column
- codex x gpt-5.5: not run, not run in this column
- codex x gpt-5.6-luna: not run, not run in this column
- codex x gpt-5.6-sol: not run, not run in this column
- codex x gpt-5.6-terra: not run, not run in this column
- codex x grok-4.20: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-4.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-4.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-4.6: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-build-0.1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x hunyuan-4-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x kimi-k2.7-code: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x kimi-k3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x llama-3.3-70b: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x llama-4-maverick: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x mistral-medium-3.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x muse-glimmer-30b: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x muse-spark-1.1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x muse-spark-1.2: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x muse-spark-1.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x nemotron-3-super: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x nemotron-3.5-lightning: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.7-max: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.7-plus: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.8-27b: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.8-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.8-max: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x step-3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x claude-fable-5-1: not run, not run in this column
- dsh x claude-opus-5.5: not run, not run in this column
- dsh x claude-sonnet-5.5: not run, not run in this column
- dsh x deepseek-v4.1-flash: not run, not run in this column
- dsh x gemini-3-flash-preview: not run, not run in this column
- dsh x gemini-3.1-flash-lite: not run, not run in this column
- dsh x gemini-3.1-pro-preview: not run, not run in this column
- dsh x gemini-3.5-flash: not run, not run in this column
- dsh x gemini-3.5-flash-lite: not run, not run in this column
- dsh x gemini-3.7-flash: not run, not run in this column
- dsh x gemini-3.8-flash: not run, not run in this column
- dsh x grok-4.20: not run, not run in this column
- dsh x grok-4.3: not run, not run in this column
- dsh x grok-4.5: not run, not run in this column
- dsh x grok-4.6: not run, not run in this column
- dsh x grok-build-0.1: not run, not run in this column
- dsh x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x hunyuan-4-preview: not run, not run in this column
- dsh x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x llama-3.3-70b: not run, not run in this column
- dsh x llama-4-maverick: not run, not run in this column
- dsh x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x muse-glimmer-30b: not run, not run in this column
- dsh x muse-spark-1.1: not run, not run in this column
- dsh x muse-spark-1.2: not run, not run in this column
- dsh x muse-spark-1.3: not run, not run in this column
- dsh x nemotron-3-super: not run, not run in this column
- dsh x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x nemotron-3.5-lightning: not run, not run in this column
- dsh x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x qwen3.7-plus: not run, not run in this column
- dsh x qwen3.8-27b: not run, not run in this column
- dsh x qwen3.8-flash: not run, not run in this column
- goose x claude-fable-5: not run, not run in this column
- goose x claude-fable-5-1: not run, not run in this column
- goose x claude-haiku-4.5: not run, not run in this column
- goose x claude-opus-4.7: not run, not run in this column
- goose x claude-opus-4.8: not run, not run in this column
- goose x claude-opus-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x claude-opus-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x claude-sonnet-4.6: not run, not run in this column
- goose x claude-sonnet-5: not run, not run in this column
- goose x claude-sonnet-5.5: not run, not run in this column
- goose x deepseek-v4-flash: not run, not run in this column
- goose x deepseek-v4-pro: not run, not run in this column
- goose x deepseek-v4.1-flash: not run, not run in this column
- goose x gemini-3-flash-preview: not run, not run in this column
- goose x gemini-3.1-flash-lite: not run, not run in this column
- goose x gemini-3.1-pro-preview: not run, not run in this column
- goose x gemini-3.5-flash: not run, not run in this column
- goose x gemini-3.5-flash-lite: not run, not run in this column
- goose x gemini-3.6-flash: not run, not run in this column
- goose x gemini-3.7-flash: not run, not run in this column
- goose x gemini-3.8-flash: not run, not run in this column
- goose x glm-5.3: not run, not run in this column
- goose x glm-5.3-flash: not run, not run in this column
- goose x gpt-5.2: not run, not run in this column
- goose x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-5.4: not run, not run in this column
- goose x gpt-5.4-mini: not run, not run in this column
- goose x gpt-5.5: not run, not run in this column
- goose x gpt-5.6-luna: not run, not run in this column
- goose x gpt-5.6-sol: not run, not run in this column
- goose x gpt-5.6-terra: not run, not run in this column
- goose x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-6-luna: not run, not run in this column
- goose x gpt-6-sol: not run, not run in this column
- goose x grok-4.20: not run, not run in this column
- goose x grok-4.3: not run, not run in this column
- goose x grok-4.5: not run, not run in this column
- goose x grok-4.6: not run, not run in this column
- goose x grok-build-0.1: not run, not run in this column
- goose x hunyuan-3: not run, not run in this column
- goose x hunyuan-4-preview: not run, not run in this column
- goose x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x kimi-k2.7-code: not run, not run in this column
- goose x kimi-k3: not run, not run in this column
- goose x ling-3.0-flash: not run, not run in this column
- goose x llama-3.3-70b: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x llama-4-maverick: not run, not run in this column
- goose x minimax-m3: not run, not run in this column
- goose x mistral-medium-3.5: not run, not run in this column
- goose x muse-glimmer-30b: not run, not run in this column
- goose x muse-spark-1.1: not run, not run in this column
- goose x muse-spark-1.2: not run, not run in this column
- goose x muse-spark-1.3: not run, not run in this column
- goose x nemotron-3-super: not run, not run in this column
- goose x nemotron-3-ultra: not run, not run in this column
- goose x nemotron-3.5-lightning: not run, not run in this column
- goose x qwen3.7-flash: not run, not run in this column
- goose x qwen3.7-max: not run, not run in this column
- goose x qwen3.7-plus: not run, not run in this column
- goose x qwen3.8-27b: not run, not run in this column
- goose x qwen3.8-flash: not run, not run in this column
- goose x qwen3.8-max: not run, not run in this column
- goose x step-3.7-flash: not run, not run in this column
- grok x claude-fable-5: not run, not run in this column
- grok x claude-fable-5-1: not run, not run in this column
- grok x claude-haiku-4.5: not run, not run in this column
- grok x claude-opus-4.7: not run, not run in this column
- grok x claude-opus-4.8: not run, not run in this column
- grok x claude-opus-5: not run, not run in this column
- grok x claude-opus-5.5: not run, not run in this column
- grok x claude-sonnet-4.6: not run, not run in this column
- grok x claude-sonnet-5: not run, not run in this column
- grok x claude-sonnet-5.5: not run, not run in this column
- grok x deepseek-v4-flash: not run, not run in this column
- grok x deepseek-v4-pro: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- grok x deepseek-v4.1-flash: not run, not run in this column
- grok x gemini-3-flash-preview: not run, not run in this column
- grok x gemini-3.1-flash-lite: not run, not run in this column
- grok x gemini-3.1-pro-preview: not run, not run in this column
- grok x gemini-3.5-flash: not run, not run in this column
- grok x gemini-3.5-flash-lite: not run, not run in this column
- grok x gemini-3.6-flash: not run, not run in this column
- grok x gemini-3.7-flash: not run, not run in this column
- grok x gemini-3.8-flash: not run, not run in this column
- grok x glm-5.3: not run, not run in this column
- grok x glm-5.3-flash: not run, not run in this column
- grok x gpt-5.2: not run, not run in this column
- grok x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- grok x gpt-5.4: not run, not run in this column
- grok x gpt-5.4-mini: not run, not run in this column
- grok x gpt-5.5: not run, not run in this column
- grok x gpt-5.6-luna: not run, not run in this column
- grok x gpt-5.6-sol: not run, not run in this column
- grok x gpt-5.6-terra: not run, not run in this column
- grok x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- grok x gpt-6-luna: not run, not run in this column
- grok x gpt-6-sol: not run, not run in this column
- grok x gpt-6.1-sol: not run, not run in this column
- grok x grok-4.20: not run, not run in this column
- grok x grok-4.3: not run, not run in this column
- grok x grok-4.5: not run, not run in this column
- grok x grok-4.6: not run, not run in this column
- grok x grok-build-0.1: not run, not run in this column
- grok x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- grok x hunyuan-4-preview: not run, not run in this column
- grok x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- grok x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- grok x kimi-k2.7-code: not run, not run in this column
- grok x kimi-k3: not run, not run in this column
- grok x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- grok x llama-3.3-70b: not run, not run in this column
- grok x llama-4-maverick: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- grok x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- grok x mistral-medium-3.5: not run, not run in this column
- grok x muse-glimmer-30b: not run, not run in this column
- grok x muse-spark-1.1: not run, not run in this column
- grok x muse-spark-1.2: not run, not run in this column
- grok x muse-spark-1.3: not run, not run in this column
- grok x nemotron-3-super: not run, not run in this column
- grok x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- grok x nemotron-3.5-lightning: not run, not run in this column
- grok x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- grok x qwen3.7-max: not run, not run in this column
- grok x qwen3.7-plus: not run, not run in this column
- grok x qwen3.8-27b: not run, not run in this column
- grok x qwen3.8-flash: not run, not run in this column
- grok x qwen3.8-max: not run, not run in this column
- grok x step-3.7-flash: not run, not run in this column
- hermes x claude-fable-5-1: not run, not run in this column
- hermes x claude-opus-5.5: not run, not run in this column
- hermes x claude-sonnet-5.5: not run, not run in this column
- hermes x gemini-3-flash-preview: not run, not run in this column
- hermes x gemini-3.1-flash-lite: not run, not run in this column
- hermes x gemini-3.1-pro-preview: not run, not run in this column
- hermes x gemini-3.5-flash: not run, not run in this column
- hermes x gemini-3.5-flash-lite: not run, not run in this column
- hermes x gemini-3.7-flash: not run, not run in this column
- hermes x gemini-3.8-flash: not run, not run in this column
- hermes x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- hermes x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kilo x claude-fable-5: not run, not run in this column
- kilo x claude-fable-5-1: not run, not run in this column
- kilo x claude-haiku-4.5: not run, not run in this column
- kilo x claude-opus-4.7: not run, not run in this column
- kilo x claude-opus-4.8: not run, not run in this column
- kilo x claude-opus-5: not run, not run in this column
- kilo x claude-opus-5.5: not run, not run in this column
- kilo x claude-sonnet-4.6: not run, not run in this column
- kilo x claude-sonnet-5: not run, not run in this column
- kilo x claude-sonnet-5.5: not run, not run in this column
- kilo x deepseek-v4-flash: not run, not run in this column
- kilo x deepseek-v4-pro: not run, not run in this column
- kilo x deepseek-v4.1-flash: not run, not run in this column
- kilo x gemini-3-flash-preview: not run, not run in this column
- kilo x gemini-3.1-flash-lite: not run, not run in this column
- kilo x gemini-3.1-pro-preview: not run, not run in this column
- kilo x gemini-3.5-flash: not run, not run in this column
- kilo x gemini-3.5-flash-lite: not run, not run in this column
- kilo x gemini-3.6-flash: not run, not run in this column
- kilo x gemini-3.7-flash: not run, not run in this column
- kilo x gemini-3.8-flash: not run, not run in this column
- kilo x glm-5.3: not run, not run in this column
- kilo x glm-5.3-flash: not run, not run in this column
- kilo x gpt-5.2: not run, not run in this column
- kilo x gpt-5.3-codex: not run, not run in this column
- kilo x gpt-5.4: not run, not run in this column
- kilo x gpt-5.4-mini: not run, not run in this column
- kilo x gpt-5.5: not run, not run in this column
- kilo x gpt-5.6-luna: not run, not run in this column
- kilo x gpt-5.6-sol: not run, not run in this column
- kilo x gpt-5.6-terra: not run, not run in this column
- kilo x gpt-6-astra: not run, not run in this column
- kilo x gpt-6-luna: not run, not run in this column
- kilo x gpt-6-sol: not run, not run in this column
- kilo x gpt-6.1-sol: not run, not run in this column
- kilo x grok-4.20: not run, not run in this column
- kilo x grok-4.3: not run, not run in this column
- kilo x grok-4.5: not run, not run in this column
- kilo x grok-4.6: not run, not run in this column
- kilo x grok-build-0.1: not run, not run in this column
- kilo x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kilo x hunyuan-4-preview: not run, not run in this column
- kilo x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kilo x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kilo x kimi-k2.7-code: not run, not run in this column
- kilo x kimi-k3: not run, not run in this column
- kilo x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kilo x llama-3.3-70b: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kilo x llama-4-maverick: not run, not run in this column
- kilo x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kilo x mistral-medium-3.5: not run, not run in this column
- kilo x muse-glimmer-30b: not run, not run in this column
- kilo x muse-spark-1.1: not run, not run in this column
- kilo x muse-spark-1.2: not run, not run in this column
- kilo x muse-spark-1.3: not run, not run in this column
- kilo x nemotron-3-super: not run, not run in this column
- kilo x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kilo x nemotron-3.5-lightning: not run, not run in this column
- kilo x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kilo x qwen3.7-max: not run, not run in this column
- kilo x qwen3.7-plus: not run, not run in this column
- kilo x qwen3.8-27b: not run, not run in this column
- kilo x qwen3.8-flash: not run, not run in this column
- kilo x qwen3.8-max: not run, not run in this column
- kilo x step-3.7-flash: not run, not run in this column
- kimi x claude-fable-5: not run, not run in this column
- kimi x claude-fable-5-1: not run, not run in this column
- kimi x claude-haiku-4.5: not run, not run in this column
- kimi x claude-opus-4.7: not run, not run in this column
- kimi x claude-opus-4.8: not run, not run in this column
- kimi x claude-opus-5: not run, not run in this column
- kimi x claude-opus-5.5: not run, not run in this column
- kimi x claude-sonnet-4.6: not run, not run in this column
- kimi x claude-sonnet-5: not run, not run in this column
- kimi x claude-sonnet-5.5: not run, not run in this column
- kimi x deepseek-v4-flash: not run, not run in this column
- kimi x deepseek-v4-pro: not run, not run in this column
- kimi x deepseek-v4.1-flash: not run, not run in this column
- kimi x gemini-3-flash-preview: not run, not run in this column
- kimi x gemini-3.1-flash-lite: not run, not run in this column
- kimi x gemini-3.1-pro-preview: not run, not run in this column
- kimi x gemini-3.5-flash: not run, not run in this column
- kimi x gemini-3.5-flash-lite: not run, not run in this column
- kimi x gemini-3.6-flash: not run, not run in this column
- kimi x gemini-3.7-flash: not run, not run in this column
- kimi x gemini-3.8-flash: not run, not run in this column
- kimi x glm-5.3: not run, not run in this column
- kimi x glm-5.3-flash: not run, not run in this column
- kimi x gpt-5.2: not run, not run in this column
- kimi x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- kimi x gpt-5.4: not run, not run in this column
- kimi x gpt-5.4-mini: not run, not run in this column
- kimi x gpt-5.5: not run, not run in this column
- kimi x gpt-5.6-luna: not run, not run in this column
- kimi x gpt-5.6-sol: not run, not run in this column
- kimi x gpt-5.6-terra: not run, not run in this column
- kimi x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- kimi x grok-4.20: not run, not run in this column
- kimi x grok-4.3: not run, not run in this column
- kimi x grok-4.5: not run, not run in this column
- kimi x grok-4.6: not run, not run in this column
- kimi x grok-build-0.1: not run, not run in this column
- kimi x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kimi x hunyuan-4-preview: not run, not run in this column
- kimi x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kimi x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kimi x kimi-k2.7-code: not run, not run in this column
- kimi x kimi-k3: not run, not run in this column
- kimi x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kimi x llama-3.3-70b: not run, not run in this column
- kimi x llama-4-maverick: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kimi x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kimi x mistral-medium-3.5: not run, not run in this column
- kimi x muse-glimmer-30b: not run, not run in this column
- kimi x muse-spark-1.1: not run, not run in this column
- kimi x muse-spark-1.2: not run, not run in this column
- kimi x muse-spark-1.3: not run, not run in this column
- kimi x nemotron-3-super: not run, not run in this column
- kimi x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kimi x nemotron-3.5-lightning: not run, not run in this column
- kimi x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kimi x qwen3.7-max: not run, not run in this column
- kimi x qwen3.7-plus: not run, not run in this column
- kimi x qwen3.8-27b: not run, not run in this column
- kimi x qwen3.8-flash: not run, not run in this column
- kimi x qwen3.8-max: not run, not run in this column
- kimi x step-3.7-flash: not run, not run in this column
- minimax x claude-fable-5: not run, not run in this column
- minimax x claude-fable-5-1: not run, not run in this column
- minimax x claude-haiku-4.5: not run, not run in this column
- minimax x claude-opus-4.7: not run, not run in this column
- minimax x claude-opus-4.8: not run, not run in this column
- minimax x claude-opus-5: not run, not run in this column
- minimax x claude-opus-5.5: not run, not run in this column
- minimax x claude-sonnet-4.6: not run, not run in this column
- minimax x claude-sonnet-5: not run, not run in this column
- minimax x claude-sonnet-5.5: not run, not run in this column
- minimax x deepseek-v4-flash: not run, not run in this column
- minimax x deepseek-v4-pro: not run, not run in this column
- minimax x deepseek-v4.1-flash: not run, not run in this column
- minimax x gemini-3-flash-preview: not run, not run in this column
- minimax x gemini-3.1-flash-lite: not run, not run in this column
- minimax x gemini-3.1-pro-preview: not run, not run in this column
- minimax x gemini-3.5-flash: not run, not run in this column
- minimax x gemini-3.5-flash-lite: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- minimax x gemini-3.6-flash: not run, not run in this column
- minimax x gemini-3.7-flash: not run, not run in this column
- minimax x gemini-3.8-flash: not run, not run in this column
- minimax x glm-5.3: not run, not run in this column
- minimax x glm-5.3-flash: not run, not run in this column
- minimax x gpt-5.2: not run, not run in this column
- minimax x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- minimax x gpt-5.4: not run, not run in this column
- minimax x gpt-5.4-mini: not run, not run in this column
- minimax x gpt-5.5: not run, not run in this column
- minimax x gpt-5.6-luna: not run, not run in this column
- minimax x gpt-5.6-sol: not run, not run in this column
- minimax x gpt-5.6-terra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- minimax x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- minimax x gpt-6-luna: not run, not run in this column
- minimax x gpt-6-sol: not run, not run in this column
- minimax x gpt-6.1-sol: not run, not run in this column
- minimax x grok-4.20: not run, not run in this column
- minimax x grok-4.3: not run, not run in this column
- minimax x grok-4.5: not run, not run in this column
- minimax x grok-4.6: not run, not run in this column
- minimax x grok-build-0.1: not run, not run in this column
- minimax x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- minimax x hunyuan-4-preview: not run, not run in this column
- minimax x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- minimax x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- minimax x kimi-k2.7-code: not run, not run in this column
- minimax x kimi-k3: not run, not run in this column
- minimax x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- minimax x llama-3.3-70b: not run, not run in this column
- minimax x llama-4-maverick: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- minimax x minimax-m3: not run, not run in this column
- minimax x mistral-medium-3.5: not run, not run in this column
- minimax x muse-glimmer-30b: not run, not run in this column
- minimax x muse-spark-1.1: not run, not run in this column
- minimax x muse-spark-1.2: not run, not run in this column
- minimax x muse-spark-1.3: not run, not run in this column
- minimax x nemotron-3-super: not run, not run in this column
- minimax x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- minimax x nemotron-3.5-lightning: not run, not run in this column
- minimax x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- minimax x qwen3.7-max: not run, not run in this column
- minimax x qwen3.7-plus: not run, not run in this column
- minimax x qwen3.8-27b: not run, not run in this column
- minimax x qwen3.8-flash: not run, not run in this column
- minimax x qwen3.8-max: not run, not run in this column
- minimax x step-3.7-flash: not run, not run in this column
- omp x claude-fable-5: not run, not run in this column
- omp x claude-fable-5-1: not run, not run in this column
- omp x claude-haiku-4.5: not run, not run in this column
- omp x claude-opus-4.7: not run, not run in this column
- omp x claude-opus-4.8: not run, not run in this column
- omp x claude-opus-5: not run, not run in this column
- omp x claude-opus-5.5: not run, not run in this column
- omp x claude-sonnet-4.6: not run, not run in this column
- omp x claude-sonnet-5: not run, not run in this column
- omp x claude-sonnet-5.5: not run, not run in this column
- omp x deepseek-v4-flash: not run, not run in this column
- omp x deepseek-v4-pro: not run, not run in this column
- omp x deepseek-v4.1-flash: not run, not run in this column
- omp x gemini-3-flash-preview: not run, not run in this column
- omp x gemini-3.1-flash-lite: not run, not run in this column
- omp x gemini-3.1-pro-preview: not run, not run in this column
- omp x gemini-3.5-flash: not run, not run in this column
- omp x gemini-3.5-flash-lite: not run, not run in this column
- omp x gemini-3.6-flash: not run, not run in this column
- omp x gemini-3.7-flash: not run, not run in this column
- omp x gemini-3.8-flash: not run, not run in this column
- omp x glm-5.3: not run, not run in this column
- omp x glm-5.3-flash: not run, not run in this column
- omp x gpt-5.2: not run, not run in this column
- omp x gpt-5.3-codex: not run, not run in this column
- omp x gpt-5.4: not run, not run in this column
- omp x gpt-5.4-mini: not run, not run in this column
- omp x gpt-5.5: not run, not run in this column
- omp x gpt-5.6-luna: not run, not run in this column
- omp x gpt-5.6-sol: not run, not run in this column
- omp x gpt-5.6-terra: not run, not run in this column
- omp x grok-4.20: not run, not run in this column
- omp x grok-4.3: not run, not run in this column
- omp x grok-4.5: not run, not run in this column
- omp x grok-4.6: not run, not run in this column
- omp x grok-build-0.1: not run, not run in this column
- omp x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x hunyuan-4-preview: not run, not run in this column
- omp x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x kimi-k2.7-code: not run, not run in this column
- omp x kimi-k3: not run, not run in this column
- omp x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x llama-3.3-70b: not run, not run in this column
- omp x llama-4-maverick: not run, not run in this column
- omp x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x mistral-medium-3.5: not run, not run in this column
- omp x muse-glimmer-30b: not run, not run in this column
- omp x muse-spark-1.1: not run, not run in this column
- omp x muse-spark-1.2: not run, not run in this column
- omp x muse-spark-1.3: not run, not run in this column
- omp x nemotron-3-super: not run, not run in this column
- omp x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x nemotron-3.5-lightning: not run, not run in this column
- omp x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x qwen3.7-max: not run, not run in this column
- omp x qwen3.7-plus: not run, not run in this column
- omp x qwen3.8-27b: not run, not run in this column
- omp x qwen3.8-flash: not run, not run in this column
- omp x qwen3.8-max: not run, not run in this column
- omp x step-3.7-flash: not run, not run in this column
- opencode x claude-fable-5-1: not run, not run in this column
- opencode x claude-opus-5.5: not run, not run in this column
- opencode x claude-sonnet-5.5: not run, not run in this column
- opencode x gemini-3-flash-preview: not run, not run in this column
- opencode x gemini-3.1-flash-lite: not run, not run in this column
- opencode x gemini-3.1-pro-preview: not run, not run in this column
- opencode x gemini-3.5-flash: not run, not run in this column
- opencode x gemini-3.5-flash-lite: not run, not run in this column
- opencode x gemini-3.7-flash: not run, not run in this column
- opencode x gemini-3.8-flash: not run, not run in this column
- opencode x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- openhands x claude-fable-5: not run, not run in this column
- openhands x claude-fable-5-1: not run, not run in this column
- openhands x claude-haiku-4.5: not run, not run in this column
- openhands x claude-opus-4.7: not run, not run in this column
- openhands x claude-opus-4.8: not run, not run in this column
- openhands x claude-opus-5: not run, not run in this column
- openhands x claude-opus-5.5: not run, not run in this column
- openhands x claude-sonnet-4.6: not run, not run in this column
- openhands x claude-sonnet-5: not run, not run in this column
- openhands x claude-sonnet-5.5: not run, not run in this column
- openhands x deepseek-v4-flash: not run, not run in this column
- openhands x deepseek-v4-pro: not run, not run in this column
- openhands x deepseek-v4.1-flash: not run, not run in this column
- openhands x gemini-3-flash-preview: not run, not run in this column
- openhands x gemini-3.1-flash-lite: not run, not run in this column
- openhands x gemini-3.1-pro-preview: not run, not run in this column
- openhands x gemini-3.5-flash: not run, not run in this column
- openhands x gemini-3.5-flash-lite: not run, not run in this column
- openhands x gemini-3.6-flash: not run, not run in this column
- openhands x gemini-3.7-flash: not run, not run in this column
- openhands x gemini-3.8-flash: not run, not run in this column
- openhands x glm-5.3: not run, not run in this column
- openhands x glm-5.3-flash: not run, not run in this column
- openhands x gpt-5.2: not run, not run in this column
- openhands x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- openhands x gpt-5.4: not run, not run in this column
- openhands x gpt-5.4-mini: not run, not run in this column
- openhands x gpt-5.5: not run, not run in this column
- openhands x gpt-5.6-luna: not run, not run in this column
- openhands x gpt-5.6-sol: not run, not run in this column
- openhands x gpt-5.6-terra: not run, not run in this column
- openhands x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- openhands x grok-4.20: not run, not run in this column
- openhands x grok-4.3: not run, not run in this column
- openhands x grok-4.5: not run, not run in this column
- openhands x grok-4.6: not run, not run in this column
- openhands x grok-build-0.1: not run, not run in this column
- openhands x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- openhands x hunyuan-4-preview: not run, not run in this column
- openhands x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- openhands x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- openhands x kimi-k2.7-code: not run, not run in this column
- openhands x kimi-k3: not run, not run in this column
- openhands x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- openhands x llama-3.3-70b: not run, not run in this column
- openhands x llama-4-maverick: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- openhands x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- openhands x mistral-medium-3.5: not run, not run in this column
- openhands x muse-glimmer-30b: not run, not run in this column
- openhands x muse-spark-1.1: not run, not run in this column
- openhands x muse-spark-1.2: not run, not run in this column
- openhands x muse-spark-1.3: not run, not run in this column
- openhands x nemotron-3-super: not run, not run in this column
- openhands x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- openhands x nemotron-3.5-lightning: not run, not run in this column
- openhands x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- openhands x qwen3.7-max: not run, not run in this column
- openhands x qwen3.7-plus: not run, not run in this column
- openhands x qwen3.8-27b: not run, not run in this column
- openhands x qwen3.8-flash: not run, not run in this column
- openhands x qwen3.8-max: not run, not run in this column
- openhands x step-3.7-flash: not run, not run in this column
- pi x claude-fable-5-1: not run, not run in this column
- pi x claude-opus-5.5: not run, not run in this column
- pi x claude-sonnet-5.5: not run, not run in this column
- pi x gemini-3-flash-preview: not run, not run in this column
- pi x gemini-3.1-flash-lite: not run, not run in this column
- pi x gemini-3.1-pro-preview: not run, not run in this column
- pi x gemini-3.5-flash: not run, not run in this column
- pi x gemini-3.5-flash-lite: not run, not run in this column
- pi x gemini-3.7-flash: not run, not run in this column
- pi x gemini-3.8-flash: not run, not run in this column
- pi x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x claude-fable-5-1: not run, not run in this column
- qwen x claude-opus-5.5: not run, not run in this column
- qwen x claude-sonnet-5.5: not run, not run in this column
- qwen x gemini-3-flash-preview: not run, not run in this column
- qwen x gemini-3.1-flash-lite: not run, not run in this column
- qwen x gemini-3.1-pro-preview: not run, not run in this column
- qwen x gemini-3.5-flash: not run, not run in this column
- qwen x gemini-3.5-flash-lite: not run, not run in this column
- qwen x gemini-3.7-flash: not run, not run in this column
- qwen x gemini-3.8-flash: not run, not run in this column
- qwen x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- qwen x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- qwen x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x jev-1.13: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x jev-latest: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)

## Provider: tokenrouter

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| aider | claude-sonnet-5.5 | pass | pass | pass (claude-opus-5) | pass | pass | My TokenRouter, Vercel AI Gateway | served as claude-sonnet-5-5 (the provider's alias of the same model) ; served by another connection (finding below) |
| aider | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | My TokenRouter |  |
| aider | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | My TokenRouter |  |
| aider | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | My TokenRouter | cache 45% of input |
| cheetahclaws | claude-sonnet-5.5 | pass | pass | pass (claude-opus-5) | pass | pass | My TokenRouter, Vercel AI Gateway | served as claude-sonnet-5-5 (the provider's alias of the same model) ; served by another connection (finding below) |
| cheetahclaws | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | My TokenRouter |  |
| cheetahclaws | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | My TokenRouter |  |
| cheetahclaws | gpt-6.1-sol | FAIL | n/a | n/a | n/a | n/a | My TokenRouter | 1 turn(s) unlabelled (finding below) ; first: The turn failed: Failed — BadRequestError: Error code: 400 - {'error': {'message': "Unsupported value: 'reasoning_effort' does not support ' |
| claude-code | claude-sonnet-4.6 | pass | pass | pass (claude-opus-5) | pass | pass | My TokenRouter |  |
| claude-code | claude-sonnet-5.5 | pass | pass | pass (claude-opus-5) | pass | pass | My TokenRouter, Vercel AI Gateway | served by another connection (finding below) |
| cline | claude-sonnet-4.6 | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | claude-sonnet-5.5 | pass | pass | pass (claude-opus-5) | pass | pass | My TokenRouter, Vercel AI Gateway | served by another connection (finding below) |
| cline | deepseek-v4.1-flash | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | gpt-5.4 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| cline | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | My TokenRouter |  |
| cline | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | My TokenRouter |  |
| cline | gpt-6.1-sol | FAIL | n/a | n/a | n/a | n/a | My TokenRouter | 1 turn(s) unlabelled (finding below) ; first: The turn failed: Unsupported value: 'reasoning_effort' does not support 'none' with this model. Supported values are: 'low', 'medium', 'high |
| cline | grok-4.20 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| cline | grok-4.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| cline | grok-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| cline | grok-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| cline | grok-build-0.1 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| cline | hunyuan-4-preview | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | nemotron-3-super | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | nemotron-3.5-lightning | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | qwen3.7-plus | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| cline | qwen3.8-flash | pass | pass | pass (gpt-5.4) | pass | pass | My TokenRouter |  |
| codex | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | My TokenRouter |  |
| codex | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| codex | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| codex | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | My TokenRouter | 4 turn(s) unlabelled (finding below) ; cache 58% of input |
| dsh | claude-sonnet-5.5 | pass | pass | pass (claude-opus-5) | pass | pass | My TokenRouter, Vercel AI Gateway | served by another connection (finding below) |
| dsh | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | My TokenRouter |  |
| dsh | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| dsh | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| dsh | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | My TokenRouter | 4 turn(s) unlabelled (finding below) ; cache 100% of input |
| goose | claude-sonnet-5.5 | pass | pass | pass (claude-sonnet-5) | pass | pass | My TokenRouter | served as claude-sonnet-5-5 (the provider's alias of the same model) ; served by another connection (finding below) |
| goose | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | My TokenRouter | cache 52% of input |
| hermes | claude-sonnet-4.6 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| hermes | claude-sonnet-5.5 | pass | pass | pass (claude-opus-5) | pass | pass | My TokenRouter, Vercel AI Gateway | served by another connection (finding below) |
| hermes | deepseek-v4.1-flash | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| hermes | gpt-5.4 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| hermes | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | My TokenRouter |  |
| hermes | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| hermes | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| hermes | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | My TokenRouter | cache 0% of input |
| hermes | grok-4.20 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| hermes | grok-4.3 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| hermes | grok-4.5 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| hermes | grok-4.6 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| hermes | grok-build-0.1 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| hermes | hunyuan-4-preview | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| hermes | nemotron-3-super | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| hermes | nemotron-3.5-lightning | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| hermes | qwen3.7-plus | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| hermes | qwen3.8-flash | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| kimi | claude-sonnet-5.5 | pass | pass | pass (claude-opus-5) | pass | pass | My TokenRouter, Vercel AI Gateway | served as claude-sonnet-5-5 (the provider's alias of the same model) ; served by another connection (finding below) |
| kimi | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | My TokenRouter |  |
| kimi | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | My TokenRouter |  |
| kimi | gpt-6.1-sol | FAIL | n/a | n/a | n/a | n/a | My TokenRouter | 1 turn(s) unlabelled (finding below) ; first: The turn failed: error: failed to run prompt: provider.api_error: 400 Unsupported value: 'reasoning_effort' does not support 'none' with thi |
| omp | claude-sonnet-5.5 | pass | pass | pass (claude-sonnet-5) | pass | pass | My TokenRouter | served as anthropic/claude-sonnet-5.5 (the provider's alias of the same model) ; served by another connection (finding below) |
| omp | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | My TokenRouter | served as openai/gpt-6-astra (the provider's alias of the same model) |
| omp | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as openai/gpt-6-luna (the provider's alias of the same model) |
| omp | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as openai/gpt-6-sol (the provider's alias of the same model) |
| omp | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | My TokenRouter | 1 turn(s) unlabelled (finding below) ; served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 100% of input |
| opencode | claude-sonnet-4.6 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| opencode | claude-sonnet-5.5 | pass | pass | pass (claude-opus-5) | pass | pass | My TokenRouter, Vercel AI Gateway | served by another connection (finding below) |
| opencode | deepseek-v4.1-flash | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as deepseek-flash (the provider's alias of the same model) |
| opencode | gpt-5.4 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| opencode | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | My TokenRouter |  |
| opencode | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| opencode | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| opencode | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | My TokenRouter | cache 100% of input |
| opencode | grok-4.20 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as x-ai/grok-4.20 (the provider's alias of the same model) |
| opencode | grok-4.3 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as x-ai/grok-4.3 (the provider's alias of the same model) |
| opencode | grok-4.5 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| opencode | grok-4.6 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| opencode | grok-build-0.1 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as x-ai/grok-build-0.1 (the provider's alias of the same model) |
| opencode | hunyuan-4-preview | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as tencent/hy4-preview (the provider's alias of the same model) |
| opencode | nemotron-3-super | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as nvidia/nemotron-3-super-120b-a12b (the provider's alias of the same model) |
| opencode | nemotron-3.5-lightning | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as nvidia/nemotron-3.5-lightning (the provider's alias of the same model) |
| opencode | qwen3.7-plus | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as qwen/qwen3.7-plus (the provider's alias of the same model) |
| opencode | qwen3.8-flash | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter |  |
| openhands | claude-sonnet-5.5 | pass | pass | pass (claude-opus-5) | pass | pass | My TokenRouter, Vercel AI Gateway | served as claude-sonnet-5-5 (the provider's alias of the same model) ; served by another connection (finding below) |
| openhands | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | My TokenRouter |  |
| openhands | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | My TokenRouter |  |
| openhands | gpt-6.1-sol | FAIL | n/a | n/a | n/a | n/a | My TokenRouter | first: The turn failed: the agent-server marked the conversation error: BadRequestError: Error code: 400 - {'error': {'message': "Unsupported value ; cache 0% of input |
| pi | claude-sonnet-4.6 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as anthropic/claude-sonnet-4.6 (the provider's alias of the same model) |
| pi | claude-sonnet-5.5 | pass | pass | pass (claude-opus-5) | pass | pass | My TokenRouter, Vercel AI Gateway | served as anthropic/claude-sonnet-5.5 (the provider's alias of the same model) ; served by another connection (finding below) |
| pi | deepseek-v4.1-flash | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as deepseek/deepseek-v4.1-flash (the provider's alias of the same model) |
| pi | gpt-5.4 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as openai/gpt-5.4 (the provider's alias of the same model) |
| pi | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | My TokenRouter | served as openai/gpt-6-astra (the provider's alias of the same model) |
| pi | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as openai/gpt-6-luna (the provider's alias of the same model) |
| pi | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as openai/gpt-6-sol (the provider's alias of the same model) |
| pi | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | My TokenRouter | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 100% of input |
| pi | grok-4.20 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as x-ai/grok-4.20-beta (the provider's alias of the same model) |
| pi | grok-4.3 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as x-ai/grok-4.3 (the provider's alias of the same model) |
| pi | grok-4.5 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as x-ai/grok-4.5 (the provider's alias of the same model) |
| pi | grok-4.6 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as x-ai/grok-4.6 (the provider's alias of the same model) |
| pi | grok-build-0.1 | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as x-ai/grok-build-0.1 (the provider's alias of the same model) |
| pi | hunyuan-4-preview | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as tencent/hy4-preview (the provider's alias of the same model) |
| pi | nemotron-3-super | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as nvidia/nemotron-3-super-120b-a12b (the provider's alias of the same model) |
| pi | nemotron-3.5-lightning | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as nvidia/nemotron-3.5-lightning (the provider's alias of the same model) |
| pi | qwen3.7-plus | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as qwen/qwen3.7-plus (the provider's alias of the same model) |
| pi | qwen3.8-flash | pass | pass | pass (gpt-6-astra) | pass | pass | My TokenRouter | served as qwen/qwen3.8-flash (the provider's alias of the same model) |
| qwen | claude-sonnet-4.6 | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter | served as claude-sonnet-4-6 (the provider's alias of the same model) |
| qwen | claude-sonnet-5.5 | pass | pass | pass (claude-opus-5) | pass | pass | My TokenRouter, Vercel AI Gateway | served as claude-sonnet-5-5 (the provider's alias of the same model) ; served by another connection (finding below) |
| qwen | deepseek-v4.1-flash | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter | served as deepseek-flash (the provider's alias of the same model) |
| qwen | gpt-5.4 | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter | served as gpt-5.4-2026-03-05 (the provider's alias of the same model) |
| qwen | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | My TokenRouter |  |
| qwen | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | My TokenRouter |  |
| qwen | gpt-6.1-sol | FAIL | n/a | n/a | n/a | n/a | My TokenRouter | 1 turn(s) unlabelled (finding below) ; first: The turn failed: API Error: 400 Unsupported value: 'reasoning_effort' does not support 'none' with this model. Supported values are: 'low',  |
| qwen | grok-4.20 | pass | pass | pass (gpt-5.6-sol) | FAIL | pass | My TokenRouter | served as x-ai/grok-4.20 (the provider's alias of the same model) ; artifact: no file card (files: none); Create a file named hello-qwen.txt containing exactly the word HELLO, then reply DONE. QWEN CODE DONE |
| qwen | grok-4.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as x-ai/grok-4.3 (the provider's alias of the same model) |
| qwen | grok-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| qwen | grok-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter |  |
| qwen | grok-build-0.1 | pass | pass | pass (gpt-5.6-sol) | pass | pass | My TokenRouter | served as x-ai/grok-build-0.1 (the provider's alias of the same model) |
| qwen | hunyuan-4-preview | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter | served as tencent/hy4-preview (the provider's alias of the same model) |
| qwen | nemotron-3-super | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter | served as nvidia/nemotron-3-super-120b-a12b (the provider's alias of the same model) |
| qwen | nemotron-3.5-lightning | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter | served as nvidia/nemotron-3.5-lightning (the provider's alias of the same model) |
| qwen | qwen3.7-plus | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter | served as qwen/qwen3.7-plus (the provider's alias of the same model) |
| qwen | qwen3.8-flash | pass | pass | pass (qwen3.7-max) | pass | pass | My TokenRouter |  |

122 pairs, 504 of 506 scenario runs passed; 20 pairs served by another connection or as another model are findings, not counted.

Findings, pairs served by a connection other than the one under test or as a model other than the id asked for:

- aider x claude-sonnet-5.5: served by integration:My TokenRouter, integration:Vercel AI Gateway (turn records: integration:My TokenRouter, integration:Vercel AI Gateway)
- cheetahclaws x claude-sonnet-5.5: served by integration:My TokenRouter, integration:Vercel AI Gateway (turn records: integration:My TokenRouter, integration:Vercel AI Gateway)
- cheetahclaws x gpt-6.1-sol: 1 turn(s) report no served model, so rule 2 could not judge them
- claude-code x claude-sonnet-5.5: served by integration:My TokenRouter, integration:Vercel AI Gateway (turn records: integration:My TokenRouter, integration:Vercel AI Gateway)
- cline x claude-sonnet-5.5: served by integration:My TokenRouter, integration:Vercel AI Gateway (turn records: integration:My TokenRouter, integration:Vercel AI Gateway)
- cline x gpt-6.1-sol: 1 turn(s) report no served model, so rule 2 could not judge them
- codex x gpt-6.1-sol: 4 turn(s) report no served model, so rule 2 could not judge them
- dsh x claude-sonnet-5.5: served by integration:My TokenRouter, integration:Vercel AI Gateway (turn records: integration:My TokenRouter, integration:Vercel AI Gateway)
- dsh x gpt-6.1-sol: 4 turn(s) report no served model, so rule 2 could not judge them
- goose x claude-sonnet-5.5: served by integration:My TokenRouter (turn records: integration:My TokenRouter)
- hermes x claude-sonnet-5.5: served by integration:My TokenRouter, integration:Vercel AI Gateway (turn records: integration:My TokenRouter, integration:Vercel AI Gateway)
- kimi x claude-sonnet-5.5: served by integration:My TokenRouter, integration:Vercel AI Gateway (turn records: integration:My TokenRouter, integration:Vercel AI Gateway)
- kimi x gpt-6.1-sol: 1 turn(s) report no served model, so rule 2 could not judge them
- omp x claude-sonnet-5.5: served by integration:My TokenRouter (turn records: integration:My TokenRouter)
- omp x gpt-6.1-sol: 1 turn(s) report no served model, so rule 2 could not judge them
- opencode x claude-sonnet-5.5: served by integration:My TokenRouter, integration:Vercel AI Gateway (turn records: integration:My TokenRouter, integration:Vercel AI Gateway)
- openhands x claude-sonnet-5.5: served by integration:My TokenRouter, integration:Vercel AI Gateway (turn records: integration:My TokenRouter, integration:Vercel AI Gateway)
- pi x claude-sonnet-5.5: served by integration:My TokenRouter, integration:Vercel AI Gateway (turn records: integration:My TokenRouter, integration:Vercel AI Gateway)
- qwen x claude-sonnet-5.5: served by integration:My TokenRouter, integration:Vercel AI Gateway (turn records: integration:My TokenRouter, integration:Vercel AI Gateway)
- qwen x gpt-6.1-sol: 1 turn(s) report no served model, so rule 2 could not judge them

Not run in this column, 578 pairs the provider serves that the harness did not run, with the reason:

- aider x claude-fable-5: not run, not run in this column
- aider x claude-fable-5-1: not run, not run in this column
- aider x claude-haiku-4.5: not run, not run in this column
- aider x claude-opus-4.7: not run, not run in this column
- aider x claude-opus-4.8: not run, not run in this column
- aider x claude-opus-5: not run, not run in this column
- aider x claude-opus-5.5: not run, not run in this column
- aider x claude-sonnet-4.6: not run, not run in this column
- aider x claude-sonnet-5: not run, not run in this column
- aider x deepseek-v4-flash: not run, not run in this column
- aider x deepseek-v4-pro: not run, not run in this column
- aider x deepseek-v4.1-flash: not run, not run in this column
- aider x gemini-3-flash-preview: not run, not run in this column
- aider x gemini-3.1-pro-preview: not run, not run in this column
- aider x gemini-3.5-flash: not run, not run in this column
- aider x gemini-3.5-flash-lite: not run, not run in this column
- aider x gemini-3.6-flash: not run, not run in this column
- aider x gemini-3.7-flash: not run, not run in this column
- aider x gemini-3.8-flash: not run, not run in this column
- aider x glm-5.3: not run, not run in this column
- aider x glm-5.3-flash: not run, not run in this column
- aider x gpt-5.2: not run, not run in this column
- aider x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- aider x gpt-5.4: not run, not run in this column
- aider x gpt-5.4-mini: not run, not run in this column
- aider x gpt-5.5: not run, not run in this column
- aider x gpt-5.6-luna: not run, not run in this column
- aider x gpt-5.6-sol: not run, not run in this column
- aider x gpt-5.6-terra: not run, not run in this column
- aider x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- aider x grok-4.20: not run, not run in this column
- aider x grok-4.3: not run, not run in this column
- aider x grok-4.5: not run, not run in this column
- aider x grok-4.6: not run, not run in this column
- aider x grok-build-0.1: not run, not run in this column
- aider x hunyuan-4-preview: not run, not run in this column
- aider x kimi-k2.7-code: not run, not run in this column
- aider x kimi-k3: not run, not run in this column
- aider x mistral-medium-3.5: not run, not run in this column
- aider x nemotron-3-super: not run, not run in this column
- aider x nemotron-3.5-lightning: not run, not run in this column
- aider x qwen3.7-max: not run, not run in this column
- aider x qwen3.7-plus: not run, not run in this column
- aider x qwen3.8-flash: not run, not run in this column
- aider x qwen3.8-max: not run, not run in this column
- aider x step-3.7-flash: not run, not run in this column
- cheetahclaws x claude-fable-5: not run, not run in this column
- cheetahclaws x claude-fable-5-1: not run, not run in this column
- cheetahclaws x claude-haiku-4.5: not run, not run in this column
- cheetahclaws x claude-opus-4.7: not run, not run in this column
- cheetahclaws x claude-opus-4.8: not run, not run in this column
- cheetahclaws x claude-opus-5: not run, not run in this column
- cheetahclaws x claude-opus-5.5: not run, not run in this column
- cheetahclaws x claude-sonnet-4.6: not run, not run in this column
- cheetahclaws x claude-sonnet-5: not run, not run in this column
- cheetahclaws x deepseek-v4-flash: not run, not run in this column
- cheetahclaws x deepseek-v4-pro: not run, not run in this column
- cheetahclaws x deepseek-v4.1-flash: not run, not run in this column
- cheetahclaws x gemini-3-flash-preview: not run, not run in this column
- cheetahclaws x gemini-3.1-pro-preview: not run, not run in this column
- cheetahclaws x gemini-3.5-flash: not run, not run in this column
- cheetahclaws x gemini-3.5-flash-lite: not run, not run in this column
- cheetahclaws x gemini-3.6-flash: not run, not run in this column
- cheetahclaws x gemini-3.7-flash: not run, not run in this column
- cheetahclaws x gemini-3.8-flash: not run, not run in this column
- cheetahclaws x glm-5.3: not run, not run in this column
- cheetahclaws x glm-5.3-flash: not run, not run in this column
- cheetahclaws x gpt-5.2: not run, not run in this column
- cheetahclaws x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cheetahclaws x gpt-5.4: not run, not run in this column
- cheetahclaws x gpt-5.4-mini: not run, not run in this column
- cheetahclaws x gpt-5.5: not run, not run in this column
- cheetahclaws x gpt-5.6-luna: not run, not run in this column
- cheetahclaws x gpt-5.6-sol: not run, not run in this column
- cheetahclaws x gpt-5.6-terra: not run, not run in this column
- cheetahclaws x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cheetahclaws x grok-4.20: not run, not run in this column
- cheetahclaws x grok-4.3: not run, not run in this column
- cheetahclaws x grok-4.5: not run, not run in this column
- cheetahclaws x grok-4.6: not run, not run in this column
- cheetahclaws x grok-build-0.1: not run, not run in this column
- cheetahclaws x hunyuan-4-preview: not run, not run in this column
- cheetahclaws x kimi-k2.7-code: not run, not run in this column
- cheetahclaws x kimi-k3: not run, not run in this column
- cheetahclaws x mistral-medium-3.5: not run, not run in this column
- cheetahclaws x nemotron-3-super: not run, not run in this column
- cheetahclaws x nemotron-3.5-lightning: not run, not run in this column
- cheetahclaws x qwen3.7-max: not run, not run in this column
- cheetahclaws x qwen3.7-plus: not run, not run in this column
- cheetahclaws x qwen3.8-flash: not run, not run in this column
- cheetahclaws x qwen3.8-max: not run, not run in this column
- cheetahclaws x step-3.7-flash: not run, not run in this column
- claude-code x claude-fable-5: not run, not run in this column
- claude-code x claude-fable-5-1: not run, not run in this column
- claude-code x claude-haiku-4.5: not run, not run in this column
- claude-code x claude-opus-4.7: not run, not run in this column
- claude-code x claude-opus-4.8: not run, not run in this column
- claude-code x claude-opus-5: not run, not run in this column
- claude-code x claude-opus-5.5: not run, not run in this column
- claude-code x claude-sonnet-5: not run, not run in this column
- claude-code x deepseek-v4-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x deepseek-v4-pro: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x deepseek-v4.1-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gemini-3-flash-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gemini-3.1-pro-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gemini-3.5-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gemini-3.5-flash-lite: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gemini-3.6-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gemini-3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gemini-3.8-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x glm-5.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x glm-5.3-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-5.2: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-5.3-codex: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-5.4: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-5.4-mini: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-5.6-luna: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-5.6-sol: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-5.6-terra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-6-astra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-6-luna: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-6-sol: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-6.1-sol: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x grok-4.20: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x grok-4.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x grok-4.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x grok-4.6: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x grok-build-0.1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x hunyuan-4-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x kimi-k2.7-code: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x kimi-k3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x mistral-medium-3.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x nemotron-3-super: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x nemotron-3.5-lightning: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x qwen3.7-max: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x qwen3.7-plus: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x qwen3.8-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x qwen3.8-max: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x step-3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x claude-fable-5: not run, not run in this column
- cline x claude-fable-5-1: not run, not run in this column
- cline x claude-haiku-4.5: not run, not run in this column
- cline x claude-opus-4.7: not run, not run in this column
- cline x claude-opus-4.8: not run, not run in this column
- cline x claude-opus-5: not run, not run in this column
- cline x claude-opus-5.5: not run, not run in this column
- cline x claude-sonnet-5: not run, not run in this column
- cline x deepseek-v4-flash: not run, not run in this column
- cline x deepseek-v4-pro: not run, not run in this column
- cline x gemini-3-flash-preview: not run, not run in this column
- cline x gemini-3.1-pro-preview: not run, not run in this column
- cline x gemini-3.5-flash: not run, not run in this column
- cline x gemini-3.5-flash-lite: not run, not run in this column
- cline x gemini-3.6-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x gemini-3.7-flash: not run, not run in this column
- cline x gemini-3.8-flash: not run, not run in this column
- cline x glm-5.3: not run, not run in this column
- cline x glm-5.3-flash: not run, not run in this column
- cline x gpt-5.2: not run, not run in this column
- cline x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cline x gpt-5.4-mini: not run, not run in this column
- cline x gpt-5.5: not run, not run in this column
- cline x gpt-5.6-luna: not run, not run in this column
- cline x gpt-5.6-sol: not run, not run in this column
- cline x gpt-5.6-terra: not run, not run in this column
- cline x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cline x kimi-k2.7-code: not run, not run in this column
- cline x kimi-k3: not run, not run in this column
- cline x mistral-medium-3.5: not run, not run in this column
- cline x qwen3.7-max: not run, not run in this column
- cline x qwen3.8-max: not run, not run in this column
- cline x step-3.7-flash: not run, not run in this column
- codex x claude-fable-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-fable-5-1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-haiku-4.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-4.7: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-4.8: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-sonnet-4.6: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-sonnet-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-sonnet-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x deepseek-v4-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x deepseek-v4-pro: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x deepseek-v4.1-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3-flash-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.1-pro-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.5-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.5-flash-lite: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.6-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.8-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x glm-5.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x glm-5.3-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gpt-5.2: not run, not run in this column
- codex x gpt-5.3-codex: not run, not run in this column
- codex x gpt-5.4: not run, not run in this column
- codex x gpt-5.4-mini: not run, not run in this column
- codex x gpt-5.5: not run, not run in this column
- codex x gpt-5.6-luna: not run, not run in this column
- codex x gpt-5.6-sol: not run, not run in this column
- codex x gpt-5.6-terra: not run, not run in this column
- codex x grok-4.20: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-4.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-4.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-4.6: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-build-0.1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x hunyuan-4-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x kimi-k2.7-code: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x kimi-k3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x mistral-medium-3.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x nemotron-3-super: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x nemotron-3.5-lightning: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.7-max: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.7-plus: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.8-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.8-max: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x step-3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x claude-fable-5: not run, not run in this column
- dsh x claude-fable-5-1: not run, not run in this column
- dsh x claude-haiku-4.5: not run, not run in this column
- dsh x claude-opus-4.7: not run, not run in this column
- dsh x claude-opus-4.8: not run, not run in this column
- dsh x claude-opus-5: not run, not run in this column
- dsh x claude-opus-5.5: not run, not run in this column
- dsh x claude-sonnet-4.6: not run, not run in this column
- dsh x claude-sonnet-5: not run, not run in this column
- dsh x deepseek-v4-flash: not run, not run in this column
- dsh x deepseek-v4-pro: not run, not run in this column
- dsh x deepseek-v4.1-flash: not run, not run in this column
- dsh x gemini-3-flash-preview: not run, not run in this column
- dsh x gemini-3.1-pro-preview: not run, not run in this column
- dsh x gemini-3.5-flash: not run, not run in this column
- dsh x gemini-3.5-flash-lite: not run, not run in this column
- dsh x gemini-3.6-flash: not run, not run in this column
- dsh x gemini-3.7-flash: not run, not run in this column
- dsh x gemini-3.8-flash: not run, not run in this column
- dsh x glm-5.3: not run, not run in this column
- dsh x glm-5.3-flash: not run, not run in this column
- dsh x gpt-5.2: not run, not run in this column
- dsh x gpt-5.3-codex: not run, not run in this column
- dsh x gpt-5.4: not run, not run in this column
- dsh x gpt-5.4-mini: not run, not run in this column
- dsh x gpt-5.5: not run, not run in this column
- dsh x gpt-5.6-luna: not run, not run in this column
- dsh x gpt-5.6-sol: not run, not run in this column
- dsh x gpt-5.6-terra: not run, not run in this column
- dsh x grok-4.20: not run, not run in this column
- dsh x grok-4.3: not run, not run in this column
- dsh x grok-4.5: not run, not run in this column
- dsh x grok-4.6: not run, not run in this column
- dsh x grok-build-0.1: not run, not run in this column
- dsh x hunyuan-4-preview: not run, not run in this column
- dsh x kimi-k2.7-code: not run, not run in this column
- dsh x kimi-k3: not run, not run in this column
- dsh x mistral-medium-3.5: not run, not run in this column
- dsh x nemotron-3-super: not run, not run in this column
- dsh x nemotron-3.5-lightning: not run, not run in this column
- dsh x qwen3.7-max: not run, not run in this column
- dsh x qwen3.7-plus: not run, not run in this column
- dsh x qwen3.8-flash: not run, not run in this column
- dsh x qwen3.8-max: not run, not run in this column
- dsh x step-3.7-flash: not run, not run in this column
- goose x claude-fable-5: not run, not run in this column
- goose x claude-fable-5-1: not run, not run in this column
- goose x claude-haiku-4.5: not run, not run in this column
- goose x claude-opus-4.7: not run, not run in this column
- goose x claude-opus-4.8: not run, not run in this column
- goose x claude-opus-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x claude-opus-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x claude-sonnet-4.6: not run, not run in this column
- goose x claude-sonnet-5: not run, not run in this column
- goose x deepseek-v4-flash: not run, not run in this column
- goose x deepseek-v4-pro: not run, not run in this column
- goose x deepseek-v4.1-flash: not run, not run in this column
- goose x gemini-3-flash-preview: not run, not run in this column
- goose x gemini-3.1-pro-preview: not run, not run in this column
- goose x gemini-3.5-flash: not run, not run in this column
- goose x gemini-3.5-flash-lite: not run, not run in this column
- goose x gemini-3.6-flash: not run, not run in this column
- goose x gemini-3.7-flash: not run, not run in this column
- goose x gemini-3.8-flash: not run, not run in this column
- goose x glm-5.3: not run, not run in this column
- goose x glm-5.3-flash: not run, not run in this column
- goose x gpt-5.2: not run, not run in this column
- goose x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-5.4: not run, not run in this column
- goose x gpt-5.4-mini: not run, not run in this column
- goose x gpt-5.5: not run, not run in this column
- goose x gpt-5.6-luna: not run, not run in this column
- goose x gpt-5.6-sol: not run, not run in this column
- goose x gpt-5.6-terra: not run, not run in this column
- goose x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-6-luna: not run, not run in this column
- goose x gpt-6-sol: not run, not run in this column
- goose x grok-4.20: not run, not run in this column
- goose x grok-4.3: not run, not run in this column
- goose x grok-4.5: not run, not run in this column
- goose x grok-4.6: not run, not run in this column
- goose x grok-build-0.1: not run, not run in this column
- goose x hunyuan-4-preview: not run, not run in this column
- goose x kimi-k2.7-code: not run, not run in this column
- goose x kimi-k3: not run, not run in this column
- goose x mistral-medium-3.5: not run, not run in this column
- goose x nemotron-3-super: not run, not run in this column
- goose x nemotron-3.5-lightning: not run, not run in this column
- goose x qwen3.7-max: not run, not run in this column
- goose x qwen3.7-plus: not run, not run in this column
- goose x qwen3.8-flash: not run, not run in this column
- goose x qwen3.8-max: not run, not run in this column
- goose x step-3.7-flash: not run, not run in this column
- hermes x claude-fable-5: not run, not run in this column
- hermes x claude-fable-5-1: not run, not run in this column
- hermes x claude-haiku-4.5: not run, not run in this column
- hermes x claude-opus-4.7: not run, not run in this column
- hermes x claude-opus-4.8: not run, not run in this column
- hermes x claude-opus-5: not run, not run in this column
- hermes x claude-opus-5.5: not run, not run in this column
- hermes x claude-sonnet-5: not run, not run in this column
- hermes x deepseek-v4-flash: not run, not run in this column
- hermes x deepseek-v4-pro: not run, not run in this column
- hermes x gemini-3-flash-preview: not run, not run in this column
- hermes x gemini-3.1-pro-preview: not run, not run in this column
- hermes x gemini-3.5-flash: not run, not run in this column
- hermes x gemini-3.5-flash-lite: not run, not run in this column
- hermes x gemini-3.6-flash: not run, not run in this column
- hermes x gemini-3.7-flash: not run, not run in this column
- hermes x gemini-3.8-flash: not run, not run in this column
- hermes x glm-5.3: not run, not run in this column
- hermes x glm-5.3-flash: not run, not run in this column
- hermes x gpt-5.2: not run, not run in this column
- hermes x gpt-5.3-codex: not run, not run in this column
- hermes x gpt-5.4-mini: not run, not run in this column
- hermes x gpt-5.5: not run, not run in this column
- hermes x gpt-5.6-luna: not run, not run in this column
- hermes x gpt-5.6-sol: not run, not run in this column
- hermes x gpt-5.6-terra: not run, not run in this column
- hermes x kimi-k2.7-code: not run, not run in this column
- hermes x kimi-k3: not run, not run in this column
- hermes x mistral-medium-3.5: not run, not run in this column
- hermes x qwen3.7-max: not run, not run in this column
- hermes x qwen3.8-max: not run, not run in this column
- hermes x step-3.7-flash: not run, not run in this column
- kimi x claude-fable-5: not run, not run in this column
- kimi x claude-fable-5-1: not run, not run in this column
- kimi x claude-haiku-4.5: not run, not run in this column
- kimi x claude-opus-4.7: not run, not run in this column
- kimi x claude-opus-4.8: not run, not run in this column
- kimi x claude-opus-5: not run, not run in this column
- kimi x claude-opus-5.5: not run, not run in this column
- kimi x claude-sonnet-4.6: not run, not run in this column
- kimi x claude-sonnet-5: not run, not run in this column
- kimi x deepseek-v4-flash: not run, not run in this column
- kimi x deepseek-v4-pro: not run, not run in this column
- kimi x deepseek-v4.1-flash: not run, not run in this column
- kimi x gemini-3-flash-preview: not run, not run in this column
- kimi x gemini-3.1-pro-preview: not run, not run in this column
- kimi x gemini-3.5-flash: not run, not run in this column
- kimi x gemini-3.5-flash-lite: not run, not run in this column
- kimi x gemini-3.6-flash: not run, not run in this column
- kimi x gemini-3.7-flash: not run, not run in this column
- kimi x gemini-3.8-flash: not run, not run in this column
- kimi x glm-5.3: not run, not run in this column
- kimi x glm-5.3-flash: not run, not run in this column
- kimi x gpt-5.2: not run, not run in this column
- kimi x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- kimi x gpt-5.4: not run, not run in this column
- kimi x gpt-5.4-mini: not run, not run in this column
- kimi x gpt-5.5: not run, not run in this column
- kimi x gpt-5.6-luna: not run, not run in this column
- kimi x gpt-5.6-sol: not run, not run in this column
- kimi x gpt-5.6-terra: not run, not run in this column
- kimi x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- kimi x grok-4.20: not run, not run in this column
- kimi x grok-4.3: not run, not run in this column
- kimi x grok-4.5: not run, not run in this column
- kimi x grok-4.6: not run, not run in this column
- kimi x grok-build-0.1: not run, not run in this column
- kimi x hunyuan-4-preview: not run, not run in this column
- kimi x kimi-k2.7-code: not run, not run in this column
- kimi x kimi-k3: not run, not run in this column
- kimi x mistral-medium-3.5: not run, not run in this column
- kimi x nemotron-3-super: not run, not run in this column
- kimi x nemotron-3.5-lightning: not run, not run in this column
- kimi x qwen3.7-max: not run, not run in this column
- kimi x qwen3.7-plus: not run, not run in this column
- kimi x qwen3.8-flash: not run, not run in this column
- kimi x qwen3.8-max: not run, not run in this column
- kimi x step-3.7-flash: not run, not run in this column
- omp x claude-fable-5: not run, not run in this column
- omp x claude-fable-5-1: not run, not run in this column
- omp x claude-haiku-4.5: not run, not run in this column
- omp x claude-opus-4.7: not run, not run in this column
- omp x claude-opus-4.8: not run, not run in this column
- omp x claude-opus-5: not run, not run in this column
- omp x claude-opus-5.5: not run, not run in this column
- omp x claude-sonnet-4.6: not run, not run in this column
- omp x claude-sonnet-5: not run, not run in this column
- omp x deepseek-v4-flash: not run, not run in this column
- omp x deepseek-v4-pro: not run, not run in this column
- omp x deepseek-v4.1-flash: not run, not run in this column
- omp x gemini-3-flash-preview: not run, not run in this column
- omp x gemini-3.1-pro-preview: not run, not run in this column
- omp x gemini-3.5-flash: not run, not run in this column
- omp x gemini-3.5-flash-lite: not run, not run in this column
- omp x gemini-3.6-flash: not run, not run in this column
- omp x gemini-3.7-flash: not run, not run in this column
- omp x gemini-3.8-flash: not run, not run in this column
- omp x glm-5.3: not run, not run in this column
- omp x glm-5.3-flash: not run, not run in this column
- omp x gpt-5.2: not run, not run in this column
- omp x gpt-5.3-codex: not run, not run in this column
- omp x gpt-5.4: not run, not run in this column
- omp x gpt-5.4-mini: not run, not run in this column
- omp x gpt-5.5: not run, not run in this column
- omp x gpt-5.6-luna: not run, not run in this column
- omp x gpt-5.6-sol: not run, not run in this column
- omp x gpt-5.6-terra: not run, not run in this column
- omp x grok-4.20: not run, not run in this column
- omp x grok-4.3: not run, not run in this column
- omp x grok-4.5: not run, not run in this column
- omp x grok-4.6: not run, not run in this column
- omp x grok-build-0.1: not run, not run in this column
- omp x hunyuan-4-preview: not run, not run in this column
- omp x kimi-k2.7-code: not run, not run in this column
- omp x kimi-k3: not run, not run in this column
- omp x mistral-medium-3.5: not run, not run in this column
- omp x nemotron-3-super: not run, not run in this column
- omp x nemotron-3.5-lightning: not run, not run in this column
- omp x qwen3.7-max: not run, not run in this column
- omp x qwen3.7-plus: not run, not run in this column
- omp x qwen3.8-flash: not run, not run in this column
- omp x qwen3.8-max: not run, not run in this column
- omp x step-3.7-flash: not run, not run in this column
- opencode x claude-fable-5: not run, not run in this column
- opencode x claude-fable-5-1: not run, not run in this column
- opencode x claude-haiku-4.5: not run, not run in this column
- opencode x claude-opus-4.7: not run, not run in this column
- opencode x claude-opus-4.8: not run, not run in this column
- opencode x claude-opus-5: not run, not run in this column
- opencode x claude-opus-5.5: not run, not run in this column
- opencode x claude-sonnet-5: not run, not run in this column
- opencode x deepseek-v4-flash: not run, not run in this column
- opencode x deepseek-v4-pro: not run, not run in this column
- opencode x gemini-3-flash-preview: not run, not run in this column
- opencode x gemini-3.1-pro-preview: not run, not run in this column
- opencode x gemini-3.5-flash: not run, not run in this column
- opencode x gemini-3.5-flash-lite: not run, not run in this column
- opencode x gemini-3.6-flash: not run, not run in this column
- opencode x gemini-3.7-flash: not run, not run in this column
- opencode x gemini-3.8-flash: not run, not run in this column
- opencode x glm-5.3: not run, not run in this column
- opencode x glm-5.3-flash: not run, not run in this column
- opencode x gpt-5.2: not run, not run in this column
- opencode x gpt-5.3-codex: not run, not run in this column
- opencode x gpt-5.4-mini: not run, not run in this column
- opencode x gpt-5.5: not run, not run in this column
- opencode x gpt-5.6-luna: not run, not run in this column
- opencode x gpt-5.6-sol: not run, not run in this column
- opencode x gpt-5.6-terra: not run, not run in this column
- opencode x kimi-k2.7-code: not run, not run in this column
- opencode x kimi-k3: not run, not run in this column
- opencode x mistral-medium-3.5: not run, not run in this column
- opencode x qwen3.7-max: not run, not run in this column
- opencode x qwen3.8-max: not run, not run in this column
- opencode x step-3.7-flash: not run, not run in this column
- openhands x claude-fable-5: not run, not run in this column
- openhands x claude-fable-5-1: not run, not run in this column
- openhands x claude-haiku-4.5: not run, not run in this column
- openhands x claude-opus-4.7: not run, not run in this column
- openhands x claude-opus-4.8: not run, not run in this column
- openhands x claude-opus-5: not run, not run in this column
- openhands x claude-opus-5.5: not run, not run in this column
- openhands x claude-sonnet-4.6: not run, not run in this column
- openhands x claude-sonnet-5: not run, not run in this column
- openhands x deepseek-v4-flash: not run, not run in this column
- openhands x deepseek-v4-pro: not run, not run in this column
- openhands x deepseek-v4.1-flash: not run, not run in this column
- openhands x gemini-3-flash-preview: not run, not run in this column
- openhands x gemini-3.1-pro-preview: not run, not run in this column
- openhands x gemini-3.5-flash: not run, not run in this column
- openhands x gemini-3.5-flash-lite: not run, not run in this column
- openhands x gemini-3.6-flash: not run, not run in this column
- openhands x gemini-3.7-flash: not run, not run in this column
- openhands x gemini-3.8-flash: not run, not run in this column
- openhands x glm-5.3: not run, not run in this column
- openhands x glm-5.3-flash: not run, not run in this column
- openhands x gpt-5.2: not run, not run in this column
- openhands x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- openhands x gpt-5.4: not run, not run in this column
- openhands x gpt-5.4-mini: not run, not run in this column
- openhands x gpt-5.5: not run, not run in this column
- openhands x gpt-5.6-luna: not run, not run in this column
- openhands x gpt-5.6-sol: not run, not run in this column
- openhands x gpt-5.6-terra: not run, not run in this column
- openhands x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- openhands x grok-4.20: not run, not run in this column
- openhands x grok-4.3: not run, not run in this column
- openhands x grok-4.5: not run, not run in this column
- openhands x grok-4.6: not run, not run in this column
- openhands x grok-build-0.1: not run, not run in this column
- openhands x hunyuan-4-preview: not run, not run in this column
- openhands x kimi-k2.7-code: not run, not run in this column
- openhands x kimi-k3: not run, not run in this column
- openhands x mistral-medium-3.5: not run, not run in this column
- openhands x nemotron-3-super: not run, not run in this column
- openhands x nemotron-3.5-lightning: not run, not run in this column
- openhands x qwen3.7-max: not run, not run in this column
- openhands x qwen3.7-plus: not run, not run in this column
- openhands x qwen3.8-flash: not run, not run in this column
- openhands x qwen3.8-max: not run, not run in this column
- openhands x step-3.7-flash: not run, not run in this column
- pi x claude-fable-5: not run, not run in this column
- pi x claude-fable-5-1: not run, not run in this column
- pi x claude-haiku-4.5: not run, not run in this column
- pi x claude-opus-4.7: not run, not run in this column
- pi x claude-opus-4.8: not run, not run in this column
- pi x claude-opus-5: not run, not run in this column
- pi x claude-opus-5.5: not run, not run in this column
- pi x claude-sonnet-5: not run, not run in this column
- pi x deepseek-v4-flash: not run, not run in this column
- pi x deepseek-v4-pro: not run, not run in this column
- pi x gemini-3-flash-preview: not run, not run in this column
- pi x gemini-3.1-pro-preview: not run, not run in this column
- pi x gemini-3.5-flash: not run, not run in this column
- pi x gemini-3.5-flash-lite: not run, not run in this column
- pi x gemini-3.6-flash: not run, not run in this column
- pi x gemini-3.7-flash: not run, not run in this column
- pi x gemini-3.8-flash: not run, not run in this column
- pi x glm-5.3: not run, not run in this column
- pi x glm-5.3-flash: not run, not run in this column
- pi x gpt-5.2: not run, not run in this column
- pi x gpt-5.3-codex: not run, not run in this column
- pi x gpt-5.4-mini: not run, not run in this column
- pi x gpt-5.5: not run, not run in this column
- pi x gpt-5.6-luna: not run, not run in this column
- pi x gpt-5.6-sol: not run, not run in this column
- pi x gpt-5.6-terra: not run, not run in this column
- pi x kimi-k2.7-code: not run, not run in this column
- pi x kimi-k3: not run, not run in this column
- pi x mistral-medium-3.5: not run, not run in this column
- pi x qwen3.7-max: not run, not run in this column
- pi x qwen3.8-max: not run, not run in this column
- pi x step-3.7-flash: not run, not run in this column
- qwen x claude-fable-5: not run, not run in this column
- qwen x claude-fable-5-1: not run, not run in this column
- qwen x claude-haiku-4.5: not run, not run in this column
- qwen x claude-opus-4.7: not run, not run in this column
- qwen x claude-opus-4.8: not run, not run in this column
- qwen x claude-opus-5: not run, not run in this column
- qwen x claude-opus-5.5: not run, not run in this column
- qwen x claude-sonnet-5: not run, not run in this column
- qwen x deepseek-v4-flash: not run, not run in this column
- qwen x deepseek-v4-pro: not run, not run in this column
- qwen x gemini-3-flash-preview: not run, not run in this column
- qwen x gemini-3.1-pro-preview: not run, not run in this column
- qwen x gemini-3.5-flash: not run, not run in this column
- qwen x gemini-3.5-flash-lite: not run, not run in this column
- qwen x gemini-3.6-flash: not run, not run in this column
- qwen x gemini-3.7-flash: not run, not run in this column
- qwen x gemini-3.8-flash: not run, not run in this column
- qwen x glm-5.3: not run, not run in this column
- qwen x glm-5.3-flash: not run, not run in this column
- qwen x gpt-5.2: not run, not run in this column
- qwen x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- qwen x gpt-5.4-mini: not run, not run in this column
- qwen x gpt-5.5: not run, not run in this column
- qwen x gpt-5.6-luna: not run, not run in this column
- qwen x gpt-5.6-sol: not run, not run in this column
- qwen x gpt-5.6-terra: not run, not run in this column
- qwen x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- qwen x kimi-k2.7-code: not run, not run in this column
- qwen x kimi-k3: not run, not run in this column
- qwen x mistral-medium-3.5: not run, not run in this column
- qwen x qwen3.7-max: not run, not run in this column
- qwen x qwen3.8-max: not run, not run in this column
- qwen x step-3.7-flash: not run, not run in this column

## Provider: vercel

| Harness | Model | First | Follow-up | Switch | Artifact | Recycle | Served by | Notes |
|---|---|---|---|---|---|---|---|---|
| agentzero | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Vercel AI Gateway | no prompt cache reads (finding below) ; served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) |
| aider | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Vercel AI Gateway | no prompt cache reads (finding below) ; served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) |
| aider | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-6-luna (the provider's alias of the same model) |
| aider | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | Vercel AI Gateway | served as openai/gpt-6-sol (the provider's alias of the same model) |
| aider | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 51% of input |
| cheetahclaws | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Vercel AI Gateway | no prompt cache reads (finding below) ; served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) |
| cheetahclaws | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-6-luna (the provider's alias of the same model) |
| cheetahclaws | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | Vercel AI Gateway | served as openai/gpt-6-sol (the provider's alias of the same model) |
| cheetahclaws | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 17% of input |
| claude-code | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Vercel AI Gateway | served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) ; cache 99% of input |
| cline | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Vercel AI Gateway | no prompt cache reads (finding below) ; 4 turn(s) unlabelled (finding below) |
| cline | deepseek-v4.1-flash | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway |  |
| cline | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | Vercel AI Gateway |  |
| cline | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway | 4 turn(s) unlabelled (finding below) ; cache 65% of input |
| cline | grok-4.1-fast | FAIL | n/a | n/a | n/a | n/a | Vercel AI Gateway | first: The turn failed: Stream error occurred |
| cline | grok-4.20 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| cline | grok-4.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| cline | grok-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| cline | grok-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| cline | grok-build-0.1 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| cline | hunyuan-4-preview | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | llama-3.3-70b | FAIL | n/a | n/a | n/a | n/a | Vercel AI Gateway | first: The turn failed: undefined: This model doesn't support tool use in streaming mode. |
| cline | llama-4-maverick | FAIL | n/a | n/a | n/a | n/a | Vercel AI Gateway | first: The turn failed: Tool calling is not supported for model: meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8 |
| cline | llama-4-scout | pass | pass | pass (gpt-5.6-sol) | FAIL | pass | Vercel AI Gateway | artifact: no file card (files: none); ning exactly the word HELLO, then reply DONE. CLINE Used 2 tools editor("/data/workspaces/hsess42a22c26ecb546b9a |
| cline | muse-glimmer-30b | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| cline | muse-spark-1.1 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| cline | muse-spark-1.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| cline | muse-spark-1.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway |  |
| cline | nemotron-3-super | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | nemotron-3.5-lightning | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | qwen3.7-plus | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | qwen3.8-27b | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| cline | qwen3.8-flash | pass | pass | pass (gpt-5.4) | pass | pass | Vercel AI Gateway |  |
| codex | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway |  |
| codex | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| codex | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| codex | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway | 4 turn(s) unlabelled (finding below) ; cache 52% of input |
| dsh | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Vercel AI Gateway | 4 turn(s) unlabelled (finding below) ; cache 100% of input |
| dsh | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway |  |
| dsh | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| dsh | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| dsh | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway | 4 turn(s) unlabelled (finding below) ; cache 100% of input |
| goose | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Vercel AI Gateway | no prompt cache reads (finding below) ; served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) |
| goose | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 62% of input |
| grok | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Vercel AI Gateway | no prompt cache reads (finding below) ; served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) |
| hermes | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Vercel AI Gateway | no prompt cache reads (finding below) ; served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) |
| hermes | deepseek-v4.1-flash | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| hermes | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway |  |
| hermes | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| hermes | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| hermes | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 0% of input |
| hermes | grok-4.1-fast | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| hermes | grok-4.20 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| hermes | grok-4.3 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| hermes | grok-4.5 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| hermes | grok-4.6 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| hermes | grok-build-0.1 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| hermes | hunyuan-4-preview | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| hermes | kimi-k2.7-code | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| hermes | ling-3.0-flash | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| hermes | llama-3.3-70b | FAIL | n/a | n/a | n/a | n/a | Vercel AI Gateway | first: The turn failed: exit_code=0 |
| hermes | llama-4-maverick | FAIL | n/a | n/a | n/a | n/a | Vercel AI Gateway | first: The turn failed: exit_code=0 |
| hermes | llama-4-scout | pass | pass | pass (gpt-6-astra) | FAIL | FAIL | Vercel AI Gateway | artifact: no file card (files: none); Create a file named hello-hermes.txt containing exactly the word HELLO, then reply DONE. HERMES write_file(path= ; recycle: answered without M1-llama-4-scout: What exact word did I ask you to reply with in my very first message of this task? Reply with just that w |
| hermes | muse-glimmer-30b | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| hermes | muse-spark-1.1 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| hermes | muse-spark-1.2 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| hermes | muse-spark-1.3 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| hermes | nemotron-3-super | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| hermes | nemotron-3.5-lightning | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| hermes | qwen3.7-plus | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| hermes | qwen3.8-27b | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| hermes | qwen3.8-flash | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway |  |
| kilo | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Vercel AI Gateway | served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) ; cache 69% of input |
| kimi | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Vercel AI Gateway | no prompt cache reads (finding below) ; served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) |
| kimi | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-6-luna (the provider's alias of the same model) |
| kimi | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | Vercel AI Gateway | served as openai/gpt-6-sol (the provider's alias of the same model) |
| kimi | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 50% of input |
| minimax | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Vercel AI Gateway | no prompt cache reads (finding below) ; served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) |
| omp | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Vercel AI Gateway | served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) ; cache 100% of input |
| omp | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-6-astra (the provider's alias of the same model) |
| omp | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as openai/gpt-6-luna (the provider's alias of the same model) |
| omp | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as openai/gpt-6-sol (the provider's alias of the same model) |
| omp | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway | 1 turn(s) unlabelled (finding below) ; served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 100% of input |
| opencode | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Vercel AI Gateway | served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) ; cache 100% of input |
| opencode | deepseek-v4.1-flash | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as deepseek/deepseek-v4.1-flash (the provider's alias of the same model) |
| opencode | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-6-astra (the provider's alias of the same model) |
| opencode | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as openai/gpt-6-luna (the provider's alias of the same model) |
| opencode | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as openai/gpt-6-sol (the provider's alias of the same model) |
| opencode | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 100% of input |
| opencode | grok-4.1-fast | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.1-fast-reasoning (finding below) |
| opencode | grok-4.20 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.20-reasoning (the provider's alias of the same model) |
| opencode | grok-4.3 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.3 (the provider's alias of the same model) |
| opencode | grok-4.5 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.5 (the provider's alias of the same model) |
| opencode | grok-4.6 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.6 (the provider's alias of the same model) |
| opencode | grok-build-0.1 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as spacexai/grok-build-0.1 (the provider's alias of the same model) |
| opencode | hunyuan-4-preview | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as tencent/hy4-preview (the provider's alias of the same model) |
| opencode | llama-3.3-70b | FAIL | n/a | n/a | n/a | n/a | Vercel AI Gateway | first: The turn failed: undefined: The maximum tokens you requested exceeds the model limit of 8192. Try again with a maximum tokens value that is  |
| opencode | llama-4-maverick | FAIL | n/a | n/a | n/a | n/a | Vercel AI Gateway | served as meta/llama-4-maverick (the provider's alias of the same model) ; first: The turn failed: Tool calling is not supported for model: meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8 |
| opencode | llama-4-scout | pass | pass | pass (gpt-6-astra) | FAIL | FAIL | Vercel AI Gateway | served as meta/llama-4-scout (the provider's alias of the same model) ; artifact: no file card (files: none); e word HELLO, then reply DONE. OPENCODE Used a tool write(content="HELLO", filePath="/data/workspaces/hsess427c8 ; recycle: answered without M1-llama-4-scout: What exact word did I ask you to reply with in my very first message of this task? Reply with just that w |
| opencode | muse-glimmer-30b | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as meta/muse-glimmer-30b (the provider's alias of the same model) |
| opencode | muse-spark-1.1 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as meta/muse-spark-1.1 (the provider's alias of the same model) |
| opencode | muse-spark-1.2 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as meta/muse-spark-1.2 (the provider's alias of the same model) |
| opencode | muse-spark-1.3 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as meta/muse-spark-1.3 (the provider's alias of the same model) |
| opencode | nemotron-3-super | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as nvidia/nemotron-3-super-120b-a12b (the provider's alias of the same model) |
| opencode | nemotron-3.5-lightning | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as nvidia/nemotron-3.5-lightning (the provider's alias of the same model) |
| opencode | qwen3.7-plus | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as alibaba/qwen3.7-plus (the provider's alias of the same model) |
| opencode | qwen3.8-27b | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as alibaba/qwen3.8-27b (the provider's alias of the same model) |
| opencode | qwen3.8-flash | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as alibaba/qwen3.8-flash (the provider's alias of the same model) |
| openhands | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Vercel AI Gateway | served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) ; cache 69% of input |
| openhands | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-6-luna (the provider's alias of the same model) |
| openhands | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | Vercel AI Gateway | served as openai/gpt-6-sol (the provider's alias of the same model) |
| openhands | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 66% of input |
| pi | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Vercel AI Gateway | served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) ; cache 83% of input |
| pi | deepseek-v4.1-flash | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as deepseek/deepseek-v4.1-flash (the provider's alias of the same model) |
| pi | gpt-6-astra | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-6-astra (the provider's alias of the same model) |
| pi | gpt-6-luna | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as openai/gpt-6-luna (the provider's alias of the same model) |
| pi | gpt-6-sol | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as openai/gpt-6-sol (the provider's alias of the same model) |
| pi | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 100% of input |
| pi | grok-4.1-fast | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.1-fast-reasoning (finding below) |
| pi | grok-4.20 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.20-reasoning (the provider's alias of the same model) |
| pi | grok-4.3 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.3 (the provider's alias of the same model) |
| pi | grok-4.5 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.5 (the provider's alias of the same model) |
| pi | grok-4.6 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.6 (the provider's alias of the same model) |
| pi | grok-build-0.1 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as spacexai/grok-build-0.1 (the provider's alias of the same model) |
| pi | hunyuan-4-preview | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as tencent/hy4-preview (the provider's alias of the same model) |
| pi | llama-3.3-70b | FAIL | n/a | n/a | n/a | n/a | Vercel AI Gateway | served as meta/llama-3.3-70b (the provider's alias of the same model) ; first: The turn failed: 400: {"message":"undefined: The maximum tokens you requested exceeds the model limit of 8192. Try again with a maximum toke |
| pi | llama-4-maverick | FAIL | n/a | n/a | n/a | n/a | Vercel AI Gateway | served as meta/llama-4-maverick (the provider's alias of the same model) ; first: The turn failed: 405: {"message":"Tool calling is not supported for model: meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8","type":"AI_API |
| pi | llama-4-scout | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as meta/llama-4-scout (the provider's alias of the same model) |
| pi | muse-glimmer-30b | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as meta/muse-glimmer-30b (the provider's alias of the same model) |
| pi | muse-spark-1.1 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as meta/muse-spark-1.1 (the provider's alias of the same model) |
| pi | muse-spark-1.2 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as meta/muse-spark-1.2 (the provider's alias of the same model) |
| pi | muse-spark-1.3 | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as meta/muse-spark-1.3 (the provider's alias of the same model) |
| pi | nemotron-3-super | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as nvidia/nemotron-3-super-120b-a12b (the provider's alias of the same model) |
| pi | nemotron-3.5-lightning | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as nvidia/nemotron-3.5-lightning (the provider's alias of the same model) |
| pi | qwen3.7-plus | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as alibaba/qwen3.7-plus (the provider's alias of the same model) |
| pi | qwen3.8-27b | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as alibaba/qwen3.8-27b (the provider's alias of the same model) |
| pi | qwen3.8-flash | pass | pass | pass (gpt-6-astra) | pass | pass | Vercel AI Gateway | served as alibaba/qwen3.8-flash (the provider's alias of the same model) |
| qwen | claude-haiku-5.5 | pass | pass | pass (claude-haiku-4.5) | pass | pass | Vercel AI Gateway | no prompt cache reads (finding below) ; served as anthropic/claude-haiku-5.5 (the provider's alias of the same model) |
| qwen | deepseek-v4.1-flash | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway | served as deepseek/deepseek-v4.1-flash (the provider's alias of the same model) |
| qwen | gpt-6-luna | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-6-luna (the provider's alias of the same model) |
| qwen | gpt-6-sol | pass | pass | pass (gpt-6-luna) | pass | pass | Vercel AI Gateway | served as openai/gpt-6-sol (the provider's alias of the same model) |
| qwen | gpt-6.1-sol | pass | pass | pass (gpt-6-sol) | pass | pass | Vercel AI Gateway | served as openai/gpt-6.1-sol (the provider's alias of the same model) ; cache 40% of input |
| qwen | grok-4.1-fast | FAIL | n/a | n/a | n/a | n/a | Vercel AI Gateway | served as spacexai/grok-4.1-fast-reasoning (finding below) ; first: The turn failed: API Error: Stream error occurred |
| qwen | grok-4.20 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.20-reasoning (the provider's alias of the same model) |
| qwen | grok-4.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.3 (the provider's alias of the same model) |
| qwen | grok-4.5 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.5 (the provider's alias of the same model) |
| qwen | grok-4.6 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as spacexai/grok-4.6 (the provider's alias of the same model) |
| qwen | grok-build-0.1 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as spacexai/grok-build-0.1 (the provider's alias of the same model) |
| qwen | hunyuan-4-preview | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway | served as tencent/hy4-preview (the provider's alias of the same model) |
| qwen | llama-3.3-70b | FAIL | n/a | n/a | n/a | n/a | Vercel AI Gateway | first: The turn failed: API Error: 400 undefined: The maximum tokens you requested exceeds the model limit of 8192. Try again with a maximum tokens |
| qwen | llama-4-maverick | FAIL | n/a | n/a | n/a | n/a | Vercel AI Gateway | first: The turn failed: API Error: 405 Tool calling is not supported for model: meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8 |
| qwen | llama-4-scout | pass | pass | pass (gpt-5.6-sol) | FAIL | FAIL | Vercel AI Gateway | served as meta/llama-4-scout (the provider's alias of the same model) ; artifact: The turn failed: API Error: Model stream ended with empty response text. ; recycle: answered without M1-llama-4-scout:  very first message of this task? Reply with just that word. QWEN CODE DONE <write_file for file_path '/d |
| qwen | muse-glimmer-30b | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as meta/muse-glimmer-30b (the provider's alias of the same model) |
| qwen | muse-spark-1.1 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as meta/muse-spark-1.1 (the provider's alias of the same model) |
| qwen | muse-spark-1.2 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as meta/muse-spark-1.2 (the provider's alias of the same model) |
| qwen | muse-spark-1.3 | pass | pass | pass (gpt-5.6-sol) | pass | pass | Vercel AI Gateway | served as meta/muse-spark-1.3 (the provider's alias of the same model) |
| qwen | nemotron-3-super | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway | served as nvidia/nemotron-3-super-120b-a12b (the provider's alias of the same model) |
| qwen | nemotron-3.5-lightning | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway | served as nvidia/nemotron-3.5-lightning (the provider's alias of the same model) |
| qwen | qwen3.7-plus | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway | served as alibaba/qwen3.7-plus (the provider's alias of the same model) |
| qwen | qwen3.8-27b | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway | served as alibaba/qwen3.8-27b (the provider's alias of the same model) |
| qwen | qwen3.8-flash | pass | pass | pass (qwen3.7-max) | pass | pass | Vercel AI Gateway | served as alibaba/qwen3.8-flash (the provider's alias of the same model) |

162 pairs, 703 of 721 scenario runs passed; 9 pairs served by another connection or as another model are findings, not counted.

Findings, pairs served by a connection other than the one under test or as a model other than the id asked for:

- agentzero x claude-haiku-5.5: no prompt cache reads over 56653 input tokens (every call paid full price)
- aider x claude-haiku-5.5: no prompt cache reads over 24423 input tokens (every call paid full price)
- cheetahclaws x claude-haiku-5.5: no prompt cache reads over 75392 input tokens (every call paid full price)
- cline x claude-haiku-5.5: 4 turn(s) report no served model, so rule 2 could not judge them
- cline x claude-haiku-5.5: no prompt cache reads over 51624 input tokens (every call paid full price)
- cline x gpt-6.1-sol: 4 turn(s) report no served model, so rule 2 could not judge them
- codex x gpt-6.1-sol: 4 turn(s) report no served model, so rule 2 could not judge them
- dsh x claude-haiku-5.5: 4 turn(s) report no served model, so rule 2 could not judge them
- dsh x gpt-6.1-sol: 4 turn(s) report no served model, so rule 2 could not judge them
- goose x claude-haiku-5.5: no prompt cache reads over 179095 input tokens (every call paid full price)
- grok x claude-haiku-5.5: no prompt cache reads over 95311 input tokens (every call paid full price)
- hermes x claude-haiku-5.5: no prompt cache reads over 124056 input tokens (every call paid full price)
- kimi x claude-haiku-5.5: no prompt cache reads over 184677 input tokens (every call paid full price)
- minimax x claude-haiku-5.5: no prompt cache reads over 83965 input tokens (every call paid full price)
- omp x gpt-6.1-sol: 1 turn(s) report no served model, so rule 2 could not judge them
- opencode x grok-4.1-fast: served as spacexai/grok-4.1-fast-reasoning (the CLI reports the model it ran)
- pi x grok-4.1-fast: served as spacexai/grok-4.1-fast-reasoning (the CLI reports the model it ran)
- qwen x claude-haiku-5.5: no prompt cache reads over 569929 input tokens (every call paid full price)
- qwen x grok-4.1-fast: served as spacexai/grok-4.1-fast-reasoning (the CLI reports the model it ran)

Not run in this column, 974 pairs the provider serves that the harness did not run, with the reason:

- agentzero x claude-fable-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- agentzero x claude-fable-5-1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- agentzero x claude-haiku-4.5: not run, not run in this column
- agentzero x claude-opus-4.7: not run, not run in this column
- agentzero x claude-opus-4.8: not run, not run in this column
- agentzero x claude-opus-5: not run, not run in this column
- agentzero x claude-opus-5.5: not run, not run in this column
- agentzero x claude-sonnet-4.6: not run, not run in this column
- agentzero x claude-sonnet-5: not run, not run in this column
- agentzero x claude-sonnet-5.5: not run, not run in this column
- agentzero x deepseek-v4-flash: not run, not run in this column
- agentzero x deepseek-v4-pro: not run, not run in this column
- agentzero x deepseek-v4.1-flash: not run, not run in this column
- agentzero x gemini-3-flash-preview: not run, not run in this column
- agentzero x gemini-3.1-flash-lite: not run, not run in this column
- agentzero x gemini-3.1-pro-preview: not run, not run in this column
- agentzero x gemini-3.5-flash: not run, not run in this column
- agentzero x gemini-3.5-flash-lite: not run, not run in this column
- agentzero x gemini-3.6-flash: not run, not run in this column
- agentzero x gemini-3.7-flash: not run, not run in this column
- agentzero x gemini-3.8-flash: not run, not run in this column
- agentzero x glm-5.3: not run, not run in this column
- agentzero x glm-5.3-flash: not run, not run in this column
- agentzero x gpt-5.2: not run, not run in this column
- agentzero x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- agentzero x gpt-5.4: not run, not run in this column
- agentzero x gpt-5.4-mini: not run, not run in this column
- agentzero x gpt-5.5: not run, not run in this column
- agentzero x gpt-5.6-luna: not run, not run in this column
- agentzero x gpt-5.6-sol: not run, not run in this column
- agentzero x gpt-5.6-terra: not run, not run in this column
- agentzero x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- agentzero x gpt-6-luna: not run, not run in this column
- agentzero x gpt-6-sol: not run, not run in this column
- agentzero x gpt-6.1-sol: not run, not run in this column
- agentzero x grok-4.20: not run, not run in this column
- agentzero x grok-4.3: not run, not run in this column
- agentzero x grok-4.5: not run, not run in this column
- agentzero x grok-4.6: not run, not run in this column
- agentzero x grok-build-0.1: not run, not run in this column
- agentzero x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- agentzero x hunyuan-4-preview: not run, not run in this column
- agentzero x kimi-k2.7-code: not run, not run in this column
- agentzero x kimi-k3: not run, not run in this column
- agentzero x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- agentzero x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- agentzero x mistral-medium-3.5: not run, not run in this column
- agentzero x muse-glimmer-30b: not run, not run in this column
- agentzero x muse-spark-1.1: not run, not run in this column
- agentzero x muse-spark-1.2: not run, not run in this column
- agentzero x muse-spark-1.3: not run, not run in this column
- agentzero x nemotron-3-super: not run, not run in this column
- agentzero x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- agentzero x nemotron-3.5-lightning: not run, not run in this column
- agentzero x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- agentzero x qwen3.7-max: not run, not run in this column
- agentzero x qwen3.7-plus: not run, not run in this column
- agentzero x qwen3.8-27b: not run, not run in this column
- agentzero x qwen3.8-flash: not run, not run in this column
- agentzero x qwen3.8-max: not run, not run in this column
- agentzero x step-3.7-flash: not run, not run in this column
- aider x claude-fable-5: not run, not run in this column
- aider x claude-fable-5-1: not run, not run in this column
- aider x claude-haiku-4.5: not run, not run in this column
- aider x claude-opus-4.7: not run, not run in this column
- aider x claude-opus-4.8: not run, not run in this column
- aider x claude-opus-5: not run, not run in this column
- aider x claude-opus-5.5: not run, not run in this column
- aider x claude-sonnet-4.6: not run, not run in this column
- aider x claude-sonnet-5: not run, not run in this column
- aider x claude-sonnet-5.5: not run, not run in this column
- aider x deepseek-v4-flash: not run, not run in this column
- aider x deepseek-v4-pro: not run, not run in this column
- aider x deepseek-v4.1-flash: not run, not run in this column
- aider x gemini-3-flash-preview: not run, not run in this column
- aider x gemini-3.1-flash-lite: not run, not run in this column
- aider x gemini-3.1-pro-preview: not run, not run in this column
- aider x gemini-3.5-flash: not run, not run in this column
- aider x gemini-3.5-flash-lite: not run, not run in this column
- aider x gemini-3.6-flash: not run, not run in this column
- aider x gemini-3.7-flash: not run, not run in this column
- aider x gemini-3.8-flash: not run, not run in this column
- aider x glm-5.3: not run, not run in this column
- aider x glm-5.3-flash: not run, not run in this column
- aider x gpt-5.2: not run, not run in this column
- aider x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- aider x gpt-5.4: not run, not run in this column
- aider x gpt-5.4-mini: not run, not run in this column
- aider x gpt-5.5: not run, not run in this column
- aider x gpt-5.6-luna: not run, not run in this column
- aider x gpt-5.6-sol: not run, not run in this column
- aider x gpt-5.6-terra: not run, not run in this column
- aider x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- aider x grok-4.20: not run, not run in this column
- aider x grok-4.3: not run, not run in this column
- aider x grok-4.5: not run, not run in this column
- aider x grok-4.6: not run, not run in this column
- aider x grok-build-0.1: not run, not run in this column
- aider x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- aider x hunyuan-4-preview: not run, not run in this column
- aider x kimi-k2.7-code: not run, not run in this column
- aider x kimi-k3: not run, not run in this column
- aider x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- aider x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- aider x mistral-medium-3.5: not run, not run in this column
- aider x muse-glimmer-30b: not run, not run in this column
- aider x muse-spark-1.1: not run, not run in this column
- aider x muse-spark-1.2: not run, not run in this column
- aider x muse-spark-1.3: not run, not run in this column
- aider x nemotron-3-super: not run, not run in this column
- aider x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- aider x nemotron-3.5-lightning: not run, not run in this column
- aider x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- aider x qwen3.7-max: not run, not run in this column
- aider x qwen3.7-plus: not run, not run in this column
- aider x qwen3.8-27b: not run, not run in this column
- aider x qwen3.8-flash: not run, not run in this column
- aider x qwen3.8-max: not run, not run in this column
- aider x step-3.7-flash: not run, not run in this column
- cheetahclaws x claude-fable-5: not run, not run in this column
- cheetahclaws x claude-fable-5-1: not run, not run in this column
- cheetahclaws x claude-haiku-4.5: not run, not run in this column
- cheetahclaws x claude-opus-4.7: not run, not run in this column
- cheetahclaws x claude-opus-4.8: not run, not run in this column
- cheetahclaws x claude-opus-5: not run, not run in this column
- cheetahclaws x claude-opus-5.5: not run, not run in this column
- cheetahclaws x claude-sonnet-4.6: not run, not run in this column
- cheetahclaws x claude-sonnet-5: not run, not run in this column
- cheetahclaws x claude-sonnet-5.5: not run, not run in this column
- cheetahclaws x deepseek-v4-flash: not run, not run in this column
- cheetahclaws x deepseek-v4-pro: not run, not run in this column
- cheetahclaws x deepseek-v4.1-flash: not run, not run in this column
- cheetahclaws x gemini-3-flash-preview: not run, not run in this column
- cheetahclaws x gemini-3.1-flash-lite: not run, not run in this column
- cheetahclaws x gemini-3.1-pro-preview: not run, not run in this column
- cheetahclaws x gemini-3.5-flash: not run, not run in this column
- cheetahclaws x gemini-3.5-flash-lite: not run, not run in this column
- cheetahclaws x gemini-3.6-flash: not run, not run in this column
- cheetahclaws x gemini-3.7-flash: not run, not run in this column
- cheetahclaws x gemini-3.8-flash: not run, not run in this column
- cheetahclaws x glm-5.3: not run, not run in this column
- cheetahclaws x glm-5.3-flash: not run, not run in this column
- cheetahclaws x gpt-5.2: not run, not run in this column
- cheetahclaws x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cheetahclaws x gpt-5.4: not run, not run in this column
- cheetahclaws x gpt-5.4-mini: not run, not run in this column
- cheetahclaws x gpt-5.5: not run, not run in this column
- cheetahclaws x gpt-5.6-luna: not run, not run in this column
- cheetahclaws x gpt-5.6-sol: not run, not run in this column
- cheetahclaws x gpt-5.6-terra: not run, not run in this column
- cheetahclaws x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cheetahclaws x grok-4.20: not run, not run in this column
- cheetahclaws x grok-4.3: not run, not run in this column
- cheetahclaws x grok-4.5: not run, not run in this column
- cheetahclaws x grok-4.6: not run, not run in this column
- cheetahclaws x grok-build-0.1: not run, not run in this column
- cheetahclaws x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cheetahclaws x hunyuan-4-preview: not run, not run in this column
- cheetahclaws x kimi-k2.7-code: not run, not run in this column
- cheetahclaws x kimi-k3: not run, not run in this column
- cheetahclaws x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cheetahclaws x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cheetahclaws x mistral-medium-3.5: not run, not run in this column
- cheetahclaws x muse-glimmer-30b: not run, not run in this column
- cheetahclaws x muse-spark-1.1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cheetahclaws x muse-spark-1.2: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cheetahclaws x muse-spark-1.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cheetahclaws x nemotron-3-super: not run, not run in this column
- cheetahclaws x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cheetahclaws x nemotron-3.5-lightning: not run, not run in this column
- cheetahclaws x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cheetahclaws x qwen3.7-max: not run, not run in this column
- cheetahclaws x qwen3.7-plus: not run, not run in this column
- cheetahclaws x qwen3.8-27b: not run, not run in this column
- cheetahclaws x qwen3.8-flash: not run, not run in this column
- cheetahclaws x qwen3.8-max: not run, not run in this column
- cheetahclaws x step-3.7-flash: not run, not run in this column
- claude-code x claude-fable-5: not run, not run in this column
- claude-code x claude-fable-5-1: not run, not run in this column
- claude-code x claude-haiku-4.5: not run, not run in this column
- claude-code x claude-opus-4.7: not run, not run in this column
- claude-code x claude-opus-4.8: not run, not run in this column
- claude-code x claude-opus-5: not run, not run in this column
- claude-code x claude-opus-5.5: not run, not run in this column
- claude-code x claude-sonnet-4.6: not run, not run in this column
- claude-code x claude-sonnet-5: not run, not run in this column
- claude-code x claude-sonnet-5.5: not run, not run in this column
- claude-code x deepseek-v4-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x deepseek-v4-pro: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x deepseek-v4.1-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gemini-3-flash-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gemini-3.1-flash-lite: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gemini-3.1-pro-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gemini-3.5-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gemini-3.5-flash-lite: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gemini-3.6-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gemini-3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gemini-3.8-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x glm-5.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x glm-5.3-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-5.2: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-5.3-codex: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-5.4: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-5.4-mini: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-5.6-luna: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-5.6-sol: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-5.6-terra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-6-astra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-6-luna: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-6-sol: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x gpt-6.1-sol: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x grok-4.20: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x grok-4.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x grok-4.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x grok-4.6: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x grok-build-0.1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x hunyuan-4-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x kimi-k2.7-code: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x kimi-k3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x mistral-medium-3.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x muse-glimmer-30b: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x muse-spark-1.1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x muse-spark-1.2: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x muse-spark-1.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x nemotron-3-super: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x nemotron-3.5-lightning: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x qwen3.7-max: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x qwen3.7-plus: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x qwen3.8-27b: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x qwen3.8-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x qwen3.8-max: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- claude-code x step-3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x claude-fable-5: not run, not run in this column
- cline x claude-fable-5-1: not run, not run in this column
- cline x claude-haiku-4.5: not run, not run in this column
- cline x claude-opus-4.7: not run, not run in this column
- cline x claude-opus-4.8: not run, not run in this column
- cline x claude-opus-5: not run, not run in this column
- cline x claude-opus-5.5: not run, not run in this column
- cline x claude-sonnet-4.6: not run, not run in this column
- cline x claude-sonnet-5: not run, not run in this column
- cline x claude-sonnet-5.5: not run, not run in this column
- cline x deepseek-v4-flash: not run, not run in this column
- cline x deepseek-v4-pro: not run, not run in this column
- cline x gemini-3-flash-preview: not run, not run in this column
- cline x gemini-3.1-flash-lite: not run, not run in this column
- cline x gemini-3.1-pro-preview: not run, not run in this column
- cline x gemini-3.5-flash: not run, not run in this column
- cline x gemini-3.5-flash-lite: not run, not run in this column
- cline x gemini-3.6-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x gemini-3.7-flash: not run, not run in this column
- cline x gemini-3.8-flash: not run, not run in this column
- cline x glm-5.3: not run, not run in this column
- cline x glm-5.3-flash: not run, not run in this column
- cline x gpt-5.2: not run, not run in this column
- cline x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cline x gpt-5.4: not run, not run in this column
- cline x gpt-5.4-mini: not run, not run in this column
- cline x gpt-5.5: not run, not run in this column
- cline x gpt-5.6-luna: not run, not run in this column
- cline x gpt-5.6-sol: not run, not run in this column
- cline x gpt-5.6-terra: not run, not run in this column
- cline x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- cline x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x kimi-k2.7-code: not run, not run in this column
- cline x kimi-k3: not run, not run in this column
- cline x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x mistral-medium-3.5: not run, not run in this column
- cline x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- cline x qwen3.7-max: not run, not run in this column
- cline x qwen3.8-max: not run, not run in this column
- cline x step-3.7-flash: not run, not run in this column
- codex x claude-fable-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-fable-5-1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-haiku-4.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-haiku-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-4.7: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-4.8: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-opus-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-sonnet-4.6: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-sonnet-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x claude-sonnet-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x deepseek-v4-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x deepseek-v4-pro: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x deepseek-v4.1-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3-flash-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.1-flash-lite: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.1-pro-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.5-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.5-flash-lite: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.6-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gemini-3.8-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x glm-5.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x glm-5.3-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x gpt-5.2: not run, not run in this column
- codex x gpt-5.3-codex: not run, not run in this column
- codex x gpt-5.4: not run, not run in this column
- codex x gpt-5.4-mini: not run, not run in this column
- codex x gpt-5.5: not run, not run in this column
- codex x gpt-5.6-luna: not run, not run in this column
- codex x gpt-5.6-sol: not run, not run in this column
- codex x gpt-5.6-terra: not run, not run in this column
- codex x grok-4.20: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-4.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-4.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-4.6: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x grok-build-0.1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x hunyuan-4-preview: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x kimi-k2.7-code: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x kimi-k3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x mistral-medium-3.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x muse-glimmer-30b: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x muse-spark-1.1: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x muse-spark-1.2: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x muse-spark-1.3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x nemotron-3-super: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x nemotron-3.5-lightning: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.7-max: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.7-plus: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.8-27b: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.8-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x qwen3.8-max: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- codex x step-3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x claude-fable-5: not run, not run in this column
- dsh x claude-fable-5-1: not run, not run in this column
- dsh x claude-haiku-4.5: not run, not run in this column
- dsh x claude-opus-4.7: not run, not run in this column
- dsh x claude-opus-4.8: not run, not run in this column
- dsh x claude-opus-5: not run, not run in this column
- dsh x claude-opus-5.5: not run, not run in this column
- dsh x claude-sonnet-4.6: not run, not run in this column
- dsh x claude-sonnet-5: not run, not run in this column
- dsh x claude-sonnet-5.5: not run, not run in this column
- dsh x deepseek-v4-flash: not run, not run in this column
- dsh x deepseek-v4-pro: not run, not run in this column
- dsh x deepseek-v4.1-flash: not run, not run in this column
- dsh x gemini-3-flash-preview: not run, not run in this column
- dsh x gemini-3.1-flash-lite: not run, not run in this column
- dsh x gemini-3.1-pro-preview: not run, not run in this column
- dsh x gemini-3.5-flash: not run, not run in this column
- dsh x gemini-3.5-flash-lite: not run, not run in this column
- dsh x gemini-3.6-flash: not run, not run in this column
- dsh x gemini-3.7-flash: not run, not run in this column
- dsh x gemini-3.8-flash: not run, not run in this column
- dsh x glm-5.3: not run, not run in this column
- dsh x glm-5.3-flash: not run, not run in this column
- dsh x gpt-5.2: not run, not run in this column
- dsh x gpt-5.3-codex: not run, not run in this column
- dsh x gpt-5.4: not run, not run in this column
- dsh x gpt-5.4-mini: not run, not run in this column
- dsh x gpt-5.5: not run, not run in this column
- dsh x gpt-5.6-luna: not run, not run in this column
- dsh x gpt-5.6-sol: not run, not run in this column
- dsh x gpt-5.6-terra: not run, not run in this column
- dsh x grok-4.20: not run, not run in this column
- dsh x grok-4.3: not run, not run in this column
- dsh x grok-4.5: not run, not run in this column
- dsh x grok-4.6: not run, not run in this column
- dsh x grok-build-0.1: not run, not run in this column
- dsh x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x hunyuan-4-preview: not run, not run in this column
- dsh x kimi-k2.7-code: not run, not run in this column
- dsh x kimi-k3: not run, not run in this column
- dsh x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x mistral-medium-3.5: not run, not run in this column
- dsh x muse-glimmer-30b: not run, not run in this column
- dsh x muse-spark-1.1: not run, not run in this column
- dsh x muse-spark-1.2: not run, not run in this column
- dsh x muse-spark-1.3: not run, not run in this column
- dsh x nemotron-3-super: not run, not run in this column
- dsh x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x nemotron-3.5-lightning: not run, not run in this column
- dsh x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- dsh x qwen3.7-max: not run, not run in this column
- dsh x qwen3.7-plus: not run, not run in this column
- dsh x qwen3.8-27b: not run, not run in this column
- dsh x qwen3.8-flash: not run, not run in this column
- dsh x qwen3.8-max: not run, not run in this column
- dsh x step-3.7-flash: not run, not run in this column
- goose x claude-fable-5: not run, not run in this column
- goose x claude-fable-5-1: not run, not run in this column
- goose x claude-haiku-4.5: not run, not run in this column
- goose x claude-opus-4.7: not run, not run in this column
- goose x claude-opus-4.8: not run, not run in this column
- goose x claude-opus-5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x claude-opus-5.5: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- goose x claude-sonnet-4.6: not run, not run in this column
- goose x claude-sonnet-5: not run, not run in this column
- goose x claude-sonnet-5.5: not run, not run in this column
- goose x deepseek-v4-flash: not run, not run in this column
- goose x deepseek-v4-pro: not run, not run in this column
- goose x deepseek-v4.1-flash: not run, not run in this column
- goose x gemini-3-flash-preview: not run, not run in this column
- goose x gemini-3.1-flash-lite: not run, not run in this column
- goose x gemini-3.1-pro-preview: not run, not run in this column
- goose x gemini-3.5-flash: not run, not run in this column
- goose x gemini-3.5-flash-lite: not run, not run in this column
- goose x gemini-3.6-flash: not run, not run in this column
- goose x gemini-3.7-flash: not run, not run in this column
- goose x gemini-3.8-flash: not run, not run in this column
- goose x glm-5.3: not run, not run in this column
- goose x glm-5.3-flash: not run, not run in this column
- goose x gpt-5.2: not run, not run in this column
- goose x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-5.4: not run, not run in this column
- goose x gpt-5.4-mini: not run, not run in this column
- goose x gpt-5.5: not run, not run in this column
- goose x gpt-5.6-luna: not run, not run in this column
- goose x gpt-5.6-sol: not run, not run in this column
- goose x gpt-5.6-terra: not run, not run in this column
- goose x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- goose x gpt-6-luna: not run, not run in this column
- goose x gpt-6-sol: not run, not run in this column
- goose x grok-4.20: not run, not run in this column
- goose x grok-4.3: not run, not run in this column
- goose x grok-4.5: not run, not run in this column
- goose x grok-4.6: not run, not run in this column
- goose x grok-build-0.1: not run, not run in this column
- goose x hunyuan-3: not run, not run in this column
- goose x hunyuan-4-preview: not run, not run in this column
- goose x kimi-k2.7-code: not run, not run in this column
- goose x kimi-k3: not run, not run in this column
- goose x ling-3.0-flash: not run, not run in this column
- goose x minimax-m3: not run, not run in this column
- goose x mistral-medium-3.5: not run, not run in this column
- goose x muse-glimmer-30b: not run, not run in this column
- goose x muse-spark-1.1: not run, not run in this column
- goose x muse-spark-1.2: not run, not run in this column
- goose x muse-spark-1.3: not run, not run in this column
- goose x nemotron-3-super: not run, not run in this column
- goose x nemotron-3-ultra: not run, not run in this column
- goose x nemotron-3.5-lightning: not run, not run in this column
- goose x qwen3.7-flash: not run, not run in this column
- goose x qwen3.7-max: not run, not run in this column
- goose x qwen3.7-plus: not run, not run in this column
- goose x qwen3.8-27b: not run, not run in this column
- goose x qwen3.8-flash: not run, not run in this column
- goose x qwen3.8-max: not run, not run in this column
- goose x step-3.7-flash: not run, not run in this column
- grok x claude-fable-5: not run, not run in this column
- grok x claude-fable-5-1: not run, not run in this column
- grok x claude-haiku-4.5: not run, not run in this column
- grok x claude-opus-4.7: not run, not run in this column
- grok x claude-opus-4.8: not run, not run in this column
- grok x claude-opus-5: not run, not run in this column
- grok x claude-opus-5.5: not run, not run in this column
- grok x claude-sonnet-4.6: not run, not run in this column
- grok x claude-sonnet-5: not run, not run in this column
- grok x claude-sonnet-5.5: not run, not run in this column
- grok x deepseek-v4-flash: not run, not run in this column
- grok x deepseek-v4-pro: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- grok x deepseek-v4.1-flash: not run, not run in this column
- grok x gemini-3-flash-preview: not run, not run in this column
- grok x gemini-3.1-flash-lite: not run, not run in this column
- grok x gemini-3.1-pro-preview: not run, not run in this column
- grok x gemini-3.5-flash: not run, not run in this column
- grok x gemini-3.5-flash-lite: not run, not run in this column
- grok x gemini-3.6-flash: not run, not run in this column
- grok x gemini-3.7-flash: not run, not run in this column
- grok x gemini-3.8-flash: not run, not run in this column
- grok x glm-5.3: not run, not run in this column
- grok x glm-5.3-flash: not run, not run in this column
- grok x gpt-5.2: not run, not run in this column
- grok x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- grok x gpt-5.4: not run, not run in this column
- grok x gpt-5.4-mini: not run, not run in this column
- grok x gpt-5.5: not run, not run in this column
- grok x gpt-5.6-luna: not run, not run in this column
- grok x gpt-5.6-sol: not run, not run in this column
- grok x gpt-5.6-terra: not run, not run in this column
- grok x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- grok x gpt-6-luna: not run, not run in this column
- grok x gpt-6-sol: not run, not run in this column
- grok x gpt-6.1-sol: not run, not run in this column
- grok x grok-4.20: not run, not run in this column
- grok x grok-4.3: not run, not run in this column
- grok x grok-4.5: not run, not run in this column
- grok x grok-4.6: not run, not run in this column
- grok x grok-build-0.1: not run, not run in this column
- grok x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- grok x hunyuan-4-preview: not run, not run in this column
- grok x kimi-k2.7-code: not run, not run in this column
- grok x kimi-k3: not run, not run in this column
- grok x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- grok x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- grok x mistral-medium-3.5: not run, not run in this column
- grok x muse-glimmer-30b: not run, not run in this column
- grok x muse-spark-1.1: not run, not run in this column
- grok x muse-spark-1.2: not run, not run in this column
- grok x muse-spark-1.3: not run, not run in this column
- grok x nemotron-3-super: not run, not run in this column
- grok x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- grok x nemotron-3.5-lightning: not run, not run in this column
- grok x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- grok x qwen3.7-max: not run, not run in this column
- grok x qwen3.7-plus: not run, not run in this column
- grok x qwen3.8-27b: not run, not run in this column
- grok x qwen3.8-flash: not run, not run in this column
- grok x qwen3.8-max: not run, not run in this column
- grok x step-3.7-flash: not run, not run in this column
- hermes x claude-fable-5: not run, not run in this column
- hermes x claude-fable-5-1: not run, not run in this column
- hermes x claude-haiku-4.5: not run, not run in this column
- hermes x claude-opus-4.7: not run, not run in this column
- hermes x claude-opus-4.8: not run, not run in this column
- hermes x claude-opus-5: not run, not run in this column
- hermes x claude-opus-5.5: not run, not run in this column
- hermes x claude-sonnet-4.6: not run, not run in this column
- hermes x claude-sonnet-5: not run, not run in this column
- hermes x claude-sonnet-5.5: not run, not run in this column
- hermes x deepseek-v4-flash: not run, not run in this column
- hermes x deepseek-v4-pro: not run, not run in this column
- hermes x gemini-3-flash-preview: not run, not run in this column
- hermes x gemini-3.1-flash-lite: not run, not run in this column
- hermes x gemini-3.1-pro-preview: not run, not run in this column
- hermes x gemini-3.5-flash: not run, not run in this column
- hermes x gemini-3.5-flash-lite: not run, not run in this column
- hermes x gemini-3.6-flash: not run, not run in this column
- hermes x gemini-3.7-flash: not run, not run in this column
- hermes x gemini-3.8-flash: not run, not run in this column
- hermes x glm-5.3: not run, not run in this column
- hermes x glm-5.3-flash: not run, not run in this column
- hermes x gpt-5.2: not run, not run in this column
- hermes x gpt-5.3-codex: not run, not run in this column
- hermes x gpt-5.4: not run, not run in this column
- hermes x gpt-5.4-mini: not run, not run in this column
- hermes x gpt-5.5: not run, not run in this column
- hermes x gpt-5.6-luna: not run, not run in this column
- hermes x gpt-5.6-sol: not run, not run in this column
- hermes x gpt-5.6-terra: not run, not run in this column
- hermes x hunyuan-3: not run, not run in this column
- hermes x kimi-k3: not run, not run in this column
- hermes x minimax-m3: not run, not run in this column
- hermes x mistral-medium-3.5: not run, not run in this column
- hermes x nemotron-3-ultra: not run, not run in this column
- hermes x qwen3.7-flash: not run, not run in this column
- hermes x qwen3.7-max: not run, not run in this column
- hermes x qwen3.8-max: not run, not run in this column
- hermes x step-3.7-flash: not run, not run in this column
- kilo x claude-fable-5: not run, not run in this column
- kilo x claude-fable-5-1: not run, not run in this column
- kilo x claude-haiku-4.5: not run, not run in this column
- kilo x claude-opus-4.7: not run, not run in this column
- kilo x claude-opus-4.8: not run, not run in this column
- kilo x claude-opus-5: not run, not run in this column
- kilo x claude-opus-5.5: not run, not run in this column
- kilo x claude-sonnet-4.6: not run, not run in this column
- kilo x claude-sonnet-5: not run, not run in this column
- kilo x claude-sonnet-5.5: not run, not run in this column
- kilo x deepseek-v4-flash: not run, not run in this column
- kilo x deepseek-v4-pro: not run, not run in this column
- kilo x deepseek-v4.1-flash: not run, not run in this column
- kilo x gemini-3-flash-preview: not run, not run in this column
- kilo x gemini-3.1-flash-lite: not run, not run in this column
- kilo x gemini-3.1-pro-preview: not run, not run in this column
- kilo x gemini-3.5-flash: not run, not run in this column
- kilo x gemini-3.5-flash-lite: not run, not run in this column
- kilo x gemini-3.6-flash: not run, not run in this column
- kilo x gemini-3.7-flash: not run, not run in this column
- kilo x gemini-3.8-flash: not run, not run in this column
- kilo x glm-5.3: not run, not run in this column
- kilo x glm-5.3-flash: not run, not run in this column
- kilo x gpt-5.2: not run, not run in this column
- kilo x gpt-5.3-codex: not run, not run in this column
- kilo x gpt-5.4: not run, not run in this column
- kilo x gpt-5.4-mini: not run, not run in this column
- kilo x gpt-5.5: not run, not run in this column
- kilo x gpt-5.6-luna: not run, not run in this column
- kilo x gpt-5.6-sol: not run, not run in this column
- kilo x gpt-5.6-terra: not run, not run in this column
- kilo x gpt-6-astra: not run, not run in this column
- kilo x gpt-6-luna: not run, not run in this column
- kilo x gpt-6-sol: not run, not run in this column
- kilo x gpt-6.1-sol: not run, not run in this column
- kilo x grok-4.20: not run, not run in this column
- kilo x grok-4.3: not run, not run in this column
- kilo x grok-4.5: not run, not run in this column
- kilo x grok-4.6: not run, not run in this column
- kilo x grok-build-0.1: not run, not run in this column
- kilo x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kilo x hunyuan-4-preview: not run, not run in this column
- kilo x kimi-k2.7-code: not run, not run in this column
- kilo x kimi-k3: not run, not run in this column
- kilo x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kilo x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kilo x mistral-medium-3.5: not run, not run in this column
- kilo x muse-glimmer-30b: not run, not run in this column
- kilo x muse-spark-1.1: not run, not run in this column
- kilo x muse-spark-1.2: not run, not run in this column
- kilo x muse-spark-1.3: not run, not run in this column
- kilo x nemotron-3-super: not run, not run in this column
- kilo x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kilo x nemotron-3.5-lightning: not run, not run in this column
- kilo x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kilo x qwen3.7-max: not run, not run in this column
- kilo x qwen3.7-plus: not run, not run in this column
- kilo x qwen3.8-27b: not run, not run in this column
- kilo x qwen3.8-flash: not run, not run in this column
- kilo x qwen3.8-max: not run, not run in this column
- kilo x step-3.7-flash: not run, not run in this column
- kimi x claude-fable-5: not run, not run in this column
- kimi x claude-fable-5-1: not run, not run in this column
- kimi x claude-haiku-4.5: not run, not run in this column
- kimi x claude-opus-4.7: not run, not run in this column
- kimi x claude-opus-4.8: not run, not run in this column
- kimi x claude-opus-5: not run, not run in this column
- kimi x claude-opus-5.5: not run, not run in this column
- kimi x claude-sonnet-4.6: not run, not run in this column
- kimi x claude-sonnet-5: not run, not run in this column
- kimi x claude-sonnet-5.5: not run, not run in this column
- kimi x deepseek-v4-flash: not run, not run in this column
- kimi x deepseek-v4-pro: not run, not run in this column
- kimi x deepseek-v4.1-flash: not run, not run in this column
- kimi x gemini-3-flash-preview: not run, not run in this column
- kimi x gemini-3.1-flash-lite: not run, not run in this column
- kimi x gemini-3.1-pro-preview: not run, not run in this column
- kimi x gemini-3.5-flash: not run, not run in this column
- kimi x gemini-3.5-flash-lite: not run, not run in this column
- kimi x gemini-3.6-flash: not run, not run in this column
- kimi x gemini-3.7-flash: not run, not run in this column
- kimi x gemini-3.8-flash: not run, not run in this column
- kimi x glm-5.3: not run, not run in this column
- kimi x glm-5.3-flash: not run, not run in this column
- kimi x gpt-5.2: not run, not run in this column
- kimi x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- kimi x gpt-5.4: not run, not run in this column
- kimi x gpt-5.4-mini: not run, not run in this column
- kimi x gpt-5.5: not run, not run in this column
- kimi x gpt-5.6-luna: not run, not run in this column
- kimi x gpt-5.6-sol: not run, not run in this column
- kimi x gpt-5.6-terra: not run, not run in this column
- kimi x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- kimi x grok-4.20: not run, not run in this column
- kimi x grok-4.3: not run, not run in this column
- kimi x grok-4.5: not run, not run in this column
- kimi x grok-4.6: not run, not run in this column
- kimi x grok-build-0.1: not run, not run in this column
- kimi x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kimi x hunyuan-4-preview: not run, not run in this column
- kimi x kimi-k2.7-code: not run, not run in this column
- kimi x kimi-k3: not run, not run in this column
- kimi x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kimi x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kimi x mistral-medium-3.5: not run, not run in this column
- kimi x muse-glimmer-30b: not run, not run in this column
- kimi x muse-spark-1.1: not run, not run in this column
- kimi x muse-spark-1.2: not run, not run in this column
- kimi x muse-spark-1.3: not run, not run in this column
- kimi x nemotron-3-super: not run, not run in this column
- kimi x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kimi x nemotron-3.5-lightning: not run, not run in this column
- kimi x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- kimi x qwen3.7-max: not run, not run in this column
- kimi x qwen3.7-plus: not run, not run in this column
- kimi x qwen3.8-27b: not run, not run in this column
- kimi x qwen3.8-flash: not run, not run in this column
- kimi x qwen3.8-max: not run, not run in this column
- kimi x step-3.7-flash: not run, not run in this column
- minimax x claude-fable-5: not run, not run in this column
- minimax x claude-fable-5-1: not run, not run in this column
- minimax x claude-haiku-4.5: not run, not run in this column
- minimax x claude-opus-4.7: not run, not run in this column
- minimax x claude-opus-4.8: not run, not run in this column
- minimax x claude-opus-5: not run, not run in this column
- minimax x claude-opus-5.5: not run, not run in this column
- minimax x claude-sonnet-4.6: not run, not run in this column
- minimax x claude-sonnet-5: not run, not run in this column
- minimax x claude-sonnet-5.5: not run, not run in this column
- minimax x deepseek-v4-flash: not run, not run in this column
- minimax x deepseek-v4-pro: not run, not run in this column
- minimax x deepseek-v4.1-flash: not run, not run in this column
- minimax x gemini-3-flash-preview: not run, not run in this column
- minimax x gemini-3.1-flash-lite: not run, not run in this column
- minimax x gemini-3.1-pro-preview: not run, not run in this column
- minimax x gemini-3.5-flash: not run, not run in this column
- minimax x gemini-3.5-flash-lite: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- minimax x gemini-3.6-flash: not run, not run in this column
- minimax x gemini-3.7-flash: not run, not run in this column
- minimax x gemini-3.8-flash: not run, not run in this column
- minimax x glm-5.3: not run, not run in this column
- minimax x glm-5.3-flash: not run, not run in this column
- minimax x gpt-5.2: not run, not run in this column
- minimax x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- minimax x gpt-5.4: not run, not run in this column
- minimax x gpt-5.4-mini: not run, not run in this column
- minimax x gpt-5.5: not run, not run in this column
- minimax x gpt-5.6-luna: not run, not run in this column
- minimax x gpt-5.6-sol: not run, not run in this column
- minimax x gpt-5.6-terra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- minimax x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- minimax x gpt-6-luna: not run, not run in this column
- minimax x gpt-6-sol: not run, not run in this column
- minimax x gpt-6.1-sol: not run, not run in this column
- minimax x grok-4.20: not run, not run in this column
- minimax x grok-4.3: not run, not run in this column
- minimax x grok-4.5: not run, not run in this column
- minimax x grok-4.6: not run, not run in this column
- minimax x grok-build-0.1: not run, not run in this column
- minimax x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- minimax x hunyuan-4-preview: not run, not run in this column
- minimax x kimi-k2.7-code: not run, not run in this column
- minimax x kimi-k3: not run, not run in this column
- minimax x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- minimax x minimax-m3: not run, not run in this column
- minimax x mistral-medium-3.5: not run, not run in this column
- minimax x muse-glimmer-30b: not run, not run in this column
- minimax x muse-spark-1.1: not run, not run in this column
- minimax x muse-spark-1.2: not run, not run in this column
- minimax x muse-spark-1.3: not run, not run in this column
- minimax x nemotron-3-super: not run, not run in this column
- minimax x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- minimax x nemotron-3.5-lightning: not run, not run in this column
- minimax x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- minimax x qwen3.7-max: not run, not run in this column
- minimax x qwen3.7-plus: not run, not run in this column
- minimax x qwen3.8-27b: not run, not run in this column
- minimax x qwen3.8-flash: not run, not run in this column
- minimax x qwen3.8-max: not run, not run in this column
- minimax x step-3.7-flash: not run, not run in this column
- omp x claude-fable-5: not run, not run in this column
- omp x claude-fable-5-1: not run, not run in this column
- omp x claude-haiku-4.5: not run, not run in this column
- omp x claude-opus-4.7: not run, not run in this column
- omp x claude-opus-4.8: not run, not run in this column
- omp x claude-opus-5: not run, not run in this column
- omp x claude-opus-5.5: not run, not run in this column
- omp x claude-sonnet-4.6: not run, not run in this column
- omp x claude-sonnet-5: not run, not run in this column
- omp x claude-sonnet-5.5: not run, not run in this column
- omp x deepseek-v4-flash: not run, not run in this column
- omp x deepseek-v4-pro: not run, not run in this column
- omp x deepseek-v4.1-flash: not run, not run in this column
- omp x gemini-3-flash-preview: not run, not run in this column
- omp x gemini-3.1-flash-lite: not run, not run in this column
- omp x gemini-3.1-pro-preview: not run, not run in this column
- omp x gemini-3.5-flash: not run, not run in this column
- omp x gemini-3.5-flash-lite: not run, not run in this column
- omp x gemini-3.6-flash: not run, not run in this column
- omp x gemini-3.7-flash: not run, not run in this column
- omp x gemini-3.8-flash: not run, not run in this column
- omp x glm-5.3: not run, not run in this column
- omp x glm-5.3-flash: not run, not run in this column
- omp x gpt-5.2: not run, not run in this column
- omp x gpt-5.3-codex: not run, not run in this column
- omp x gpt-5.4: not run, not run in this column
- omp x gpt-5.4-mini: not run, not run in this column
- omp x gpt-5.5: not run, not run in this column
- omp x gpt-5.6-luna: not run, not run in this column
- omp x gpt-5.6-sol: not run, not run in this column
- omp x gpt-5.6-terra: not run, not run in this column
- omp x grok-4.20: not run, not run in this column
- omp x grok-4.3: not run, not run in this column
- omp x grok-4.5: not run, not run in this column
- omp x grok-4.6: not run, not run in this column
- omp x grok-build-0.1: not run, not run in this column
- omp x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x hunyuan-4-preview: not run, not run in this column
- omp x kimi-k2.7-code: not run, not run in this column
- omp x kimi-k3: not run, not run in this column
- omp x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x mistral-medium-3.5: not run, not run in this column
- omp x muse-glimmer-30b: not run, not run in this column
- omp x muse-spark-1.1: not run, not run in this column
- omp x muse-spark-1.2: not run, not run in this column
- omp x muse-spark-1.3: not run, not run in this column
- omp x nemotron-3-super: not run, not run in this column
- omp x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x nemotron-3.5-lightning: not run, not run in this column
- omp x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- omp x qwen3.7-max: not run, not run in this column
- omp x qwen3.7-plus: not run, not run in this column
- omp x qwen3.8-27b: not run, not run in this column
- omp x qwen3.8-flash: not run, not run in this column
- omp x qwen3.8-max: not run, not run in this column
- omp x step-3.7-flash: not run, not run in this column
- opencode x claude-fable-5: not run, not run in this column
- opencode x claude-fable-5-1: not run, not run in this column
- opencode x claude-haiku-4.5: not run, not run in this column
- opencode x claude-opus-4.7: not run, not run in this column
- opencode x claude-opus-4.8: not run, not run in this column
- opencode x claude-opus-5: not run, not run in this column
- opencode x claude-opus-5.5: not run, not run in this column
- opencode x claude-sonnet-4.6: not run, not run in this column
- opencode x claude-sonnet-5: not run, not run in this column
- opencode x claude-sonnet-5.5: not run, not run in this column
- opencode x deepseek-v4-flash: not run, not run in this column
- opencode x deepseek-v4-pro: not run, not run in this column
- opencode x gemini-3-flash-preview: not run, not run in this column
- opencode x gemini-3.1-flash-lite: not run, not run in this column
- opencode x gemini-3.1-pro-preview: not run, not run in this column
- opencode x gemini-3.5-flash: not run, not run in this column
- opencode x gemini-3.5-flash-lite: not run, not run in this column
- opencode x gemini-3.6-flash: not run, not run in this column
- opencode x gemini-3.7-flash: not run, not run in this column
- opencode x gemini-3.8-flash: not run, not run in this column
- opencode x glm-5.3: not run, not run in this column
- opencode x glm-5.3-flash: not run, not run in this column
- opencode x gpt-5.2: not run, not run in this column
- opencode x gpt-5.3-codex: not run, not run in this column
- opencode x gpt-5.4: not run, not run in this column
- opencode x gpt-5.4-mini: not run, not run in this column
- opencode x gpt-5.5: not run, not run in this column
- opencode x gpt-5.6-luna: not run, not run in this column
- opencode x gpt-5.6-sol: not run, not run in this column
- opencode x gpt-5.6-terra: not run, not run in this column
- opencode x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x kimi-k2.7-code: not run, not run in this column
- opencode x kimi-k3: not run, not run in this column
- opencode x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x mistral-medium-3.5: not run, not run in this column
- opencode x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- opencode x qwen3.7-max: not run, not run in this column
- opencode x qwen3.8-max: not run, not run in this column
- opencode x step-3.7-flash: not run, not run in this column
- openhands x claude-fable-5: not run, not run in this column
- openhands x claude-fable-5-1: not run, not run in this column
- openhands x claude-haiku-4.5: not run, not run in this column
- openhands x claude-opus-4.7: not run, not run in this column
- openhands x claude-opus-4.8: not run, not run in this column
- openhands x claude-opus-5: not run, not run in this column
- openhands x claude-opus-5.5: not run, not run in this column
- openhands x claude-sonnet-4.6: not run, not run in this column
- openhands x claude-sonnet-5: not run, not run in this column
- openhands x claude-sonnet-5.5: not run, not run in this column
- openhands x deepseek-v4-flash: not run, not run in this column
- openhands x deepseek-v4-pro: not run, not run in this column
- openhands x deepseek-v4.1-flash: not run, not run in this column
- openhands x gemini-3-flash-preview: not run, not run in this column
- openhands x gemini-3.1-flash-lite: not run, not run in this column
- openhands x gemini-3.1-pro-preview: not run, not run in this column
- openhands x gemini-3.5-flash: not run, not run in this column
- openhands x gemini-3.5-flash-lite: not run, not run in this column
- openhands x gemini-3.6-flash: not run, not run in this column
- openhands x gemini-3.7-flash: not run, not run in this column
- openhands x gemini-3.8-flash: not run, not run in this column
- openhands x glm-5.3: not run, not run in this column
- openhands x glm-5.3-flash: not run, not run in this column
- openhands x gpt-5.2: not run, not run in this column
- openhands x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- openhands x gpt-5.4: not run, not run in this column
- openhands x gpt-5.4-mini: not run, not run in this column
- openhands x gpt-5.5: not run, not run in this column
- openhands x gpt-5.6-luna: not run, not run in this column
- openhands x gpt-5.6-sol: not run, not run in this column
- openhands x gpt-5.6-terra: not run, not run in this column
- openhands x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- openhands x grok-4.20: not run, not run in this column
- openhands x grok-4.3: not run, not run in this column
- openhands x grok-4.5: not run, not run in this column
- openhands x grok-4.6: not run, not run in this column
- openhands x grok-build-0.1: not run, not run in this column
- openhands x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- openhands x hunyuan-4-preview: not run, not run in this column
- openhands x kimi-k2.7-code: not run, not run in this column
- openhands x kimi-k3: not run, not run in this column
- openhands x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- openhands x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- openhands x mistral-medium-3.5: not run, not run in this column
- openhands x muse-glimmer-30b: not run, not run in this column
- openhands x muse-spark-1.1: not run, not run in this column
- openhands x muse-spark-1.2: not run, not run in this column
- openhands x muse-spark-1.3: not run, not run in this column
- openhands x nemotron-3-super: not run, not run in this column
- openhands x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- openhands x nemotron-3.5-lightning: not run, not run in this column
- openhands x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- openhands x qwen3.7-max: not run, not run in this column
- openhands x qwen3.7-plus: not run, not run in this column
- openhands x qwen3.8-27b: not run, not run in this column
- openhands x qwen3.8-flash: not run, not run in this column
- openhands x qwen3.8-max: not run, not run in this column
- openhands x step-3.7-flash: not run, not run in this column
- pi x claude-fable-5: not run, not run in this column
- pi x claude-fable-5-1: not run, not run in this column
- pi x claude-haiku-4.5: not run, not run in this column
- pi x claude-opus-4.7: not run, not run in this column
- pi x claude-opus-4.8: not run, not run in this column
- pi x claude-opus-5: not run, not run in this column
- pi x claude-opus-5.5: not run, not run in this column
- pi x claude-sonnet-4.6: not run, not run in this column
- pi x claude-sonnet-5: not run, not run in this column
- pi x claude-sonnet-5.5: not run, not run in this column
- pi x deepseek-v4-flash: not run, not run in this column
- pi x deepseek-v4-pro: not run, not run in this column
- pi x gemini-3-flash-preview: not run, not run in this column
- pi x gemini-3.1-flash-lite: not run, not run in this column
- pi x gemini-3.1-pro-preview: not run, not run in this column
- pi x gemini-3.5-flash: not run, not run in this column
- pi x gemini-3.5-flash-lite: not run, not run in this column
- pi x gemini-3.6-flash: not run, not run in this column
- pi x gemini-3.7-flash: not run, not run in this column
- pi x gemini-3.8-flash: not run, not run in this column
- pi x glm-5.3: not run, not run in this column
- pi x glm-5.3-flash: not run, not run in this column
- pi x gpt-5.2: not run, not run in this column
- pi x gpt-5.3-codex: not run, not run in this column
- pi x gpt-5.4: not run, not run in this column
- pi x gpt-5.4-mini: not run, not run in this column
- pi x gpt-5.5: not run, not run in this column
- pi x gpt-5.6-luna: not run, not run in this column
- pi x gpt-5.6-sol: not run, not run in this column
- pi x gpt-5.6-terra: not run, not run in this column
- pi x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x kimi-k2.7-code: not run, not run in this column
- pi x kimi-k3: not run, not run in this column
- pi x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x mistral-medium-3.5: not run, not run in this column
- pi x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- pi x qwen3.7-max: not run, not run in this column
- pi x qwen3.8-max: not run, not run in this column
- pi x step-3.7-flash: not run, not run in this column
- qwen x claude-fable-5: not run, not run in this column
- qwen x claude-fable-5-1: not run, not run in this column
- qwen x claude-haiku-4.5: not run, not run in this column
- qwen x claude-opus-4.7: not run, not run in this column
- qwen x claude-opus-4.8: not run, not run in this column
- qwen x claude-opus-5: not run, not run in this column
- qwen x claude-opus-5.5: not run, not run in this column
- qwen x claude-sonnet-4.6: not run, not run in this column
- qwen x claude-sonnet-5: not run, not run in this column
- qwen x claude-sonnet-5.5: not run, not run in this column
- qwen x deepseek-v4-flash: not run, not run in this column
- qwen x deepseek-v4-pro: not run, not run in this column
- qwen x gemini-3-flash-preview: not run, not run in this column
- qwen x gemini-3.1-flash-lite: not run, not run in this column
- qwen x gemini-3.1-pro-preview: not run, not run in this column
- qwen x gemini-3.5-flash: not run, not run in this column
- qwen x gemini-3.5-flash-lite: not run, not run in this column
- qwen x gemini-3.6-flash: not run, not run in this column
- qwen x gemini-3.7-flash: not run, not run in this column
- qwen x gemini-3.8-flash: not run, not run in this column
- qwen x glm-5.3: not run, not run in this column
- qwen x glm-5.3-flash: not run, not run in this column
- qwen x gpt-5.2: not run, not run in this column
- qwen x gpt-5.3-codex: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- qwen x gpt-5.4: not run, not run in this column
- qwen x gpt-5.4-mini: not run, not run in this column
- qwen x gpt-5.5: not run, not run in this column
- qwen x gpt-5.6-luna: not run, not run in this column
- qwen x gpt-5.6-sol: not run, not run in this column
- qwen x gpt-5.6-terra: not run, not run in this column
- qwen x gpt-6-astra: not run, the model answers on the Responses API only and this harness speaks chat/completions only
- qwen x hunyuan-3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x kimi-k2.7-code: not run, not run in this column
- qwen x kimi-k3: not run, not run in this column
- qwen x ling-3.0-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x minimax-m3: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x mistral-medium-3.5: not run, not run in this column
- qwen x nemotron-3-ultra: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x qwen3.7-flash: not run, not in this harness's catalog (unmeasured or excluded, see the catalog's note)
- qwen x qwen3.7-max: not run, not run in this column
- qwen x qwen3.8-max: not run, not run in this column
- qwen x step-3.7-flash: not run, not run in this column

## Browser plugin, every base

Measured 2026-09-27 on hr-test (self-hosted, 0.25.7-rc.17). One task in plain words, "Open https://example.com/ in the browser, click the only link on that page, and reply with the URL and the title of the page you land on." A base passes when the task completed, the trace shows the browser navigating and clicking, the answer names the page the link leads to, and the browser session was stopped and billed; a failure is retested once. System One is not in the column: its models choose among offered actions and call no tools. The run's findings are in [support-matrix-notes.md](support-matrix-notes.md).

| base | model | browser | tools seen | seconds | notes |
|---|---|---|---|---:|---|
| codex | gpt-5.4 | pass | click, navigate, open | 33 |  |
| claude-code | claude-sonnet-4.6 | pass | click, navigate, open | 46 |  |
| hermes | gpt-5.4 | pass | click, get_url, navigate, open | 52 |  |
| pi | gpt-5.4 | pass | click, get_url, navigate, open | 34 |  |
| omp | gpt-5.4 | pass | click, navigate, open | 40 |  |
| dsh | deepseek-v4-pro | pass | click, navigate, open | 27 |  |
| goose | gpt-5.4 | pass | click, get_url, navigate, open | 33 |  |
| opencode | gpt-5.4 | pass | click, get_url, navigate, open | 27 |  |
| aider | gpt-5.4 | pass | click, get_url, navigate, open, snapshot | 33 |  |
| kimi | kimi-k3 | pass | click, navigate, open | 40 |  |
| openhands | gpt-5.4 | pass | click, get_url, navigate, open, snapshot | 46 |  |
| cheetahclaws | gpt-5.4 | pass | click, navigate, open | 27 |  |
| qwen | qwen3.7-max | pass | click, get_url, navigate, open | 40 |  |
| gemini | gemini-3.8-flash | pass | click, get_url, navigate, open | 33 |  |
| cline | gpt-5.4 | pass | click, get_url, navigate, open, snapshot, wait_for | 33 |  |

15 of 15 bases drive the browser.

