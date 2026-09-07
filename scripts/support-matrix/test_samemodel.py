from samemodel import alias_of, same_model


def test_the_providers_alias_of_the_same_model_is_the_same_model():
    for asked, served in [("claude-fable-5", "anthropic/claude-fable-5"), ("gpt-5.6-sol", "openai/gpt-5.6-sol"),
                          ("mistral-medium-3.5", "mistralai/mistral-medium-3-5"), ("qwen3.8-max", "qwen/qwen3.8-max-0902"),
                          ("claude-haiku-4-5", "claude-haiku-4-5-20251001"), ("gemini-2.5-flash", "gemini-2.5-flash-001")]:
        assert same_model(asked, served), (asked, served)


def test_another_family_number_or_tier_is_a_finding():
    for asked, served in [("gemini-3.8-flash", "google/gemini-3-flash-preview"), ("gemini-2.5-flash", "gemini-2.5-flash-lite"),
                          ("claude-sonnet-5", "claude-opus-5"), ("gemini-3.8-flash", "")]:
        assert not same_model(asked, served), (asked, served)


def test_a_turn_on_several_models_is_an_alias_only_when_all_are_the_same_model():
    assert alias_of("gemini-3.8-flash", "google/gemini-3.8-flash, gemini-3.8-flash-001")
    assert not alias_of("gemini-3.8-flash", "gemini-3.8-flash, gemini-3-flash-preview")
    assert not alias_of("gemini-3.8-flash", "")
