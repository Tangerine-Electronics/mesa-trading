"""Esquema estricto de la mesa. Cualquier modo fuera de sombra/simulado aborta el arranque."""

from __future__ import annotations

import os
from decimal import Decimal
from importlib.resources import as_file, files
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
        coinbase = self.connectors.get("coinbase")
        if coinbase is not None and coinbase.enabled:
            raise ValueError("el conector de Coinbase está apagado: sus términos no permiten este uso")
        for name, market in self.markets.items():
            if market.venue == "coinbase":
                raise ValueError(f"el mercado {name} no puede usar Coinbase")
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
    """Raíz del checkout, o `/app` / el cwd si ahí está `config/desk.yaml`.

    En el árbol fuente, `src/mesa_trading/config.py` queda dos niveles bajo la raíz.
    Tras `pip install .`, `__file__` vive en site-packages y ese cálculo no es el repo.
    """
    source = _source_checkout_root()
    if source is not None:
        return source
    for base in (Path("/app"), Path.cwd()):
        if (base / "config" / "desk.yaml").is_file():
            return base.resolve()
    return Path(__file__).resolve().parents[2]


def default_desk_path() -> Path:
    return _resolve_config_file("desk.yaml", "MESA_DESK_CONFIG")


def default_promotion_path() -> Path:
    return _resolve_config_file("promotion.yaml", "MESA_PROMOTION_CONFIG")


def default_fees_path() -> Path:
    return _resolve_config_file("fees.yaml", "MESA_FEES_CONFIG")


def default_policy_path() -> Path:
    return _resolve_config_file("policy.yaml", "MESA_POLICY_CONFIG")


def _resolve_config_file(filename: str, env_name: str) -> Path:
    override = os.environ.get(env_name, "").strip()
    if override:
        return Path(override)
    candidates: list[Path] = []
    source = _source_checkout_root()
    if source is not None:
        candidates.append(source / "config" / filename)
    bundled = _bundled_file(filename)
    if bundled is not None:
        candidates.append(bundled)
    for base in (Path("/app"), Path.cwd()):
        candidates.append(base / "config" / filename)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    if candidates:
        return candidates[0]
    return Path(__file__).resolve().parents[2] / "config" / filename


def _source_checkout_root() -> Path | None:
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "config" / "desk.yaml").is_file():
        return candidate
    return None


def _bundled_file(filename: str) -> Path | None:
    """YAML copiados dentro del paquete al construir el wheel."""
    try:
        resource = files("mesa_trading").joinpath("bundled_config", filename)
    except ModuleNotFoundError:
        return None
    try:
        present = resource.is_file()
    except OSError:
        return None
    if not present:
        return None
    with as_file(resource) as extracted:
        path = Path(extracted)
        if path.is_file():
            return path
    return None
