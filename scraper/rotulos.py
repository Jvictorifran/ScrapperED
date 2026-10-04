"""Leitura por IA da tabela nutricional publicada só como imagem.

A IA **transcreve** a tabela da imagem do rótulo; não completa nem estima.
Se a imagem não tem tabela legível, a resposta diz isso e nada é gravado como
nutricional. Cada imagem é lida uma vez (tabela `rotulos_ia`); rodar de novo
só processa imagens novas.

    ./.venv/bin/python -m scraper ler-rotulos --limit 10

Funciona com qualquer provedor (Anthropic, OpenAI, Gemini, OpenRouter,
servidor local): basta a chave em IA_CHAVE no .env — ver `scraper/ia.py`.
A instrução e o esquema são os mesmos para todos; o modelo usado fica gravado
em `rotulos_ia.modelo` como "provedor:modelo".
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .core.http import DEFAULT_HEADERS
from .ia import ErroFatal, Leitor, configurar

log = logging.getLogger(__name__)

TIPOS_DE_IMAGEM = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_BYTES = 5 * 1024 * 1024  # limite da API por imagem

INSTRUCAO = """\
Esta imagem vem da página de um produto numa loja brasileira de suplementos.

Se ela contém uma tabela de Informação Nutricional legível, transcreva-a
exatamente como está impressa:
- Transcreva só o que está visível. Não complete, não estime e não corrija
  valores; não use conhecimento sobre o produto.
