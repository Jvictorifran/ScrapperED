"""Orquestração da coleta: lê sites.yaml, roda os adapters e grava no SQLite."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Iterable

import yaml

from .adapters import base
from .adapters import (  # noqa: F401 (registro dos adapters)
    magento, shopify, shopify_storefront, sitemap, vtex, woo,
)
from .core.db import Database
from .core.http import Client

log = logging.getLogger(__name__)


def carregar_config(caminho: str | Path = "sites.yaml") -> dict[str, Any]:
    with open(caminho, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _config_do_site(cfg: dict[str, Any], nome: str) -> dict[str, Any]:
    defaults = cfg.get("defaults") or {}
    return {**defaults, **(cfg["sites"][nome])}


def coletar(
    sites: Iterable[str] | None = None,
    config_path: str | Path = "sites.yaml",
    db_path: str | Path = "data/produtos.sqlite3",
    cache_ttl: float | None = 86400,
    limite: int | None = None,
) -> dict[str, Any]:
    """Roda a coleta nos sites indicados (ou em todos) e grava no banco.

    Devolve um resumo por site com contagem de produtos e erros.
    """
    cfg = carregar_config(config_path)
    disponiveis = list(cfg.get("sites") or {})
    alvos = list(sites) if sites else disponiveis

    if desconhecidos := [s for s in alvos if s not in disponiveis]:
        raise KeyError(f"site(s) não registrado(s): {desconhecidos}. "
                       f"Disponíveis: {disponiveis}")

    db = Database(db_path)
    run_id = db.start_run(alvos)
    log.info("run #%d — %d site(s)", run_id, len(alvos))

    resumo: dict[str, Any] = {}
    total = erros_total = 0

    for nome in alvos:
        site_cfg = _config_do_site(cfg, nome)
        if limite:
            site_cfg = {**site_cfg, "limit": limite}
        adapter_nome = site_cfg.get("adapter")
        marca = site_cfg.get("brand", nome)

        try:
            classe = base.get_adapter(adapter_nome)
        except KeyError as exc:
            log.error("[%s] %s", nome, exc)
            resumo[nome] = {"produtos": 0, "erro": str(exc)}
            erros_total += 1
            continue

        cliente = Client(
            delay=float(site_cfg.get("delay", 1.0)),
            cache_dir="data/cache" if cache_ttl else None,
        )
        adapter = classe(nome, marca, site_cfg, cliente)

        inicio = time.monotonic()
        n = 0
        falha: str | None = None
        try:
            for produto in adapter.fetch():
                if not produto.name or not produto.url:
                    continue
                db.upsert(produto)
                n += 1
                if n % 25 == 0:
                    db.commit()
                    log.info("[%s] %d produtos...", nome, n)
                if limite and n >= limite:
                    log.info("[%s] limite de %d atingido", nome, limite)
                    break
        except KeyboardInterrupt:
            db.commit()
            log.warning("interrompido pelo usuário — %d produtos de %s salvos", n, nome)
            raise
        except Exception as exc:
            falha = f"{type(exc).__name__}: {exc}"
            log.exception("[%s] a coleta falhou", nome)
            erros_total += 1
        db.commit()

        duracao = time.monotonic() - inicio
        resumo[nome] = {
            "marca": marca,
            "adapter": adapter_nome,
            "produtos": n,
            "segundos": round(duracao, 1),
        }
        if falha:
            resumo[nome]["erro"] = falha
        total += n
        log.info("[%s] concluído: %d produtos em %.1fs%s",
                 nome, n, duracao, f" (ERRO: {falha})" if falha else "")

    db.finish_run(total, erros_total)
    db.reclassificar()
    resumo["_total"] = {"produtos": total, "erros": erros_total, "run_id": run_id}
    db.close()
    return resumo
