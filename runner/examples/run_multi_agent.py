"""Run the real multi-agent broadcast flow against HarnessRouter.

PowerShell example::

    $env:HR_API_KEY = 'your-test-key'
    $env:HR_HARNESS_IDS = 'worker-harness-id-1,worker-harness-id-2'
    $env:HR_SYNTHESIZER_ID = 'final-harness-id'
    python runner/examples/run_multi_agent.py "比较两个方案并给出建议"
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from runner.multi_agent_client import Agent, MultiAgentClient


def main() -> int:
    api_key = os.environ.get("HR_API_KEY", "").strip()
    worker_ids = [x.strip() for x in os.environ.get("HR_HARNESS_IDS", "").split(",") if x.strip()]
    synthesizer_id = os.environ.get("HR_SYNTHESIZER_ID", "").strip()
    base_url = os.environ.get("HR_API_BASE", "http://localhost:3000/api/harness").rstrip("/")
    task = " ".join(sys.argv[1:]).strip()

    missing = [
        name for name, value in (
            ("HR_API_KEY", api_key),
            ("HR_HARNESS_IDS", worker_ids),
            ("HR_SYNTHESIZER_ID", synthesizer_id),
            ("task argument", task),
        ) if not value
    ]
    if missing:
        print("Missing: " + ", ".join(missing), file=sys.stderr)
        return 2

    workers = [
        Agent(name=f"worker-{index}", base_url=base_url, api_key=api_key,
              metadata={"harness_id": harness_id})
        for index, harness_id in enumerate(worker_ids, 1)
    ]
    synthesizer = Agent(
        name="final-synthesizer",
        base_url=base_url,
        api_key=api_key,
        metadata={"harness_id": synthesizer_id},
    )

    result = MultiAgentClient(workers, synthesizer).run(task)
    for reply in result.replies:
        print(f"[{reply.agent}] {reply.text if reply.ok else reply.error}")
    print("\n[final-synthesizer]")
    print(result.conclusion if result.synthesis.ok else result.synthesis.error)
    return 0 if result.synthesis.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
