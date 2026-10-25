"""A provider refusing a replayed history is said in a sentence, never in the provider's JSON."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

REC = {"model_req": "grok-4.5", "models_before": ["gpt-5.4", "gemini-3.5-flash"]}


def test_openai_s_and_xai_s_wording_both_read_as_a_history_refusal():
    openai = ("Error code: 400 - The encrypted content for item rs_tmp_1 could not be verified. "
              "Reason: Encrypted content could not be decrypted or parsed.")
    xai = ("Error code: 400 - {'error': {'message': 'Provider returned error', 'metadata': {'raw': "
           "'{\"code\":\"invalid-argument\",\"error\":\"Could not decrypt the provided encrypted_content. "
           "Ensure the value is the unmodified encrypted_content from a previous response.\"}'}}}")
    for reason in (openai, xai):
        said = gw._history_refusal(REC, reason)
        assert said.startswith("grok-4.5 cannot continue this task's earlier reasoning"), reason
        assert "keep this task on gemini-3.5-flash" in said and "{" not in said


def test_any_other_refusal_is_not_one():
    assert gw._history_refusal(REC, "Error code: 400 - invalid tool schema") == ""