- Use a coluna da porção. Se houver também uma coluna "100 g" ou "100 ml",
  ignore-a. Se houver colunas por grupo populacional (por exemplo "9 a 18
  anos" e "≥ 19 anos"), use a de adultos (≥ 19 anos).
- Transcreva só a tabela de Informação Nutricional; quadros à parte (como
  contagem de probióticos) ficam de fora.
- "nutriente" é o nome da linha como impresso, incluindo a unidade entre
  parênteses quando houver, por exemplo "Proteínas (g)".
- "quantidade" é o valor da coluna da porção como impresso, por exemplo "0,6"
  ou "1.650". "vd" é o %VD da linha, ou "" se estiver vazio ou só com
  asterisco ("**", VD não estabelecido).
- "porcao" e "porcoes_por_embalagem" como impressos no topo da tabela, ou "".
- "coluna_lida" é o cabeçalho da coluna que você usou, por exemplo "4,5 g".

Se a imagem não tem tabela nutricional, ou ela está cortada, borrada ou
ilegível a ponto de algum valor ficar incerto, responda tem_tabela = false,
deixe itens vazio e explique em "motivo". Uma tabela incompleta é pior do que
nenhuma tabela."""

ESQUEMA = {
    "type": "object",
    "properties": {
        "tem_tabela": {"type": "boolean"},
        "motivo": {"type": "string"},
        "porcao": {"type": "string"},
        "porcoes_por_embalagem": {"type": "string"},
        "coluna_lida": {"type": "string"},
        "itens": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nutriente": {"type": "string"},
                    "quantidade": {"type": "string"},
                    "vd": {"type": "string"},
                },
                "required": ["nutriente", "quantidade", "vd"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["tem_tabela", "motivo", "porcao", "porcoes_por_embalagem", "coluna_lida", "itens"],
    "additionalProperties": False,
}

TABELA = """
CREATE TABLE IF NOT EXISTS rotulos_ia (
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    imagem_url  TEXT NOT NULL,
    modelo      TEXT NOT NULL,
    lido_em     TEXT NOT NULL,
    tem_tabela  INTEGER,
    resposta    TEXT,      -- JSON devolvido pela IA, para auditoria
    erro        TEXT,
    PRIMARY KEY (product_id, imagem_url)
);
"""


def carregar_env(caminho: str | Path = ".env") -> None:
    """Lê KEY=valor do .env sem sobrescrever o que já está no ambiente."""
    arquivo = Path(caminho)
    if not arquivo.exists():
        return
    # utf-8-sig: o Bloco de Notas do Windows pode salvar com BOM, e o BOM
    # grudaria no nome da primeira variável
    for linha in arquivo.read_text(encoding="utf-8-sig").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip("'\""))


def _baixar(url: str) -> tuple[bytes, str]:
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=45)
    resp.raise_for_status()
    tipo = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if tipo == "image/jpg":
        tipo = "image/jpeg"
    if tipo not in TIPOS_DE_IMAGEM:
        raise ValueError(f"formato não aceito pela API: {tipo or 'desconhecido'}")
    if len(resp.content) > MAX_BYTES:
        raise ValueError(f"imagem de {len(resp.content) // 1024} KB passa do limite de 5 MB")
    return resp.content, tipo


def pendentes(conn: sqlite3.Connection, site: str | None) -> list[tuple[int, str, str, str]]:
    """Produtos do escopo sem tabela em texto, com imagem de rótulo ainda não lida."""
    sql = """
        SELECT p.id, p.site, p.name, j.value AS imagem
        FROM products p
        JOIN classificacao c ON c.product_id = p.id
        JOIN json_each(json_extract(p.nutrition, '$.imagens')) j
        WHERE c.grupo IN ('proteina', 'suplemento')
          AND COALESCE(json_array_length(json_extract(p.nutrition, '$.itens')), 0) = 0
          -- leitura com erro (rede, chave, crédito) volta para a fila
          AND NOT EXISTS (SELECT 1 FROM rotulos_ia r WHERE r.product_id = p.id
                          AND r.imagem_url = j.value AND r.erro IS NULL)
    """
    args: list[Any] = []
    if site:
        sql += " AND p.site = ?"
        args.append(site)
    return conn.execute(sql + " ORDER BY p.site, p.id", args).fetchall()


def processar(db_path: str, limite: int | None = None, site: str | None = None,
              modelo: str | None = None, provedor: str | None = None) -> dict[str, Any]:
    carregar_env()
    leitor: Leitor = configurar(modelo, provedor)
    conn = sqlite3.connect(db_path)
    conn.executescript(TABELA)

    fila = pendentes(conn, site)
    if limite:
        fila = fila[:limite]
    log.info("%d imagens de rótulo para ler com %s", len(fila), leitor.rotulo)

    resumo: dict[str, Any] = {"modelo": leitor.rotulo, "lidas": 0, "com_tabela": 0, "sem_tabela": 0, "erros": 0}
    for product_id, loja, nome, url in fila:
        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            dados, tipo = _baixar(url)
            leitura = leitor.ler(dados, tipo, INSTRUCAO, ESQUEMA)
        except ErroFatal as exc:
            # chave inválida, sem crédito, modelo sem visão: as próximas imagens
            # falhariam igual, então para aqui sem marcar nada
            log.error("leitura interrompida: %s", exc)
            resumo["erros"] += 1
            resumo["interrompido"] = str(exc)[:300]
            break
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            log.warning("[%s] %s: %s", loja, nome[:50], exc)
            conn.execute(
                "INSERT OR REPLACE INTO rotulos_ia VALUES (?,?,?,?,NULL,NULL,?)",
                (product_id, url, leitor.rotulo, agora, f"{type(exc).__name__}: {exc}"))
            conn.commit()
            resumo["erros"] += 1
            continue

        tem = bool(leitura["tem_tabela"] and leitura["itens"])
        conn.execute(
            "INSERT OR REPLACE INTO rotulos_ia VALUES (?,?,?,?,?,?,NULL)",
            (product_id, url, leitura["_modelo"], agora, int(tem), json.dumps(leitura, ensure_ascii=False)))
        conn.commit()
        resumo["lidas"] += 1
        resumo["com_tabela" if tem else "sem_tabela"] += 1
        log.info("[%s] %s: %s", loja, nome[:50],
                 f"{len(leitura['itens'])} nutrientes" if tem else f"sem tabela ({leitura['motivo'][:60]})")

    conn.close()
    return resumo
