<?php

namespace App\Exports;

use App\Support\Formato;
use OpenSpout\Common\Entity\Row;
use OpenSpout\Common\Entity\Style\Style;
use OpenSpout\Writer\AutoFilter;
use OpenSpout\Writer\Common\Entity\Sheet;
use OpenSpout\Writer\XLSX\Entity\SheetView;
use OpenSpout\Writer\XLSX\Writer;

/**
 * Planilha .xlsx com os produtos de um filtro, em quatro abas ligadas pelo ID:
 *
 *   Produtos             uma linha por produto
 *   Tabela nutricional   uma linha por produto, uma coluna por nutriente
 *   Histórico de preços  uma linha por coleta de cada produto
 *   Filtros              o filtro usado e quando o arquivo foi gerado
 *
 * Preços, pesos e nutrientes vão como número, não texto, para somar, ordenar
 * e comparar. A padronização dos nutrientes é feita na API
 * (scraper/core/nutricional_padrao.py).
 */
class ProdutosPlanilha
{
    /** Limite de caracteres por célula do Excel. */
    private const MAX_CELULA = 32_000;

    private Style $cabecalho;

    private Style $dinheiro;

    private Style $decimal;

    public function __construct()
    {
        $this->cabecalho = new Style(fontBold: true, backgroundColor: 'E2E6DF');
        $this->dinheiro = new Style(format: '"R$" #,##0.00');
        $this->decimal = new Style(format: '#,##0.##');
    }

    /** Grava em $caminho a planilha com a resposta de /exportacao. */
    public function gravar(string $caminho, array $exportacao, array $filtros): void
    {
        $w = new Writer;
        $w->openToFile($caminho);

        $this->produtos($w->getCurrentSheet(), $w, $exportacao['itens']);
        $this->nutricional($w->addNewSheetAndMakeItCurrent(), $w, $exportacao['itens']);
        $this->historico($w->addNewSheetAndMakeItCurrent(), $w, $exportacao['itens']);
        $this->filtros($w->addNewSheetAndMakeItCurrent(), $w, $exportacao, $filtros);

        $w->close();
    }

    private function produtos(Sheet $aba, Writer $w, array $itens): void
    {
        // o que se lê primeiro vem primeiro; detalhes da classificação no fim
        $colunas = [
            'ID' => [7, null],
            'Loja' => [20, null],
            'Produto' => [50, null],
            'Categoria' => [18, null],
            'Preço' => [11, $this->dinheiro],
            'Preço "de"' => [11, $this->dinheiro],
            'Em estoque' => [10, null],
            'Peso (g)' => [10, $this->decimal],
            'R$ por kg' => [11, $this->dinheiro],
            'Tem tabela nutricional' => [11, null],
            'EAN' => [15, null],
            'Ingredientes' => [60, null],
            'Alérgicos' => [30, null],
            'Modo de uso' => [30, null],
            'Advertências' => [30, null],
            'Link' => [40, null],
            'Grupo' => [12, null],
            'Kit' => [6, null],
            'Cápsulas' => [9, null],
            'SKU' => [14, null],
            'Categorias na loja' => [30, null],
            'Classificado pelo termo' => [16, null],
            'Termo encontrado' => [22, null],
            'Imagem' => [40, null],
            'Atualizado em' => [17, null],
        ];
        $this->iniciar($aba, 'Produtos', $w, $colunas);

        $estilos = array_column(array_values($colunas), 1);
        foreach ($itens as $p) {
            $n = $p['nutricional'] ?? [];
            $w->addRow(Row::fromValuesWithStyles([
                $p['id'],
                $p['marca'],
                $this->texto($p['nome']),
                Formato::categoria($p['categoria']),
                $p['preco'],
                $p['preco_de'],
                $this->simNao($p['disponivel']),
                $p['peso_g'],
                $p['preco_por_kg'],
                $p['tem_nutricional'] ? 'sim' : 'não',
                $p['ean'],
                $this->texto($p['ingredientes']),
                $this->texto($n['allergens'] ?? null),
                $this->texto($n['usage'] ?? null),
                $this->texto($n['warnings'] ?? null),
                $p['url'],
                Formato::grupo($p['grupo']),
                $p['kit'] ? 'sim' : 'não',
                $p['classificacao']['capsulas'] ?? null,
                $p['sku'],
                $this->texto(implode(' | ', $p['categorias_loja'])),
                $p['classificacao']['termo'] ?? null,
                isset($p['classificacao']['fonte']) ? config('catalogo.fontes.'.$p['classificacao']['fonte']) : null,
                $p['imagens'][0] ?? null,
                Formato::data($p['atualizado_em']),
            ], $estilos));
        }

        $this->filtrar($aba, count($colunas), count($itens));
    }

