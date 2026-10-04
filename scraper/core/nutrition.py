"""Extração de ingredientes e tabela nutricional a partir de conteúdo heterogêneo.

Cada loja publica o nutricional de um jeito diferente: tabela HTML, JSON de
linhas, prosa com "Ingredientes:" no meio, ou só uma imagem da embalagem.
Este módulo tenta estruturar o que é estruturável e preserva o resto em
`texto_bruto`, para que nada seja perdido silenciosamente.
"""
from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

from .models import clean_text

# --- classificação de rótulos de especificação -------------------------------
PATTERNS = {
    "ingredients": re.compile(
        r"ingredient|composi[çc][ãa]o", re.I),
    "nutrition": re.compile(
        r"tabela\s*nutricional|informa[çc][ãa]o\s*nutricional|conte[úu]do\s*nutricional"
        r"|nutritional|tabela(?!\s*de\s*medidas)|aminograma|aminogram", re.I),
    "nutrition_image": re.compile(
        r"imagem\s*nutricional|nutricional[-_\s]*imagem", re.I),
    "allergens": re.compile(r"al[eé]rg|al[eé]rgico|cont[eé]m\s+gl[úu]ten", re.I),
    "usage": re.compile(
        r"recomenda[çc][ãa]o\s*de\s*uso|uso\s*recomendado|modo\s*de\s*(uso|consumo|preparo)"
        r"|como\s*(e\s*quando\s*)?(tomar|usar|consumir)|posologia|dose", re.I),
    "warnings": re.compile(r"advert[êe]nc|precau[çc]|contraindica", re.I),
    "portion": re.compile(r"por[çc][ãa]o|serving", re.I),
    "specs": re.compile(r"ficha\s*t[ée]cnica|especifica[çc]|caracter[íi]sticas?\b", re.I),
}

IMG_RE = re.compile(r"https?://[^\s\"'<>)]+\.(?:png|jpe?g|webp|gif)", re.I)

# Imagem dentro da seção nutricional nem sempre é o rótulo: MixNutri e Essential
# põem ícones, fotos de pessoas e banners no mesmo bloco. Nome do arquivo e alt
# são os sinais mais fortes; "clean-label" é selo de marketing, não rótulo.
IMG_ROTULO_RE = re.compile(r"tabela|nutricional|nutrition[-_ ]?facts|r[oó]tulo|aminograma", re.I)
IMG_NAO_ROTULO_RE = re.compile(
    r"persona|cena|banner|lifestyle|foto|selo|[íi]cone?s?\b|icon|logo|mobile|clean[-_]?label"
    r"|image[-_]product|produto[-_]|infogr[áa]fico|modelo|atleta", re.I)
# ícone: a loja fixa o tamanho no style ("width:150px;height:150px")
_LADO_PX_RE = re.compile(r"(?:width|height)\s*:\s*(\d+)px", re.I)
LADO_MAX_ICONE = 200
# tabela publicada como imagem vem logo após o título da seção (no máximo o
# nome do sabor antes); foto de marketing vem depois de parágrafos de texto
TEXTO_MAX_ANTES = 300
MAX_IMAGENS = 5

# interface de loja capturada por engano no lugar do conteúdo (acordeão, SPA)
JUNK_RE = re.compile(
    r"R\$\s*\d|adicionar\s+ao\s+carrinho|comprar\s+agora|calcular\s+frete|digite\s+seu\s+cep"
    r"|quantidade\s+de\s+produto|assine\s+e\s+economize|fora\s+de\s+estoque|avise-me"
    r"|parcelas?\s+de|x\s+de\s+R\$", re.I)

# verbos que aparecem em texto de marketing e nunca em lista de ingredientes
VERBO_RE = re.compile(
    r"\b(?:é|são|foi|ser[áã]|ajuda|auxilia|promove|contribui|pode|podem|possui|garante"
    r"|oferece|melhora|favorece|indicado|recomendado|ideal|desenvolvido|produzido"
    r"|utilizado|conhecid[oa]|trata-se)\b", re.I)
