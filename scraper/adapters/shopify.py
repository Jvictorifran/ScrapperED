"""Adapter Shopify — FTW, Soldiers Nutrition, Bold Snacks, Urso (Cimed).

`/products.json` entrega o catálogo paginado com variantes, preço e SKU. O
nutricional não tem campo próprio: vem dentro de `body_html`, separado por
títulos, e algumas lojas (Bold) só o publicam na página do produto. Nesses
casos, `enrich: true` em sites.yaml manda buscar a página quando a descrição
não rende ingredientes nem tabela.
"""
from __future__ import annotations

import logging
from typing import Any, Iterator

from ..core.http import FetchError
from ..core.models import Produto, to_float
from ..core.nutrition import from_description, html_to_text
from .base import Adapter, register

log = logging.getLogger(__name__)

PAGE = 250
MAX_PAGES = 40


@register("shopify")
class ShopifyAdapter(Adapter):
    def fetch(self) -> Iterator[Produto]:
        for page in range(1, MAX_PAGES + 1):
            url = f"{self.base}/products.json?limit={PAGE}&page={page}"
            try:
                payload = self.http.get_json(url)
            except FetchError as exc:
                log.error("[%s] falha na página %d: %s", self.site, page, exc)
                return
            produtos = (payload or {}).get("products") or []
            if not produtos:
                return
            for raw in produtos:
                try:
                    yield self._parse(raw)
                except Exception:
                    log.exception("[%s] erro no produto %s", self.site, raw.get("handle"))
            if len(produtos) < PAGE:
                return

    # ------------------------------------------------------------------
    def _parse(self, raw: dict[str, Any]) -> Produto:
        variantes = raw.get("variants") or [{}]
        # preço de referência: a variante disponível mais barata
        disponiveis = [v for v in variantes if v.get("available")]
        escolha = min(
            disponiveis or variantes,
            key=lambda v: to_float(v.get("price")) or float("inf"),
        )
        handle = raw.get("handle") or ""
        url = f"{self.base}/products/{handle}"

        body = raw.get("body_html") or ""
        ingredientes, nutricional = from_description(body)

        if self.cfg.get("enrich") and not ingredientes and not nutricional.get("itens"):
            ingredientes, nutricional = self._from_page(url, ingredientes, nutricional)

        return self.novo(
            url=url,
            name=raw.get("title") or "",
            external_id=str(raw.get("id") or "") or None,
            sku=escolha.get("sku") or None,
            ean=escolha.get("barcode") or None,
            price=to_float(escolha.get("price")),
            list_price=to_float(escolha.get("compare_at_price")),
            available=any(v.get("available") for v in variantes),
            categories=self._categories(raw),
            images=[i.get("src") for i in (raw.get("images") or []) if i.get("src")],
            description_html=body or None,
            description_text=html_to_text(body),
            ingredients=ingredientes,
            nutrition=nutricional,
        )

    def _from_page(
        self, url: str, ingredientes: str | None, nutricional: dict[str, Any]
    ) -> tuple[str | None, dict[str, Any]]:
        """Busca a página do produto quando a descrição não trouxe nutricional."""
        try:
            html = self.http.get(url)
        except FetchError as exc:
            log.warning("[%s] não consegui enriquecer %s: %s", self.site, url, exc)
            return ingredientes, nutricional
        ing_pag, nut_pag = from_description(html)
        # a descrição tem prioridade; a página preenche o que faltou
        combinado = {**nut_pag, **nutricional}
        return ingredientes or ing_pag, combinado

    @staticmethod
    def _categories(raw: dict[str, Any]) -> list[str]:
        cats: list[str] = []
        if tipo := raw.get("product_type"):
            cats.append(tipo)
        for tag in (raw.get("tags") or []):
            # tags da Shopify costumam vir namespaced: "colecao:street-fighter"
            cats.append(tag.split(":", 1)[-1] if ":" in tag else tag)
        return list(dict.fromkeys(c for c in cats if c))
