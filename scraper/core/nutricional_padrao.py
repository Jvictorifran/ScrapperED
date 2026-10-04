"""Tabela nutricional padronizada: um valor numérico por nutriente, na mesma
unidade para todos os produtos.

As lojas escrevem a mesma coisa de vários jeitos — "Proteínas (g)" / "proteínas",
"5.000" (cinco mil) / "1,65mg" / "12" com a unidade só no nome. Aqui isso vira
`{"proteinas_g": 21.0, ...}`, comparável entre produtos.

Só os nutrientes obrigatórios do rótulo (RDC 429/2020 da Anvisa) ganham coluna
própria; o resto (creatina, vitaminas, cafeína...) vai para `outros`, como a
loja escreveu. Valores são **por porção**, que é o que a tabela publica.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from .nutrition import achar_porcao

# chave -> (padrão no nome normalizado, unidade de destino)
CAMPOS: dict[str, tuple[re.Pattern[str], str]] = {
    "energia_kcal": (re.compile(r"^valor energetico|^energia"), "kcal"),
    "carboidratos_g": (re.compile(r"^carboidratos?\b(?! *de)"), "g"),
    "acucares_totais_g": (re.compile(r"^acucares? totais"), "g"),
    "acucares_adicionados_g": (re.compile(r"^acucares? adicionados"), "g"),
    "proteinas_g": (re.compile(r"^proteinas?\b"), "g"),
    "gorduras_totais_g": (re.compile(r"^gorduras? totais"), "g"),
    "gorduras_saturadas_g": (re.compile(r"^gorduras? saturadas"), "g"),
    "gorduras_trans_g": (re.compile(r"^gorduras? trans"), "g"),
    "fibras_g": (re.compile(r"^fibras?\b"), "g"),
    "sodio_mg": (re.compile(r"^sodio"), "mg"),
}

# quanto vale 1 unidade em gramas (massa) ou kcal (energia)
_MASSA = {"g": 1.0, "mg": 1e-3, "mcg": 1e-6, "ug": 1e-6}
_ENERGIA = {"kcal": 1.0, "kj": 1 / 4.184}

_UNIDADE_RE = re.compile(r"(kcal|kj|mcg|µg|μg|ug|mg|g)\b", re.I)
_NUMERO_RE = re.compile(r"\d[\d.,]*")


def _sem_acento(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in t if not unicodedata.combining(c)).casefold().strip()


def numero(texto: str) -> float | None:
    """Número no formato brasileiro, com as ambiguidades do mundo real.

    "1,65" -> 1.65; "5.000" -> 5000 (ponto com três dígitos depois é milhar);
    "1.5" -> 1.5; "1.234,5" -> 1234.5.
    """
    if not (m := _NUMERO_RE.search(texto)):
        return None
    s = m.group(0).rstrip(".,")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def _unidade(texto: str) -> str | None:
    if m := _UNIDADE_RE.search(texto):
        u = m.group(1).casefold()
        return "ug" if u in ("µg", "μg", "mcg") else u
    return None


def _converter(valor: float, de: str | None, para: str) -> float | None:
    if de is None or de == para:
        return valor
    for tabela in (_MASSA, _ENERGIA):
        if de in tabela and para in tabela:
            return valor * tabela[de] / tabela[para]
    return None  # unidade incompatível (ex: "%" num campo de massa)


def _quantidade(nome: str, quantidade: str, destino: str) -> float | None:
    texto = quantidade.strip()
    if not texto or texto in {"-", "—", "–"}:
        return None
    if destino == "kcal":
        # "125kcal = 523kJ": prefere o trecho em kcal
        if m := re.search(r"(\d[\d.,]*)\s*kcal", texto, re.I):
            return numero(m.group(1))
    valor = numero(texto)
    if valor is None:
        return None
    # a unidade vem da quantidade ("21g") ou, se não houver, do nome ("Proteínas (g)")
    unidade = _unidade(texto) or _unidade(re.sub(r"^[^(]*", "", nome))
    convertido = _converter(valor, unidade, destino)
    return round(convertido, 3) if convertido is not None else None


def porcao_em_gramas(porcao: str | None) -> float | None:
    """ "40g (2 medidas dosadoras)" -> 40; "Porção de 5 g (1 scoop)" -> 5."""
    if not porcao:
        return None
    if m := re.search(r"(\d[\d.,]*)\s*g\b", porcao, re.I):
        return numero(m.group(1))
    return None


_PORCAO_TEXTO_RE = re.compile(r"por[çc][ãa]o\s*(?:de|:)?\s*\(?\s*(\d[\d.,]*)\s*g\b", re.I)


def _porcao_no_texto(texto: str | None) -> float | None:
    """ "Por porção (30g)" no texto da tabela, quando o campo porção veio vazio."""
    if texto and (m := achar_porcao(texto, _PORCAO_TEXTO_RE)):
        return numero(m.group(1))
    return None


def _inconsistencia(v: dict[str, Any], porcao: float | None) -> str | None:
    """Checagem física: o que a porção não comporta não pode ser verdade.

    1 g de gordura tem 9 kcal, o máximo possível; e proteína + carboidrato +
    gordura não pesam mais que a porção. Folga de 10% para arredondamento.
    """
    if not porcao:
        return None
    if v["energia_kcal"] is not None and v["energia_kcal"] > porcao * 9 * 1.1 + 1:
        return f"{v['energia_kcal']:g} kcal não cabem em {porcao:g} g"
    macros = sum(v[k] or 0 for k in ("proteinas_g", "carboidratos_g", "gorduras_totais_g"))
    if macros > porcao * 1.1 + 0.5:
        return f"{macros:g} g de macronutrientes não cabem em {porcao:g} g"
    # acima de 95% de proteína sem valor energético (obrigatório na tabela da
    # Anvisa): não é tabela, é "proteína por porção: 12g" de marketing lido como
    # porção e proteína ao mesmo tempo. Com tabela de verdade, 100% existe:
    # aminoácido puro (Glutamine New Millen declara 5 g de proteína em 5 g).
    if (v["proteinas_g"] and porcao >= 5 and v["proteinas_g"] > porcao * 0.95
            and v["energia_kcal"] is None):
        return f"{v['proteinas_g']:g} g de proteína em {porcao:g} g de porção (mais de 95%)"
    return None


def padronizar(nutrition: dict[str, Any] | None) -> dict[str, Any] | None:
    """Tabela da loja -> valores numéricos por porção. None se não há tabela."""
    itens = (nutrition or {}).get("itens") or []
    if not itens:
        return None

    saida: dict[str, Any] = {chave: None for chave in CAMPOS}
    outros: list[str] = []
    for item in itens:
        nome = str(item.get("nutriente") or "").strip()
        quantidade = str(item.get("quantidade") or "").strip()
        if not nome:
            continue
        nome_n = _sem_acento(nome)
        for chave, (padrao, unidade) in CAMPOS.items():
            if padrao.search(nome_n):
                # tabelas com vários sabores repetem os nutrientes: vale a primeira
                if saida[chave] is None:
                    saida[chave] = _quantidade(nome, quantidade, unidade)
                break
        else:
            if quantidade and quantidade not in {"-", "—", "–", "0"}:
                outros.append(f"{nome}: {quantidade}")

    porcao = porcao_em_gramas(nutrition.get("porcao")) or _porcao_no_texto(nutrition.get("texto_bruto"))
    motivo = _inconsistencia(saida, porcao)
    if motivo:
        # números que não cabem na porção vêm de tabela misturada (outro produto
        # na mesma página) ou de coluna errada: melhor vazio do que errado
        for chave in CAMPOS:
            saida[chave] = None
    proteina = saida["proteinas_g"]
    saida.update(
        porcao_g=porcao,
        inconsistente=motivo,
        # concentração de proteína: o número que separa um whey de outro
        proteina_pct=round(proteina / porcao * 100, 1) if proteina is not None and porcao else None,
        outros="; ".join(dict.fromkeys(outros)) or None,
    )
    return saida
