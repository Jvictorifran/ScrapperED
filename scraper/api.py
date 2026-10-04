"""API HTTP de leitura do catálogo, consumida pelo sistema Laravel (web/).

    ./.venv/bin/uvicorn scraper.api:app --port 8001

Só lê: o banco é aberto em modo somente leitura, quem escreve é o scraper.
A documentação interativa fica em http://localhost:8001/docs.
"""
from __future__ import annotations

import json
import os
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator

from fastapi import Depends, FastAPI, HTTPException, Query

from .core.classify import normalizar
from .core.nutricional_padrao import padronizar

DB_PATH = os.environ.get("SCRAPER_DB", "data/produtos.sqlite3")

# `nutrition` também guarda modo de uso e alergênicos sem tabela nenhuma:
# "tem nutricional" é ter linhas na tabela
TEM_TABELA = "COALESCE(json_array_length(json_extract(nutrition, '$.itens')), 0) > 0"

app = FastAPI(
    title="Catálogo de suplementos",
    description="Produtos coletados de lojas brasileiras de suplementos.",
    version="1.0",
)

# grupo "escopo" = o foco do TCC
ESCOPO = ("proteina", "suplemento")
# o banco inteiro tem ~3.600 produtos; o teto só evita resposta gigante se crescer
LIMITE_EXPORTACAO = 10_000
ORDENS = {
    "nome": "name",
    "preco": "price",
    "preco_kg": "preco_por_kg",
    "loja": "site",
}


def conexao() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # busca sem acento e sem maiúscula: "proteina" acha "Proteína"
    conn.create_function("norm", 1, normalizar, deterministic=True)
    try:
        yield conn
    finally:
        conn.close()


def _json(valor: str | None, padrao: Any) -> Any:
    if not valor:
        return padrao
    try:
        return json.loads(valor)
    except json.JSONDecodeError:
        return padrao


def _item(r: sqlite3.Row) -> dict[str, Any]:
    nutri = _json(r["nutrition"], {})
    return {
        "id": r["id"],
        "loja": r["site"],
        "marca": r["brand"],
        "nome": r["name"],
        "grupo": r["grupo"],
        "categoria": r["categoria"],
        "kit": bool(r["kit"]),
        "preco": r["price"],
        "preco_de": r["list_price"],
        "disponivel": {"sim": True, "nao": False}.get(r["disponivel"]),
        "peso_g": r["peso_g"],
        "preco_por_kg": r["preco_por_kg"],
        "ean": r["ean"],
        "tem_ingredientes": bool(r["ingredients"]),
        "tem_nutricional": bool(nutri.get("itens")),
        "url": r["url"],
        "atualizado_em": r["last_seen_at"],
    }


@app.get("/resumo", summary="Totais gerais e por loja")
def resumo(conn: sqlite3.Connection = Depends(conexao)) -> dict[str, Any]:
    grupos = {r["grupo"] or "sem_grupo": r["n"] for r in conn.execute(
        "SELECT grupo, COUNT(*) n FROM v_catalogo GROUP BY grupo")}
    lojas = [dict(r) for r in conn.execute(
        f"""
        SELECT site AS loja, brand AS marca, COUNT(*) AS produtos,
               SUM(grupo IN ('proteina','suplemento')) AS no_escopo,
               SUM(ean IS NOT NULL) AS com_ean,
               SUM(ingredients IS NOT NULL) AS com_ingredientes,
               SUM({TEM_TABELA}) AS com_nutricional,
               ROUND(AVG(price), 2) AS preco_medio,
               MAX(last_seen_at) AS atualizado_em
        FROM v_catalogo GROUP BY site ORDER BY produtos DESC
        """)]
    ultima = conn.execute(
        "SELECT id, started_at, finished_at, n_products FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    return {
        "total": sum(grupos.values()),
        "no_escopo": sum(grupos.get(g, 0) for g in ESCOPO),
        "por_grupo": grupos,
        "lojas": lojas,
        "ultima_coleta": dict(ultima) if ultima else None,
    }


@app.get("/lojas", summary="Lojas com produtos no banco")
def lojas(conn: sqlite3.Connection = Depends(conexao)) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT site AS loja, brand AS marca, COUNT(*) AS produtos FROM v_catalogo"
        " GROUP BY site ORDER BY brand")]


