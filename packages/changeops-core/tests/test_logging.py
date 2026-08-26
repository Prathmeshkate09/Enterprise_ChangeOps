from changeops_core.logging import redact_sensitive_data


def test_redaction_covers_nested_secrets_and_personal_data() -> None:
    event = {
        "authorization": "Bearer sensitive-token",
        "actor": {
            "email": "person@example.com",
            "metadata": ["contact person@example.com", {"api-key": "abc123"}],
        },
    }

    redacted = redact_sensitive_data(event)

    assert redacted == {
        "authorization": "[REDACTED]",
        "actor": {
            "email": "[REDACTED_EMAIL]",
            "metadata": ["contact [REDACTED_EMAIL]", {"api-key": "[REDACTED]"}],
        },
    }
