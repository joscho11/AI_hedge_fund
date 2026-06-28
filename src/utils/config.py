"""Typed config loader. Single source of truth is config.yaml at the repo root."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"


class ProjectCfg(BaseModel):
    name: str
    random_seed: int = 7


class UniverseCfg(BaseModel):
    name: str
    min_price: float
    min_dollar_volume: float


class CalendarCfg(BaseModel):
    exchange: str = "XNYS"


class DatesCfg(BaseModel):
    start: str
    end: str
    holdout_start: str


class LabelCfg(BaseModel):
    horizon_days: int
    rebalance: str
    targets: list[str]


class AvailabilityCfg(BaseModel):
    fundamental_lag_days: int = 1
    macro_realtime_only: bool = True


class CostsCfg(BaseModel):
    commission_bps: float
    slippage_bps: float


class ValidationCfg(BaseModel):
    scheme: str
    train_window: str
    embargo_days: int
    purge_days: int


class PathsCfg(BaseModel):
    cache_dir: str
    edgar_user_agent: str


class Config(BaseModel):
    project: ProjectCfg
    universe: UniverseCfg
    calendar: CalendarCfg = Field(default_factory=CalendarCfg)
    dates: DatesCfg
    label: LabelCfg
    availability: AvailabilityCfg
    costs: CostsCfg
    validation: ValidationCfg
    paths: PathsCfg

    @property
    def cache_path(self) -> Path:
        p = Path(self.paths.cache_dir)
        return p if p.is_absolute() else REPO_ROOT / p


def load_config(path: str | Path | None = None) -> Config:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Config(**raw)