# "Porção: 40 g (2 dosadores)" / "Porções por embalagem: cerca de 45"
# Na mesma linha ("Porção: 30 g (2 scoops) - Porções por embalagem: 15") o
# complemento da porção para no separador ou no início da outra informação.
PORCAO_RE = re.compile(
    r"por[çc][ãa]o(?:\s*de)?\s*[:\-]?\s*([0-9][0-9.,]*\s*(?:g|mg|ml|kcal|c[áa]psulas?|"
    r"tablet[es]*|sach[êe]s?|unidades?|comprimidos?)"
    r"(?:(?!\s*(?:[-–]\s*)?por[çc][õo]es)[^<\n.;|•]){0,40})", re.I)
# "Proteína por porção: 12g" / "21 g de proteínas por porção" é quantidade de
# um nutriente, não a porção. Lido como porção, dava proteína = 100% da porção
# (Tasty Wafer da Adaptogen, Iso Whey Balance da MixNutri).
NUTRIENTE_ANTES_RE = re.compile(
    r"(?:prote[ií]na|carboidrat|gordura|fibra|a[çc][úu]car|s[óo]dio|caloria|kcal|creatina"
    r"|cafe[íi]na|col[áa]geno|leucina|bcaa|glutamina|vitamina)s?\b[^\n.;]{0,15}$", re.I)


def achar_porcao(texto: str, regex: re.Pattern[str] = PORCAO_RE) -> re.Match[str] | None:
    """Primeira menção de porção que não seja "<nutriente> por porção"."""
    for m in regex.finditer(texto):
        if not NUTRIENTE_ANTES_RE.search(texto[max(0, m.start() - 40):m.start()]):
            return m
    return None


# número seguido de medida não é contagem: a Essential às vezes escreve a
# porção nesse campo ("Porções por embalagem: 250 ml (1 unidade)")
PORCOES_RE = re.compile(
    r"por[çc][õo]es\s*por\s*embalagem\s*[:\-]?\s*(?:cerca\s*de\s*)?([0-9][0-9.,]*)"
    r"(?![0-9.,]|\s*(?:k?g|mg|m?l)\b)", re.I)
# "Proteínas 24 g 48%" em prosa
PROSE_NUTRIENT_RE = re.compile(
    r"(?P<nome>[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9 ,\-/()]{2,40}?)\s*[:\-]?\s*"
    r"(?P<qtd>[0-9][0-9.,]*\s*(?:kcal|kJ|mcg|µg|mg|g|ml|UI))\b"
    r"(?:\s*\(?(?P<vd>[0-9][0-9.,]*)\s*%\)?)?", re.I)

NUTRIENT_HINTS = re.compile(
    r"valor\s*energ|carboidrato|a[çc][úu]car|prote[íi]na|gordura|fibra|s[óo]dio|colesterol"
    r"|vitamina|c[áa]lcio|ferro|zinco|magn[ée]sio|pot[áa]ssio|f[óo]sforo|sele[nê]io"
    r"|[óo]mega|epa\b|dha\b|cre?atina|leucina|bcaa|glutamina|cafe[íi]na|col[áa]geno", re.I)

# conectores que indicam fim do nome do nutriente em texto corrido
CONECTOR_RE = re.compile(
    r"\s*,\s*|\s+(?:e|ou|com|sem|de|do|da|dos|das|que|tem|por|para|em|no|na|at[ée]"
    r"|apenas|cada|sendo|onde|cujo|essa|esse|este|esta)\s+", re.I)

# cabeçalhos de tabela que não são nutrientes
HEADER_RE = re.compile(
    r"^\s*(?:quantidade|por\s|por[çc][ãa]o|%\s*vd|valor\s*di[áa]rio|nutriente|"
    r"informa[çc][ãa]o|composi[çc][ãa]o)|^\s*$", re.I)

