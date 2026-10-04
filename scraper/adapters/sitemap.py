"""Adapter genérico por sitemap — Nuvemshop, Tray, Wake/Fbits e Magento.

Essas plataformas não expõem API pública de catálogo, mas publicam sitemap e
metadados estruturados na página do produto. O fluxo é sempre o mesmo:

    sitemap (seguindo índices) -> URLs candidatas -> página -> JSON-LD /
    microdata / Open Graph + seções de ingredientes e tabela nutricional

Como o padrão de URL de produto varia (a Magento usa slug de um só nível, igual
a páginas institucionais), a validação final é a presença de dados de produto na
página, não o formato da URL. `include`/`exclude` em sites.yaml servem para
evitar baixar páginas que certamente não são produto.
"""
from __future__ import annotations

import gzip
import logging
import re
from typing import Any, Iterator
from urllib.parse import urljoin, urlsplit

from ..core.http import FetchError
from ..core.jsonld import (
    availability, brand_de, breadcrumbs, ean_de, extract_product, images_de, offer,
)
from ..core.models import Produto, to_float
from ..core.nutrition import from_description, html_to_text
from .base import Adapter, register

log = logging.getLogger(__name__)

LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
SITEMAP_REF_RE = re.compile(r"(?i)^\s*sitemap:\s*(\S+)", re.M)
MAX_SITEMAPS = 25
CANONICAL_RE = re.compile(r"""<link[^>]+rel=["']canonical["'][^>]+href=["']([^"']+)""", re.I)

# páginas que nunca são produto — evita baixá-las só para descobrir isso
EXCLUDE_PADRAO = re.compile(
    r"/(?:blog|institucional|politica|privacidade|termos|contato|sobre|quem-somos"
    r"|trabalhe|faq|duvidas|atendimento|carrinho|checkout|login|conta|busca|search"
    r"|categoria|colecao|cole[çc][ãa]o|marcas?|fabricante|tag|autor|receitas?)\b", re.I)


