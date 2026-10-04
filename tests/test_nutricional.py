"""Regressões da tabela nutricional: leitura das colunas e padronização.

Os casos vieram de tabelas reais em que o resultado saiu errado.
"""
import unittest

from scraper.core.nutricional_padrao import numero, padronizar, porcao_em_gramas
from scraper.core.nutrition import _row_items


class ColunaPor100g(unittest.TestCase):
    """Essential: "Porção | 100g | 40g | %VD" — lia-se a coluna de 100 g."""

    LINHAS = [
        ["Porção: 40g (1 unidade)", "100g", "40g", "%VD*"],
        ["Valor energético (kcal)", "457", "186", "9"],
        ["Açúcares totais (g)", "2,9", "1,2", ""],
        ["Proteínas (g)", "20", "8", "16"],
    ]

    def test_le_a_coluna_da_porcao(self):
        itens = {i["nutriente"]: i for i in _row_items(self.LINHAS)}
        self.assertEqual(itens["Valor energético (kcal)"]["quantidade"], "186")
        self.assertEqual(itens["Valor energético (kcal)"]["vd"], "9")
        self.assertEqual(itens["Proteínas (g)"]["quantidade"], "8")

    def test_vd_vazio_nao_vira_dado(self):
        itens = {i["nutriente"]: i for i in _row_items(self.LINHAS)}
        self.assertNotIn("vd", itens["Açúcares totais (g)"])

    def test_tabela_sem_coluna_100g_continua_igual(self):
        itens = _row_items([["Quantidade por porção", "30 g", "%VD*"], ["Proteínas", "21g", "42%"]])
        self.assertEqual(itens, [{"nutriente": "Proteínas", "quantidade": "21g", "vd": "42"}])


class IngredienteUnico(unittest.TestCase):
    """Growth: parágrafo "INGREDIENTES: Clara de ovo desidratada." no meio da página."""

    def test_lista_de_um_ingrediente_em_paragrafo(self):
        from scraper.core.nutrition import from_description
        html = ("<div><table><tr><td>Proteínas</td><td>24 g</td></tr></table>"
                "<p>Natural</p><p>INGREDIENTES: Clara de ovo desidratada. CONTÉM DERIVADOS DE OVOS.</p>"
                "<p>Recomendação de consumo: 1 porção ao dia.</p></div>")
        self.assertEqual(from_description(html)[0], "Clara de ovo desidratada.")

    def test_secao_titulada_com_um_ingrediente(self):
        from scraper.core.nutrition import from_description
        html = "<h3>Ingredientes</h3><p>Clara de ovo desidratada.</p><h3>Modo de uso</h3><p>Misture.</p>"
        self.assertEqual(from_description(html)[0], "Clara de ovo desidratada.")

    def test_secao_titulada_com_marketing_continua_rejeitada(self):
        # Dux: prosa de marketing sob o título não é lista de ingredientes
        from scraper.core.nutrition import from_description
        html = "<h3>Ingredientes</h3><p>A creatina monohidratada é formada a partir de aminoácidos.</p>"
        self.assertIsNone(from_description(html)[0])

    def test_frase_curta_de_marketing_nao_vira_ingrediente(self):
        from scraper.core.nutrition import from_description
        self.assertIsNone(from_description("<h3>Ingredientes</h3><p>Rápida absorção</p>")[0])

    def test_cabecalho_no_meio_do_texto_continua_ignorado(self):
        from scraper.core.nutrition import from_description
        html = "<p>Leia o rótulo. Ingredientes: veja embalagem</p>"
        self.assertIsNone(from_description(html)[0])


class Numero(unittest.TestCase):
    def test_formatos_brasileiros(self):
        self.assertEqual(numero("1,65mg"), 1.65)
        self.assertEqual(numero("5.000"), 5000)      # ponto de milhar
        self.assertEqual(numero("1.5 g"), 1.5)       # ponto decimal
        self.assertEqual(numero("1.234,5"), 1234.5)
        self.assertIsNone(numero("—"))

    def test_porcao(self):
        self.assertEqual(porcao_em_gramas("40g (2 medidas dosadoras)"), 40)
        self.assertEqual(porcao_em_gramas("Porção de 5 g (1 scoop)"), 5)
        self.assertEqual(porcao_em_gramas("1,5g (2 cápsulas)"), 1.5)
        self.assertIsNone(porcao_em_gramas("200 ml"))


