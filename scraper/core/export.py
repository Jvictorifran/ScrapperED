"""Exportação do banco para CSV e JSON, para análise fora do SQLite."""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

COLUNAS = [
    "site", "brand", "name", "grupo", "categoria", "kit", "classificacao_fonte",
    "peso_g", "preco_por_kg", "ean", "sku", "price", "list_price", "disponivel",
    "categories", "porcao", "nutrientes", "origem_nutricional", "ingredients",
    "url", "last_seen_at",
]


def _linha_plana(r: sqlite3.Row) -> dict[str, object]:
    nutri = json.loads(r["nutrition"]) if r["nutrition"] else {}
    itens = nutri.get("itens") or []
    return {
        "site": r["site"],
        "brand": r["brand"],
        "name": r["name"],
        "grupo": r["grupo"] or "",
        "categoria": r["categoria"] or "",
        "kit": "sim" if r["kit"] else "nao",
        "classificacao_fonte": r["classificacao_fonte"] or "",
        "peso_g": r["peso_g"] if r["peso_g"] is not None else "",
        "preco_por_kg": r["preco_por_kg"] if r["preco_por_kg"] is not None else "",
        "ean": r["ean"] or "",
        "sku": r["sku"] or "",
        "price": r["price"] if r["price"] is not None else "",
        "list_price": r["list_price"] if r["list_price"] is not None else "",
        "disponivel": r["disponivel"] or "",
        "categories": " | ".join(json.loads(r["categories"] or "[]")),
        "porcao": nutri.get("porcao") or "",
        # a tabela nutricional vira "nutriente=quantidade" numa única célula,
        # para caber em planilha sem perder a informação
        "nutrientes": "; ".join(
            f"{i.get('nutriente')}={i.get('quantidade','')}" for i in itens
        ),
        "origem_nutricional": nutri.get("origem") or "",
        "ingredients": (r["ingredients"] or "").replace("\n", " "),
        "url": r["url"],
        "last_seen_at": r["last_seen_at"],
    }


def para_csv(db_path: str | Path, destino: str | Path) -> int:
    """Exporta a última foto de cada produto para um CSV único."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    linhas = conn.execute(
        "SELECT * FROM v_catalogo ORDER BY site, name"
    ).fetchall()
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUNAS)
        w.writeheader()
        for r in linhas:
            w.writerow(_linha_plana(r))
    conn.close()
    return len(linhas)


def para_json(db_path: str | Path, destino: str | Path) -> int:
    """Exporta tudo em JSON, preservando a estrutura do nutricional."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    linhas = conn.execute(
        """
        SELECT p.*, h.price, h.list_price, h.available,
               c.grupo, c.categoria, c.kit, c.fonte AS classificacao_fonte,
               c.peso_g, c.capsulas
        FROM products p
        LEFT JOIN price_history h
               ON h.product_id = p.id AND h.run_id = p.last_seen_run
        LEFT JOIN classificacao c ON c.product_id = p.id
        ORDER BY p.site, p.name
        """
    ).fetchall()
    saida = []
    for r in linhas:
        item = dict(r)
        for campo in ("categories", "images", "nutrition"):
            if item.get(campo):
                try:
                    item[campo] = json.loads(item[campo])
                except (TypeError, json.JSONDecodeError):
                    pass
        saida.append(item)
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    conn.close()
    return len(saida)