@register("sitemap")
class SitemapAdapter(Adapter):
    def fetch(self) -> Iterator[Produto]:
        urls = self._urls_de_produto()
        if not urls:
            log.error("[%s] nenhuma URL candidata encontrada", self.site)
            return
        log.info("[%s] %d URLs candidatas", self.site, len(urls))

        vistos: set[str] = set()
        sem_produto = 0
        for url in urls:
            try:
                html = self.http.get(url)
            except FetchError as exc:
                log.warning("[%s] %s", self.site, exc)
                continue
            try:
                produto = self._parse(url, html)
            except Exception:
                log.exception("[%s] erro ao parsear %s", self.site, url)
                continue
            if produto is None:
                sem_produto += 1
                continue
            if produto.url in vistos:
                continue
            vistos.add(produto.url)
            yield produto

        log.info("[%s] %d produtos, %d páginas sem dados de produto",
                 self.site, len(vistos), sem_produto)

    # ------------------------------------------------------------------
    def _urls_de_produto(self) -> list[str]:
        """URLs finais a visitar. O limite é aplicado por último, depois de
        qualquer filtro de subclasse — senão um `limit` pequeno pode cortar
        justamente as URLs que a subclasse ainda ia descartar."""
        urls = self._candidatas()
        if limite := self.cfg.get("limit"):
            urls = urls[: int(limite)]
        return urls

    def _candidatas(self) -> list[str]:
        brutas = self._coletar_sitemaps()
        incluir = self.cfg.get("include")
        excluir = self.cfg.get("exclude")
        rx_in = re.compile(incluir, re.I) if incluir else None
        rx_out = re.compile(excluir, re.I) if excluir else EXCLUDE_PADRAO

        host = urlsplit(self.base).netloc
        filtradas: list[str] = []
        for url in brutas:
            if urlsplit(url).netloc != host:
                continue
            caminho = urlsplit(url).path
            if not caminho.strip("/"):
                continue  # home
            if rx_in and not rx_in.search(url):
                continue
            if not rx_in and rx_out and rx_out.search(url):
                continue
            filtradas.append(url)

        return list(dict.fromkeys(filtradas))

    def _coletar_sitemaps(self) -> list[str]:
        """Baixa os sitemaps configurados (ou descobertos) seguindo os índices."""
        fila = list(self.cfg.get("sitemaps") or [])
        if not fila:
            fila = [urljoin(self.base, "/sitemap.xml")]
            fila.extend(self._sitemaps_do_robots())

        vistos: set[str] = set()
        urls: list[str] = []
        while fila and len(vistos) < MAX_SITEMAPS:
            atual = fila.pop(0)
            if atual in vistos:
                continue
            vistos.add(atual)
            try:
                texto = self._baixar_xml(atual)
            except FetchError as exc:
                log.warning("[%s] sitemap %s: %s", self.site, atual, exc)
                continue
            locs = LOC_RE.findall(texto)
            # um índice de sitemaps aponta para outros .xml
            indices = [l for l in locs if re.search(r"\.xml(\.gz)?($|\?)", l, re.I)]
            if indices and "<sitemapindex" in texto.lower():
                fila.extend(indices)
                continue
            fila.extend(l for l in indices if l not in vistos)
            urls.extend(l for l in locs if l not in indices)
        return urls

    def _sitemaps_do_robots(self) -> list[str]:
        try:
            robots = self.http.get(urljoin(self.base, "/robots.txt"), cache_ttl=86400)
        except FetchError:
            return []
        return SITEMAP_REF_RE.findall(robots)

    def _baixar_xml(self, url: str) -> str:
        """Baixa um sitemap, descomprimindo quando for de fato gzip.

        Algumas lojas servem um .xml comum em URL terminada em .gz, então a
        extensão não basta: checamos o número mágico do gzip.
        """
        if url.lower().endswith(".gz"):
            # o Client devolve texto; para .gz precisamos dos bytes crus
            resp = self.http.session.get(url, timeout=self.http.timeout)
            resp.raise_for_status()
            bruto = resp.content
            if bruto[:2] == b"\x1f\x8b":
                bruto = gzip.decompress(bruto)
            return bruto.decode("utf-8", "replace")
        return self.http.get(url, cache_ttl=43200)

    # ------------------------------------------------------------------
    def _parse(self, url: str, html: str) -> Produto | None:
        dados = extract_product(html)
        if not dados:
            return None
        oferta = offer(dados)
        preco = to_float(oferta.get("price"))
        if preco is None and not self.cfg.get("permitir_sem_preco"):
            return None  # página de categoria ou produto fora de linha

        ingredientes, nutricional = from_description(html)
        descricao = dados.get("description")

        return self.novo(
            url=self._url_do_produto(url, html, dados),
            name=dados.get("name") or "",
            external_id=str(dados.get("productID") or "") or None,
            sku=str(dados.get("sku") or "") or None,
            ean=ean_de(dados),
            price=preco,
            list_price=to_float(oferta.get("listPrice") or oferta.get("highPrice")),
            available=availability(oferta.get("availability")),
            categories=self._categories(dados, html),
            images=images_de(dados),
            description_html=descricao if descricao and "<" in str(descricao) else None,
            description_text=html_to_text(str(descricao)) if descricao else None,
            ingredients=ingredientes,
            nutrition=nutricional,
        )

    def _url_do_produto(self, url: str, html: str, dados: dict[str, Any]) -> str:
        """Chave do produto no banco.

        Com `usar_canonical: true` vale o <link rel="canonical">: a Growth lista
        no sitemap várias URLs para o mesmo produto ("kit-x", "kit-x-1",
        "kit-x-3") e só a canônica identifica. É opcional porque trocar a chave
        de uma loja já coletada duplicaria os produtos dela no banco.
        """
        if self.cfg.get("usar_canonical") and (m := CANONICAL_RE.search(html)):
            return urljoin(url, m.group(1))
        return dados.get("url") if isinstance(dados.get("url"), str) else url

    def _categories(self, dados: dict[str, Any], html: str) -> list[str]:
        cats: list[str] = []
        bruto = dados.get("category")
        if isinstance(bruto, str):
            cats.extend(p.strip() for p in re.split(r"[>/|]", bruto) if p.strip())
        elif isinstance(bruto, list):
            cats.extend(str(c).strip() for c in bruto if c)
        cats.extend(breadcrumbs(html))
        marca = brand_de(dados)
        return list(dict.fromkeys(c for c in cats if c and c != marca))
