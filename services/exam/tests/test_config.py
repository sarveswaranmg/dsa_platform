import pytest

from app.core.config import Settings, validate_production_config


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "rs256_private_key": "dummy",
        "env": "production",
        "google_client_id": "id",
        "google_client_secret": "secret",
        "google_redirect_uri": "https://example.com/candidate/auth/invite",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_production_passes_when_all_three_are_set() -> None:
    validate_production_config(_settings())  # must not raise


@pytest.mark.parametrize(
    "missing_field",
    ["google_client_id", "google_client_secret", "google_redirect_uri"],
)
def test_production_fails_fast_when_a_var_is_missing(missing_field: str) -> None:
    settings = _settings(**{missing_field: ""})
    with pytest.raises(RuntimeError, match=missing_field.upper()):
        validate_production_config(settings)


def test_production_fails_fast_lists_every_missing_var() -> None:
    settings = _settings(
        google_client_id="", google_client_secret="", google_redirect_uri=""
    )
    with pytest.raises(RuntimeError) as exc_info:
        validate_production_config(settings)
    message = str(exc_info.value)
    assert "GOOGLE_CLIENT_ID" in message
    assert "GOOGLE_CLIENT_SECRET" in message
    assert "GOOGLE_REDIRECT_URI" in message


def test_non_production_env_skips_validation() -> None:
    settings = _settings(
        env="dev", google_client_id="", google_client_secret="", google_redirect_uri=""
    )
    validate_production_config(settings)  # must not raise
