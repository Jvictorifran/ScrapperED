"""Regressões da classificação por palavra-chave (core/classify.py + categorias.yaml).

Cada caso veio de um erro encontrado auditando o banco real.
"""
import unittest
from pathlib import Path

from scraper.core.classify import Classificador, normalizar, peso_em_gramas

REGRAS = Path(__file__).resolve().parent.parent / "categorias.yaml"


class Categoria(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = Classificador(REGRAS)

    def cat(self, nome, marca="", categorias_loja=None, descricao=None, ingredientes=None):
        return self.c.classificar(nome, marca, categorias_loja, descricao, ingredientes).categoria

    def test_substantivo_que_abre_o_nome_decide(self):
        # "Whey Nerd" é a marca
        self.assertEqual(self.cat("Creatina Monohidratada 300g - Whey Nerd"), "creatina")
        # "Bone Crusher" não é boné
        self.assertEqual(self.cat("Pré-Treino Bone Crusher 150g - Black Skull"), "pre_treino")

    def test_formato_tem_prioridade(self):
        self.assertEqual(self.cat("Whey Crisp Bar Chocolate"), "barra_proteica")

    def test_acessorio_antes_do_conteudo(self):
        self.assertEqual(self.cat("Coqueteleira Whey 600ml"), "acessorio")

    def test_sabor_nao_classifica(self):
        self.assertEqual(self.cat("100% Beef 900g Chocolate"), "proteina_outras")

    def test_top_whey_nao_e_roupa(self):
        self.assertEqual(self.cat("Top Whey 3W + Sabor 900G"), "whey")
        self.assertEqual(self.cat("Top Adaptogen Elastic Preto M"), "vestuario")

    def test_energy_gel_e_carboidrato(self):
        self.assertEqual(self.cat("Energy Gel - 10 unidades"), "carboidrato")

    def test_massa_de_cacau_nao_e_hipercalorico(self):
        self.assertNotEqual(
            self.cat("Chocolift Be Unique", ingredientes="Massa de cacau, proteína isolada"),
            "hipercalorico")

    def test_marca_da_loja_nao_classifica(self):
        r = self.c.classificar("Ômega 3 MEG-3® - FTW Suplementos", "FTW Suplementos")
        self.assertEqual(r.categoria, "omega")

    def test_cai_para_ingredientes_e_registra_a_fonte(self):
        r = self.c.classificar(
            "Arsenal do URSO",
            ingredientes="Proteína de soro do leite concentrada (WPC), proteína de soro do leite isolada")
        self.assertEqual(r.fonte, "ingredientes")
        self.assertEqual(r.grupo, "proteina")

    def test_categoria_da_loja_quando_o_nome_nao_diz(self):
        r = self.c.classificar("Tasty Iso Original 900g", categorias_loja=["Whey Protein Isolado e Hidrolisado"])
        self.assertEqual(r.categoria, "whey")

    def test_kit(self):
        r = self.c.classificar("Kit Whey 900g + Creatina 300g")
        self.assertTrue(r.kit)
        self.assertEqual(r.categoria, "whey")
        self.assertIsNone(r.peso_g)


class Peso(unittest.TestCase):
    def peso(self, nome):
        return peso_em_gramas(normalizar(nome))

    def test_simples(self):
        self.assertEqual(self.peso("Whey Protein Isolado - Pote 450g"), 450)
        self.assertEqual(self.peso("Tasty Iso Chocolate Trufado Bag 1.8 kg"), 1800)
        self.assertEqual(self.peso("100% Hiper Mass Flavour (Pacote 2,5kg)"), 2500)

    def test_display_multiplica(self):
        self.assertEqual(self.peso("FITZEI® Barras de proteínas: Display c/12 Barras 40g"), 480)
        self.assertEqual(self.peso("Tasty Whey 3w Gourmet Pack com 12 sachês de 34g"), 408)

    def test_porcentagem_nao_e_contagem(self):
        self.assertEqual(self.peso("Display 100% Whey Double Tasty - 10 Sachês de 40g cada"), 400)

    def test_composicao_nao_e_peso(self):
        self.assertIsNone(self.peso("Barra de Proteína Whey Bar 24 Unidades – 15g de Proteína"))
        self.assertEqual(self.peso("Gel Carb Up Black 10 Sachês 30g – 18g Carbo + Cafeína"), 300)

    def test_total_declarado(self):
        self.assertEqual(self.peso("Best Whey (Display de 105g com 14 Unidades de 7,5g cada)"), 105)


if __name__ == "__main__":
    unittest.main()
