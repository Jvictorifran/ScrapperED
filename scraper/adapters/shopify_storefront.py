"""Adapter Shopify headless via Storefront GraphQL API — Integralmédica.

A loja é um front Next.js sobre Shopify: `/products.json` responde 404 e o
conteúdo (ingredientes, tabela nutricional, porção) vive em metafields que só
aparecem na página dentro do payload serializado do React Server Components.

Em vez de garimpar esse payload, lemos o `storefrontAccessToken` que a própria
página publica — ele é público por design, com escopo de leitura do catálogo — e
consultamos a API oficial. O token é relido a cada execução, então rotação não
quebra a coleta.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterator

from ..core.http import FetchError
from ..core.models import Produto, to_float
from ..core.nutrition import extract_ingredients, html_to_text, parse_nutrition
from .base import Adapter, register

log = logging.getLogger(__name__)

API_VERSION = "2024-10"
PAGE = 50

TOKEN_RE = re.compile(r'"storefrontAccessToken"\s*,\s*"([0-9a-f]{32})"')
SHOP_RE = re.compile(r"([a-z0-9][a-z0-9-]*\.myshopify\.com)")

# metafields de conteúdo nutricional usados pela loja
IDENTIFIERS = [
    ("custom", "ingredientes"),
    ("custom", "tabela_nutricional"),
    ("custom", "porcao_do_produto"),
    ("custom", "modo_de_uso"),
    ("custom", "advertencias"),
]

QUERY = """
query Produtos($cursor: String, $n: Int!) {
  products(first: $n, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges { node {
      id
      title
      handle
      vendor
      productType
      descriptionHtml
      collections(first: 10) { edges { node { title } } }
      images(first: 10) { edges { node { url } } }
      metafields(identifiers: [%s]) { key value type }
      variants(first: 50) { edges { node {
        sku barcode availableForSale
        price { amount }
        compareAtPrice { amount }
      } } }
    } }
  }
}
""" % ", ".join(f'{{namespace:"{ns}", key:"{k}"}}' for ns, k in IDENTIFIERS)


@register("shopify_storefront")
class ShopifyStorefrontAdapter(Adapter):
    def fetch(self) -> Iterator[Produto]:
        try:
            shop, token = self._credenciais()
        except FetchError as exc:
            log.error("[%s] não obtive credenciais da Storefront API: %s", self.site, exc)
            return

        endpoint = f"https://{shop}/api/{API_VERSION}/graphql.json"
        headers = {
            "X-Shopify-Storefront-Access-Token": token,
            "Content-Type": "application/json",
        }
        cursor: str | None = None
        while True:
            corpo = {"query": QUERY, "variables": {"cursor": cursor, "n": PAGE}}
            try:
                resp = self.http.get_json(
                    endpoint, method="POST", json_body=corpo, headers=headers
                )
            except FetchError as exc:
                log.error("[%s] falha na Storefront API: %s", self.site, exc)
                return
            if erros := resp.get("errors"):
                log.error("[%s] GraphQL retornou erros: %s", self.site, str(erros)[:300])
                return

            bloco = (resp.get("data") or {}).get("products") or {}
            for edge in bloco.get("edges") or []:
                no = edge.get("node") or {}
                try:
                    yield self._parse(no)
                except Exception:
                    log.exception("[%s] erro no produto %s", self.site, no.get("handle"))

            info = bloco.get("pageInfo") or {}
            if not info.get("hasNextPage"):
                return
            cursor = info.get("endCursor")

    # ------------------------------------------------------------------
    def _credenciais(self) -> tuple[str, str]:
        """Lê o domínio myshopify e o token público da página da loja."""
        if (shop := self.cfg.get("shop")) and (token := self.cfg.get("token")):
            return shop, token
        html = self.http.get(self.cfg.get("token_page") or self.base, cache_ttl=3600)
        plano = html.replace("\\", "")
        token_m = TOKEN_RE.search(plano)
        shop_m = SHOP_RE.search(plano)
        if not (token_m and shop_m):
            raise FetchError(self.base, None, "token ou domínio myshopify não encontrados")
        return shop_m.group(1), token_m.group(1)

    def _parse(self, no: dict[str, Any]) -> Produto:
        variantes = [e["node"] for e in (no.get("variants") or {}).get("edges") or []]
        disponiveis = [v for v in variantes if v.get("availableForSale")]
        escolha = min(
            disponiveis or variantes or [{}],
            key=lambda v: to_float((v.get("price") or {}).get("amount")) or float("inf"),
        )

        mf = self._metafields(no.get("metafields") or [])
        ingredientes = extract_ingredients(_textos(mf.get("ingredientes")), trusted=True)
        nutricional = parse_nutrition(
            [mf.get("tabela_nutricional")],
            contexto=[mf.get("porcao_do_produto")],
        )
        # campo dedicado de porção: mais confiável que varrer o texto da tabela
        if porcao := mf.get("porcao_do_produto"):
            nutricional["porcao"] = str(porcao).strip()
        for origem, destino in (("modo_de_uso", "usage"), ("advertencias", "warnings")):
            if textos := _textos(mf.get(origem)):
                nutricional[destino] = "\n".join(textos)[:2000]

        descricao = no.get("descriptionHtml") or ""
        return self.novo(
            url=f"{self.base}/{no.get('handle')}/p",
            name=no.get("title") or "",
            external_id=str(no.get("id") or "").rsplit("/", 1)[-1] or None,
            sku=escolha.get("sku") or None,
            ean=escolha.get("barcode") or None,
            price=to_float((escolha.get("price") or {}).get("amount")),
            list_price=to_float((escolha.get("compareAtPrice") or {}).get("amount")),
            available=any(v.get("availableForSale") for v in variantes),
            categories=self._categories(no),
            images=[e["node"]["url"] for e in (no.get("images") or {}).get("edges") or []],
            description_html=descricao or None,
            description_text=html_to_text(descricao),
            ingredients=ingredientes,
            nutrition=nutricional,
        )

    @staticmethod
    def _metafields(lista: list[dict[str, Any] | None]) -> dict[str, Any]:
        """Decodifica os metafields; os do tipo json chegam como string."""
        out: dict[str, Any] = {}
        for campo in lista:
            if not campo or not campo.get("key"):
                continue
            valor = campo.get("value")
            if campo.get("type") == "json" and isinstance(valor, str):
                try:
                    valor = json.loads(valor)
                except json.JSONDecodeError:
                    pass
            out[campo["key"]] = valor
        return out

    @staticmethod
    def _categories(no: dict[str, Any]) -> list[str]:
        cats: list[str] = []
        if tipo := no.get("productType"):
            cats.append(tipo)
        for edge in (no.get("collections") or {}).get("edges") or []:
            if titulo := (edge.get("node") or {}).get("title"):
                cats.append(titulo)
        return list(dict.fromkeys(c for c in cats if c))


def _textos(valor: Any) -> list[str]:
    """Reduz um metafield a uma lista de textos, qualquer que seja o formato."""
    if valor is None:
        return []
    if isinstance(valor, str):
        return [valor] if valor.strip() else []
    if isinstance(valor, list):
        return [t for item in valor for t in _textos(item)]
    if isinstance(valor, dict):
        return [t for item in valor.values() for t in _textos(item)]
    return [str(valor)]
