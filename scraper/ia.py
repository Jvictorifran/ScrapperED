"""Provedores de IA para ler imagens: troca-se o provedor trocando a chave.

Configuração no .env (só a chave é obrigatória):

    IA_CHAVE=...          chave de qualquer provedor abaixo
    IA_PROVEDOR=openai    opcional: força o provedor (senão, deduzido da chave)
    IA_MODELO=gpt-4.1     opcional: outro modelo do mesmo provedor
    IA_URL=http://...     opcional: servidor compatível com a API da OpenAI
                          (Ollama, LM Studio, vLLM...); implica IA_PROVEDOR=compativel

ANTHROPIC_API_KEY continua valendo, por compatibilidade.

A Anthropic usa o SDK próprio. Os demais falam o formato de chat da OpenAI
(`/chat/completions` com imagem em base64), que OpenAI, Gemini, DeepSeek,
OpenRouter e servidores locais aceitam; muda só o endereço e o modelo.
"""
from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class Provedor:
    nome: str
    url: str | None          # None = SDK da Anthropic
    modelo_padrao: str
    pagina_da_chave: str


PROVEDORES = {
    "anthropic": Provedor("anthropic", None, "claude-opus-5-5",
                          "https://console.anthropic.com/settings/keys"),
    "openai": Provedor("openai", "https://api.openai.com/v1", "gpt-4.1",
                       "https://platform.openai.com/api-keys"),
    "gemini": Provedor("gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash",
                       "https://aistudio.google.com/app/apikey"),
    "deepseek": Provedor("deepseek", "https://api.deepseek.com/v1", "deepseek-chat",
                         "https://platform.deepseek.com/api_keys"),
    "openrouter": Provedor("openrouter", "https://openrouter.ai/api/v1", "openai/gpt-4.1",
                           "https://openrouter.ai/keys"),
    "compativel": Provedor("compativel", None, "", ""),
}


class ErroFatal(RuntimeError):
    """Chave inválida, sem crédito ou modelo inexistente: não adianta tentar a próxima imagem."""


def deduzir_provedor(chave: str) -> str:
    """Provedor pelo formato da chave. DeepSeek e as chaves antigas da OpenAI
    começam ambas com "sk-": a DeepSeek usa 32 caracteres hexadecimais depois."""
    chave = chave.strip()
    if chave.startswith("sk-ant-"):
        return "anthropic"
    if chave.startswith("AIza"):
        return "gemini"
    if chave.startswith("sk-or-"):
        return "openrouter"
    if re.fullmatch(r"sk-[0-9a-f]{32}", chave):
        return "deepseek"
    if chave.startswith("sk-"):
        return "openai"
    raise ValueError("não reconheci o provedor pela chave; defina IA_PROVEDOR no .env "
                     f"({', '.join(p for p in PROVEDORES if p != 'compativel')})")


@dataclass
class Leitor:
    provedor: str
    modelo: str
    chave: str
    url: str | None

    @property
    def rotulo(self) -> str:
        """O que fica gravado em rotulos_ia.modelo, para auditoria."""
        return f"{self.provedor}:{self.modelo}"

    def ler(self, dados: bytes, tipo: str, instrucao: str, esquema: dict[str, Any]) -> dict[str, Any]:
        if self.provedor == "anthropic":
            return _ler_anthropic(self, dados, tipo, instrucao, esquema)
        return _ler_compativel(self, dados, tipo, instrucao, esquema)


def configurar(modelo: str | None = None, provedor: str | None = None) -> Leitor:
    """Monta o leitor a partir do ambiente (.env já carregado)."""
    chave = (os.environ.get("IA_CHAVE") or os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    url = os.environ.get("IA_URL", "").strip() or None
    provedor = (provedor or os.environ.get("IA_PROVEDOR", "").strip().lower()
                or ("compativel" if url else None))
    if not chave and provedor != "compativel":
        raise ErroFatal("sem chave de IA: defina IA_CHAVE no .env")
    provedor = provedor or deduzir_provedor(chave)
    if provedor not in PROVEDORES:
        raise ErroFatal(f"IA_PROVEDOR desconhecido: {provedor} ({', '.join(PROVEDORES)})")
    p = PROVEDORES[provedor]
    modelo = modelo or os.environ.get("IA_MODELO", "").strip() or p.modelo_padrao
    if provedor == "compativel" and not (url and modelo):
        raise ErroFatal("IA_PROVEDOR=compativel precisa de IA_URL e IA_MODELO")
    return Leitor(provedor, modelo, chave, url or p.url)


# --- Anthropic ---------------------------------------------------------------

def _ler_anthropic(leitor: Leitor, dados: bytes, tipo: str, instrucao: str, esquema: dict) -> dict[str, Any]:
    import anthropic

    client = anthropic.Anthropic(api_key=leitor.chave)
    try:
        resposta = client.beta.messages.create(
            model=leitor.modelo,
            max_tokens=16000,
            # transcrever uma tabela não pede raciocínio longo
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": esquema}},
            # se o modelo recusar, a API refaz a chamada noutro modelo (padrão recomendado)
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": tipo,
                        "data": base64.standard_b64encode(dados).decode("ascii"),
                    }},
                    {"type": "text", "text": instrucao},
                ],
            }],
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError) as exc:
        raise ErroFatal(f"anthropic: {exc}") from exc
    except anthropic.BadRequestError as exc:
        if "credit balance" in str(exc).lower():
            raise ErroFatal(f"anthropic: {exc}") from exc
        raise RuntimeError(str(exc)) from exc
    except anthropic.APIError as exc:
        raise RuntimeError(str(exc)) from exc
    if resposta.stop_reason == "refusal":
        raise RuntimeError("a IA recusou a imagem")
    if resposta.stop_reason == "max_tokens":
        raise RuntimeError("resposta cortada por max_tokens")
    texto = next(b.text for b in resposta.content if b.type == "text")
    return {**json.loads(texto), "_modelo": f"anthropic:{resposta.model}", "_uso": resposta.usage.to_dict()}


