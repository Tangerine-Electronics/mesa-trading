"""Baterías por bot. Cada pregunta trae su regla de resultado y su horizonte."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any, Literal


@dataclass(frozen=True)
class Question:
    id: str
    type: Literal["choice", "noul", "score"]
    text: str
    options: tuple[str, ...]
    criteria: dict[str, str] | tuple[str, ...]
    fields: tuple[str, ...]
    horizon: timedelta
    calibrable: bool = True

    def jev_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {"type": self.type, "instructions": self.text}
        if self.type == "score":
            body["criteria"] = list(self.criteria) if isinstance(self.criteria, tuple) else list(self.criteria.values())
        else:
            body["criteria"] = dict(self.criteria) if isinstance(self.criteria, dict) else {item: item for item in self.criteria}
        return body


GAMBLER: tuple[Question, ...] = (
    Question(
        id="regimen",
        type="choice",
        text="¿En qué régimen está este mercado ahora: tendencia, reversión a la media, caótico u otro?",
        options=("tendencia", "reversion", "caotico", "otro"),
        criteria={
            "tendencia": "El precio camina en una dirección con persistencia",
            "reversion": "El precio vuelve hacia su media reciente",
            "caotico": "Sin dirección usable, ruido",
            "otro": "No encaja o faltan datos",
        },
        fields=("ret_15m", "ret_1h", "ret_4h", "vol"),
        horizon=timedelta(hours=1),
    ),
    Question(
        id="presion_compra",
        type="noul",
        text="¿Se está acumulando presión de compra en este mercado?",
        options=("si", "no"),
        criteria={"si": "Hay presión de compra", "no": "No hay presión de compra"},
        fields=("imbalance", "ret_15m"),
        horizon=timedelta(minutes=15),
    ),
    Question(
        id="setup",
        type="score",
        text="¿Qué tanto se parece esto a un setup que ha funcionado?",
        options=("0", "1", "2", "3"),
        criteria=(
            "No se parece a un setup usable",
            "Parecido débil",
            "Parecido claro",
            "Parecido fuerte",
        ),
        fields=("ret_15m", "ret_1h", "vol", "dist_high", "dist_low"),
        horizon=timedelta(hours=1),
    ),
    Question(
        id="accion",
        type="choice",
        text="¿Qué acción encaja con este estado: largo, corto o hold (no hacer nada)?",
        options=("largo", "corto", "hold"),
        criteria={
            "largo": "Apostar a que el precio sube",
            "corto": "Apostar a que el precio baja",
            "hold": "No entrar",
        },
        fields=("ret_15m", "ret_1h", "ret_4h", "vol", "spread_bps"),
        horizon=timedelta(hours=1),
    ),
    Question(
        id="ejecucion_degradada",
        type="noul",
        text="¿La calidad de ejecución está degradada (spread o liquidez peores de lo operable)?",
        options=("si", "no"),
        criteria={"si": "Ejecutar ahora saldría caro", "no": "La ejecución se ve normal"},
        fields=("spread_bps", "liquidity_usd"),
        horizon=timedelta(minutes=5),
    ),
)

HOUSE: tuple[Question, ...] = (
    Question(
        id="estado_rango",
        type="choice",
        text="¿El precio está dentro del rango, probando el borde, rompiendo el rango u otro?",
        options=("dentro", "borde", "rompiendo", "otro"),
        criteria={
            "dentro": "Cómodo dentro del rango",
            "borde": "Probando un extremo sin romperlo",
            "rompiendo": "Salió del rango",
            "otro": "No encaja o faltan datos",
        },
        fields=("dist_low", "dist_high", "range_low", "range_high", "last_close"),
        horizon=timedelta(minutes=30),
    ),
    Question(
        id="flujo_toxico",
        type="noul",
        text="¿El flujo es tóxico (quien nos ejecuta parece saber algo que el libro no muestra)?",
        options=("si", "no"),
        criteria={"si": "El flujo parece informado", "no": "El flujo parece ruido"},
        fields=("imbalance", "spread_bps", "fill_rate"),
        horizon=timedelta(minutes=30),
    ),
    Question(
        id="vale_cotizar",
        type="score",
        text="¿Vale la pena cotizar en este rango ahora?",
        options=("0", "1", "2", "3"),
        criteria=(
            "No cotizar",
            "Cotizar solo si el costo es mínimo",
            "Cotizar con tamaño normal",
            "Cotizar con convicción",
        ),
        fields=("spread_bps", "reprice_cost_bps", "vol", "quote_spread"),
        horizon=timedelta(minutes=30),
    ),
    Question(
        id="hay_volumen",
        type="noul",
        text="¿Sigue habiendo volumen suficiente para que el rango pague el spread?",
        options=("si", "no"),
        criteria={"si": "Hay actividad", "no": "El volumen se apagó"},
        fields=("volume_6h_vs_day", "fill_rate"),
        horizon=timedelta(minutes=30),
    ),
)

SPY: tuple[Question, ...] = (
    Question(
        id="perfil",
        type="choice",
        text="¿Esta billetera parece hábil, con suerte, un bot, con información privilegiada u otro?",
        options=("habil", "suerte", "bot", "privilegiada", "otro"),
        criteria={
            "habil": "Ventaja repetida y consistente",
            "suerte": "Resultados sin patrón",
            "bot": "Tamaño y ritmo mecánicos",
            "privilegiada": "Entra antes que el mercado de forma recurrente",
            "otro": "No encaja o faltan datos",
        },
        fields=("hit_rate", "realized_pnl", "hold_hours", "size_consistency", "early_entry"),
        horizon=timedelta(hours=24),
    ),
    Question(
        id="consistente",
        type="noul",
        text="¿Este movimiento es consistente con los hábitos de esa billetera?",
        options=("si", "no"),
        criteria={"si": "Encaja con su historia", "no": "Se sale de su patrón"},
        fields=("hold_hours", "size_consistency", "early_entry"),
        horizon=timedelta(hours=24),
    ),
    Question(
        id="copiar",
        type="choice",
        text="¿Copiar el movimiento completo, parcial o no copiarlo?",
        options=("completo", "parcial", "no"),
        criteria={
            "completo": "Copiar el tamaño permitido",
            "parcial": "Copiar una fracción",
            "no": "No copiar",
        },
        fields=("hit_rate", "size_consistency"),
        horizon=timedelta(hours=24),
    ),
    Question(
        id="rug",
        type="noul",
        text="¿Hay riesgo de rug pull dadas las banderas del contrato?",
        options=("si", "no"),
        criteria={"si": "Las banderas sugieren rug pull", "no": "Las banderas no lo sugieren"},
        fields=("holder_concentration", "mint_authority_open", "liquidity_locked", "honeypot"),
        horizon=timedelta(hours=24),
    ),
)

BATTERIES = {"gambler": GAMBLER, "house": HOUSE, "spy": SPY}


def battery_for(bot: str) -> tuple[Question, ...]:
    try:
        return BATTERIES[bot]
    except KeyError as exc:
        raise KeyError(f"bot sin batería: {bot}") from exc


def realized_outcome(question_id: str, future: list[dict], entry: Decimal | None) -> str | None:
    """Clase realizada con velas posteriores al instante de decisión. None si aún no hay horizonte."""
    if entry is None or not future:
        return None
    last = Decimal(str(future[-1]["close"]))
    ret = (last - entry) / entry if entry != 0 else Decimal("0")
    if question_id == "accion":
        if ret > Decimal("0.003"):
            return "largo"
        if ret < Decimal("-0.003"):
            return "corto"
        return "hold"
    if question_id == "presion_compra":
        return "si" if ret > 0 else "no"
    if question_id == "ejecucion_degradada":
        return "no"
    if question_id == "regimen":
        if abs(ret) > Decimal("0.01"):
            return "tendencia"
        if abs(ret) < Decimal("0.001"):
            return "reversion"
        return "caotico"
    if question_id == "setup":
        if ret > Decimal("0.005"):
            return "3"
        if ret > Decimal("0.002"):
            return "2"
        if ret > 0:
            return "1"
        return "0"
    if question_id == "estado_rango":
        return "rompiendo" if abs(ret) > Decimal("0.01") else "dentro"
    if question_id == "flujo_toxico":
        return "si" if ret < Decimal("-0.005") else "no"
    if question_id == "vale_cotizar":
        return "2" if abs(ret) < Decimal("0.005") else "0"
    if question_id == "hay_volumen":
        return "si" if future and sum(Decimal(str(c.get("volume") or 0)) for c in future) > 0 else "no"
    if question_id in {"perfil", "consistente", "copiar", "rug"}:
        return None
    return None
