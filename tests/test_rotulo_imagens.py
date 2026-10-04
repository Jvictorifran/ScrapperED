"""Filtro de imagens de rótulo e porção/porções na mesma linha (2026-10-02)."""
import unittest

from scraper.core.nutrition import imagens_de_rotulo, parse_nutrition, sections_from_html

MIX = "https://mixnutri.fbitsstatic.net/media/"
NM = "https://d1a9qnv764bsoo.cloudfront.net/stores/001/942/073/rte/"


class ImagensDeRotulo(unittest.TestCase):
    def test_icone_por_tamanho_e_foto_por_nome(self):
        bloco = (f'<p><img src="{MIX}1-formula.png" style="width:150px;height:150px"></p>'
                 f'<p><img src="{MIX}persona-bodyfort.png"></p>')
        self.assertEqual(imagens_de_rotulo([bloco]), [])

    def test_tabela_anunciada_em_outro_bloco_descarta_icones(self):
        # MixNutri Fiberlax: ícones sem tamanho num bloco, tabela noutro
        icones = f'<p><img src="{MIX}1-fibras.png"></p><p>12 g de fibras</p><p><img src="{MIX}1-magnesio.png"></p>'
        tabela = f'<p>{"texto " * 80}</p><img src="{MIX}tabela-site.png">'
        self.assertEqual(imagens_de_rotulo([icones, tabela]), [f"{MIX}tabela-site.png"])

    def test_bloco_so_de_imagem_fica_mesmo_com_outra_anunciada(self):
        # New Millen Isolate em sachês: duas tabelas, só uma se chama Tabela.png
        a = f'<p><img src="{NM}base64_img_227499670-51c6.png"></p>'
        b = f'<p><img src="{NM}Tabela.png"></p>'
        self.assertEqual(imagens_de_rotulo([a, b]), [f"{NM}base64_img_227499670-51c6.png", f"{NM}Tabela.png"])

    def test_imagem_depois_de_muito_texto_e_marketing(self):
        bloco = f'<p>{"benefícios do produto " * 30}</p><img src="https://x.com/img-02.jpg">'
        self.assertEqual(imagens_de_rotulo([bloco]), [])

    def test_filtra_antes_de_cortar(self):
        # Bodyfort: o rótulo era a 6ª imagem e o corte em 5 o jogava fora
        fotos = "".join(f'<p><img src="{MIX}{i}-icone.png" style="width:150px"></p>' for i in range(5))
        nut = parse_nutrition([fotos + f'<img src="{MIX}tabela-bodyfort.png">'])
        self.assertEqual(nut["imagens"], [f"{MIX}tabela-bodyfort.png"])


class PorcaoNaMesmaLinha(unittest.TestCase):
    def casos(self):
        return [
            ("Porção: 30 g (2 scoops) Porções por embalagem: 15", "30 g (2 scoops)", "15"),
            ("Porção: 30 g (2 scoops) - Porções por embalagem: cerca de 15", "30 g (2 scoops)", "15"),
            ("Porção de 40 g (2 scoops) | Porções por embalagem: 22", "40 g (2 scoops)", "22"),
            ("Porções por embalagem: 15 • Porção: 8 g (1 stick)", "8 g (1 stick)", "15"),
            ("Porção: 4,5 g (3 cápsulas - 1,5 g cada)", "4,5 g (3 cápsulas - 1,5 g cada)", None),
        ]

    def test_porcao_nao_engole_porcoes(self):
        for texto, porcao, porcoes in self.casos():
            with self.subTest(texto=texto):
                nut = parse_nutrition([texto])
                self.assertEqual(nut.get("porcao"), porcao)
                self.assertEqual(nut.get("porcoes_por_embalagem"), porcoes)

    def test_medida_no_campo_de_porcoes_nao_e_contagem(self):
        self.assertIsNone(parse_nutrition(["Porções por embalagem: 250 ml (1 unidade)"]).get("porcoes_por_embalagem"))

    def test_legenda_fora_da_tabela_solta(self):
        # Essential: o <p> com as porções é irmão do contêiner da tabela
        html = ('<div class="tabela-nutri"><p>Porções por embalagem: 1 unidade (40g)</p>'
                '<div><table><tr><td>Porção: 40g (1 unidade)</td></tr>'
                '<tr><td>Proteínas (g)</td><td>8</td></tr><tr><td>Carboidratos (g)</td><td>15</td></tr>'
                '<tr><td>Sódio (mg)</td><td>20</td></tr></table></div><p>' + "nota " * 300 + '</p></div>')
        nut = parse_nutrition(sections_from_html(html)["nutrition"])
        self.assertEqual(nut.get("porcoes_por_embalagem"), "1")


if __name__ == "__main__":
    unittest.main()
