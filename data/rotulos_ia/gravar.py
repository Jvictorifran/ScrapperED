"""Grava no banco os rótulos lidos pelos dois leitores (Claude na sessão + Codex CLI).

A leitura final é a do Claude, revisada contra a imagem quando houve
divergência; as duas leituras e as divergências ficam no JSON para auditoria.
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/Users/joaovictorifran/dev/ScrappingTcc")
from scraper.rotulos import TABELA  # noqa: E402

from comparar import comparar  # noqa: E402

BASE = Path(__file__).parent
DB = "/Users/joaovictorifran/dev/ScrappingTcc/data/produtos.sqlite3"
MODELO = "claude-code (sessão) + codex-cli"

manifesto = {m["id"]: m for m in json.loads((BASE / "manifesto.json").read_text())}
conn = sqlite3.connect(DB)
conn.executescript(TABELA)
gravados = 0
for arq in sorted((BASE / "claude").glob("*.json")):
    pid = int(arq.stem)
    cx = BASE / "codex" / arq.name
    if pid not in manifesto or not cx.exists():
        continue
    claude, codex = json.loads(arq.read_text()), json.loads(cx.read_text())
    resposta = {**claude, "divergencias": comparar(claude, codex), "leituras": {"claude": claude, "codex": codex}}
    conn.execute(
        "INSERT OR REPLACE INTO rotulos_ia VALUES (?,?,?,?,?,?,NULL)",
        (pid, manifesto[pid]["url"], MODELO, datetime.now(timezone.utc).isoformat(timespec="seconds"),
         int(bool(claude["tem_tabela"] and claude["itens"])), json.dumps(resposta, ensure_ascii=False)))
    gravados += 1
conn.commit()
print(f"{gravados} rótulos gravados em rotulos_ia")
print(conn.execute("SELECT COUNT(*), SUM(tem_tabela) FROM rotulos_ia").fetchone())
