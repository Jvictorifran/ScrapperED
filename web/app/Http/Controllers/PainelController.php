<?php

namespace App\Http\Controllers;

use App\Services\CatalogoApi;
use Illuminate\View\View;

class PainelController extends Controller
{
    public function __invoke(CatalogoApi $api): View
    {
        return view('painel', [
            'resumo' => $api->resumo(),
            'comparativo' => $api->comparativo('whey'),
            'categorias' => collect($api->categorias())->groupBy('grupo'),
        ]);
    }
}
