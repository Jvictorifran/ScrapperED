"""Classificação dos produtos por palavras-chave (regras em categorias.yaml).

A classificação é derivada do catálogo e não da coleta: fica numa tabela
própria, recalculada por inteiro a cada execução. Assim, mudar uma palavra-chave
não exige raspar as lojas de novo — só `scraper classificar`.
"""
from __future__ import annotations

import html
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def normalizar(texto: Any) -> str:
    """Sem acento, minúsculo, pontuação vira espaço. "Pré-Treino®" -> "pre treino"."""
    t = unicodedata.normalize("NFKD", html.unescape(str(texto or "")))
    t = "".join(c for c in t if not unicodedata.combining(c)).casefold()
    # "%" fica: sem ele, "100% Whey" vira "100 whey" e o 100 parece contagem
    t = re.sub(r"[^a-z0-9.,%]+", " ", t)
    # "1.8 kg" e "2,5kg" seguem legíveis para o peso; ponto/vírgula soltos somem
    t = re.sub(r"(?<!\d)[.,]|[.,](?!\d)", " ", t)
    return " ".join(t.split())


def _compilar(termos: list[str]) -> re.Pattern[str] | None:
    if not termos:
        return None
    return re.compile(r"\b(?:" + "|".join(f"(?:{t})" for t in termos) + r")\b")


@dataclass
class Categoria:
    nome: str
    grupo: str
    prioridade: bool
    termos: re.Pattern[str]
    exceto: re.Pattern[str] | None


@dataclass
class Resultado:
    categoria: str | None
    grupo: str | None
    kit: bool
    fonte: str | None    # nome | categoria_loja | descricao | ingredientes
    termo: str | None    # o trecho que casou, para auditar a regra
    peso_g: float | None
    capsulas: int | None


class Classificador:
    def __init__(self, path: str | Path = "categorias.yaml"):
        cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        self.kit = _compilar((cfg.get("kit") or {}).get("termos") or [])
        self.categorias = [
            Categoria(
                nome=nome,
                grupo=c["grupo"],
                prioridade=bool(c.get("prioridade")),
                termos=_compilar(c["termos"]),
                exceto=_compilar(c.get("exceto") or []),
            )
            for nome, c in (cfg.get("categorias") or {}).items()
        ]

    def _categoria(self, texto: str) -> tuple[Categoria, str] | None:
        achados: list[tuple[bool, int, int, Categoria, str]] = []
        for ordem, cat in enumerate(self.categorias):
            if cat.exceto and cat.exceto.search(texto):
                continue
            if m := cat.termos.search(texto):
                # prioridade primeiro, depois posição no texto, depois ordem no yaml
                achados.append((not cat.prioridade, m.start(), ordem, cat, m.group(0)))
        if not achados:
            return None
        _, _, _, cat, termo = min(achados, key=lambda a: a[:3])
        return cat, termo

    def classificar(self, nome: str, marca: str = "", categorias_loja: list[str] | None = None,
                    descricao: str | None = None, ingredientes: str | None = None) -> Resultado:
        nome_n = normalizar(nome)
        # o nome costuma terminar com a marca ("... - FTW Suplementos"), e a
        # marca não diz o que o produto é
        if marca and (marca_n := normalizar(marca)):
            nome_n = re.sub(rf"\b{re.escape(marca_n)}\b", " ", nome_n)

        fontes = [
            ("nome", nome_n),
            ("categoria_loja", normalizar(" | ".join(categorias_loja or []))),
            # só o começo: o fim da descrição costuma ser modo de uso e avisos
            ("descricao", normalizar((descricao or "")[:300])),
            # a rotulagem lista ingredientes em ordem decrescente de quantidade:
            # o começo da lista diz do que o produto é feito
            ("ingredientes", normalizar((ingredientes or "")[:120])),
        ]
        categoria = grupo = fonte = termo = None
        for origem, texto in fontes:
            if texto and (achado := self._categoria(texto)):
                cat, termo = achado
                categoria, grupo, fonte = cat.nome, cat.grupo, origem
                break

        kit = bool(self.kit and self.kit.search(nome_n))
        return Resultado(
            categoria=categoria,
            grupo=grupo,
            kit=kit,
            fonte=fonte,
            termo=termo,
            # kit ou "A + B" junta itens diferentes: não há um peso que sirva
            # para preço/kg ("Whey 900 + Pre Workout 300G" dava 300 g)
            peso_g=None if kit or "+" in (nome or "") else peso_em_gramas(nome_n),
            capsulas=capsulas(nome_n),
        )


