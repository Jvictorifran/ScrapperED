<?php

namespace App\Http\Controllers;

use App\Exports\ProdutosPlanilha;
use App\Http\Requests\FiltroProdutosRequest;
use App\Services\CatalogoApi;
use Illuminate\Http\RedirectResponse;
use Illuminate\Pagination\LengthAwarePaginator;
use Illuminate\View\View;
use Symfony\Component\HttpFoundation\BinaryFileResponse;

class ProdutoController extends Controller
{
    private const POR_PAGINA = 50;

    public function index(FiltroProdutosRequest $request, CatalogoApi $api): View
    {
        $filtros = $request->filtros();
        $pagina = (int) ($filtros['pagina'] ?? 1);

        $resultado = $api->produtos([
            ...$request->paraApi(),
            'pagina' => $pagina,
            'por_pagina' => self::POR_PAGINA,
        ]);

        $produtos = new LengthAwarePaginator(
            $resultado['itens'],
            $resultado['total'],
            self::POR_PAGINA,
            $pagina,
            ['path' => $request->url(), 'query' => $request->except('pagina'), 'pageName' => 'pagina'],
        );

        return view('produtos.index', [
            'produtos' => $produtos,
            'filtros' => $filtros,
            'lojas' => $api->lojas(),
            'categorias' => collect($api->categorias())->groupBy('grupo'),
        ]);
    }

    /** Baixa em planilha (.xlsx) todos os produtos do filtro atual, não só a página. */
    public function exportar(FiltroProdutosRequest $request, CatalogoApi $api, ProdutosPlanilha $planilha): BinaryFileResponse|RedirectResponse
    {
        $filtros = $request->paraApi();
        $resposta = $api->exportacao($filtros);

        if ($resposta->status() === 413) {
            return redirect()
                ->route('produtos.index', $request->query())
                ->withErrors(['exportacao' => 'Filtro grande demais para exportar de uma vez. Restrinja por loja ou categoria.']);
        }
        $dados = $resposta->throw()->json();

        // xlsx é um zip: precisa existir inteiro antes de ser enviado
        $temporario = tempnam(sys_get_temp_dir(), 'produtos');
        $planilha->gravar($temporario, $dados, $filtros);

        return response()
            ->download($temporario, 'produtos-'.now('America/Sao_Paulo')->format('Y-m-d-His').'.xlsx', [
                'Content-Type' => 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            ])
            ->deleteFileAfterSend();
    }

    public function show(int $id, CatalogoApi $api): View
    {
        $produto = $api->produto($id) ?? abort(404, 'Produto não encontrado.');

        return view('produtos.show', [
            'produto' => $produto,
            'precos' => $api->precos($id),
        ]);
    }
}
