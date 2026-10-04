"""Compara duas transcrições independentes de cada rótulo (Claude x Codex)."""
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, "/Users/joaovictorifran/dev/ScrappingTcc")
from scraper.core.nutricional_padrao import numero  # noqa: E402

BASE = Path(__file__).parent


ABREVIACOES = {r"\bgord\b": "gorduras", r"\bac\b": "acucares", r"\bvit\b": "vitamina"}


def chave(nome: str) -> str:
    """Nome comparável: sem acento, sem a unidade entre parênteses ("Proteínas (g)"
    = "Proteínas") e com as abreviações dos rótulos lineares expandidas."""
    t = re.sub(r"\([^)]*\)", " ", nome.replace("μ", "µ"))
    t = unicodedata.normalize("NFKD", t).casefold()
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    for abreviada, completa in ABREVIACOES.items():
        t = re.sub(abreviada, completa, t)
    return t


def valor(texto: str):
    texto = (texto or "").strip()
    return (numero(texto), texto) if texto else (None, "")


def comparar(a: dict, b: dict) -> list[str]:
    difs = []
    if a["tem_tabela"] != b["tem_tabela"]:
        return [f"tem_tabela: claude={a['tem_tabela']} codex={b['tem_tabela']}"]
    for campo in ("porcao", "porcoes_por_embalagem"):
        if numero(a[campo] or "") != numero(b[campo] or ""):
            difs.append(f"{campo}: claude={a[campo]!r} codex={b[campo]!r}")
    ia = {chave(i["nutriente"]): i for i in a["itens"]}
    ib = {chave(i["nutriente"]): i for i in b["itens"]}
    for k in sorted(ia.keys() - ib.keys()):
        difs.append(f"só claude: {ia[k]['nutriente']} = {ia[k]['quantidade']}")
    for k in sorted(ib.keys() - ia.keys()):
        difs.append(f"só codex: {ib[k]['nutriente']} = {ib[k]['quantidade']}")
    for k in ia.keys() & ib.keys():
        for campo in ("quantidade", "vd"):
            va, vb = valor(ia[k][campo]), valor(ib[k][campo])
            if va[0] != vb[0] or (va[0] is None and va[1] != vb[1]):
                difs.append(f"{ia[k]['nutriente']} {campo}: claude={va[1]!r} codex={vb[1]!r}")
    return difs


def main() -> None:
    manifesto = {m["id"]: m for m in json.loads((BASE / "manifesto.json").read_text())}
    total = concordes = campos = campos_ok = 0
    for arq in sorted((BASE / "claude").glob("*.json")):
        pid = int(arq.stem)
        cx = BASE / "codex" / arq.name
        if not cx.exists():
            print(f"{pid}: sem leitura do Codex")
            continue
        a, b = json.loads(arq.read_text()), json.loads(cx.read_text())
        difs = comparar(a, b)
        n = 2 + 2 * max(len(a["itens"]), len(b["itens"]))
        total += 1
        campos += n
        campos_ok += n - len(difs)
        concordes += not difs
        nome = manifesto.get(pid, {}).get("nome", "")[:45]
        print(f"{pid} {nome:45} {'✅ igual' if not difs else '⚠️  ' + str(len(difs)) + ' diferença(s)'}")
        for d in difs:
            print(f"      - {d}")
    if total:
        print(f"\nrótulos idênticos: {concordes}/{total} | campos concordantes: {campos_ok}/{campos} ({campos_ok / campos:.1%})")


if __name__ == "__main__":
    main()