@app.get("/categorias", summary="Categorias da classificação, com contagem")
def categorias(conn: sqlite3.Connection = Depends(conexao)) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT grupo, categoria, COUNT(*) AS produtos FROM v_catalogo"
        " WHERE categoria IS NOT NULL GROUP BY grupo, categoria ORDER BY grupo, produtos DESC")]


@dataclass
class Filtros:
    """Filtros da listagem. Os mesmos para /produtos e /exportacao, para o
    arquivo exportado conter exatamente o que a tela mostra."""

    q: str | None = Query(None, description="busca no nome, sem acento")
    loja: str | None = Query(None, description="chave da loja (ex: vitafor)")
    grupo: str | None = Query(None, description="proteina, suplemento, alimento, fora ou 'escopo'")
    categoria: str | None = None
    preco_min: float | None = None
    preco_max: float | None = None
    disponivel: bool | None = None
    com_nutricional: bool | None = None
    ordem: str = Query("nome", enum=list(ORDENS))
    direcao: str = Query("asc", enum=["asc", "desc"])

    def where(self) -> tuple[str, list[Any]]:
        partes: list[str] = []
        args: list[Any] = []
        if self.q and (termo := normalizar(self.q)):
            partes.append("norm(v.name) LIKE ?")
            args.append(f"%{termo}%")
        if self.loja:
            partes.append("v.site = ?")
            args.append(self.loja)
        if self.grupo == "escopo":
            partes.append(f"v.grupo IN ({','.join('?' * len(ESCOPO))})")
            args.extend(ESCOPO)
        elif self.grupo:
            partes.append("v.grupo = ?")
            args.append(self.grupo)
        if self.categoria:
            partes.append("v.categoria = ?")
            args.append(self.categoria)
        if self.preco_min is not None:
            partes.append("v.price >= ?")
            args.append(self.preco_min)
        if self.preco_max is not None:
            partes.append("v.price <= ?")
            args.append(self.preco_max)
        if self.disponivel is not None:
            partes.append("v.disponivel = ?")
            args.append("sim" if self.disponivel else "nao")
        if self.com_nutricional is not None:
            tabela = TEM_TABELA.replace("nutrition", "v.nutrition")
            partes.append(tabela if self.com_nutricional else f"NOT ({tabela})")
        return (f"WHERE {' AND '.join(partes)}" if partes else ""), args

    def order_by(self) -> str:
        # nulos sempre por último, em qualquer direção
        coluna = f"v.{ORDENS[self.ordem]}"
        return f"ORDER BY {coluna} IS NULL, {coluna} {self.direcao.upper()}, v.name"


# produto completo: a view + o que só existe em products/classificacao
SELECT_COMPLETO = """
    SELECT v.*, p.external_id, p.images, p.description_text, p.first_seen_at,
           c.termo, c.capsulas
    FROM v_catalogo v
    JOIN products p ON p.id = v.id
    LEFT JOIN classificacao c ON c.product_id = v.id
"""