# uma quantidade nutricional é um número seguido de unidade: "125kcal", "8,4 g", "0 mg"
MEDIDA_RE = re.compile(
    r"^[<>~=\s]*[0-9][0-9.,]*\s*(?:kcal|kJ|cal|mcg|µg|ug|mg|g|ml|l|UI|%)?\s*$", re.I)


def classify(label: str) -> str | None:
    """Mapeia o nome de uma especificação para um campo canônico."""
    for field, rx in PATTERNS.items():
        if rx.search(label):
            return field
    return None


def html_to_text(html: str | None) -> str | None:
    if not html:
        return None
    if "<" not in html:
        return clean_text(html)
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    for br in soup.find_all(["br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4"]):
        br.append("\n")
    return clean_text(soup.get_text(" "))


_POR_100_RE = re.compile(r"^\s*(?:por\s*|quantidade\s*(?:por|em)\s*)?100\s*(?:g|ml)\b", re.I)
_VD_RE = re.compile(r"%\s*vd|valor(?:es)?\s*di[áa]rio", re.I)


def _colunas_do_cabecalho(cells: list[str]) -> tuple[int, int | None] | None:
    """Posições (porção, %VD) num cabeçalho que tem também a coluna "100 g".

    Rótulos novos (RDC 429) trazem "100 g | porção | %VD". Sem isso, a primeira
    coluna numérica — a de 100 g — era lida como se fosse a porção: a Essential
    inteira saiu com valores ~2,5× maiores.
    """
    if not any(_POR_100_RE.match(c) for c in cells[1:]):
        return None
    vd = next((i for i, c in enumerate(cells) if i and _VD_RE.search(c)), None)
    porcao = next((i for i, c in enumerate(cells)
                   if i and c and i != vd and not _POR_100_RE.match(c)), None)
    return (porcao, vd) if porcao is not None else None


def _row_items(rows: list[list[str]]) -> list[dict[str, str]]:
    """Converte linhas [nutriente, quantidade, %VD] em registros."""
    itens: list[dict[str, str]] = []
    # (coluna da porção, coluna do %VD) quando a tabela tem também "por 100 g"
    layout: tuple[int, int | None] | None = None
    for row in rows:
        cells = [clean_text(str(c)) or "" for c in row]
        if novo := _colunas_do_cabecalho(cells):
            layout = novo
            continue
        if not cells or not cells[0]:
            continue
        if layout:
            porcao, vd = layout
            qtd = cells[porcao] if porcao < len(cells) else ""
            eh_cabecalho = HEADER_RE.match(cells[0]) and not NUTRIENT_HINTS.search(cells[0])
            if not re.search(r"\d", qtd) or eh_cabecalho:
                continue
            item = {"nutriente": cells[0], "quantidade": qtd}
            if vd is not None and vd < len(cells) and cells[vd]:
                item["vd"] = cells[vd].rstrip("%").strip()
            itens.append(item)
            continue
        nome = cells[0]
        eh_nutriente = bool(NUTRIENT_HINTS.search(nome))
        if HEADER_RE.match(nome) and not eh_nutriente:
            continue
        rest = [c for c in cells[1:] if c]
        if not rest:
            continue
        qtd = rest[0]
        # Sem nome reconhecidamente nutricional, só aceita se a quantidade for uma
        # medida pura. Isso descarta tabelas de especificação do tipo
        # "Apresentação | Pote com 500g", que não são nutricionais.
        if not eh_nutriente and not MEDIDA_RE.match(qtd):
            continue
        if not re.search(r"\d", qtd):
            continue
        item = {"nutriente": nome, "quantidade": qtd}
        if len(rest) > 1:
            item["vd"] = rest[1].rstrip("%").strip()
        itens.append(item)
    return itens


