<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="color-scheme" content="light dark">
    <title>{{ isset($titulo) ? $titulo.' · ' : '' }}{{ config('app.name') }}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..900&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
    @vite(['resources/css/app.css', 'resources/js/app.js'])
</head>
<body class="min-h-screen">
    <a href="#conteudo" class="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 bg-cartao px-3 py-2">Pular para o conteúdo</a>

    <header class="border-b-2 border-linha-forte">
        <div class="mx-auto flex max-w-7xl flex-wrap items-end justify-between gap-x-8 gap-y-3 px-4 py-4 sm:px-6">
            <a href="{{ route('painel') }}" class="no-underline" style="color: inherit">
                <span class="titulo block text-3xl sm:text-4xl">Catálogo de suplementos</span>
                <span class="rotulo-pequeno">Preços e composição coletados das lojas</span>
            </a>
            <nav aria-label="Principal" class="flex gap-1 text-sm font-medium">
                @php($atual = request()->route()?->getName())
                <a href="{{ route('painel') }}"
                   @class(['rounded-md px-3 py-1.5 no-underline', 'bg-tinta text-papel' => $atual === 'painel', 'text-tinta hover:bg-trilho' => $atual !== 'painel'])
                   @if ($atual === 'painel') aria-current="page" @endif>Visão geral</a>
                <a href="{{ route('produtos.index') }}"
                   @class(['rounded-md px-3 py-1.5 no-underline', 'bg-tinta text-papel' => str_starts_with($atual ?? '', 'produtos'), 'text-tinta hover:bg-trilho' => ! str_starts_with($atual ?? '', 'produtos')])
                   @if (str_starts_with($atual ?? '', 'produtos')) aria-current="page" @endif>Produtos</a>
            </nav>
        </div>
    </header>

    <main id="conteudo" class="mx-auto max-w-7xl px-4 py-8 sm:px-6">
        @yield('conteudo')
    </main>

    <footer class="mx-auto max-w-7xl px-4 pb-10 text-xs text-tinta-3 sm:px-6">
        Dados coletados das páginas públicas das lojas. Preços mudam com frequência:
        confira na loja antes de comprar.
    </footer>
</body>
</html>