def _completo(r: sqlite3.Row, precos: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    item = {
        **_item(r),
        "sku": r["sku"],
        "id_na_loja": r["external_id"],
        "categorias_loja": _json(r["categories"], []),
        "imagens": _json(r["images"], []),
        "descricao": r["description_text"],
        "ingredientes": r["ingredients"],
        "nutricional": _json(r["nutrition"], {}),
        # mesmos números, numéricos e na mesma unidade para todos os produtos
        "nutricional_padrao": padronizar(_json(r["nutrition"], {})),
        "classificacao": {
            "fonte": r["classificacao_fonte"],
            "termo": r["termo"],
            "capsulas": r["capsulas"],
        } if r["categoria"] else None,
        "visto_primeiro_em": r["first_seen_at"],
    }
    if precos is not None:
        item["precos"] = precos
    return item


def _historico(conn: sqlite3.Connection, ids_sql: str, args: list[Any]) -> dict[int, list[dict[str, Any]]]:
    """Histórico de preço de vários produtos numa consulta só."""
    por_produto: dict[int, list[dict[str, Any]]] = {}
    for h in conn.execute(
        f"""
        SELECT product_id, run_id AS coleta, scraped_at AS data, price AS preco,
               list_price AS preco_de, available AS disponivel
        FROM price_history WHERE product_id IN ({ids_sql}) ORDER BY scraped_at
        """, args,
    ):
        linha = dict(h)
        por_produto.setdefault(linha.pop("product_id"), []).append(linha)
    return por_produto


@app.get("/produtos", summary="Lista filtrável e paginada")
def produtos(
    filtros: Filtros = Depends(),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(50, ge=1, le=200),
    conn: sqlite3.Connection = Depends(conexao),
) -> dict[str, Any]:
    where, args = filtros.where()
    total = conn.execute(f"SELECT COUNT(*) FROM v_catalogo v {where}", args).fetchone()[0]
    linhas = conn.execute(
        f"SELECT * FROM v_catalogo v {where} {filtros.order_by()} LIMIT ? OFFSET ?",
        [*args, por_pagina, (pagina - 1) * por_pagina],
    ).fetchall()
    return {
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "paginas": max(1, -(-total // por_pagina)),
        "itens": [_item(r) for r in linhas],
    }


@app.get("/exportacao", summary="Todos os produtos do filtro, completos, sem paginação")
def exportacao(
    filtros: Filtros = Depends(),
    conn: sqlite3.Connection = Depends(conexao),
) -> dict[str, Any]:
    """Para exportar: cada item vem como no detalhe (ingredientes, tabela
    nutricional, imagens) e com o histórico de preço."""
    where, args = filtros.where()
    linhas = conn.execute(f"{SELECT_COMPLETO} {where} {filtros.order_by()} LIMIT ?",
                          [*args, LIMITE_EXPORTACAO + 1]).fetchall()
    if len(linhas) > LIMITE_EXPORTACAO:
        raise HTTPException(413, f"o filtro tem mais de {LIMITE_EXPORTACAO} produtos; refine a busca")
    historico = _historico(conn, f"SELECT v.id FROM v_catalogo v {where}", args)
    return {
        "total": len(linhas),
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "itens": [_completo(r, historico.get(r["id"], [])) for r in linhas],
    }


@app.get("/produtos/{produto_id}", summary="Detalhe com ingredientes e tabela nutricional")
def produto(produto_id: int, conn: sqlite3.Connection = Depends(conexao)) -> dict[str, Any]:
    r = conn.execute(f"{SELECT_COMPLETO} WHERE v.id = ?", (produto_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "produto não encontrado")
    return _completo(r)


@app.get("/produtos/{produto_id}/precos", summary="Histórico de preço por coleta")
def precos(produto_id: int, conn: sqlite3.Connection = Depends(conexao)) -> list[dict[str, Any]]:
    if not conn.execute("SELECT 1 FROM products WHERE id = ?", (produto_id,)).fetchone():
        raise HTTPException(404, "produto não encontrado")
    return _historico(conn, "?", [produto_id]).get(produto_id, [])


@app.get("/comparativo", summary="R$/kg mediano por loja numa categoria")
def comparativo(
    categoria: str = "whey",
    peso_min: float = Query(400, description="ignora embalagens menores (sachês, amostras)"),
    conn: sqlite3.Connection = Depends(conexao),
) -> dict[str, Any]:
    """Mediana e não média: o peso vem do nome e sobram outliers (caixa com o
    peso de uma unidade), que a média deixaria arrastar."""
    por_loja: dict[str, list[float]] = {}
    marcas: dict[str, str] = {}
    for r in conn.execute(
        "SELECT site, brand, preco_por_kg FROM v_catalogo"
        " WHERE categoria = ? AND kit = 0 AND peso_g >= ? AND preco_por_kg IS NOT NULL",
        (categoria, peso_min),
    ):
        por_loja.setdefault(r["site"], []).append(r["preco_por_kg"])
        marcas[r["site"]] = r["brand"]
    lojas = sorted(
        ({"loja": s, "marca": marcas[s], "produtos": len(v), "mediana": round(statistics.median(v), 2),
          "minimo": round(min(v), 2), "maximo": round(max(v), 2)} for s, v in por_loja.items()),
        key=lambda x: x["mediana"],
    )
    return {"categoria": categoria, "peso_min": peso_min, "lojas": lojas}
