from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_SOURCE_ROOT = Path(__file__).resolve().parents[2]


class AppSettings(BaseSettings):
    # extra='ignore'：.env 里已退役的键（operator_* / langsmith / openai / psychology_* …，
    # 2026-10-08 删除）照旧无害。
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        env_prefix='NUTMEG_',
        extra='ignore',
    )

    data_dir: Path = Path('.nutmeg-data')
    production_data_dir: Path = Field(
        default_factory=lambda: (_SOURCE_ROOT / '.nutmeg-data').resolve()
    )
    release_version: str = 'unreleased'
    # 定时 claude -p 的模型分档（2026-09-23 Jun 裁定）：
    #   逻辑层只把卡片字段说成人话、cites 逐条校验兜底 → 便宜模型；
    #   深研产出 stance/tilt/falsifier，是判断层 → 空串＝不传 --model，
    #   继承 Claude Code 默认（opus）。
    # 实际用的模型名会写进 brief 卡片 logic.model 与 research-*.json 的 model，供记分牌按模型分层。
    #   实测 2026-09-23：haiku 64–70s/场且往正文里漏字段名，sonnet 31s/场、说人话 → 默认 sonnet。
    model_logic: str = 'sonnet'
    model_research: str = ''
    # 系统一读者（2026-10-02 判断 rubric）：只读研究文本、只回类型化问题的概率、不解释——
    # Jev 形状的任务，便宜模型即可；两读 kappa 与历史重打分都走它。
    model_reader: str = 'haiku'
    api_football_base_url: str = 'https://v3.football.api-sports.io/'
    api_football_key: str | None = Field(default=None, repr=False)
    telegram_api_base_url: str = 'https://api.telegram.org'
    telegram_bot_token: str | None = Field(default=None, repr=False)
    telegram_allowed_chat_ids: str | None = None

    @field_validator('production_data_dir')
    @classmethod
    def _production_data_dir_is_absolute(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError('production_data_dir must be absolute')
        return value

    @property
    def ontology_dir(self) -> Path:
        return self.data_dir / 'ontology'

    @property
    def ontology_db_path(self) -> Path:
        return self.ontology_dir / 'ontology.db'

    @property
    def ontology_artifact_dir(self) -> Path:
        return self.ontology_dir / 'artifacts'


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings()


