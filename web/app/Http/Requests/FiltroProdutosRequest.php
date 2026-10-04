<?php

namespace App\Http\Requests;

use Illuminate\Foundation\Http\FormRequest;

/**
 * Filtros da lista de produtos. Usado pela listagem e pela exportação, para
 * o arquivo exportado conter exatamente o que a tela mostra.
 */
class FiltroProdutosRequest extends FormRequest
{
    public function rules(): array
    {
        return [
            'q' => ['nullable', 'string', 'max:100'],
            'loja' => ['nullable', 'string', 'max:40'],
            'grupo' => ['nullable', 'in:escopo,todos,proteina,suplemento,alimento,fora'],
            'categoria' => ['nullable', 'string', 'max:40'],
            'preco_min' => ['nullable', 'numeric', 'min:0'],
            'preco_max' => ['nullable', 'numeric', 'min:0'],
            'disponivel' => ['nullable', 'boolean'],
            'com_nutricional' => ['nullable', 'boolean'],
            'ordem' => ['nullable', 'in:nome,preco,preco_kg,loja'],
            'direcao' => ['nullable', 'in:asc,desc'],
            'pagina' => ['nullable', 'integer', 'min:1'],
        ];
    }

    /** Filtros como a tela os entende (grupo padrão = foco do TCC). */
    public function filtros(): array
    {
        $filtros = $this->validated();
        $filtros['grupo'] ??= 'escopo';

        return $filtros;
    }

    /** Filtros no formato da API do scraper, sem paginação. */
    public function paraApi(): array
    {
        $f = $this->filtros();

        return [
            'q' => $f['q'] ?? null,
            'loja' => $f['loja'] ?? null,
            // "todos" na tela = nenhum filtro de grupo na API
            'grupo' => $f['grupo'] === 'todos' ? null : $f['grupo'],
            'categoria' => $f['categoria'] ?? null,
            'preco_min' => $f['preco_min'] ?? null,
            'preco_max' => $f['preco_max'] ?? null,
            // checkbox marcado = só os que têm; desmarcado = sem filtro
            'disponivel' => ! empty($f['disponivel']) ? true : null,
            'com_nutricional' => ! empty($f['com_nutricional']) ? true : null,
            'ordem' => $f['ordem'] ?? null,
            'direcao' => $f['direcao'] ?? null,
        ];
    }
}
