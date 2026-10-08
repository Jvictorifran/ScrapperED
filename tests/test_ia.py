"""Leitura de rótulo com qualquer provedor de IA (scraper/ia.py), HTTP simulado."""
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from scraper import ia, rotulos
from scraper.rotulos import ESQUEMA, INSTRUCAO

LEITURA = {"tem_tabela": True, "motivo": "", "porcao": "30 g", "porcoes_por_embalagem": "30",
           "coluna_lida": "30 g", "itens": [{"nutriente": "Proteínas (g)", "quantidade": "21", "vd": "42"}]}


def resposta(status: int, corpo: dict | str) -> mock.Mock:
    r = mock.Mock(status_code=status)
    r.text = corpo if isinstance(corpo, str) else json.dumps(corpo)
    r.json.return_value = corpo if isinstance(corpo, dict) else {}
    return r


def chat(conteudo: str) -> dict:
    return {"model": "gpt-4.1-2025", "choices": [{"finish_reason": "stop", "message": {"content": conteudo}}],
            "usage": {"total_tokens": 10}}


class DeduzirProvedor(unittest.TestCase):
    def test_formatos(self):
        casos = {
            "sk-ant-api03-abc": "anthropic",
            "sk-proj-abcDEF123": "openai",
            "sk-" + "A1b2" * 12: "openai",              # chave antiga da OpenAI
            "sk-0123456789abcdef0123456789abcdef": "deepseek",
            "AIzaSyD-xyz": "gemini",
            "sk-or-v1-abc": "openrouter",
        }
        for chave, esperado in casos.items():
            with self.subTest(chave=chave):
                self.assertEqual(ia.deduzir_provedor(chave), esperado)

    def test_desconhecida_pede_ia_provedor(self):
        with self.assertRaisesRegex(ValueError, "IA_PROVEDOR"):
            ia.deduzir_provedor("xyz-123")