    /**
     * Uma linha por produto, uma coluna por nutriente do rótulo (padrão
     * Anvisa), todos por porção e na mesma unidade. Só entram produtos com
     * tabela; o que não é nutriente obrigatório fica em "Outros nutrientes".
     */
    private function nutricional(Sheet $aba, Writer $w, array $itens): void
    {
        $colunas = [
            'ID' => [7, null],
            'Loja' => [20, null],
            'Produto' => [50, null],
            'Categoria' => [16, null],
            'Porção (g)' => [10, $this->decimal],
            'Valor energético (kcal)' => [12, $this->decimal],
            'Carboidratos (g)' => [12, $this->decimal],
            'Açúcares totais (g)' => [12, $this->decimal],
            'Açúcares adicionados (g)' => [12, $this->decimal],
            'Proteínas (g)' => [11, $this->decimal],
            'Proteína (% da porção)' => [12, $this->decimal],
            'Gorduras totais (g)' => [12, $this->decimal],
            'Gorduras saturadas (g)' => [12, $this->decimal],
            'Gorduras trans (g)' => [11, $this->decimal],
            'Fibras (g)' => [10, $this->decimal],
            'Sódio (mg)' => [10, $this->decimal],
            'Outros nutrientes' => [60, null],
            'Porção no rótulo' => [24, null],
            'Origem da tabela' => [24, null],
            'Observação' => [40, null],
        ];
        $this->iniciar($aba, 'Tabela nutricional', $w, $colunas);

        $estilos = array_column(array_values($colunas), 1);
        $linhas = 0;
        foreach ($itens as $p) {
            $v = $p['nutricional_padrao'] ?? null;
            if (! $v) {
                continue;
            }
            $n = $p['nutricional'] ?? [];
            $w->addRow(Row::fromValuesWithStyles([
                $p['id'],
                $p['marca'],
                $this->texto($p['nome']),
                Formato::categoria($p['categoria']),
                $v['porcao_g'],
                $v['energia_kcal'],
                $v['carboidratos_g'],
                $v['acucares_totais_g'],
                $v['acucares_adicionados_g'],
                $v['proteinas_g'],
                $v['proteina_pct'],
                $v['gorduras_totais_g'],
                $v['gorduras_saturadas_g'],
                $v['gorduras_trans_g'],
                $v['fibras_g'],
                $v['sodio_mg'],
                $this->texto($v['outros']),
                $n['porcao'] ?? null,
                isset($n['origem']) ? config('catalogo.origens_nutricional.'.$n['origem'], $n['origem']) : null,
                $v['inconsistente'] ? 'Valores descartados: '.$v['inconsistente'].'. Confira na loja.' : null,
            ], $estilos));
            $linhas++;
        }

        $this->filtrar($aba, count($colunas), $linhas);
    }

    private function historico(Sheet $aba, Writer $w, array $itens): void
    {
        $colunas = [
            'ID do produto' => [10, null],
            'Loja' => [20, null],
            'Produto' => [50, null],
            'Coleta' => [8, null],
            'Data' => [17, null],
            'Preço' => [12, $this->dinheiro],
            'Preço "de"' => [12, $this->dinheiro],
            'Em estoque' => [10, null],
        ];
        $this->iniciar($aba, 'Histórico de preços', $w, $colunas);

        $estilos = array_column(array_values($colunas), 1);
        $linhas = 0;
        foreach ($itens as $p) {
            foreach ($p['precos'] ?? [] as $h) {
                $w->addRow(Row::fromValuesWithStyles([
                    $p['id'],
                    $p['marca'],
                    $this->texto($p['nome']),
                    $h['coleta'],
                    Formato::data($h['data']),
                    $h['preco'],
                    $h['preco_de'],
                    $this->simNao($h['disponivel'] === null ? null : (bool) $h['disponivel']),
                ], $estilos));
                $linhas++;
            }
        }

        $this->filtrar($aba, count($colunas), $linhas);
    }

    private function filtros(Sheet $aba, Writer $w, array $exportacao, array $filtros): void
    {
        $this->iniciar($aba, 'Filtros', $w, ['Filtro' => [22, null], 'Valor' => [40, null]]);

        $w->addRow(Row::fromValues(['Gerado em', Formato::data($exportacao['gerado_em'])]));
        $w->addRow(Row::fromValues(['Produtos exportados', $exportacao['total']]));
        foreach ($filtros as $nome => $valor) {
            if ($valor === null || $valor === '') {
                continue;
            }
            $w->addRow(Row::fromValues([$nome, is_bool($valor) ? ($valor ? 'sim' : 'não') : (string) $valor]));
        }
    }

    /** Nome, larguras, cabeçalho em negrito e primeira linha congelada. */
    private function iniciar(Sheet $aba, string $nome, Writer $w, array $colunas): void
    {
        $aba->setName($nome);
        $aba->setSheetView((new SheetView)->withFreezeRow(2));
        $i = 1;
        foreach ($colunas as [$largura]) {
            $aba->setColumnWidth($largura, $i++);
        }
        $w->addRow(Row::fromValuesWithStyle(array_keys($colunas), $this->cabecalho));
    }

    /** Liga o filtro do Excel (setinhas no cabeçalho) sobre os dados escritos. */
    private function filtrar(Sheet $aba, int $colunas, int $linhas): void
    {
        $aba->setAutoFilter(new AutoFilter(0, 1, $colunas - 1, $linhas + 1));
    }

    private function simNao(?bool $valor): ?string
    {
        return $valor === null ? null : ($valor ? 'sim' : 'não');
    }

    /**
     * Texto numa linha só, que cabe numa célula e sem caracteres de controle
     * (o Excel recusa o arquivo). As lojas mandam modo de uso e advertências
     * cheios de quebras de linha, e cada quebra esticava a linha da planilha.
     */
    private function texto(?string $s): ?string
    {
        if ($s === null || $s === '') {
            return null;
        }
        $s = preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F]/u', '', $s) ?? '';
        $s = trim(preg_replace('/\s+/u', ' ', $s) ?? '');

        return mb_strlen($s) > self::MAX_CELULA ? mb_substr($s, 0, self::MAX_CELULA).'…' : $s;
    }
}