# --- quantidade -------------------------------------------------------------

_PESO_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(kg|g|gr|grs|gramas|lbs?)\b"
    # "15g de proteína", "18g carbo" é composição por porção, não peso
    r"(?!\s*(?:de\s*)?(?:proteinas?|carbo\w*|cafeina|fibras?|acucar))")
_CONTAGEM_RE = re.compile(
    r"\b(?:c|com|cx|caixa|display|pack)\s*(?:com\s*|de\s*|c\s*)?(\d{1,3})\b(?!\s*%)"
    r"|\b(\d{1,3})\s*(?:un|und|unid\w*|saches|sache|barras?|sticks?|doses|wafers|sachets?)\b")
_CAPS_RE = re.compile(r"\b(\d{1,4})\s*(?:capsulas?|caps|comprimidos?|softgels?|tabletes?|tabs)\b")
_FATOR = {"kg": 1000.0, "lb": 453.592, "lbs": 453.592}


def peso_em_gramas(nome_n: str) -> float | None:
    """Peso total declarado no nome, em gramas.

    "Display c/12 Barras 40g" -> 480: quando há uma contagem e um peso
    unitário pequeno, multiplica. É uma heurística — serve para preço por
    quilo, não para rotular. Retorna None quando há pesos diferentes no nome
    (kits com itens distintos).
    """
    pesos = [float(v.replace(",", ".")) * _FATOR.get(u, 1.0) for v, u in _PESO_RE.findall(nome_n)]
    if not pesos:
        return None
    if len(set(pesos)) > 1:
        # "Display de 105g com 14 Unidades de 7,5g" — o maior é o total
        maior, menor = max(pesos), min(pesos)
        contagem = _contagem(nome_n)
        if contagem and abs(contagem * menor - maior) <= maior * 0.05:
            return maior
        return None
    peso = pesos[0]
    contagem = _contagem(nome_n)
    if contagem and contagem > 1 and peso <= 120:
        return round(peso * contagem, 1)
    return peso


def _contagem(nome_n: str) -> int | None:
    if m := _CONTAGEM_RE.search(nome_n):
        return int(m.group(1) or m.group(2))
    return None


def capsulas(nome_n: str) -> int | None:
    if m := _CAPS_RE.search(nome_n):
        return int(m.group(1))
    return None


def reclassificar(conn, classificador: Classificador) -> int:
    """Recalcula a tabela `classificacao` inteira a partir de `products`."""
    linhas = conn.execute(
        "SELECT id, name, brand, categories, description_text, ingredients FROM products"
    ).fetchall()
    registros = []
    for r in linhas:
        res = classificador.classificar(
            r["name"], r["brand"], json.loads(r["categories"] or "[]"), r["description_text"],
            r["ingredients"])
        registros.append((r["id"], res.categoria, res.grupo, int(res.kit), res.fonte,
                          res.termo, res.peso_g, res.capsulas))
    conn.execute("DELETE FROM classificacao")
    conn.executemany(
        "INSERT INTO classificacao (product_id, categoria, grupo, kit, fonte, termo, peso_g, capsulas)"
        " VALUES (?,?,?,?,?,?,?,?)", registros)
    conn.commit()
    return len(registros)