def _from_html_table(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[list[str]] = []
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if cells:
                rows.append(cells)
    return _row_items(rows)


def _from_json_rows(blob: Any) -> list[dict[str, str]]:
    """Formato Nutrify: {"neutro": [[nutriente, qtd, vd], ...]}."""
    data = blob
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return []
    rows: list[list[str]] = []
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                rows.extend(r for r in value if isinstance(r, list))
    elif isinstance(data, list):
        rows.extend(r for r in data if isinstance(r, list))
    return _row_items(rows)


def _from_prose(text: str) -> list[dict[str, str]]:
    """Último recurso: varre o texto por 'Nutriente 00 g (00%)'.

    Só aceita nomes que pareçam nutrientes, para não capturar frases de marketing
    do tipo "contém 12g de proteína por garrafa" espalhadas na descrição.
    """
    itens: list[dict[str, str]] = []
    vistos: set[str] = set()
    for m in PROSE_NUTRIENT_RE.finditer(text):
        nome = clean_text(m.group("nome")) or ""
        hint = NUTRIENT_HINTS.search(nome)
        if not hint:
            continue
        # o nome real começa no termo nutricional e termina no primeiro conector:
        # "proteína e tem apenas" -> "proteína"
        nome = CONECTOR_RE.split(nome[hint.start():])[0].strip(" ,;:-.")
        if not nome:
            continue
        chave = nome.casefold()
        if chave in vistos:
            continue
        vistos.add(chave)
        item = {"nutriente": nome, "quantidade": clean_text(m.group("qtd")) or ""}
        if m.group("vd"):
            item["vd"] = m.group("vd")
        itens.append(item)
    return itens


def parse_nutrition(
    blobs: list[Any],
    images: list[str] | None = None,
    contexto: list[Any] | None = None,
) -> dict[str, Any]:
    """Estrutura a tabela nutricional a partir de um ou mais blocos de conteúdo.

    Tenta, em ordem: tabela HTML, JSON de linhas, prosa. Guarda imagens
    nutricionais (quando a tabela só existe como figura) e o texto bruto.

    `contexto` são blocos consultados apenas para achar porção e porções por
    embalagem — tipicamente a ficha técnica do produto, que traz a porção mas
    não é uma tabela nutricional e portanto não deve virar nutriente.
    """
    out: dict[str, Any] = {}
    itens: list[dict[str, str]] = []
    textos: list[str] = []
    origens: set[str] = set()

    for blob in blobs:
        if blob is None:
            continue
        raw = blob if isinstance(blob, str) else json.dumps(blob, ensure_ascii=False)
        if not raw.strip():
            continue

        if not isinstance(blob, str) or raw.lstrip().startswith(("{", "[")):
            if novos := _from_json_rows(blob):
                itens.extend(novos)
                origens.add("json")
        if "<table" in raw.lower():
            if novos := _from_html_table(raw):
                itens.extend(novos)
                origens.add("tabela")

        texto = html_to_text(raw) if "<" in raw else clean_text(raw)
        if texto:
            textos.append(texto)
            if not itens:
                if novos := _from_prose(texto):
                    itens.extend(novos)
                    origens.add("prosa")

    texto_ctx = "\n".join(
        t for t in (html_to_text(str(b)) for b in (contexto or []) if b) if t
    )
    texto_full = "\n".join(textos)
    busca = "\n".join(x for x in (texto_full, texto_ctx) if x)
    if busca:
        if m := achar_porcao(busca):
            out["porcao"] = clean_text(m.group(1))
        if m := PORCOES_RE.search(busca):
            out["porcoes_por_embalagem"] = m.group(1)
    if texto_full:
        out["texto_bruto"] = texto_full[:6000]

    # deduplica preservando a ordem
    if itens:
        dedup, vistos = [], set()
        for it in itens:
            k = it["nutriente"].casefold()
            if k not in vistos:
                vistos.add(k)
                dedup.append(it)
        out["itens"] = dedup
        # "prosa" significa valores garimpados de texto corrido: tratar como estimativa
        out["origem"] = "+".join(sorted(origens)) or "desconhecida"

    # `images` vem de campo dedicado ("imagem nutricional"); as achadas no
    # meio do bloco passam pelo filtro de rótulo
    imgs = list(images or []) + imagens_de_rotulo([b for b in blobs if isinstance(b, str)])
    if imgs:
        # filtrar antes de cortar: o corte primeiro deixava o rótulo de fora
        # quando ele era a 6ª imagem, depois de ícones e fotos (MixNutri Bodyfort)
        out["imagens"] = list(dict.fromkeys(imgs))[:MAX_IMAGENS]

    return out


def imagens_de_rotulo(blocos: list[str]) -> list[str]:
    """Imagens dos blocos nutricionais que podem ser a tabela do rótulo.

    Descarta ícones (tamanho fixo pequeno no style), fotos e banners (pelo nome
    do arquivo ou alt) e imagens precedidas de muito texto no bloco. Se alguma
    imagem se anuncia como tabela/rótulo (nome ou alt), as demais só ficam se
    estiverem no mesmo bloco que ela ou num bloco que é só imagem — decidido
    no produto todo: na MixNutri os ícones ficam entre parágrafos, noutra seção
    que a tabela; na New Millen um produto traz duas tabelas em blocos sem
    texto, e só uma se chama "Tabela.png".
    """
    so_imagem: set[int] = set()
    candidatas: list[tuple[str, bool, int, int]] = []
    for n, raw in enumerate(blocos):
        if "<img" not in raw.lower():
            candidatas += [(u, bool(IMG_ROTULO_RE.search(_nome_arquivo(u))), 0, n) for u in IMG_RE.findall(raw)
                           if not IMG_NAO_ROTULO_RE.search(_nome_arquivo(u))]
            continue
        soup = BeautifulSoup(raw, "lxml")
        if not soup.get_text(strip=True):
            so_imagem.add(n)
        for tag in soup.find_all("img"):
            url = next((str(v) for a in ("src", "data-src", "data-original")
                        if (v := tag.get(a)) and IMG_RE.match(str(v))), None)
            if not url:
                continue
            lados = [int(px) for px in _LADO_PX_RE.findall(str(tag.get("style") or ""))]
            lados += [int(v) for a in ("width", "height") if str(v := tag.get(a) or "").isdigit()]
            if lados and max(lados) <= LADO_MAX_ICONE:
                continue
            sinais = f"{_nome_arquivo(url)} {tag.get('alt') or ''}"
            if IMG_NAO_ROTULO_RE.search(sinais):
                continue
            antes = len(" ".join("".join(tag.find_all_previous(string=True)).split()))
            candidatas.append((url, bool(IMG_ROTULO_RE.search(sinais)), antes, n))

    blocos_anunciados = {n for _, rotulo, _, n in candidatas if rotulo}
    return [u for u, rotulo, antes, n in candidatas
            if rotulo or (antes <= TEXTO_MAX_ANTES and (not blocos_anunciados or n in blocos_anunciados | so_imagem))]


def _nome_arquivo(url: str) -> str:
    return url.split("?", 1)[0].rsplit("/", 1)[-1]


def extract_ingredients(blobs: list[Any], trusted: bool = False, com_titulo: bool = False) -> str | None:
    """Pega a lista de ingredientes de um bloco dedicado ou de prosa.

    O cabeçalho "Ingredientes:" só é reconhecido no começo do texto. Procurá-lo
    em qualquer posição corta no lugar errado, porque rótulos legais costumam
    trazer notas de rodapé como "*Ingrediente utilizado como veículo".

    A lista termina onde começa a próxima seção do rótulo (alérgicos, sugestão
    de consumo, conservação, modo de uso).

    `trusted=True` indica que os blocos vêm de um campo dedicado a ingredientes
    na loja de origem. Nesse caso o conteúdo é aceito como está — sem isso,
    valores curtos e legítimos como "Creatina monohidratada" seriam descartados
    pela heurística de lista separada por vírgulas.

    `com_titulo=True` é a segunda tentativa para blocos de uma seção titulada
    "Ingredientes", quando a regra das vírgulas não achou nada: aceita lista de
    um item só ("Clara de ovo desidratada."), mas só se tiver cara de rótulo —
    ver `_lista_curta_de_rotulo`. Aceitar qualquer texto sob o título trazia
    slogans ("Rápida absorção", "CUIDADOSAMENTE SELECIONADOS").
    """
    stop = re.compile(
        r"\b(al[eé]rgic|al[eé]rgen|cont[eé]m\s+deriv|cont[eé]m\s+lactose|modo\s*de"
        r"|recomenda[çc]|sugest[ãa]o\s*de|conserva[çc][ãa]o|advert[êe]nc|por[çc][õo]es\s*por"
        r"|por[çc][ãa]o\s*:|n[ãa]o\s+cont[eé]m|informa[çc][ãa]o\s*nutri|este\s+produto\s+n[ãa]o"
        r"|\*\s*ingrediente\s+utilizado)", re.I)
    cabecalho = re.compile(r"\s*ingredientes?\b[^\n:]{0,40}:?\s*", re.I)

    for blob in blobs:
        if blob is None:
            continue
        raw = blob if isinstance(blob, str) else json.dumps(blob, ensure_ascii=False)
        texto = html_to_text(raw) if "<" in raw else clean_text(raw)
        if not texto:
            continue

        tinha_cabecalho = False
        if m := cabecalho.match(texto):
            texto = texto[m.end():]
            tinha_cabecalho = True

        if s := stop.search(texto):
            texto = texto[: s.start()]

        trecho = clean_text(texto)
        minimo = 3 if trusted else 10
        if not trecho or len(trecho) <= minimo:
            continue
        if com_titulo and not tinha_cabecalho:
            if not _lista_curta_de_rotulo(trecho):
                continue
        elif not trusted and not tinha_cabecalho and not _parece_ingredientes(trecho):
            continue
        if not trusted and tinha_cabecalho and JUNK_RE.search(trecho[:600]):
            continue
        return trecho[:4000]
    return None


_ABERTURA_DE_MARKETING_RE = re.compile(r"^(?:nossa|nosso|sua|seu|para|com|sem|mais|o|a|os|as|um|uma)\b", re.I)


def _lista_curta_de_rotulo(texto: str) -> bool:
    """Lista de ingrediente(s) sem vírgulas suficientes, mas com cara de rótulo.

    "Clara de ovo desidratada." / "Creatina monohidratada e antiumectante
    dióxido de silício." passam; "Rápida absorção", "CUIDADOSAMENTE
    SELECIONADOS" e "Nossa fórmula prática reúne..." não.
    """
    t = texto.strip()
    letras = [c for c in t if c.isalpha()]
    return (
        t.endswith(".")
        and len(t) <= 90
        and len(t.split()) <= 12
        and not re.search(r"\.\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]", t[:-1])        # uma frase só
        and sum(c.isupper() for c in letras) < 0.6 * max(len(letras), 1)
        and not _ABERTURA_DE_MARKETING_RE.match(t)
        and not VERBO_RE.search(t)
        and not JUNK_RE.search(t)
    )


def _parece_ingredientes(texto: str) -> bool:
    """Filtra o que foi capturado por engano quando a fonte não é confiável.

    Sem campo dedicado, o que sobra é heurística sobre HTML de tema: um
    acordeão pode entregar a interface de compra, e um título de seção pode
    entregar texto de marketing. Uma lista de ingredientes de verdade não cita
    preço nem conjuga verbos.
    """
    amostra = texto[:600]
    if JUNK_RE.search(amostra):
        return False
    if VERBO_RE.search(amostra):
        return False
    return texto.count(",") >= 2 or "\n" in texto.strip()


# --- extração a partir de HTML livre (Shopify, Nuvemshop, Tray, Magento, Wake) ---

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "caption", "legend", "summary")


