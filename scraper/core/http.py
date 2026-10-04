"""Cliente HTTP com throttle por domínio, retry e cache em disco.

O throttle é por host e não global: o VTEX devolve respostas vazias ou 500
quando recebe requisições concorrentes, então cada host tem seu próprio
intervalo mínimo entre chamadas.
"""
from __future__ import annotations

import gzip
import hashlib
import re
import logging
import random
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

from .desafios import eh_desafio_noc, resolver_noc

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
RETRY_STATUS = {429, 500, 502, 503, 504, 520, 522, 524}


class FetchError(RuntimeError):
    def __init__(self, url: str, status: int | None, detail: str = ""):
        self.url, self.status = url, status
        super().__init__(f"{status or 'ERR'} {url} {detail}".strip())


class Throttle:
    """Garante um intervalo mínimo entre requisições para o mesmo host."""

    def __init__(self, delay: float):
        self.delay = delay
        self._locks: dict[str, threading.Lock] = {}
        self._last: dict[str, float] = {}
        self._guard = threading.Lock()

    def wait(self, host: str) -> None:
        if self.delay <= 0:
            return
        with self._guard:
            lock = self._locks.setdefault(host, threading.Lock())
        with lock:
            elapsed = time.monotonic() - self._last.get(host, 0.0)
            sleep_for = self.delay - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for + random.uniform(0, self.delay * 0.25))
            self._last[host] = time.monotonic()


_META_CHARSET = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9_\-]+)""", re.I)


def _encoding_de(resp: requests.Response) -> str:
    """Decide o charset da resposta.

    O `requests` assume ISO-8859-1 para qualquer `text/*` sem charset no header,
    o que corrompe páginas UTF-8. Mas algumas lojas (Tray) realmente servem
    ISO-8859-1, então não dá para forçar UTF-8: só desconfiamos do ISO-8859-1
    quando ele não foi declarado explicitamente.
    """
    declarado = "charset=" in resp.headers.get("Content-Type", "").lower()
    if declarado and resp.encoding:
        return resp.encoding
    if m := _META_CHARSET.search(resp.content[:4096]):
        return m.group(1).decode("ascii", "ignore")
    return resp.apparent_encoding or resp.encoding or "utf-8"


class Client:
    def __init__(
        self,
        delay: float = 0.7,
        timeout: int = 45,
        retries: int = 3,
        cache_dir: str | Path | None = "data/cache",
        headers: dict[str, str] | None = None,
    ):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        if headers:
            self.session.headers.update(headers)
        self.timeout = timeout
        self.retries = retries
        self.throttle = Throttle(delay)
        self.cache = Path(cache_dir) if cache_dir else None
        if self.cache:
            self.cache.mkdir(parents=True, exist_ok=True)

    # -- cache ---------------------------------------------------------------
    def _cache_path(self, method: str, url: str, body: str | None) -> Path | None:
        if not self.cache:
            return None
        key = hashlib.sha256(f"{method} {url} {body or ''}".encode()).hexdigest()
        host = urlsplit(url).netloc or "unknown"
        return self.cache / host / f"{key}.gz"

    def _cache_read(self, path: Path | None, max_age: float | None) -> str | None:
        if not path or not path.exists():
            return None
        if max_age is not None and time.time() - path.stat().st_mtime > max_age:
            return None
        try:
            return gzip.decompress(path.read_bytes()).decode("utf-8")
        except (OSError, EOFError, UnicodeDecodeError):
            return None

    def _cache_write(self, path: Path | None, text: str) -> None:
        if not path:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(gzip.compress(text.encode("utf-8")))
        tmp.replace(path)

    # -- fetch ---------------------------------------------------------------
    def get(
        self,
        url: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        method: str = "GET",
        cache_ttl: float | None = 86400,
        headers: dict[str, str] | None = None,
        allow_status: set[int] | None = None,
    ) -> str:
        """Devolve o corpo da resposta como texto. Usa cache quando disponível."""
        prepared = requests.Request(method, url, params=params).prepare().url or url
        body_key = repr(json_body) if json_body else None
        cpath = self._cache_path(method, prepared, body_key)
        if (cached := self._cache_read(cpath, cache_ttl)) is not None:
            return cached

        host = urlsplit(prepared).netloc
        last: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self.throttle.wait(host)
            try:
                resp = self.session.request(
                    method, prepared, json=json_body, headers=headers,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last = exc
                log.warning("tentativa %d/%d falhou (%s): %s", attempt, self.retries, url, exc)
                time.sleep(min(2 ** attempt, 20))
                continue

            if resp.status_code in RETRY_STATUS and attempt < self.retries:
                log.warning("HTTP %d em %s — retry %d/%d", resp.status_code, url, attempt, self.retries)
                time.sleep(min(2 ** attempt, 20) + random.uniform(0, 1))
                continue

            if resp.ok or (allow_status and resp.status_code in allow_status):
                resp.encoding = _encoding_de(resp)
                text = resp.text
                # A CDN noc.org (Growth) responde 200 com uma página de
                # verificação. Resolve, guarda o cookie na sessão e repete;
                # a página de desafio nunca vai para o cache.
                if eh_desafio_noc(text):
                    if (cookie := resolver_noc(text)) and attempt < self.retries:
                        self.session.cookies.set(*cookie, domain=host, path="/")
                        log.info("verificação noc.org resolvida para %s", host)
                        continue
                    raise FetchError(url, resp.status_code, "verificação noc.org não resolvida")
                # O VTEX responde 200 com corpo de erro em texto puro, e devolve
                # lista vazia quando está limitando a taxa. Gravar isso no cache
                # envenena as execuções seguintes, então tratamos como falha.
                enxuto = text.strip()
                if enxuto in ('"The operation was canceled."', "", "[]", "{}"):
                    if attempt < self.retries:
                        log.warning("corpo vazio em %s — retry %d/%d",
                                    url, attempt, self.retries)
                        time.sleep(2 ** attempt + random.uniform(0, 1))
                        continue
                    return text  # devolve sem cachear: o adapter decide o que fazer
                self._cache_write(cpath, text)
                return text

            raise FetchError(url, resp.status_code, resp.text[:120])

        raise FetchError(url, None, str(last))

    def get_json(self, url: str, **kw):
        import json

        text = self.get(url, **kw)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise FetchError(url, None, f"resposta não-JSON: {text[:120]}") from exc
