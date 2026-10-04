"""Interface de linha de comando."""
from __future__ import annotations

import argparse
import json
import logging
import sys

from .adapters import base
from .core.db import Database
from .runner import carregar_config, coletar


def _log(verboso: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verboso else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="scraper",
        description="Coleta de produtos de lojas de suplementos.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="coleta e grava no banco")
    p_run.add_argument("sites", nargs="*", help="sites a coletar (padrão: todos)")
    p_run.add_argument("--db", default="data/produtos.sqlite3")
    p_run.add_argument("--config", default="sites.yaml")
    p_run.add_argument("--limit", type=int, help="máximo de itens por site (teste)")
    p_run.add_argument("--no-cache", action="store_true", help="ignora o cache em disco")
    p_run.add_argument("-v", "--verbose", action="store_true")

    p_ls = sub.add_parser("sites", help="lista os sites registrados")
    p_ls.add_argument("--config", default="sites.yaml")

    p_st = sub.add_parser("stats", help="resumo do que já foi coletado")
    p_st.add_argument("--db", default="data/produtos.sqlite3")

    p_ia = sub.add_parser("ler-rotulos", help="IA transcreve tabelas nutricionais que só existem em imagem")
    p_ia.add_argument("--db", default="data/produtos.sqlite3")
    p_ia.add_argument("--limit", type=int, help="máximo de imagens nesta execução (teste)")
    p_ia.add_argument("--site", help="só uma loja (ex: vitafor)")
    p_ia.add_argument("--modelo", help="modelo da IA (padrão: o do provedor; ou IA_MODELO no .env)")
    p_ia.add_argument("--provedor", help="anthropic, openai, gemini, deepseek, openrouter, compativel "
                                         "(padrão: deduzido da chave IA_CHAVE)")

    p_cl = sub.add_parser("classificar", help="reaplica categorias.yaml sem recoletar")
    p_cl.add_argument("--db", default="data/produtos.sqlite3")
    p_cl.add_argument("--regras", default="categorias.yaml")

    p_ex = sub.add_parser("export", help="exporta o banco para CSV e/ou JSON")
    p_ex.add_argument("--db", default="data/produtos.sqlite3")
    p_ex.add_argument("--csv", default="data/produtos.csv")
    p_ex.add_argument("--json", dest="json_path", default="data/produtos.json")
    p_ex.add_argument("--only", choices=["csv", "json"], help="exporta só um formato")

    args = ap.parse_args(argv)

    if args.cmd == "sites":
        cfg = carregar_config(args.config)
        print(f"{'site':16} {'adapter':20} {'marca':24} host")
        print("-" * 86)
        for nome, s in (cfg.get("sites") or {}).items():
            print(f"{nome:16} {s.get('adapter',''):20} {s.get('brand',''):24} {s.get('host','')}")
        if bloq := cfg.get("bloqueados"):
            print(f"\nbloqueados (precisam de browser): {', '.join(bloq)}")
        print(f"\nadapters disponíveis: {', '.join(base.available())}")
        return 0

    if args.cmd == "stats":
        db = Database(args.db)
        linhas = db.stats()
        if not linhas:
            print("banco vazio — rode 'run' primeiro.")
            return 0
        cab = ("site", "produtos", "c/EAN", "c/ingred", "c/nutri", "preço médio")
        print(f"{cab[0]:16}{cab[1]:>9}{cab[2]:>7}{cab[3]:>10}{cab[4]:>9}{cab[5]:>14}")
        print("-" * 65)
        tot = 0
        for r in linhas:
            tot += r["produtos"]
            preco = f"R$ {r['preco_medio']:.2f}" if r["preco_medio"] else "-"
            print(f"{r['site']:16}{r['produtos']:>9}{r['com_ean'] or 0:>7}"
                  f"{r['com_ingredientes'] or 0:>10}{r['com_nutricional'] or 0:>9}{preco:>14}")
        print("-" * 65)
        print(f"{'TOTAL':16}{tot:>9}")
        db.close()
        return 0

    if args.cmd == "ler-rotulos":
        from .ia import ErroFatal
        from .rotulos import processar
        _log(True)
        try:
            resumo = processar(args.db, limite=args.limit, site=args.site,
                               modelo=args.modelo, provedor=args.provedor)
        except (ErroFatal, ValueError) as exc:
            print(f"erro: {exc}")
            return 1
        print(json.dumps(resumo, ensure_ascii=False))
        return 1 if resumo["erros"] else 0

    if args.cmd == "classificar":
        db = Database(args.db)
        n = db.reclassificar(args.regras)
        print(f"{n} produtos classificados")
        for r in db.conn.execute(
            "SELECT COALESCE(grupo,'-') g, COALESCE(categoria,'(sem categoria)') c, COUNT(*) n"
            " FROM classificacao GROUP BY g, c ORDER BY g, n DESC"
        ):
            print(f"  {r['g']:11} {r['c']:20} {r['n']:>5}")
        db.close()
        return 0

    if args.cmd == "export":
        from .core.export import para_csv, para_json
        if args.only != "json":
            print(f"{para_csv(args.db, args.csv)} produtos -> {args.csv}")
        if args.only != "csv":
            print(f"{para_json(args.db, args.json_path)} produtos -> {args.json_path}")
        return 0

    _log(args.verbose)
    resumo = coletar(
        sites=args.sites or None,
        config_path=args.config,
        db_path=args.db,
        cache_ttl=None if args.no_cache else 86400,
        limite=args.limit,
    )
    print(json.dumps(resumo, ensure_ascii=False, indent=2))
    return 1 if resumo["_total"]["erros"] else 0


if __name__ == "__main__":
    sys.exit(main())
