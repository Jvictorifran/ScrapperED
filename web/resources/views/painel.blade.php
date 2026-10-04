@extends('layouts.app')
@use('App\Support\Formato')

@section('conteudo')
    @php
        $linhas = $comparativo['lojas'];
        $maior = collect($linhas)->max('mediana') ?: 1;
        $nProdutos = collect($linhas)->sum('produtos');
    @endphp

    {{-- 1. A pergunta que os dados respondem melhor --}}
    <section aria-labelledby="titulo-whey" class="grid gap-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-12">
        <div>
            <p class="rotulo-pequeno">Comparativo de preço</p>
            <h1 id="titulo-whey" class="titulo mt-2 text-5xl sm:text-6xl">Quanto custa 1&nbsp;kg de whey em cada loja</h1>
            <p class="mt-4 max-w-prose text-tinta-2">
                Preço por quilo mediano de {{ $nProdutos }} wheys em {{ count($linhas) }} lojas.
                Entram só embalagens a partir de {{ Formato::peso($comparativo['peso_min']) }}, sem kits, porque
                sachês e combos distorcem o preço por quilo.
            </p>
            @if (count($linhas))
                <p class="mt-6 text-sm text-tinta-2">
                    A diferença entre a loja mais barata e a mais cara é de
                    <strong class="num text-tinta">{{ number_format(collect($linhas)->last()['mediana'] / collect($linhas)->first()['mediana'], 1, ',', '.') }}×</strong>.
                </p>
            @endif
            <p class="mt-6 text-xs text-tinta-3">
                O peso é lido do nome do produto. Usamos a mediana porque ela não se deixa levar
                por um anúncio com peso errado.
            </p>
        </div>

        <figure>
            <figcaption class="sr-only">R$ por quilo, mediana por loja, da mais barata para a mais cara</figcaption>
            <ol class="space-y-1.5">
                @foreach ($linhas as $l)
                    <li>
                        <a href="{{ route('produtos.index', ['loja' => $l['loja'], 'categoria' => 'whey', 'ordem' => 'preco_kg']) }}"
                           class="group relative grid grid-cols-[7.5rem_1fr_4.5rem] items-center gap-3 rounded-md px-1 py-1 text-sm no-underline hover:bg-trilho sm:grid-cols-[10rem_1fr_5rem]"
                           style="color: inherit"
                           aria-label="{{ $l['marca'] }}: {{ Formato::porKg($l['mediana']) }} por quilo, mediana de {{ $l['produtos'] }} produtos, de {{ Formato::porKg($l['minimo']) }} a {{ Formato::porKg($l['maximo']) }}">
                            <span class="truncate">{{ $l['marca'] }}</span>
                            <span class="h-3.5 rounded-r-[4px] bg-barra" style="width: {{ max(2, $l['mediana'] / $maior * 100) }}%"></span>
                            <span class="num text-right font-medium">{{ Formato::porKg($l['mediana']) }}</span>

                            {{-- tooltip: n e faixa --}}
                            <span role="presentation"
                                  class="pointer-events-none absolute right-0 top-full z-10 mt-1 hidden w-56 rounded-md border border-linha bg-cartao p-2.5 text-xs shadow-lg group-hover:block group-focus-visible:block">
                                <span class="block font-semibold">{{ $l['marca'] }}</span>
                                <span class="num mt-1 block text-tinta-2">{{ $l['produtos'] }} {{ $l['produtos'] === 1 ? 'produto' : 'produtos' }}</span>
                                <span class="num block text-tinta-2">de {{ Formato::porKg($l['minimo']) }} a {{ Formato::porKg($l['maximo']) }} / kg</span>
                            </span>
                        </a>
                    </li>
                @endforeach
            </ol>
            <p class="mt-3 text-xs text-tinta-3">R$ por kg · clique numa loja para ver os wheys dela</p>
        </figure>
    </section>

    {{-- 2. O que tem no banco --}}
    <section aria-labelledby="titulo-banco" class="mt-16 border-t-2 border-linha-forte pt-6">
        <div class="flex flex-wrap items-baseline justify-between gap-4">
            <h2 id="titulo-banco" class="titulo text-3xl">O que foi coletado</h2>
            <p class="text-sm text-tinta-2">
                <span class="num text-tinta">{{ Formato::inteiro($resumo['total']) }}</span> produtos,
                <span class="num text-tinta">{{ Formato::inteiro($resumo['no_escopo']) }}</span> deles suplementos ou proteínas
                · última coleta {{ Formato::data($resumo['ultima_coleta']['finished_at'] ?? null) }}
            </p>
        </div>

        <div class="mt-4 overflow-x-auto">
            <table class="w-full min-w-[44rem] text-sm">
                <thead>
                    <tr class="border-b border-linha-forte text-left">
                        <th scope="col" class="rotulo-pequeno py-2 pr-4">Loja</th>
                        <th scope="col" class="rotulo-pequeno py-2 pr-4 text-right">Produtos</th>
                        <th scope="col" class="rotulo-pequeno py-2 pr-4 text-right">No escopo</th>
                        <th scope="col" class="rotulo-pequeno py-2 pr-4 text-right" title="Produtos com código de barras">Com EAN</th>
                        <th scope="col" class="rotulo-pequeno py-2 pr-4 text-right">Com ingredientes</th>
                        <th scope="col" class="rotulo-pequeno py-2 pr-4 text-right">Com tabela nutricional</th>
                        <th scope="col" class="rotulo-pequeno py-2 text-right">Preço médio</th>
                    </tr>
                </thead>
                <tbody>
                    @foreach ($resumo['lojas'] as $l)
                        <tr class="border-b border-linha">
                            <th scope="row" class="py-2 pr-4 text-left font-medium">
                                <a href="{{ route('produtos.index', ['loja' => $l['loja']]) }}">{{ $l['marca'] }}</a>
                            </th>
                            <td class="num py-2 pr-4 text-right">{{ Formato::inteiro($l['produtos']) }}</td>
                            <td class="num py-2 pr-4 text-right">{{ Formato::inteiro($l['no_escopo']) }}</td>
                            <td class="num py-2 pr-4 text-right text-tinta-2">{{ Formato::pct($l['com_ean'], $l['produtos']) }}</td>
                            <td class="num py-2 pr-4 text-right text-tinta-2">{{ Formato::pct($l['com_ingredientes'], $l['produtos']) }}</td>
                            <td class="num py-2 pr-4 text-right text-tinta-2">{{ Formato::pct($l['com_nutricional'], $l['produtos']) }}</td>
                            <td class="num py-2 text-right">{{ Formato::brl($l['preco_medio']) }}</td>
                        </tr>
                    @endforeach
                </tbody>
            </table>
        </div>
        <p class="mt-2 text-xs text-tinta-3">
            Percentuais sobre todos os produtos da loja. Tabela nutricional publicada só como imagem não é extraída.
        </p>
    </section>

    {{-- 3. Atalhos por categoria --}}
    <section aria-labelledby="titulo-categorias" class="mt-16 border-t-2 border-linha-forte pt-6">
        <h2 id="titulo-categorias" class="titulo text-3xl">Por categoria</h2>
        <div class="mt-4 grid gap-6 sm:grid-cols-2">
            @foreach (['proteina', 'suplemento'] as $grupo)
                <div>
                    <h3 class="rotulo-pequeno">{{ Formato::grupo($grupo) }}</h3>
                    <ul class="mt-2 flex flex-wrap gap-2">
                        @foreach ($categorias[$grupo] ?? [] as $c)
                            <li>
                                <a href="{{ route('produtos.index', ['categoria' => $c['categoria']]) }}"
                                   class="inline-flex items-baseline gap-2 rounded-full border border-linha bg-cartao px-3 py-1 text-sm no-underline hover:border-tinta"
                                   style="color: inherit">
                                    {{ Formato::categoria($c['categoria']) }}
                                    <span class="num text-xs text-tinta-3">{{ $c['produtos'] }}</span>
                                </a>
                            </li>
                        @endforeach
                    </ul>
                </div>
            @endforeach
        </div>
    </section>
@endsection
