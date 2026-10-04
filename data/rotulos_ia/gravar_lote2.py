"""Grava o lote 2 (New Millen, MixNutri, Essential): uma linha por (produto, imagem).

Diferenças para o lote da Vitafor: aqui um produto pode ter várias imagens, e
as imagens foram **filtradas antes da leitura** — fotos, cenas, banners e
ícones entram como `tem_tabela = 0` com o motivo, para não voltarem à fila.
O Codex leu às cegas uma amostra sorteada (12 de 37 tabelas distintas);
quando há leitura dele, ela e as divergências ficam no JSON.

Duas tabelas legíveis foram recusadas por não serem do produto da página
(ver REJEITADAS): a leitura fica guardada, mas não vira nutricional.
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
DB = BASE.parent / "produtos.sqlite3"
MODELO = "claude-code (sessão) + codex-cli (amostra)"

# (produto, hash da imagem) -> motivo
REJEITADAS = {
    (2782, "37bc96de8928"): "tabela de outro produto: a página do Whey 100% Display com Sachês "
                            "mostra a tabela de um pré-treino (taurina, cafeína, beta-alanina)",
    (2783, "5c1bcb65cf88"): "tabela de outra apresentação (porção de 1 copo dosador, 30 porções); "
                            "o produto é o de sachês — vale a outra imagem da página",
}
# divergências Claude x Codex já revistas contra a imagem
REVISTAS = {
    "b0c7eeda5f0e": "%VD da Coenzima Q10: há um '67' quase transparente na célula (resíduo de "
                    "edição, como o '133' fantasma acima); mantido vazio",
}

grupos = json.loads((BASE / "lote2_grupos.json").read_text())
conn = sqlite3.connect(DB)
conn.executescript(TABELA)
agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
gravados = com_tabela = 0
for h, produtos in grupos.items():
    claude = json.loads((BASE / "claude" / f"v_{h}.json").read_text())
    resposta = dict(claude)
    cx = BASE / "codex" / f"v_{h}.json"
    if cx.exists():
        codex = json.loads(cx.read_text())
        resposta |= {"divergencias": comparar(claude, codex), "leituras": {"claude": claude, "codex": codex}}
        if h in REVISTAS:
            resposta["revisao"] = REVISTAS[h]
    for p in produtos:
        r = dict(resposta)
        tem = bool(claude["tem_tabela"] and claude["itens"])
        if motivo := REJEITADAS.get((p["id"], h)):
            tem, r["rejeitada"] = False, motivo
        conn.execute(
            "INSERT OR REPLACE INTO rotulos_ia VALUES (?,?,?,?,?,?,NULL)",
            (p["id"], p["url"], MODELO, agora, int(tem), json.dumps(r, ensure_ascii=False)))
        gravados += 1
        com_tabela += tem
conn.commit()
print(f"{gravados} linhas gravadas ({com_tabela} com tabela)")
print(conn.execute("SELECT COUNT(*), SUM(tem_tabela), COUNT(DISTINCT product_id) FROM rotulos_ia").fetchone())
