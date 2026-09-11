import pytest

from webhookrelay_hermes.config import Settings


def test_secure_route_requires_secret_environment(monkeypatch):
    settings = Settings.from_extra(
        {"routes": {"github": {"provider": "github", "secret_env": "TEST_GH_SECRET"}}}
    )
    monkeypatch.delenv("TEST_GH_SECRET", raising=False)
    with pytest.raises(ValueError, match="TEST_GH_SECRET"):
        settings.validate()
    monkeypatch.setenv("TEST_GH_SECRET", "secret")
    settings.validate()


def test_insecure_route_must_be_explicit():
    settings = Settings.from_extra({"routes": {"dev": {"insecure_no_auth": True}}})
    settings.validate()
    assert settings.routes["dev"].bucket == "hermes-dev"


def test_invalid_concurrency_is_rejected():
    settings = Settings.from_extra(
        {"max_concurrent": -1, "routes": {"dev": {"insecure_no_auth": True}}}
    )
    with pytest.raises(ValueError, match="max_concurrent"):
        settings.validate()


def test_routes_cannot_share_a_bucket():
    settings = Settings.from_extra(
        {
            "routes": {
                "one": {"bucket": "shared", "insecure_no_auth": True},
                "two": {"bucket": "shared", "insecure_no_auth": True},
            }
        }
    )
    with pytest.raises(ValueError, match="more than one route"):
        settings.validate()
