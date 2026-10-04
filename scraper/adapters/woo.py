"""Adapter WooCommerce Store API — Adaptogen Science.

A Store API é pública e não exige chave. Devolve preços em centavos
(`prices.price` + `currency_minor_unit`), o que exige conversão.
"""
from __future__ import annotations

import logging
from typing import Any, Iterator

from ..core.http import FetchError
from ..core.models import Produto, to_float
from ..core.nutrition import from_description, html_to_text
from .base import Adapter, register

log = logging.getLogger(__name__)

PAGE = 100
MAX_PAGES = 60


@register("woo")
class WooAdapter(Adapter):
    def fetch(self) -> Iterator[Produto]:
        for page in range(1, MAX_PAGES + 1):
            url = f"{self.base}/wp-json/wc/store/products?per_page={PAGE}&page={page}"
            try:
                itens = self.http.get_json(url)
            except FetchError as exc:
                log.error("[%s] falha na página %d: %s", self.site, page, exc)
                return
            if not isinstance(itens, list) or not itens:
                return
            for raw in itens:
                try:
                    yield self._parse(raw)
                except Exception:
                    log.exception("[%s] erro no produto %s", self.site, raw.get("id"))
            if len(itens) < PAGE:
                return

    def _parse(self, raw: dict[str, Any]) -> Produto:
        precos = raw.get("prices") or {}
        descricao = raw.get("description") or raw.get("short_description") or ""
        ingredientes, nutricional = from_description(descricao)

        return self.novo(
            url=raw.get("permalink") or f"{self.base}/?p={raw.get('id')}",
            name=raw.get("name") or "",
            external_id=str(raw.get("id") or "") or None,
            sku=raw.get("sku") or None,
            price=self._money(precos.get("price"), precos),
            list_price=self._money(precos.get("regular_price"), precos),
            available=raw.get("is_in_stock"),
            categories=[c["name"] for c in (raw.get("categories") or []) if c.get("name")],
            images=[i["src"] for i in (raw.get("images") or []) if i.get("src")],
            description_html=descricao or None,
            description_text=html_to_text(descricao),
            ingredients=ingredientes,
            nutrition=nutricional,
        )

    @staticmethod
    def _money(valor: Any, precos: dict[str, Any]) -> float | None:
        """Converte o inteiro em unidade menor da Store API para reais."""
        numero = to_float(valor)
        if numero is None:
            return None
        casas = precos.get("currency_minor_unit")
        return numero / (10 ** casas) if isinstance(casas, int) else numero
