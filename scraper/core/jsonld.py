"""Leitura de JSON-LD (schema.org) das páginas de produto.

Shopify, Nuvemshop, Tray, Magento e Wake publicam o produto em
`<script type="application/ld+json">`. É a fonte mais estável de nome, preço,
SKU, EAN e disponibilidade — muito mais resistente a troca de tema do que
seletores de CSS.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import unicodedata
from typing import Any, Iterator
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .models import to_float

AVAIL_IN = re.compile(r"instock|in_stock|limitedavailability|preorder", re.I)
AVAIL_OUT = re.compile(r"outofstock|out_of_stock|soldout|discontinued", re.I)
# JSON-LD real às vezes vem com vírgula sobrando ou comentário de template
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def _loads(texto: str) -> Any:
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        try:
            return json.loads(_TRAILING_COMMA.sub(r"\1", texto))
        except json.JSONDecodeError:
            return None


def iter_ld(html: str) -> Iterator[dict[str, Any]]:
    """Percorre todos os objetos JSON-LD da página, inclusive dentro de @graph."""
    soup = BeautifulSoup(html, "lxml")
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        dados = _loads(script.string or script.get_text() or "")
        if dados is None:
            continue
        pilha = [dados]
        while pilha:
            atual = pilha.pop()
            if isinstance(atual, list):
                pilha.extend(atual)
            elif isinstance(atual, dict):
                yield atual
                if isinstance(grafo := atual.get("@graph"), list):
                    pilha.extend(grafo)


def _tipos(obj: dict[str, Any]) -> set[str]:
    bruto = obj.get("@type") or []
    valores = bruto if isinstance(bruto, list) else [bruto]
    return {str(v).split("/")[-1].casefold() for v in valores}


def _norm(texto: Any) -> str:
    """Forma comparável de um título: sem acento, caixa, pontuação nem entidades."""
    t = unicodedata.normalize("NFKD", html_lib.unescape(str(texto or "")))
    t = "".join(c for c in t if not unicodedata.combining(c)).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", t))


def _caminho(url: Any) -> str:
    return urlsplit(str(url or "")).path.rstrip("/").casefold()


def identidade(html: str) -> tuple[set[str], str]:
    """Títulos (h1, og:title, <title>) e caminho canônico da página.

    É o que diz qual produto a página é de fato. Lojas colocam Product de
    carrossel e de "recomendados" na mesma página — a Dux chega a publicar
    seis Product em JSON-LD e nenhum deles é o produto da página.
    """
    soup = BeautifulSoup(html, "lxml")
    titulos = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
    canonico = ""
    for tag in soup.find_all("meta"):
        chave = (tag.get("property") or tag.get("name") or "").lower()
        if chave == "og:title":
            titulos.append(tag.get("content") or "")
        elif chave == "og:url" and not canonico:
            canonico = tag.get("content") or ""
    if soup.title and soup.title.string:
        titulos.append(soup.title.string)
    if (link := soup.find("link", rel="canonical")) and link.get("href"):
        canonico = link["href"]
    return {n for t in titulos if (n := _norm(t))}, _caminho(canonico)


def _e_da_pagina(obj: dict[str, Any], titulos: set[str], caminho: str) -> bool:
    """O produto é o da página? Bate pela URL ou pelo nome.

    O <title> costuma vir com sufixo ("Nome - Comprar em Loja"), por isso o
    título pode começar pelo nome. O contrário não vale: o h1 de uma categoria
    ("Barra de proteína") é prefixo do nome de qualquer produto dela.
    """
    if caminho and isinstance(obj.get("url"), str) and _caminho(obj["url"]) == caminho:
        return True
    nome = _norm(obj.get("name"))
    return bool(nome) and any(t == nome or t.startswith(nome + " ") for t in titulos)


def find_product(html: str) -> dict[str, Any] | None:
    """Devolve o JSON-LD do produto principal da página.

    Com um único Product, ele é aceito a menos que aponte para outra URL. Com
    vários, só vale o que bater com o título ou a URL da página — escolher pelo
    primeiro ou pelo mais completo gravou o mesmo produto de carrossel em todas
    as páginas da Dux e da New Millen.
    """
    candidatos = [o for o in iter_ld(html) if "product" in _tipos(o)]
    if not candidatos:
        return None
    titulos, caminho = identidade(html)
    if len(candidatos) == 1:
        unico = candidatos[0]
        url = unico.get("url")
        if caminho and isinstance(url, str) and _caminho(url) not in ("", caminho) \
                and not _e_da_pagina(unico, titulos, ""):
            return None
        return unico

    candidatos = [o for o in candidatos if _e_da_pagina(o, titulos, caminho)]
    if not candidatos:
        return None

    def pontos(obj: dict[str, Any]) -> int:
        p = 0
        if obj.get("sku") or obj.get("mpn"):
            p += 2
        if any(obj.get(k) for k in ("gtin13", "gtin", "gtin12", "gtin8", "gtin14")):
            p += 2
        if offer(obj).get("price") is not None:
            p += 1
        if obj.get("aggregateRating") or obj.get("review"):
            p += 1
        return p

    return max(candidatos, key=pontos)


# --- Nuvemshop: LS.product + data-variants ----------------------------------

_LS_PRODUCT_RE = re.compile(
    r"LS\.product\s*=\s*\{\s*id\s*:\s*(\d+)\s*,\s*name\s*:\s*'((?:[^'\\]|\\.)*)'")
_DATA_VARIANTS_RE = re.compile(r'data-variants="([^"]*)"')
_JS_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})|\\(.)")


def _js_string(bruto: str) -> str:
    return _JS_ESCAPE_RE.sub(lambda m: chr(int(m[1], 16)) if m[1] else m[2], bruto)


def from_nuvemshop(html: str) -> dict[str, Any] | None:
    """Produto da página numa loja Nuvemshop, no formato do JSON-LD.

    `LS.product` é o objeto que o tema usa para o produto exibido — é a única
    fonte que identifica a página com certeza. Preço, preço "de", SKU e estoque
    vêm das variantes em `data-variants`, filtradas pelo id do produto (a página
    também traz variantes dos produtos recomendados).
    """
    if not (m := _LS_PRODUCT_RE.search(html)):
        return None
    pid, nome = int(m[1]), _js_string(m[2])

    variantes: list[dict[str, Any]] = []
    for bruto in _DATA_VARIANTS_RE.findall(html):
        try:
            lista = json.loads(html_lib.unescape(bruto))
        except json.JSONDecodeError:
            continue
        if isinstance(lista, list):
            variantes.extend(v for v in lista
                             if isinstance(v, dict) and v.get("product_id") == pid)
    variantes = list({v.get("id"): v for v in variantes}.values())
    if not variantes:
        return None

    ofertas = [{
        "price": v.get("price_number"),
        "listPrice": v.get("compare_at_price_number"),
        "availability": "InStock" if v.get("available") else "OutOfStock",
        "sku": v.get("sku"),
    } for v in variantes if v.get("price_number") is not None]
    if not ofertas:
        return None

    og = from_opengraph(html) or {}
    imagens = list(og.get("image") or [])
    for v in variantes:
        if url := v.get("image_url"):
            imagens.append("https:" + url if url.startswith("//") else url)

    return {
        "@type": "Product",
        "name": nome,
        "productID": str(pid),
        "sku": next((o["sku"] for o in ofertas if o.get("sku")), None),
        "description": og.get("description"),
        "image": list(dict.fromkeys(imagens)),
        "offers": ofertas,
        "_fonte": "nuvemshop",
    }


def offer(produto: dict[str, Any]) -> dict[str, Any]:
    """Normaliza `offers`, que pode ser objeto, lista ou AggregateOffer."""
    bruto = produto.get("offers")
    if isinstance(bruto, list):
        ofertas = [o for o in bruto if isinstance(o, dict)]
        if not ofertas:
            return {}
        # prefere uma oferta disponível; entre elas, a mais barata
        disp = [o for o in ofertas if AVAIL_IN.search(str(o.get("availability") or ""))]
        return min(disp or ofertas, key=lambda o: to_float(o.get("price")) or float("inf"))
    if isinstance(bruto, dict):
        if "lowPrice" in bruto and "price" not in bruto:
            return {**bruto, "price": bruto.get("lowPrice")}
        return bruto
    return {}


def availability(valor: Any) -> bool | None:
    texto = str(valor or "")
    if AVAIL_IN.search(texto):
        return True
    if AVAIL_OUT.search(texto):
        return False
    return None


def ean_de(produto: dict[str, Any]) -> str | None:
    for chave in ("gtin13", "gtin14", "gtin12", "gtin8", "gtin"):
        if valor := produto.get(chave):
            return str(valor)
    return None


def images_de(produto: dict[str, Any]) -> list[str]:
    bruto = produto.get("image")
    itens = bruto if isinstance(bruto, list) else [bruto]
    urls: list[str] = []
    for item in itens:
        if isinstance(item, str):
            urls.append(item)
        elif isinstance(item, dict) and (u := item.get("url") or item.get("contentUrl")):
            urls.append(str(u))
    return list(dict.fromkeys(urls))


def brand_de(produto: dict[str, Any]) -> str | None:
    marca = produto.get("brand")
    if isinstance(marca, dict):
        return marca.get("name")
    return marca if isinstance(marca, str) else None


def breadcrumbs(html: str) -> list[str]:
    """Categorias a partir do BreadcrumbList, descartando home e o próprio produto."""
    for obj in iter_ld(html):
        if "breadcrumblist" not in _tipos(obj):
            continue
        itens = obj.get("itemListElement") or []
        nomes: list[str] = []
        for el in itens:
            if not isinstance(el, dict):
                continue
            nome = el.get("name")
            if not nome and isinstance(el.get("item"), dict):
                nome = el["item"].get("name")
            if nome:
                nomes.append(str(nome).strip())
        if len(nomes) > 1:
            nomes = nomes[:-1]  # o último é o próprio produto
        return [n for n in nomes if n and n.casefold() not in {"home", "início", "inicio"}]
    return []


# --- fallbacks: microdata (Tray) e Open Graph -------------------------------

_ITEMPROPS = {
    "name", "description", "sku", "productID", "mpn", "model", "brand",
    "price", "priceCurrency", "availability", "gtin13", "gtin14", "gtin12",
    "gtin8", "gtin", "image", "category",
}
_OFFER_PROPS = {"price", "priceCurrency", "availability"}


def _valor_itemprop(tag) -> str | None:
    for attr in ("content", "href", "src", "datetime"):
        if (v := tag.get(attr)):
            return str(v).strip()
    texto = tag.get_text(" ", strip=True)
    return texto or None


def from_microdata(html: str) -> dict[str, Any] | None:
    """Monta um Product no formato do JSON-LD a partir de microdata itemprop.

    A Tray não publica JSON-LD, só microdata. Normalizar aqui mantém os adapters
    sem ramificação por plataforma.
    """
    soup = BeautifulSoup(html, "lxml")
    tags = soup.find_all(attrs={"itemprop": True})
    if not tags:
        return None

    produto: dict[str, Any] = {}
    oferta: dict[str, Any] = {}
    imagens: list[str] = []
    for tag in tags:
        prop = str(tag.get("itemprop") or "").strip()
        if prop not in _ITEMPROPS:
            continue
        valor = _valor_itemprop(tag)
        if not valor:
            continue
        if prop == "image":
            imagens.append(valor)
        elif prop in _OFFER_PROPS:
            oferta.setdefault(prop, valor)
        elif prop == "productID":
            produto.setdefault("sku", valor)
            produto.setdefault("productID", valor)
        else:
            produto.setdefault(prop, valor)

    if not produto.get("name") or oferta.get("price") is None:
        return None
    # em página de categoria da Tray, o primeiro itemprop="name" é o de um
    # produto da listagem; só aceitamos se bater com o título da página
    titulos, _ = identidade(html)
    if titulos and not _e_da_pagina(produto, titulos, ""):
        return None
    if imagens:
        produto["image"] = list(dict.fromkeys(imagens))
    produto["offers"] = oferta
    produto["@type"] = "Product"
    produto["_fonte"] = "microdata"
    return produto


def from_opengraph(html: str) -> dict[str, Any] | None:
    """Último recurso: og:title + og:image + product:price:amount."""
    soup = BeautifulSoup(html, "lxml")
    meta: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        chave = (tag.get("property") or tag.get("name") or "").strip().lower()
        if chave and (conteudo := tag.get("content")):
            meta.setdefault(chave, str(conteudo).strip())

    nome = meta.get("og:title")
    preco = meta.get("product:price:amount") or meta.get("og:price:amount")
    if not nome:
        return None
    produto: dict[str, Any] = {
        "@type": "Product",
        "name": nome,
        "description": meta.get("og:description") or meta.get("description"),
        "_fonte": "opengraph",
    }
    if imagem := meta.get("og:image"):
        produto["image"] = [imagem]
    if preco:
        produto["offers"] = {
            "price": preco,
            "priceCurrency": meta.get("product:price:currency") or "BRL",
            "availability": meta.get("product:availability"),
        }
    return produto


def extract_product(html: str) -> dict[str, Any] | None:
    """Nuvemshop, JSON-LD, microdata e Open Graph, nessa ordem de confiabilidade."""
    for extrator in (from_nuvemshop, find_product, from_microdata, from_opengraph):
        if (produto := extrator(html)):
            produto.setdefault("_fonte", "jsonld")
            return produto
    return None
