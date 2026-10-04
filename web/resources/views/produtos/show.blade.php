@extends('layouts.app', ['titulo' => $produto['nome']])
@use('App\Support\Formato')

@php
    $nutri = $produto['nutricional'] ?? [];
    $itens = $nutri['itens'] ?? [];
    $temVd = collect($itens)->contains(fn ($i) => filled($i['vd'] ?? null));
    $origem = $nutri['origem'] ?? null;
    $imagensRotulo = $nutri['imagens'] ?? [];
    $classificacao = $produto['classificacao'];
@endphp

@section('conteudo')
    <nav aria-label="Trilha" class="text-sm">
        <a href="{{ url()->previous() !== url()->current() ? url()->previous() : route('produtos.index') }}">← Voltar para a lista</a>
    </nav>

    <div class="mt-4 grid gap-10 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        {{-- coluna principal --}}
        <div>
            <p class="rotulo-pequeno">{{ $produto['marca'] }} · {{ Formato::categoria($produto['categoria']) }}@if ($produto['kit']) · kit @endif</p>
            <h1 class="titulo mt-2 text-4xl sm:text-5xl">{{ $produto['nome'] }}</h1>

            <dl class="mt-6 grid grid-cols-2 gap-x-6 gap-y-4 border-y border-linha py-5 sm:grid-cols-4">
                <div>
                    <dt class="rotulo-pequeno">Preço</dt>
                    <dd class="num mt-1 text-2xl font-medium">{{ Formato::brl($produto['preco']) }}</dd>
                    @if ($produto['preco_de'] && $produto['preco'] && $produto['preco_de'] > $produto['preco'])
                        <dd class="num text-xs text-tinta-3">de <s>{{ Formato::brl($produto['preco_de']) }}</s></dd>
                    @endif
                </div>
                <div>
                    <dt class="rotulo-pequeno">R$ por kg</dt>
                    <dd class="num mt-1 text-2xl font-medium">{{ Formato::porKg($produto['preco_por_kg']) }}</dd>
                </div>
                <div>
                    <dt class="rotulo-pequeno">Peso</dt>
                    <dd class="num mt-1 text-2xl">{{ Formato::peso($produto['peso_g']) }}</dd>
                </div>
                <div>
                    <dt class="rotulo-pequeno">Estoque</dt>
                    <dd class="mt-1 text-lg">
                        @if ($produto['disponivel'] === true)
                            <span class="text-ok">● Em estoque</span>
                        @elseif ($produto['disponivel'] === false)
                            <span class="text-nao">○ Esgotado</span>
                        @else
                            <span class="text-tinta-3">Não informado</span>
                        @endif
                    </dd>
                </div>
            </dl>

            <p class="mt-4 text-sm">
                <a href="{{ $produto['url'] }}" target="_blank" rel="noopener noreferrer">Ver na loja ↗</a>
                <span class="text-tinta-3"> · atualizado em {{ Formato::data($produto['atualizado_em']) }}</span>
            </p>

            @if ($produto['ingredientes'])
                <section aria-labelledby="titulo-ingredientes" class="mt-10">
                    <h2 id="titulo-ingredientes" class="titulo text-2xl">Ingredientes</h2>
                    <p class="mt-3 max-w-prose leading-relaxed text-tinta-2">{{ $produto['ingredientes'] }}</p>
                </section>
            @endif

            @if (count($precos) > 0)
                <section aria-labelledby="titulo-precos" class="mt-10">
                    <h2 id="titulo-precos" class="titulo text-2xl">Histórico de preço</h2>
                    <p class="mt-1 text-xs text-tinta-3">Uma linha por coleta. O histórico cresce a cada execução do scraper.</p>
                    <table class="mt-3 w-full max-w-md text-sm">
                        <thead>
                            <tr class="border-b border-linha-forte text-left">
                                <th scope="col" class="rotulo-pequeno py-1.5">Data</th>
                                <th scope="col" class="rotulo-pequeno py-1.5 text-right">Preço</th>
                                <th scope="col" class="rotulo-pequeno py-1.5 text-right">Estoque</th>
                            </tr>
                        </thead>
                        <tbody>
                            @foreach (array_reverse($precos) as $h)
                                <tr class="border-b border-linha">
                                    <td class="num py-1.5">{{ Formato::data($h['data']) }}</td>
                                    <td class="num py-1.5 text-right">{{ Formato::brl($h['preco']) }}</td>
                                    <td class="py-1.5 text-right text-xs">{{ $h['disponivel'] === 1 ? 'sim' : ($h['disponivel'] === 0 ? 'não' : '—') }}</td>
                                </tr>
                            @endforeach
                        </tbody>
                    </table>
                </section>
            @endif

            <section aria-labelledby="titulo-origem" class="mt-10 rounded-lg border border-linha bg-cartao p-4 text-sm">
                <h2 id="titulo-origem" class="rotulo-pequeno">De onde vêm estes dados</h2>
                <ul class="mt-2 space-y-1 text-tinta-2">
                    <li>
                        Categoria <strong class="text-tinta">{{ Formato::categoria($produto['categoria']) }}</strong>
                        @if ($classificacao && $classificacao['fonte'])
                            definida pelo termo “{{ $classificacao['termo'] }}” encontrado
                            {{ config('catalogo.fontes.'.$classificacao['fonte'], $classificacao['fonte']) }}.
                        @else
                            — nenhum termo de categorias.yaml casou com este produto.
                        @endif
                    </li>
                    @if ($produto['peso_g'])
                        <li>Peso lido do nome do produto; o R$/kg depende dele.</li>
                    @endif
                    @if ($produto['ean'])
                        <li>EAN <span class="num">{{ $produto['ean'] }}</span></li>
                    @endif
                    @if (count($produto['categorias_loja']))
                        <li>Categorias na loja: {{ implode(' · ', $produto['categorias_loja']) }}</li>
                    @endif
                </ul>
            </section>
        </div>

        {{-- coluna do rótulo --}}
        <aside aria-labelledby="titulo-nutricional" class="space-y-6">
            @if (count($produto['imagens']))
                <img src="{{ $produto['imagens'][0] }}" alt="Foto de {{ $produto['nome'] }}"
                     class="aspect-square w-full rounded-lg border border-linha bg-white object-contain p-4" loading="lazy">
            @endif

            @if (count($itens))
                <div class="rotulo-anvisa">
                    <h3 id="titulo-nutricional">Informação nutricional</h3>
                    @if (! empty($nutri['porcoes_por_embalagem']))
                        <p class="pt-1 text-xs">Porções por embalagem: {{ $nutri['porcoes_por_embalagem'] }}</p>
                    @endif
                    @if (! empty($nutri['porcao']))
                        <p class="text-xs">Porção: {{ $nutri['porcao'] }}</p>
                    @endif
                    <table class="mt-1">
                        <thead>
                            <tr>
                                <th scope="col" class="text-left"></th>
                                <th scope="col" class="text-right">Porção</th>
                                @if ($temVd)
                                    <th scope="col" class="w-14 text-right">%VD*</th>
                                @endif
                            </tr>
                        </thead>
                        <tbody>
                            @foreach ($itens as $i)
                                <tr>
                                    <td>{{ $i['nutriente'] }}</td>
                                    <td class="text-right">{{ $i['quantidade'] ?? '' }}</td>
                                    @if ($temVd)
                                        <td class="text-right">{{ filled($i['vd'] ?? null) ? rtrim($i['vd'], '%').(is_numeric(rtrim($i['vd'], '%')) ? '%' : '') : '' }}</td>
                                    @endif
                                </tr>
                            @endforeach
                        </tbody>
                    </table>
                    @if ($temVd)
                        <p class="pt-1.5 text-[0.6875rem] leading-snug">*Percentual de valores diários fornecidos pela porção.</p>
                    @endif
                </div>
                <p class="text-xs text-tinta-3">
                    Fonte: {{ config('catalogo.origens_nutricional.'.$origem, $origem ?? 'origem não registrada') }}.
                    @if ($origem === 'prosa')
                        Valores garimpados de texto — trate como estimativa.
                    @elseif ($origem === 'ia_imagem')
                        A loja publica a tabela só como imagem; ela foi transcrita por IA
                        @if (! empty($nutri['ia']['conferido'])) e conferida por um segundo leitor independente @endif.
                        @if (! empty($nutri['ia']['imagem']))
                            <a href="{{ $nutri['ia']['imagem'] }}" target="_blank" rel="noopener noreferrer">Ver a imagem original ↗</a>
                        @endif
                    @endif
                </p>
            @else
                <div class="rounded-lg border border-dashed border-linha p-5 text-sm">
                    <h3 id="titulo-nutricional" class="titulo text-xl">Sem tabela nutricional</h3>
                    @if (count($imagensRotulo))
                        <p class="mt-2 text-tinta-2">A loja publica a tabela só como imagem, que ainda não é lida automaticamente.</p>
                        <a href="{{ $imagensRotulo[0] }}" target="_blank" rel="noopener noreferrer" class="mt-2 inline-block">Abrir imagem do rótulo ↗</a>
                    @else
                        <p class="mt-2 text-tinta-2">A página da loja não traz a tabela em texto. Confira a embalagem na loja.</p>
                    @endif
                </div>
            @endif
        </aside>
    </div>
@endsection
