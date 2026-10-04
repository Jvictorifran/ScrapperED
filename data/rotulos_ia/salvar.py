"""Converte transcrições em formato compacto (stdin) para o JSON do esquema.

    @<hash da imagem>
    porcao=30 g (1 sachê)
    porcoes=15
    coluna=30 g (≥ 19 anos)
    Valor energético (kcal);109;5
    Açúcares totais (g);0,7;
    @<outro hash>
    sem=foto da embalagem, sem tabela
"""
import json
import sys
from pathlib import Path

DESTINO = Path(__file__).parent / "claude"
atual, gravados = None, []


def fechar():
    if atual:
        (DESTINO / f"v_{atual['_id']}.json").write_text(
            json.dumps({k: v for k, v in atual.items() if k != "_id"}, ensure_ascii=False, indent=1))
        gravados.append(atual["_id"])


for linha in sys.stdin.read().splitlines():
    linha = linha.strip()
    if not linha:
        continue
    if linha.startswith("@"):
        fechar()
        atual = {"_id": linha[1:], "tem_tabela": True, "motivo": "", "porcao": "",
                 "porcoes_por_embalagem": "", "coluna_lida": "", "itens": []}
    elif linha.startswith("sem="):
        atual.update(tem_tabela=False, motivo=linha[4:])
    elif linha.startswith("porcao="):
        atual["porcao"] = linha[7:]
    elif linha.startswith("porcoes="):
        atual["porcoes_por_embalagem"] = linha[8:]
    elif linha.startswith("coluna="):
        atual["coluna_lida"] = linha[7:]
    else:
        nome, qtd, vd = (linha.split(";") + ["", ""])[:3]
        atual["itens"].append({"nutriente": nome.strip(), "quantidade": qtd.strip(), "vd": vd.strip()})
fechar()
print(f"gravados {len(gravados)}: {' '.join(gravados)} | total lido: {len(list(DESTINO.glob('v_*.json')))}")
