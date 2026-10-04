"""Modelo canônico de produto, compartilhado por todos os adapters."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Produto:
    # identificação
    site: str                      # chave do site em sites.yaml (ex: "maxtitanium")
    brand: str                     # marca exibida (ex: "Max Titanium")
    url: str                       # URL canônica do produto (chave natural)
    name: str

    external_id: str | None = None  # id do produto na plataforma de origem
    sku: str | None = None
    ean: str | None = None

    # comercial
    price: float | None = None       # preço praticado (à vista/com desconto)
    list_price: float | None = None  # preço "de"
    available: bool | None = None

    # conteúdo
    categories: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    description_html: str | None = None
    description_text: str | None = None

    # nutricional
    ingredients: str | None = None
    nutrition: dict[str, Any] = field(default_factory=dict)

    def as_row(self) -> dict[str, Any]:
        return asdict(self)

    def __post_init__(self) -> None:
        # a Store API do WooCommerce devolve o nome com entidades ("&#8211;")
        self.name = clean_text(html.unescape(self.name or "")) or ""
        self.url = (self.url or "").strip()
        if self.ean:
            digits = re.sub(r"\D", "", str(self.ean))
            # EAN-8/12/13/14 — descarta lixo como "0" ou códigos internos curtos
            self.ean = digits if len(digits) in (8, 12, 13, 14) else None


_WS = re.compile(r"[ \t\r\f\v ]+")
_NL = re.compile(r"\n{3,}")


def clean_text(value: str | None) -> str | None:
    """Normaliza espaços preservando quebras de parágrafo."""
    if not value:
        return None
    text = value.replace(" ", " ")
    text = _WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _NL.sub("\n\n", text)
    return text.strip() or None


def to_float(value: Any) -> float | None:
    """Converte preço em formato BR ou US para float.

    Aceita 1.234,56 / 1,234.56 / 1234.56 / "R$ 99,90" / 9990 (centavos não é tratado aqui).
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) or None
    text = re.sub(r"[^\d,.\-]", "", str(value))
    if not text:
        return None
    if "," in text and "." in text:
        # o separador decimal é o que aparece por último
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text) or None
    except ValueError:
        return None