def _is_heading(tag) -> bool:
    if tag.name in _HEADING_TAGS:
        return True
    # <p><strong>Ingredientes:</strong></p> funciona como cabeçalho
    if tag.name in ("p", "div") and len(tag.find_all(["strong", "b"], recursive=False)) == 1:
        texto = tag.get_text(" ", strip=True)
        forte = tag.find(["strong", "b"]).get_text(" ", strip=True)
        return bool(forte) and len(texto) <= len(forte) + 3 and len(texto) < 90
    return False


def sections_from_html(html: str | None) -> dict[str, list[str]]:
    """Fatia um HTML de descrição em seções canônicas pelos seus cabeçalhos.

    Lojas que não expõem campos estruturados (Shopify, Nuvemshop, Tray, Magento,
    Wake) jogam ingredientes e tabela nutricional dentro da descrição, separados
    por títulos. Esta função devolve {campo_canônico: [trechos de HTML]}.

    Tabelas cujo conteúdo parece nutricional entram em "nutrition" mesmo sem
    cabeçalho, porque muitas lojas publicam a tabela solta.
    """
    if not html or "<" not in html:
        return {}
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    out: dict[str, list[str]] = {}
    root = soup.body or soup
    # desce enquanto houver um único wrapper, para achar a lista real de blocos
    while True:
        filhos = [c for c in root.find_all(recursive=False)]
        if len(filhos) == 1 and filhos[0].name in ("div", "section", "article"):
            root = filhos[0]
        else:
            break

    campo_atual: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer, campo_atual
        if campo_atual and buffer:
            trecho = "".join(buffer).strip()
            if trecho:
                out.setdefault(campo_atual, []).append(trecho)
        buffer = []

    for bloco in root.find_all(recursive=False):
        if _is_heading(bloco):
            flush()
            campo_atual = classify(bloco.get_text(" ", strip=True))
            continue
        if campo_atual:
            buffer.append(str(bloco))
    flush()

    # nada pelos filhos diretos: a página enterra os títulos (acordeão, SPA)
    if not out:
        out = _deep_sections(soup)

    # tabelas nutricionais soltas, sem cabeçalho que as identifique
    for table in soup.find_all("table"):
        texto = table.get_text(" ", strip=True)
        if len(NUTRIENT_HINTS.findall(texto)) >= 2:
            html_tab = _com_legenda(table)
            if not any(html_tab in t for t in out.get("nutrition", [])):
                out.setdefault("nutrition", []).append(html_tab)

    return out