class Configurar(unittest.TestCase):
    def test_chave_generica_e_compatibilidade(self):
        with mock.patch.dict(os.environ, {"IA_CHAVE": "sk-proj-x"}, clear=True):
            leitor = ia.configurar()
            self.assertEqual((leitor.provedor, leitor.modelo, leitor.url),
                             ("openai", "gpt-4.1", "https://api.openai.com/v1"))
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-x"}, clear=True):
            self.assertEqual(ia.configurar().provedor, "anthropic")

    def test_modelo_e_provedor_forcados(self):
        env = {"IA_CHAVE": "sk-abc", "IA_PROVEDOR": "openrouter", "IA_MODELO": "google/gemini-2.5-pro"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(ia.configurar().rotulo, "openrouter:google/gemini-2.5-pro")

    def test_servidor_local_sem_chave(self):
        env = {"IA_URL": "http://localhost:11434/v1", "IA_MODELO": "qwen2.5vl"}
        with mock.patch.dict(os.environ, env, clear=True):
            leitor = ia.configurar()
            self.assertEqual((leitor.provedor, leitor.url), ("compativel", "http://localhost:11434/v1"))

    def test_sem_chave(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ia.ErroFatal):
                ia.configurar()


class LerCompativel(unittest.TestCase):
    def setUp(self):
        self.leitor = ia.Leitor("openai", "gpt-4.1", "sk-proj-x", "https://api.openai.com/v1")

    def ler(self, *respostas):
        with mock.patch.object(ia.requests, "post", side_effect=list(respostas)) as post:
            return self.leitor.ler(b"img", "image/png", INSTRUCAO, ESQUEMA), post

    def test_leitura_com_esquema(self):
        leitura, post = self.ler(resposta(200, chat(json.dumps(LEITURA))))
        self.assertEqual(leitura["itens"], LEITURA["itens"])
        self.assertEqual(leitura["_modelo"], "openai:gpt-4.1-2025")
        corpo = post.call_args.kwargs["json"]
        self.assertEqual(corpo["response_format"]["type"], "json_schema")
        self.assertTrue(corpo["messages"][0]["content"][0]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_provedor_sem_json_schema_cai_para_json_livre(self):
        cercado = "```json\n" + json.dumps(LEITURA) + "\n```"
        leitura, post = self.ler(resposta(400, "response_format json_schema not supported"),
                                 resposta(200, chat(cercado)))
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args.kwargs["json"]["response_format"], {"type": "json_object"})
        self.assertTrue(leitura["tem_tabela"])

    def test_deepseek_sem_raciocinio_e_json_livre(self):
        self.leitor = ia.Leitor("deepseek", "deepseek-chat", "sk-x", "https://api.deepseek.com/v1")
        leitura, post = self.ler(resposta(200, chat(json.dumps(LEITURA))))
        self.assertEqual(post.call_count, 1)
        corpo = post.call_args.kwargs["json"]
        self.assertEqual(corpo["thinking"], {"type": "disabled"})
        self.assertEqual(corpo["response_format"], {"type": "json_object"})
        self.assertTrue(leitura["tem_tabela"])

    def test_chave_invalida_e_fatal(self):
        with self.assertRaises(ia.ErroFatal):
            self.ler(resposta(401, "invalid api key"))

    def test_modelo_sem_visao_e_fatal(self):
        with self.assertRaisesRegex(ia.ErroFatal, "não aceita imagem"):
            self.ler(resposta(400, "unknown variant `image_url`, expected `text`"))

    def test_resposta_incompleta(self):
        with self.assertRaisesRegex(RuntimeError, "sem os campos"):
            self.ler(resposta(200, chat('{"tem_tabela": true}')))


class Processar(unittest.TestCase):
    """Erro fatal para a fila sem marcar imagens; erro comum volta para a fila."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        self.tmp.close()
        conn = sqlite3.connect(self.tmp.name)
        conn.executescript("""
            CREATE TABLE products (id INTEGER PRIMARY KEY, site TEXT, name TEXT, nutrition TEXT);
            CREATE TABLE classificacao (product_id INTEGER, grupo TEXT);
            INSERT INTO products VALUES (1, 'loja', 'Whey', '{"imagens": ["https://x/a.png"]}'),
                                        (2, 'loja', 'Creatina', '{"imagens": ["https://x/b.png"]}');
            INSERT INTO classificacao VALUES (1, 'proteina'), (2, 'suplemento');
        """)
        conn.close()
        self.env = mock.patch.dict(os.environ, {"IA_CHAVE": "sk-proj-x"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(os.unlink, self.tmp.name)
        baixar = mock.patch.object(rotulos, "_baixar", return_value=(b"img", "image/png"))
        baixar.start()
        self.addCleanup(baixar.stop)
        mock.patch.object(rotulos, "carregar_env").start()
        self.addCleanup(mock.patch.stopall)

    def linhas(self):
        conn = sqlite3.connect(self.tmp.name)
        self.addCleanup(conn.close)
        return conn.execute("SELECT COUNT(*) FROM rotulos_ia").fetchone()[0]

    def test_fatal_interrompe_sem_gravar(self):
        with mock.patch.object(ia.requests, "post", return_value=resposta(401, "bad key")) as post:
            resumo = rotulos.processar(self.tmp.name)
        self.assertEqual(post.call_count, 1)
        self.assertIn("interrompido", resumo)
        self.assertEqual(self.linhas(), 0)

    def test_erro_comum_volta_para_fila(self):
        with mock.patch.object(ia.requests, "post", return_value=resposta(500, "upstream")):
            self.assertEqual(rotulos.processar(self.tmp.name)["erros"], 2)
        conn = sqlite3.connect(self.tmp.name)
        self.addCleanup(conn.close)
        self.assertEqual(len(rotulos.pendentes(conn, None)), 2)
        with mock.patch.object(ia.requests, "post", return_value=resposta(200, chat(json.dumps(LEITURA)))):
            resumo = rotulos.processar(self.tmp.name)
        self.assertEqual((resumo["lidas"], resumo["modelo"]), (2, "openai:gpt-4.1"))
        self.assertEqual(len(rotulos.pendentes(conn, None)), 0)


if __name__ == "__main__":
    unittest.main()