# --- formato da OpenAI (OpenAI, Gemini, DeepSeek, OpenRouter, local) ----------

def _ler_compativel(leitor: Leitor, dados: bytes, tipo: str, instrucao: str, esquema: dict) -> dict[str, Any]:
    imagem = f"data:{tipo};base64,{base64.standard_b64encode(dados).decode('ascii')}"
    corpo: dict[str, Any] = {
        "model": leitor.modelo,
        "temperature": 0,
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": imagem}},
            {"type": "text", "text": instrucao},
        ]}],
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "rotulo", "schema": esquema, "strict": True}},
    }
    resp = _post(leitor, corpo)
    if resp.status_code == 400 and re.search(r"response_format|json_schema", resp.text, re.I):
        # nem todo provedor aceita esquema estrito: cai para JSON livre com o
        # esquema descrito no texto
        corpo["response_format"] = {"type": "json_object"}
        corpo["messages"][0]["content"][1]["text"] = (
            f"{instrucao}\n\nResponda só com um objeto JSON neste esquema:\n"
            f"{json.dumps(esquema, ensure_ascii=False)}")
        resp = _post(leitor, corpo)
    if resp.status_code in (401, 402, 403, 404):
        raise ErroFatal(f"{leitor.provedor} HTTP {resp.status_code}: {resp.text[:300]}")
    if resp.status_code == 400 and re.search(r"image|vision|multimodal|image_url", resp.text, re.I):
        raise ErroFatal(f"{leitor.rotulo} não aceita imagem; use outro modelo (IA_MODELO) "
                        f"ou outro provedor. Resposta: {resp.text[:300]}")
    if resp.status_code >= 400:
        raise RuntimeError(f"{leitor.provedor} HTTP {resp.status_code}: {resp.text[:300]}")

    dados_resp = resp.json()
    escolha = (dados_resp.get("choices") or [{}])[0]
    if escolha.get("finish_reason") == "length":
        raise RuntimeError("resposta cortada por max_tokens")
    mensagem = escolha.get("message") or {}
    if mensagem.get("refusal"):
        raise RuntimeError(f"a IA recusou a imagem: {mensagem['refusal']}")
    leitura = extrair_json(mensagem.get("content") or "")
    faltando = [c for c in esquema["required"] if c not in leitura]
    if faltando:
        raise RuntimeError(f"resposta sem os campos {faltando}")
    return {**leitura, "_modelo": f"{leitor.provedor}:{dados_resp.get('model') or leitor.modelo}",
            "_uso": dados_resp.get("usage") or {}}


def _post(leitor: Leitor, corpo: dict[str, Any]) -> requests.Response:
    cabecalhos = {"Content-Type": "application/json"}
    if leitor.chave:
        cabecalhos["Authorization"] = f"Bearer {leitor.chave}"
    try:
        return requests.post(f"{leitor.url.rstrip('/')}/chat/completions",
                             headers=cabecalhos, json=corpo, timeout=180)
    except requests.RequestException as exc:
        raise RuntimeError(f"{leitor.provedor}: {exc}") from exc


def extrair_json(texto: str) -> dict[str, Any]:
    """JSON da resposta, tolerando cerca de código (```json ... ```) em volta."""
    texto = texto.strip()
    if m := re.search(r"```(?:json)?\s*(\{.*\})\s*```", texto, re.S):
        texto = m.group(1)
    elif (i := texto.find("{")) > 0:
        texto = texto[i:texto.rfind("}") + 1]
    try:
        valor = json.loads(texto)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"resposta não é JSON: {texto[:120]!r}") from exc
    if not isinstance(valor, dict):
        raise RuntimeError("resposta JSON não é um objeto")
    return valor