def _com_legenda(table, niveis: int = 3) -> str:
    """A tabela precedida das linhas curtas de porção que ficam fora dela.

    A Essential põe "Porções por embalagem: 1 unidade (40g)" num <p> irmão de
    um ancestral da tabela; sem ele a informação se perde. Só entram irmãos
    anteriores curtos que falam de porção — o contêiner inteiro traria notas e
    outros blocos.
    """
    legendas: list[str] = []
    no = table
    for _ in range(niveis):
        for irmao in no.find_previous_siblings(limit=3):
            texto = irmao.get_text(" ", strip=True) if hasattr(irmao, "get_text") else ""
            if texto and len(texto) <= 200 and _PORCAO_ALGUMA_RE.search(texto):
                legendas.insert(0, str(irmao))
        if legendas or not no.parent or no.parent.name in ("body", "html"):
            break
        no = no.parent
    return "".join(legendas) + str(table)


_PORCAO_ALGUMA_RE = re.compile(r"por[çc](?:[ãa]o|[õo]es)", re.I)


_PARAGRAFO_INGREDIENTES_RE = re.compile(r"^\s*ingredientes?\s*:", re.I)


def _paragrafos_de_ingredientes(html: str | None) -> list[str]:
    """Parágrafos que abrem com "Ingredientes:", como blocos próprios.

    Sem título de seção (Growth), a lista fica num parágrafo no meio do bloco
    da tabela. Listas com vírgulas passavam pela heurística, mas as de um
    ingrediente só ("Clara de ovo desidratada") não. Separar o parágrafo
    mantém a regra de que o cabeçalho tem de abrir o bloco.
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    achados = {
        t for tag in soup.find_all(["p", "li", "span", "div", "td"])
        if len(t := tag.get_text(" ", strip=True)) < 4000 and _PARAGRAFO_INGREDIENTES_RE.match(t)
    }
    # o menor é o parágrafo em si; os maiores são contêineres dele
    return sorted(achados, key=len)


def from_description(
    html: str | None, images: list[str] | None = None
) -> tuple[str | None, dict[str, Any]]:
    """Atalho: devolve (ingredientes, nutricional) a partir de uma descrição HTML."""
    secoes = sections_from_html(html)
    nutri_blobs = secoes.get("nutrition", [])
    dedicado = secoes.get("ingredients", [])
    # uma seção de HTML é inferida pelo título, não é campo de API: o título vale
    # como cabeçalho, mas o conteúdo ainda passa pelos filtros
    # 1ª: regra das vírgulas; 2ª: lista curta com cara de rótulo
    ingredientes = (extract_ingredients(dedicado) or extract_ingredients(dedicado, com_titulo=True)) if dedicado else None
    if ingredientes is None:
        ingredientes = extract_ingredients(_paragrafos_de_ingredientes(html) + nutri_blobs)
    especificacoes = secoes.get("specs", [])
    nutrition = parse_nutrition(
        nutri_blobs,
        images=secoes.get("nutrition_image") or None,
        contexto=especificacoes,
    )
    if ficha := _key_values(especificacoes):
        nutrition["ficha_tecnica"] = ficha
    for campo in ("allergens", "usage", "warnings", "portion"):
        if valores := [html_to_text(v) for v in secoes.get(campo, []) if v]:
            nutrition[campo] = "\n".join(v for v in valores if v)[:2000]

    return ingredientes, nutrition


def _key_values(blobs: list[Any]) -> dict[str, str]:
    """Lê tabelas de duas colunas (ficha técnica) como pares chave/valor."""
    out: dict[str, str] = {}
    for blob in blobs:
        if not isinstance(blob, str) or "<" not in blob:
            continue
        soup = BeautifulSoup(blob, "lxml")
        for tr in soup.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) == 2 and cells[0] and cells[1]:
                chave = clean_text(cells[0])
                valor = clean_text(cells[1])
                if chave and valor and len(chave) < 60:
                    out.setdefault(chave, valor[:300])
    return out


def _deep_sections(soup) -> dict[str, list[str]]:
    """Varre cabeçalhos em qualquer profundidade da árvore.

    Páginas de produto renderizadas (e acordeões do tipo "INGREDIENTES +")
    enterram os títulos em vários níveis de div, então o passeio pelos filhos
    diretos do body não os encontra. Aqui cada cabeçalho reconhecido leva os
    irmãos seguintes até o próximo cabeçalho.
    """
    out: dict[str, list[str]] = {}
    candidatos = soup.find_all(list(_HEADING_TAGS) + ["p", "div", "span", "button", "dt", "strong", "b"])
    for tag in candidatos:
        texto = tag.get_text(" ", strip=True)
        if not texto or len(texto) > 90:
            continue
        campo = classify(texto)
        if not campo:
            continue
        # o rótulo tem que ser o conteúdo do elemento, não um trecho perdido num parágrafo
        if len(texto) > 60:
            continue
        pedacos: list[str] = []
        for irmao in tag.next_siblings:
            if getattr(irmao, "name", None) is None:
                if txt := str(irmao).strip():
                    pedacos.append(txt)
                continue
            if classify(irmao.get_text(" ", strip=True)[:90]) and irmao.get_text(strip=True):
                break
            pedacos.append(str(irmao))
            if sum(len(x) for x in pedacos) > 20000:
                break
        # acordeão: o conteúdo pode ser filho do próprio elemento, após o rótulo
        if not pedacos:
            interno = tag.get_text(" ", strip=True)
            if len(interno) > len(texto) + 10:
                # o rótulo do acordeão se repete no início do conteúdo
                if interno.startswith(texto):
                    interno = interno[len(texto):].lstrip(" :–-+")
                pedacos.append(interno)
        trecho = "".join(pedacos).strip()
        if trecho and len(trecho) > 15:
            out.setdefault(campo, []).append(trecho[:20000])
    return out
