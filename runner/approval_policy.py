"""Fail-closed boundary for approval policy fields entering the Runner."""


def approval_policy_error(policy, *, field_present: bool = False) -> str | None:
    """Return the stable refusal reason for an unsupported durable approval policy.

    ``None`` is a valid explicit value in the Gateway request model, so callers must pass
    ``field_present`` separately.  The Runner has no native checkpoint and exact continuation
    implementation yet; every explicit policy is therefore refused before backend selection.
    """
    if field_present:
        return "hexa_approval_unavailable"
    return None
