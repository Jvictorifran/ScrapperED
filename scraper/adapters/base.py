"""Contrato comum dos adapters e registro por nome."""
from __future__ import annotations

import logging
from typing import Any, Iterator

from ..core.http import Client
from ..core.models import Produto

log = logging.getLogger(__name__)

_REGISTRY: dict[str, type["Adapter"]] = {}


def register(name: str):
    def deco(cls: type[Adapter]) -> type[Adapter]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls
    return deco


def get_adapter(name: str) -> type[Adapter]:
    if name not in _REGISTRY:
        raise KeyError(f"adapter '{name}' não registrado (disponíveis: {sorted(_REGISTRY)})")
    return _REGISTRY[name]


def available() -> list[str]:
    return sorted(_REGISTRY)


class Adapter:
    """Um adapter sabe listar os produtos de uma loja e normalizá-los.

    Subclasses implementam `fetch()`, que produz Produto em streaming — assim
    o banco recebe dados conforme a coleta avança, sem acumular tudo em memória.
    """

    name: str = "base"

    def __init__(self, site: str, brand: str, config: dict[str, Any], client: Client):
        self.site = site
        self.brand = brand
        self.cfg = config
        self.http = client
        self.host: str = config["host"]

    @property
    def base(self) -> str:
        return f"https://{self.host}"

    def fetch(self) -> Iterator[Produto]:
        raise NotImplementedError

    def novo(self, **kw: Any) -> Produto:
        kw.setdefault("site", self.site)
        kw.setdefault("brand", self.brand)
        return Produto(**kw)
