from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        env_prefix='NUTMEG_',
        extra='ignore',
    )

    app_name: str = 'nutmeg'
    app_env: str = 'dev'
    default_user_id: str = 'owner'
    data_dir: Path = Path('.nutmeg-data')
    default_sync_days: int = 30
    sync_timezone: str = 'UTC'
    langsmith_enabled: bool = False
    langsmith_project: str = 'nutmeg-local'
    langsmith_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            'LANGSMITH_API_KEY',
            'NUTMEG_LANGSMITH_API_KEY',
        ),
    )
    portkey_base_url: str = 'https://api.portkey.ai/v1'
    portkey_api_key: str | None = None
    anthropic_model: str = 'claude-sonnet-4-5'
    agent_synthesis_enabled: bool = False
    openai_base_url: str = 'https://api.openai.com/v1'
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            'OPENAI_API_KEY',
            'NUTMEG_OPENAI_API_KEY',
        ),
    )
    bot_llm_fallback_enabled: bool = False
    bot_llm_fallback_model: str = 'gpt-5.5'
    api_football_base_url: str = 'https://v3.football.api-sports.io/'
    api_football_key: str | None = None
    odds_provider: str = 'api-football'
    the_odds_api_base_url: str = 'https://api.the-odds-api.com/v4/'
    the_odds_api_key: str | None = None
    open_meteo_geocoding_base_url: str = 'https://geocoding-api.open-meteo.com/v1/'
    open_meteo_weather_base_url: str = 'https://api.open-meteo.com/v1/'
    telegram_api_base_url: str = 'https://api.telegram.org'
    telegram_bot_token: str | None = None
    telegram_allowed_chat_ids: str | None = None

    @property
    def project_root(self) -> Path:
        return Path.cwd()

    @property
    def state_dir(self) -> Path:
        return self.data_dir / 'state'

    @property
    def analytics_dir(self) -> Path:
        return self.data_dir / 'analytics'

    @property
    def state_db_path(self) -> Path:
        return self.state_dir / 'state.db'

    @property
    def state_db_url(self) -> str:
        return f'sqlite:///{self.state_db_path.resolve()}'

    @property
    def analytics_db_path(self) -> Path:
        return self.analytics_dir / 'analytics.duckdb'

    @property
    def analytics_db_url(self) -> str:
        return f'duckdb:///{self.analytics_db_path.resolve()}'


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
