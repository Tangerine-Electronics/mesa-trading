"""Esquema estricto de la mesa. Cualquier modo fuera de sombra/simulado aborta el arranque."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mesa_trading.constants import ALLOWED_MODELS, MONTHLY_BUDGET_USD, PINNED_MODEL


class RiskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_position_pct: Decimal
    max_exposure_pct: Decimal
    daily_loss_pct: Decimal
    leverage: Decimal
    single_position: bool


class JudgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    deadline_ms: int = 2000
    monthly_budget_usd: Decimal
    price_usd_per_million_input_tokens: Decimal = Decimal("0.042")
    url: str = ""

    @field_validator("model")
    @classmethod
    def pin_model(cls, value: str) -> str:
        if "latest" in value or value not in ALLOWED_MODELS:
            raise ValueError(f"modelo no permitido: {value}; fijado {PINNED_MODEL}")
        return value

    @field_validator("monthly_budget_usd")
    @classmethod
    def cap_budget(cls, value: Decimal) -> Decimal:
        if value != MONTHLY_BUDGET_USD:
            raise ValueError(f"monthly_budget_usd debe ser {MONTHLY_BUDGET_USD}")
        return value


class BotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    mode: Literal["shadow", "simulated"]
    markets: list[str]


class ConnectorToggle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True


class MarketConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    venue: Literal["coinbase", "geckoterminal", "hyperliquid", "fixture"]
    kind: Literal["spot", "perp"]
    product: str
    network: str = ""
    pool: str = ""
    fee_schedule: str = "coinbase_spot"
    tick: Decimal = Decimal("0.01")


class RangeBand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    low: Decimal
    high: Decimal


class DeskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cadence_minutes: int
    snapshot_max_age_s: int
    capital_usd: Decimal
    timezone_reports: str
    risk: RiskConfig
    judge: JudgeConfig
    bots: dict[str, BotConfig]
    connectors: dict[str, ConnectorToggle]
    markets: dict[str, MarketConfig]
    house_range: dict[str, RangeBand] = Field(default_factory=dict)
    policy_version: int = 1
    data_retries: int = 2

    @model_validator(mode="after")
    def required_bots(self) -> DeskConfig:
        missing = {"gambler", "house", "spy"} - set(self.bots)
        if missing:
            raise ValueError(f"faltan bots: {sorted(missing)}")
        if self.risk.leverage != Decimal("1"):
            raise ValueError("apalancamiento permitido: 1")
        if not self.risk.single_position:
            raise ValueError("la mesa opera una sola posición")
        return self


class PromotionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_shadow_days: int
    min_resolved_per_question: int
    min_brier_skill: Decimal
    min_bucket_samples: int
    max_bucket_deviation_pp: Decimal
    max_missed_cycle_pct: Decimal


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"config inválida: {path}")
    return data


def load_desk(path: Path) -> DeskConfig:
    return DeskConfig.model_validate(load_yaml(path))


def load_promotion(path: Path) -> PromotionConfig:
    return PromotionConfig.model_validate(load_yaml(path))


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_desk_path() -> Path:
    return repo_root() / "config" / "desk.yaml"


def default_promotion_path() -> Path:
    return repo_root() / "config" / "promotion.yaml"
