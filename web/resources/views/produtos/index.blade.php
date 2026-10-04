@extends('layouts.app', ['titulo' => 'Produtos'])
@use('App\Support\Formato')

@php
    $ordem = $filtros['ordem'] ?? 'nome';
    $direcao = $filtros['direcao'] ?? 'asc';

    // link de ordenação: clicar na coluna atual inverte a direção
    $ordenar = function (string $coluna) use ($ordem, $direcao) {
        $nova = $ordem === $coluna && $direcao === 'asc' ? 'desc' : 'asc';
        return request()->fullUrlWithQuery(['ordem' => $coluna, 'direcao' => $nova, 'pagina' => null]);
    };
    $seta = fn (string $coluna) => $ordem === $coluna ? ($direcao === 'asc' ? '↑' : '↓') : '';
    $ariaSort = fn (string $coluna) => $ordem === $coluna ? ($direcao === 'asc' ? 'ascending' : 'descending') : 'none';
@endphp

@section('conteudo')
    <div class="flex flex-wrap items-baseline justify-between gap-4">
        <h1 class="titulo text-5xl">Produtos</h1>
        <div class="flex flex-wrap items-center gap-4">
            <p class="text-sm text-tinta-2" aria-live="polite">
                <span class="num text-tinta">{{ Formato::inteiro($produtos->total()) }}</span>
                {{ $produtos->total() === 1 ? 'produto encontrado' : 'produtos encontrados' }}
            </p>
            @if ($produtos->total() > 0)
                <a href="{{ route('produtos.exportar', request()->except('pagina')) }}"
                   class="inline-flex items-center gap-2 rounded-md border border-tinta px-3 py-1.5 text-sm font-medium text-tinta no-underline hover:bg-tinta hover:text-papel"
                   download>
                    Baixar planilha ({{ Formato::inteiro($produtos->total()) }})
                </a>
            @endif
        </div>
    </div>

    @if ($errors->any())
        <div role="alert" class="mt-6 rounded-lg border border-nao p-3 text-sm text-nao">
            @if ($errors->has('exportacao'))
                {{ $errors->first('exportacao') }}
            @else
                Filtro ignorado: {{ $errors->first() }}
            @endif
        </div>
    @endif

    <form method="get" action="{{ route('produtos.index') }}" class="mt-6 rounded-lg border border-linha bg-cartao p-4" role="search">
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-[1.6fr_1fr_1.4fr_1.2fr_0.6fr_0.6fr]">
            <label class="block">
                <span class="rotulo-pequeno">Buscar no nome</span>
                <input type="search" name="q" value="{{ $filtros['q'] ?? '' }}" placeholder="ex: creatina, isolado, 900g" class="campo mt-1">
            </label>
            <label class="block">
                <span class="rotulo-pequeno">Loja</span>
                <select name="loja" class="campo mt-1">
                    <option value="">Todas</option>
                    @foreach ($lojas as $l)
                        <option value="{{ $l['loja'] }}" @selected(($filtros['loja'] ?? '') === $l['loja'])>{{ $l['marca'] }}</option>
                    @endforeach
                </select>
            </label>
            <label class="block">
                <span class="rotulo-pequeno">Mostrar</span>
                <select name="grupo" class="campo mt-1">
                    <option value="escopo" @selected($filtros['grupo'] === 'escopo')>Suplementos e proteínas</option>
                    @foreach (config('catalogo.grupos') as $chave => $nome)
                        <option value="{{ $chave }}" @selected($filtros['grupo'] === $chave)>Só {{ mb_strtolower($nome) }}</option>
                    @endforeach
                    <option value="todos" @selected($filtros['grupo'] === 'todos')>Tudo, inclusive roupas</option>
                </select>
            </label>
            <label class="block">
                <span class="rotulo-pequeno">Categoria</span>
                <select name="categoria" class="campo mt-1">
                    <option value="">Todas</option>
                    @foreach ($categorias as $grupo => $itens)
                        <optgroup label="{{ Formato::grupo($grupo) }}">
                            @foreach ($itens as $c)
                                <option value="{{ $c['categoria'] }}" @selected(($filtros['categoria'] ?? '') === $c['categoria'])>
                                    {{ Formato::categoria($c['categoria']) }} ({{ $c['produtos'] }})
                                </option>
                            @endforeach
                        </optgroup>
                    @endforeach
                </select>
            </label>
            <label class="block">
                <span class="rotulo-pequeno">Preço mín.</span>
                <input type="number" name="preco_min" min="0" step="1" inputmode="decimal" value="{{ $filtros['preco_min'] ?? '' }}" class="campo num mt-1">
            </label>
            <label class="block">
                <span class="rotulo-pequeno">Preço máx.</span>
                <input type="number" name="preco_max" min="0" step="1" inputmode="decimal" value="{{ $filtros['preco_max'] ?? '' }}" class="campo num mt-1">
            </label>
        </div>

        <div class="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
            <label class="inline-flex items-center gap-2">
                <input type="checkbox" name="disponivel" value="1" @checked(! empty($filtros['disponivel'])) class="size-4 accent-[var(--acento)]">
                Só em estoque
            </label>
            <label class="inline-flex items-center gap-2">
                <input type="checkbox" name="com_nutricional" value="1" @checked(! empty($filtros['com_nutricional'])) class="size-4 accent-[var(--acento)]">
                Só com tabela nutricional
            </label>
            <input type="hidden" name="ordem" value="{{ $ordem }}">
            <input type="hidden" name="direcao" value="{{ $direcao }}">
            <div class="ml-auto flex gap-2">
                <a href="{{ route('produtos.index') }}" class="rounded-md px-3 py-1.5 text-tinta-2 no-underline hover:bg-trilho">Limpar filtros</a>
                <button type="submit" class="rounded-md bg-tinta px-4 py-1.5 font-medium text-papel hover:opacity-90">Filtrar</button>
            </div>
        </div>
    </form>

    @if ($produtos->isEmpty())
        <div class="mt-10 rounded-lg border border-dashed border-linha p-10 text-center">
            <p class="titulo text-2xl">Nenhum produto com esses filtros</p>
            <p class="mt-2 text-sm text-tinta-2">Tente tirar a loja ou a faixa de preço, ou busque por uma parte do nome.</p>
            <a href="{{ route('produtos.index') }}" class="mt-4 inline-block text-sm">Limpar filtros</a>
        </div>
    @else
        <div class="mt-6 overflow-x-auto">
            <table class="w-full text-sm">
                <thead>
                    <tr class="border-b-2 border-linha-forte text-left">
                        <th scope="col" class="py-2 pr-4" aria-sort="{{ $ariaSort('nome') }}">
                            <a href="{{ $ordenar('nome') }}" class="rotulo-pequeno whitespace-nowrap no-underline">Produto {{ $seta('nome') }}</a>
                        </th>
                        <th scope="col" class="rotulo-pequeno hidden py-2 pr-4 md:table-cell">Categoria</th>
                        <th scope="col" class="rotulo-pequeno hidden py-2 pr-4 text-right md:table-cell">Peso</th>
                        <th scope="col" class="py-2 pr-4 text-right" aria-sort="{{ $ariaSort('preco') }}">
                            <a href="{{ $ordenar('preco') }}" class="rotulo-pequeno whitespace-nowrap no-underline">Preço {{ $seta('preco') }}</a>
                        </th>
                        <th scope="col" class="py-2 pr-4 text-right" aria-sort="{{ $ariaSort('preco_kg') }}">
                            <a href="{{ $ordenar('preco_kg') }}" class="rotulo-pequeno whitespace-nowrap no-underline">R$ / kg {{ $seta('preco_kg') }}</a>
                        </th>
                        <th scope="col" class="rotulo-pequeno py-2">Estoque</th>
                    </tr>
                </thead>
                <tbody>
                    @foreach ($produtos as $p)
                        <tr class="border-b border-linha align-top hover:bg-trilho/60">
                            <td class="py-2.5 pr-4">
                                <a href="{{ route('produtos.show', $p['id']) }}" class="font-medium">{{ $p['nome'] }}</a>
                                <span class="mt-0.5 block text-xs text-tinta-3">
                                    {{ $p['marca'] }}@if ($p['kit']) · kit @endif<span class="md:hidden">@if ($p['peso_g']) · {{ Formato::peso($p['peso_g']) }}@endif</span>
                                </span>
                            </td>
                            <td class="hidden whitespace-nowrap py-2.5 pr-4 text-tinta-2 md:table-cell">{{ Formato::categoria($p['categoria']) }}</td>
                            <td class="num hidden whitespace-nowrap py-2.5 pr-4 text-right text-tinta-2 md:table-cell">{{ Formato::peso($p['peso_g']) }}</td>
                            <td class="num whitespace-nowrap py-2.5 pr-4 text-right">
                                {{ Formato::brl($p['preco']) }}
                                @if ($p['preco_de'] && $p['preco'] && $p['preco_de'] > $p['preco'])
                                    <s class="block text-xs text-tinta-3">{{ Formato::brl($p['preco_de']) }}</s>
                                @endif
                            </td>
                            <td class="num whitespace-nowrap py-2.5 pr-4 text-right font-medium">{{ Formato::porKg($p['preco_por_kg']) }}</td>
                            <td class="whitespace-nowrap py-2.5 text-xs">
                                @if ($p['disponivel'] === true)
                                    <span class="text-ok">● Em estoque</span>
                                @elseif ($p['disponivel'] === false)
                                    <span class="text-nao">○ Esgotado</span>
                                @else
                                    <span class="text-tinta-3">—</span>
                                @endif
                            </td>
                        </tr>
                    @endforeach
                </tbody>
            </table>
        </div>

        <div class="mt-6">
            {{ $produtos->onEachSide(1)->links() }}
        </div>
    @endif
@endsection
