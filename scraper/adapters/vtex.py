"""Adapter VTEX — 6 lojas (Max Titanium, Probiótica, Black Skull, Vitafor,
Atlhetica, Nutrify).

Usa a API pública de catálogo, que pagina em janelas de 50 itens
(`_from`/`_to`). O endpoint é severamente limitado por taxa: requisições
concorrentes retornam corpo vazio ou 500, por isso a coleta é serial e o
Client aplica throttle por host.

Cada loja nomeia suas especificações de forma diferente ("Tabela",
"tabela-nutricional-io", "Conteúdo Nutricional"...), então os campos
nutricionais são descobertos por padrão de nome em `nutrition.classify`,
não por chave fixa.
"""
from __future__ import annotations

import logging
from typing import Any, Iterator

from ..core.http import FetchError
from ..core.models import Produto, to_float
from ..core.nutrition import classify, extract_ingredients, html_to_text, parse_nutrition
from .base import Adapter, register

log = logging.getLogger(__name__)

PAGE = 50
MIN_PAGE = 5
MAX_OFFSET = 2500  # limite da API VTEX


@register("vtex")
class VtexAdapter(Adapter):
    def fetch(self) -> Iterator[Produto]:
        janela = int(self.cfg.get("page_size") or PAGE)
        offset = 0
        seen: set[str] = set()
        while offset < MAX_OFFSET:
            batch = self._janela(offset, janela)

            # Algumas lojas rejeitam a janela de 50 e respondem HTTP 200 com um
            # objeto de erro ("upstream_unavailable"). Reduzir a janela resolve,
            # então tentamos metade antes de desistir da loja.
            if batch is None:
                if janela > MIN_PAGE:
                    janela = max(MIN_PAGE, janela // 2)
                    log.warning("[%s] janela rejeitada; tentando %d por página",
                                self.site, janela)
                    continue
                log.error("[%s] a loja rejeitou até a menor janela (%d)",
                          self.site, janela)
                break
            if not batch:
                break

            for raw in batch:
                try:
                    produto = self._parse(raw)
                except Exception:  # um produto malformado não derruba a loja
                    log.exception("[%s] erro ao parsear produto %s",
                                  self.site, raw.get("productId"))
                    continue
                if produto and produto.url not in seen:
                    seen.add(produto.url)
                    yield produto

            if len(batch) < janela:
                break
            offset += janela

    def _janela(self, offset: int, tamanho: int) -> list[dict[str, Any]] | None:
        """Busca uma janela do catálogo.

        Devolve a lista de produtos, `[]` quando o catálogo acabou, ou `None`
        quando a loja recusou a requisição — o que pede uma janela menor.
        """
        url = (f"{self.base}/api/catalog_system/pub/products/search"
               f"?_from={offset}&_to={offset + tamanho - 1}")
        try:
            resposta = self.http.get_json(url, allow_status={206})
        except FetchError as exc:
            log.error("[%s] falha na janela %d: %s", self.site, offset, exc)
            return None
        if isinstance(resposta, dict):
            log.warning("[%s] erro da API na janela %d: %s", self.site, offset,
                        resposta.get("reason") or str(resposta)[:80])
            return None
        return resposta if isinstance(resposta, list) else None

    # ------------------------------------------------------------------
    def _parse(self, raw: dict[str, Any]) -> Produto | None:
        items = raw.get("items") or []
        if not items:
            return None

        # SKU escolhido: o primeiro disponível; senão o primeiro de todos
        sku = next((i for i in items if self._offer(i).get("IsAvailable")), items[0])
        offer = self._offer(sku)

        groups = self._spec_groups(raw)
        nutri_blobs = groups.get("nutrition", [])
        # campo dedicado a ingredientes é confiável; cair no nutricional é garimpo
        dedicado = groups.get("ingredients", [])
        ingred_blobs, confiavel = (dedicado, True) if dedicado else (nutri_blobs, False)

        nutrition = parse_nutrition(nutri_blobs, images=groups.get("nutrition_image", []))
        for campo in ("allergens", "usage", "warnings", "portion"):
            if valores := [html_to_text(v) for v in groups.get(campo, []) if v]:
                nutrition[campo] = "\n".join(v for v in valores if v)[:2000]

        images = [
            img.get("imageUrl") for img in (sku.get("images") or [])
            if img.get("imageUrl")
        ]

        return self.novo(
            url=raw.get("link") or f"{self.base}/{raw.get('linkText')}/p",
            name=raw.get("productName") or sku.get("name") or "",
            external_id=str(raw.get("productId") or "") or None,
            sku=sku.get("itemId"),
            ean=sku.get("ean"),
            price=to_float(offer.get("Price")),
            list_price=to_float(offer.get("ListPrice")),
            available=bool(offer.get("IsAvailable")) if offer else None,
            categories=self._categories(raw),
            images=list(dict.fromkeys(images)),
            description_html=raw.get("description"),
            description_text=html_to_text(raw.get("description")),
            ingredients=extract_ingredients(ingred_blobs, trusted=confiavel),
            nutrition=nutrition,
        )

    @staticmethod
    def _offer(sku: dict[str, Any]) -> dict[str, Any]:
        sellers = sku.get("sellers") or []
        if not sellers:
            return {}
        # prefere o seller principal (loja própria) quando marcado
        principal = next((s for s in sellers if s.get("sellerDefault")), sellers[0])
        return principal.get("commertialOffer") or {}

    @staticmethod
    def _spec_groups(raw: dict[str, Any]) -> dict[str, list[Any]]:
        """Agrupa as especificações da loja nos campos canônicos."""
        groups: dict[str, list[Any]] = {}
        for label in (raw.get("allSpecifications") or []):
            campo = classify(label)
            if not campo:
                continue
            valor = raw.get(label)
            if isinstance(valor, list):
                groups.setdefault(campo, []).extend(valor)
            elif valor:
                groups.setdefault(campo, []).append(valor)
        return groups

    @staticmethod
    def _categories(raw: dict[str, Any]) -> list[str]:
        """VTEX entrega caminhos como '/Proteinas/Whey/'. Achata em termos únicos."""
        termos: list[str] = []
        for caminho in (raw.get("categories") or []):
            termos.extend(p for p in caminho.strip("/").split("/") if p)
        return list(dict.fromkeys(termos))
