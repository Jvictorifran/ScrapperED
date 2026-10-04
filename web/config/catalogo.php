<?php

/*
 * Nomes de exibição para as chaves que vêm da API. As chaves em si são
 * definidas em categorias.yaml, no scraper — uma categoria nova lá aparece
 * aqui com o nome cru até ganhar um rótulo.
 */

return [

    'grupos' => [
        'proteina' => 'Proteína',
        'suplemento' => 'Suplemento',
        'alimento' => 'Alimento',
        'fora' => 'Fora do escopo',
    ],

    'categorias' => [
        'whey' => 'Whey',
        'proteina_vegetal' => 'Proteína vegetal',
        'proteina_outras' => 'Outras proteínas',
        'barra_proteica' => 'Barra proteica',
        'snack_proteico' => 'Snack proteico',
        'bebida_proteica' => 'Bebida proteica',
        'hipercalorico' => 'Hipercalórico',
        'creatina' => 'Creatina',
        'pre_treino' => 'Pré-treino',
        'aminoacido' => 'Aminoácido',
        'colageno' => 'Colágeno',
        'termogenico' => 'Termogênico',
        'carboidrato' => 'Carboidrato',
        'omega' => 'Ômega',
        'vitamina_mineral' => 'Vitamina e mineral',
        'outros_suplementos' => 'Outros suplementos',
        'alimento' => 'Alimento',
        'vestuario' => 'Vestuário',
        'acessorio' => 'Acessório',
        'cosmetico' => 'Cosmético',
    ],

    // de onde veio a classificação — mostrado no detalhe do produto
    'fontes' => [
        'nome' => 'no nome do produto',
        'categoria_loja' => 'na categoria da loja',
        'descricao' => 'na descrição',
        'ingredientes' => 'na lista de ingredientes',
    ],

    'origens_nutricional' => [
        'tabela' => 'tabela da página',
        'json' => 'dado estruturado da loja',
        'prosa' => 'texto corrido — estimativa',
        'ia_imagem' => 'lida da imagem do rótulo por IA',
    ],

];
