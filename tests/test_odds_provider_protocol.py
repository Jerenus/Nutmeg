from __future__ import annotations

import pytest

from nutmeg.config.settings import AppSettings
from nutmeg.domain.odds import OddsProvider


def test_odds_provider_is_runtime_checkable() -> None:
    """The unified OddsProvider protocol is runtime-checkable for selection sites."""

    class _Conforming:
        def fetch_fixture_odds(self, fixture_id: str):  # noqa: ANN001, ANN202
            return None

    class _NonConforming:
        pass

    assert isinstance(_Conforming(), OddsProvider)
    assert not isinstance(_NonConforming(), OddsProvider)


def test_api_football_client_satisfies_odds_provider() -> None:
    """ApiFootballClient is a structural OddsProvider."""
    from nutmeg.data.api_football import ApiFootballClient

    client = ApiFootballClient(
        base_url='https://example.test/',
        api_key=None,
    )
    try:
        assert isinstance(client, OddsProvider)
    finally:
        client.close()


def test_the_odds_api_client_satisfies_odds_provider() -> None:
    """TheOddsApiClient is a structural OddsProvider."""
    from nutmeg.data.the_odds_api import TheOddsApiClient

    class _NullFixtureRepository:
        def get_fixture(self, fixture_id: str):  # noqa: ANN001, ANN202
            return None

    class _NullEventRepository:
        def get_event(self, fixture_id: str, *, provider: str):  # noqa: ANN001, ANN202
            return None

        def upsert_event(self, event) -> None:  # noqa: ANN001
            return None

        def delete_event(self, fixture_id: str, *, provider: str) -> None:  # noqa: ANN001
            return None

    client = TheOddsApiClient(
        base_url='https://example.test/',
        api_key=None,
        fixture_repository=_NullFixtureRepository(),
        event_repository=_NullEventRepository(),
    )
    try:
        assert isinstance(client, OddsProvider)
    finally:
        client.close()


@pytest.mark.parametrize(
    ('settings', 'expected_class'),
    [
        (AppSettings(), 'ApiFootballClient'),
        (
            AppSettings(odds_provider='the-odds-api', the_odds_api_key='demo-key'),
            'TheOddsApiClient',
        ),
    ],
)
def test_build_odds_provider_client_returns_odds_provider(
    settings: AppSettings,
    expected_class: str,
) -> None:
    """build_odds_provider_client yields an OddsProvider regardless of selection."""
    from nutmeg.interfaces.cli import build_odds_provider_client

    client = build_odds_provider_client(settings)

    assert client.__class__.__name__ == expected_class
    assert isinstance(client, OddsProvider)