class Padronizar(unittest.TestCase):
    def tabela(self, itens, porcao="30g"):
        return padronizar({"porcao": porcao, "itens": itens})

    def test_nomes_e_unidades_diferentes_viram_a_mesma_coluna(self):
        p = self.tabela([
            {"nutriente": "Valor energético", "quantidade": "125kcal = 523kJ"},
            {"nutriente": "Proteínas (g)", "quantidade": "21"},
            {"nutriente": "Sódio", "quantidade": "0,249 g"},
            {"nutriente": "Açúcares totais", "quantidade": "1,2g"},
        ])
        self.assertEqual(p["energia_kcal"], 125)
        self.assertEqual(p["proteinas_g"], 21)
        self.assertEqual(p["sodio_mg"], 249)          # g -> mg
        self.assertEqual(p["acucares_totais_g"], 1.2)
        self.assertEqual(p["proteina_pct"], 70.0)     # 21 g em 30 g

    def test_so_kj_converte_para_kcal(self):
        self.assertAlmostEqual(self.tabela([{"nutriente": "Energia", "quantidade": "523 kJ"}])["energia_kcal"], 125, delta=0.1)

    def test_o_resto_vai_para_outros(self):
        p = self.tabela([{"nutriente": "Creatina (mg)", "quantidade": "5.000"},
                         {"nutriente": "Vitamina C", "quantidade": "45 mg"}], porcao="5g")
        self.assertEqual(p["outros"], "Creatina (mg): 5.000; Vitamina C: 45 mg")

    def test_primeiro_sabor_vale(self):
        p = self.tabela([{"nutriente": "Proteínas", "quantidade": "21g"},
                         {"nutriente": "Proteínas", "quantidade": "20g"}])
        self.assertEqual(p["proteinas_g"], 21)

    def test_tabela_misturada_e_descartada(self):
        # Nutrify: cápsula de 0,56 g com 36 kcal e 8 g de proteína de outro produto
        p = self.tabela([{"nutriente": "Valor Energético", "quantidade": "36 kcal"},
                         {"nutriente": "Proteínas", "quantidade": "8,0 g"}], porcao="0,56 g (1 cápsula)")
        self.assertIsNotNone(p["inconsistente"])
        self.assertIsNone(p["energia_kcal"])
        self.assertIsNone(p["proteina_pct"])

    def test_porcao_no_texto_da_tabela(self):
        p = padronizar({"texto_bruto": "Por porção (30g)\nQuantidade", "itens": [{"nutriente": "Proteínas", "quantidade": "21g"}]})
        self.assertEqual(p["porcao_g"], 30)

    def test_sem_tabela(self):
        self.assertIsNone(padronizar({"usage": "Tomar 1 cápsula"}))


if __name__ == "__main__":
    unittest.main()


class ProteinaDeMarketing(unittest.TestCase):
    """ "Proteína por porção 12g" não é a porção (Tasty Wafer, Iso Whey Balance)."""

    def test_nutriente_por_porcao_nao_vira_porcao(self):
        from scraper.core.nutrition import parse_nutrition
        for texto in ["Proteína por porção\n12g\n1–2g", "21 g de proteínas por porção: 25 g, com dois sabores"]:
            with self.subTest(texto=texto):
                self.assertIsNone(parse_nutrition([texto]).get("porcao"))
        self.assertEqual(parse_nutrition(["Porção: 30 g (2 scoops)\nProteína por porção: 24 g"])["porcao"],
                         "30 g (2 scoops)")

    def test_proteina_acima_de_95_por_cento_e_inconsistente(self):
        p = padronizar({"itens": [{"nutriente": "Proteínas (g)", "quantidade": "12"}], "porcao": "12g"})
        self.assertIsNotNone(p["inconsistente"])
        self.assertIsNone(p["proteina_pct"])
        glutamina = padronizar({"itens": [{"nutriente": "Valor energético", "quantidade": "20 kcal"},
                                          {"nutriente": "Proteína", "quantidade": "5,0 g"}], "porcao": "5,0g"})
        self.assertEqual((glutamina["inconsistente"], glutamina["proteina_pct"]), (None, 100.0))
        isolado = padronizar({"itens": [{"nutriente": "Proteínas (g)", "quantidade": "27"}], "porcao": "30 g"})
        self.assertEqual((isolado["inconsistente"], isolado["proteina_pct"]), (None, 90.0))
