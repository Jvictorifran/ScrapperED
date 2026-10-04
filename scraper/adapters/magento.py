"""Adapter Magento 2 — Essential Nutrition.

A loja não publica JSON-LD, microdata nem Open Graph: o que resta no HTML
estático é o padrão do próprio Magento (`data-price-amount`, `h1.page-title`,
breadcrumbs). Nome, preço, categorias e imagens saem daí.

Limitação conhecida: ingredientes e tabela nutricional são renderizados no
cliente e não existem no HTML servido, então esses campos ficam vazios para
esta loja. Preenchê-los exige browser headless, igual ao Grupo C do RECON.md.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterator

from bs4 import BeautifulSoup

from ..core.models import Produto, to_float
from ..core.nutrition import from_description, html_to_text
from .sitemap import SitemapAdapter
from .base import register

log = logging.getLogger(__name__)

IMG_PRODUTO_RE = re.compile(r"/media/catalog/product/", re.I)
LIXO_URL_RE = re.compile(
    r"/(?:privacy|policy|cookie|prescritor|nossa-marca|politica|termos|contato"
    r"|produtos|blog|conteudos|sobre|trabalhe|faq|duvidas|login|customer|checkout"
    r"|cart|search|busca|catalogsearch|wishlist|sitemap|newsletter)", re.I)


@register("magento")
class MagentoAdapter(SitemapAdapter):
    """Reusa a descoberta por sitemap do SitemapAdapter e troca o parser."""

    def _candidatas(self) -> list[str]:
        urls = super()._candidatas()
        # na Magento o produto é um slug de primeiro nível, igual às páginas
        # institucionais; filtrar pelos nomes conhecidos evita baixá-las
        return [u for u in urls if not LIXO_URL_RE.search(u)]

    def _parse(self, url: str, html: str) -> Produto | None:
        soup = BeautifulSoup(html, "lxml")

        titulo = soup.select_one(".page-title span, .page-title, h1")
        nome = titulo.get_text(" ", strip=True) if titulo else ""
        if not nome:
            return None

        preco, de = self._precos(soup)
        if preco is None:
            return None  # sem preço não é página de produto

        descricao_html = self._descricao(soup)
        ingredientes, nutricional = from_description(descricao_html or html)

        return self.novo(
            url=url,
            name=nome,
            sku=self._sku(soup),
            price=preco,
            list_price=de,
            available=self._disponivel(soup, html),
            categories=self._trilha(soup, nome),
            images=self._imagens(soup),
            description_html=descricao_html,
            description_text=html_to_text(descricao_html),
            ingredients=ingredientes,
            nutrition=nutricional,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _precos(soup) -> tuple[float | None, float | None]:
        """Lê `data-price-amount`, separando preço final de preço antigo."""
        final: list[float] = []
        antigo: list[float] = []
        for tag in soup.select("[data-price-amount]"):
            valor = to_float(tag.get("data-price-amount"))
            if valor is None:
                continue
            tipo = (tag.get("data-price-type") or "").strip()
            if tipo == "oldPrice":
                antigo.append(valor)
            elif tipo in ("finalPrice", "basePrice", ""):
                final.append(valor)
        # o primeiro finalPrice é o do produto da página; os demais são
        # blocos de produtos relacionados
        return (final[0] if final else None, antigo[0] if antigo else None)

    @staticmethod
    def _sku(soup) -> str | None:
        for sel in (".product.attribute.sku .value", "[itemprop=sku]",
                    "[data-th=SKU]", ".product-info-sku .value"):
            if tag := soup.select_one(sel):
                if texto := tag.get_text(" ", strip=True):
                    return texto[:60]
        return None

    @staticmethod
    def _descricao(soup) -> str | None:
        for sel in (".product.attribute.description .value",
                    ".product.attribute.overview .value",
                    ".product.attribute.description",
                    "#description", "[id*=description]"):
            if tag := soup.select_one(sel):
                html = str(tag)
                if len(html) > 80:
                    return html
        return None

    @staticmethod
    def _disponivel(soup, html: str) -> bool | None:
        """Lê o estoque só dentro do bloco do produto da página.

        Varrer o HTML inteiro por "fora de estoque" dá falso negativo: a frase
        aparece em vitrines de produtos relacionados e em strings de JavaScript.
        """
        bloco = soup.select_one(
            ".product-info-main, .product-info-price, #product_addtocart_form"
        ) or soup
        if bloco.select_one(".stock.unavailable, .out-of-stock, [class*=unavailable]"):
            return False
        if bloco.select_one(".stock.available, [class*=in-stock]"):
            return True
        if bloco.select_one("button#product-addtocart-button, [id*=addtocart]"):
            return True
        return None

    @staticmethod
    def _trilha(soup, nome: str) -> list[str]:
        itens = [
            t.get_text(" ", strip=True)
            for t in soup.select(".breadcrumbs li, [class*=breadcrumb] li, [class*=breadcrumb] a")
        ]
        limpos = [
            i for i in itens
            if i and i.casefold() not in {"home", "início", "inicio", nome.casefold()}
        ]
        return list(dict.fromkeys(limpos))

    @staticmethod
    def _imagens(soup) -> list[str]:
        urls: list[str] = []
        for tag in soup.find_all("img"):
            for attr in ("src", "data-src", "data-original"):
                if (valor := tag.get(attr)) and IMG_PRODUTO_RE.search(str(valor)):
                    urls.append(str(valor))
                    break
        return list(dict.fromkeys(urls))[:10]
