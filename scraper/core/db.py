"""Persistência em SQLite com histórico de coletas.

Três tabelas:
  runs          — uma linha por execução do scraper
  products      — catálogo deduplicado por (site, url); guarda o conteúdo atual
  price_history — preço/disponibilidade por produto em cada run

Assim o catálogo não duplica entre coletas, mas a série de preços fica preservada
para análise temporal.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import Produto

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    sites       TEXT,
    n_products  INTEGER DEFAULT 0,
    n_errors    INTEGER DEFAULT 0,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS products (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    site             TEXT NOT NULL,
    brand            TEXT NOT NULL,
    url              TEXT NOT NULL,
    name             TEXT NOT NULL,
    external_id      TEXT,
    sku              TEXT,
    ean              TEXT,
    categories       TEXT,   -- JSON array
    images           TEXT,   -- JSON array
    description_html TEXT,
    description_text TEXT,
    ingredients      TEXT,
    nutrition        TEXT,   -- JSON object
    first_seen_run   INTEGER REFERENCES runs(id),
    last_seen_run    INTEGER REFERENCES runs(id),
    first_seen_at    TEXT,
    last_seen_at     TEXT,
    UNIQUE (site, url)
);

CREATE INDEX IF NOT EXISTS idx_products_site  ON products(site);
CREATE INDEX IF NOT EXISTS idx_products_ean   ON products(ean) WHERE ean IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand);

CREATE TABLE IF NOT EXISTS price_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    run_id     INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    price      REAL,
    list_price REAL,
    available  INTEGER,
    scraped_at TEXT NOT NULL,
    UNIQUE (product_id, run_id)
);

CREATE INDEX IF NOT EXISTS idx_price_product ON price_history(product_id);

-- Classificação por palavra-chave (categorias.yaml). Derivada de products e
-- recalculada por inteiro: mudar uma regra não exige recoletar.
CREATE TABLE IF NOT EXISTS classificacao (
    product_id INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
    categoria  TEXT,     -- whey, creatina, barra_proteica, vestuario...
    grupo      TEXT,     -- proteina | suplemento | alimento | fora
    kit        INTEGER,  -- 1 se for kit/combo
    fonte      TEXT,     -- nome | categoria_loja | descricao | ingredientes
    termo      TEXT,     -- trecho que casou, para auditar a regra
    peso_g     REAL,     -- peso total declarado no nome (heurístico)
    capsulas   INTEGER
);

CREATE INDEX IF NOT EXISTS idx_classificacao_categoria ON classificacao(categoria);

-- Tabela nutricional transcrita da imagem do rótulo (scraper/rotulos.py ou
-- leitura manual conferida). Criada aqui também para a view sempre compilar.
CREATE TABLE IF NOT EXISTS rotulos_ia (
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    imagem_url  TEXT NOT NULL,
    modelo      TEXT NOT NULL,
    lido_em     TEXT NOT NULL,
    tem_tabela  INTEGER,
    resposta    TEXT,
    erro        TEXT,
    PRIMARY KEY (product_id, imagem_url)
);

-- Última foto de cada produto, pronta para exportar/analisar. Recriada a cada
-- abertura para acompanhar mudanças de colunas.
--
-- `nutrition`: a tabela em texto da loja quando existe; senão, a lida da
-- imagem do rótulo, marcada com origem "ia_imagem". A da loja nunca é
-- substituída — só se preenche o que estava vazio.
DROP VIEW IF EXISTS v_catalogo;
CREATE VIEW v_catalogo AS
SELECT p.id, p.site, p.brand, p.name, p.ean, p.sku,
       h.price, h.list_price,
       CASE h.available WHEN 1 THEN 'sim' WHEN 0 THEN 'nao' END AS disponivel,
       c.categoria, c.grupo, c.kit, c.fonte AS classificacao_fonte,
       c.peso_g, c.capsulas,
       CASE WHEN c.peso_g > 0 AND h.price > 0
            THEN ROUND(h.price / c.peso_g * 1000, 2) END AS preco_por_kg,
       p.categories, p.ingredients,
       CASE WHEN COALESCE(json_array_length(json_extract(p.nutrition, '$.itens')), 0) = 0
                 AND r.resposta IS NOT NULL
            THEN json_patch(COALESCE(p.nutrition, '{}'), json_object(
                     'itens', json_extract(r.resposta, '$.itens'),
                     'porcao', json_extract(r.resposta, '$.porcao'),
                     'porcoes_por_embalagem', json_extract(r.resposta, '$.porcoes_por_embalagem'),
                     'origem', 'ia_imagem',
                     'ia', json_object('modelo', r.modelo, 'imagem', r.imagem_url,
                                       'coluna_lida', json_extract(r.resposta, '$.coluna_lida'),
                                       'conferido', json_extract(r.resposta, '$.conferido_pelo_codex'))))
            ELSE p.nutrition END AS nutrition,
       p.url, p.last_seen_at
FROM products p
LEFT JOIN price_history h
       ON h.product_id = p.id AND h.run_id = p.last_seen_run
LEFT JOIN classificacao c ON c.product_id = p.id
-- uma imagem com tabela por produto (a primeira lida)
LEFT JOIN rotulos_ia r ON r.rowid = (
    SELECT r2.rowid FROM rotulos_ia r2
    WHERE r2.product_id = p.id AND r2.tem_tabela = 1 ORDER BY r2.lido_em LIMIT 1);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path = "data/produtos.sqlite3"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.run_id: int | None = None

    # -- runs ----------------------------------------------------------------
    def start_run(self, sites: Iterable[str], notes: str | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (started_at, sites, notes) VALUES (?, ?, ?)",
            (_now(), ",".join(sites), notes),
        )
        self.conn.commit()
        self.run_id = cur.lastrowid
        return self.run_id

    def finish_run(self, n_products: int, n_errors: int) -> None:
        if self.run_id is None:
            return
        self.conn.execute(
            "UPDATE runs SET finished_at=?, n_products=?, n_errors=? WHERE id=?",
            (_now(), n_products, n_errors, self.run_id),
        )
        self.conn.commit()

    # -- produtos ------------------------------------------------------------
    def upsert(self, p: Produto) -> int:
        """Insere ou atualiza o produto e registra o preço desta run."""
        if self.run_id is None:
            raise RuntimeError("chame start_run() antes de gravar produtos")
        now, run = _now(), self.run_id
        cats = json.dumps(p.categories, ensure_ascii=False)
        imgs = json.dumps(p.images, ensure_ascii=False)
        nutri = json.dumps(p.nutrition, ensure_ascii=False) if p.nutrition else None

        cur = self.conn.execute(
            """
            INSERT INTO products (site, brand, url, name, external_id, sku, ean,
                categories, images, description_html, description_text,
                ingredients, nutrition,
                first_seen_run, last_seen_run, first_seen_at, last_seen_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(site, url) DO UPDATE SET
                brand=excluded.brand,
                name=excluded.name,
                external_id=COALESCE(excluded.external_id, products.external_id),
                sku=COALESCE(excluded.sku, products.sku),
                ean=COALESCE(excluded.ean, products.ean),
                categories=excluded.categories,
                images=excluded.images,
                description_html=COALESCE(excluded.description_html, products.description_html),
                description_text=COALESCE(excluded.description_text, products.description_text),
                ingredients=COALESCE(excluded.ingredients, products.ingredients),
                nutrition=COALESCE(excluded.nutrition, products.nutrition),
                last_seen_run=excluded.last_seen_run,
                last_seen_at=excluded.last_seen_at
            RETURNING id
            """,
            (p.site, p.brand, p.url, p.name, p.external_id, p.sku, p.ean,
             cats, imgs, p.description_html, p.description_text,
             p.ingredients, nutri, run, run, now, now),
        )
        product_id = cur.fetchone()[0]

        self.conn.execute(
            """
            INSERT INTO price_history (product_id, run_id, price, list_price, available, scraped_at)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(product_id, run_id) DO UPDATE SET
                price=excluded.price, list_price=excluded.list_price,
                available=excluded.available, scraped_at=excluded.scraped_at
            """,
            (product_id, run, p.price, p.list_price,
             None if p.available is None else int(p.available), now),
        )
        return product_id

    def reclassificar(self, regras: str | Path = "categorias.yaml") -> int:
        from .classify import Classificador, reclassificar
        return reclassificar(self.conn, Classificador(regras))

    def commit(self) -> None:
        self.conn.commit()

    def stats(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT site, brand, COUNT(*) AS produtos,
                   SUM(ean IS NOT NULL)         AS com_ean,
                   SUM(ingredients IS NOT NULL) AS com_ingredientes,
                   -- o campo também guarda modo de uso e alergênicos; só conta
                   -- quem tem a tabela de fato
                   SUM(COALESCE(json_array_length(json_extract(nutrition, '$.itens')), 0) > 0)
                                                AS com_nutricional,
                   SUM(json_extract(nutrition, '$.origem') = 'ia_imagem') AS nutri_ia,
                   ROUND(AVG(price), 2)         AS preco_medio
            FROM v_catalogo GROUP BY site ORDER BY produtos DESC
            """
        ).fetchall()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()
