"""Regressões da identificação do produto da página (core/jsonld.py).

Rodar com:  ./.venv/bin/python -m unittest discover tests
"""
import json
import unittest
from html import escape

from scraper.core.jsonld import extract_product, find_product
from scraper.core.models import Produto


def _ld(obj: dict) -> str:
    return f'<script type="application/ld+json">{json.dumps(obj)}</script>'


def _produto_ld(nome: str, preco: float, url: str | None = None) -> dict:
    obj = {"@type": "Product", "name": nome, "sku": nome[:3],
           "offers": {"price": preco, "availability": "InStock"}}
    if url:
        obj["url"] = url
    return obj


class CarrosselNaoEhOProduto(unittest.TestCase):
    """Dux: seis Product de recomendados em JSON-LD e nenhum é o da página."""

    HTML = (
        '<html><head><title>Bcaa Powder - Pote 200g - Comprar em Dux</title>'
        '<meta property="og:title" content="Bcaa Powder - Pote 200g">'
        '<link rel="canonical" href="https://dux.com/produtos/bcaa-powder/"></head>'
        '<body><h1>Bcaa Powder - Pote 200g</h1>'
        + _ld(_produto_ld("Creatina Monohidratada - Pote 300g", 89.9))
        + _ld(_produto_ld("Whey Protein Isolado - Pote 900g", 199.9))
        + "</body></html>"
    )

    def test_json_ld_rejeita_produtos_alheios(self):
        self.assertIsNone(find_product(self.HTML))

    def test_escolhe_o_que_bate_com_o_titulo(self):
        html = self.HTML.replace("</body>", _ld(_produto_ld("Bcaa Powder - Pote 200g", 105.9)) + "</body>")
        self.assertEqual(find_product(html)["name"], "Bcaa Powder - Pote 200g")

    def test_escolhe_o_que_bate_com_a_url_canonica(self):
        html = self.HTML.replace("</body>", _ld(_produto_ld("BCAA 200g", 105.9, "https://dux.com/produtos/bcaa-powder")) + "</body>")
        self.assertEqual(find_product(html)["name"], "BCAA 200g")


class Nuvemshop(unittest.TestCase):
    VARIANTES = [
        {"product_id": 1, "id": 10, "price_number": 105.9, "compare_at_price_number": 113.9,
         "available": True, "sku": "410103002", "image_url": "//cdn/bcaa.avif"},
        {"product_id": 1, "id": 11, "price_number": 99.9, "compare_at_price_number": 113.9,
         "available": False, "sku": "410103003"},
    ]
    RECOMENDADO = [{"product_id": 2, "id": 20, "price_number": 9.9, "available": True}]

    def html(self) -> str:
        return (
            "<html><head><title>Bcaa</title></head><body>"
            "<script>LS.product = {\n id : 1,\n name : 'Bcaa\\u0020Powder\\u0020\\u002D\\u0020Pote',\n brand: ''};</script>"
            f'<div data-variants="{escape(json.dumps(self.RECOMENDADO))}"></div>'
            f'<div data-variants="{escape(json.dumps(self.VARIANTES))}"></div>'
            + _ld(_produto_ld("Creatina Monohidratada - Pote 300g", 89.9))
            + "</body></html>"
        )

    def test_le_ls_product_e_ignora_variantes_de_outros_produtos(self):
        p = extract_product(self.html())
        self.assertEqual(p["_fonte"], "nuvemshop")
        self.assertEqual(p["name"], "Bcaa Powder - Pote")
        self.assertEqual(p["productID"], "1")
        self.assertEqual({o["price"] for o in p["offers"]}, {105.9, 99.9})
        self.assertIn("https://cdn/bcaa.avif", p["image"])


class MicrodataDeCategoria(unittest.TestCase):
    """Tray (Nutrata): página de categoria tem itemprop="name" dos produtos listados."""

    def pagina(self, h1: str) -> str:
        return (
            f"<html><head><title>{h1} - Nutrata</title></head><body><h1>{h1}</h1>"
            '<div itemscope itemtype="http://schema.org/Product">'
            '<span itemprop="name">Nutrata Caixa Mista - Display c/8 und</span>'
            '<meta itemprop="price" content="120.00"></div></body></html>'
        )

    def test_categoria_nao_vira_produto(self):
        self.assertIsNone(extract_product(self.pagina("BARRA DE PROTEÍNA")))

    def test_pagina_do_produto_continua_aceita(self):
        p = extract_product(self.pagina("Nutrata Caixa Mista - Display c/8 und"))
        self.assertEqual(p["_fonte"], "microdata")


class ProdutoUnico(unittest.TestCase):
    def test_aceito_mesmo_com_h1_diferente(self):
        html = "<html><body><h1>Nome curto</h1>" + _ld(_produto_ld("Nome completo do produto 900g", 50)) + "</body></html>"
        self.assertIsNotNone(find_product(html))


class NomeComEntidade(unittest.TestCase):
    def test_entidade_html_decodificada(self):
        p = Produto(site="x", brand="X", url="u", name="Camiseta &#8211; Tam G")
        self.assertEqual(p.name, "Camiseta – Tam G")


if __name__ == "__main__":
    unittest.main()
