"""Verificação "Verifying your browser" da CDN noc.org (usada pela Growth).

A página de desafio responde HTTP 200 com um script que testa os 256 sufixos
hexadecimais de dois dígitos até o MD5 de `prefixo + sufixo` bater com um alvo,
e grava o resultado num cookie `noc_verification_id_*`. É o mesmo cálculo que o
navegador faria, em microssegundos — não precisa de browser.

Os nomes das variáveis do script mudam a cada resposta, então os valores são
achados pelo conteúdo: o base64 que decodifica para `noc_verification_id_...=`
é o par nome/prefixo, e o que decodifica para 32 hex é o MD5 alvo.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re

_MARCA = "noc-cdn"
_BASE64_RE = re.compile(r"'([A-Za-z0-9+/]{16,}={0,2})'")
_HEX = "0123456789abcdef"


def eh_desafio_noc(html: str) -> bool:
    # a página de desafio é pequena (~1 KB); não confundir com página real
    # que só mencione o nome
    return len(html) < 5000 and _MARCA in html and "Verifying your browser" in html


def resolver_noc(html: str) -> tuple[str, str] | None:
    """Devolve (nome do cookie, valor) ou None se o formato mudou."""
    par = alvo = None
    for bruto in _BASE64_RE.findall(html):
        try:
            texto = base64.b64decode(bruto).decode("ascii")
        except (binascii.Error, UnicodeDecodeError):
            continue
        if texto.startswith("noc_verification_id_") and "=" in texto:
            par = texto
        elif re.fullmatch(r"[0-9a-f]{32}", texto):
            alvo = texto
    if not par or not alvo:
        return None
    nome, prefixo = par.split("=", 1)
    for a in _HEX:
        for b in _HEX:
            if hashlib.md5(f"{prefixo}{a}{b}".encode()).hexdigest() == alvo:
                return nome, f"{prefixo}{a}{b}"
    return None
