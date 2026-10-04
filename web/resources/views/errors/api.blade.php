@extends('layouts.app', ['titulo' => 'API indisponível'])

@section('conteudo')
    <div class="max-w-2xl">
        <p class="rotulo-pequeno">Erro {{ $motivo === 'offline' ? 503 : 502 }}</p>
        @if ($motivo === 'offline')
            <h1 class="titulo mt-2 text-5xl">A API do scraper não respondeu</h1>
            <p class="mt-4 text-tinta-2">
                Os dados vêm da API em Python, em <code class="num">{{ config('services.scraper.url') }}</code>,
                e ela não está no ar. Para subir, na pasta do scraper:
            </p>
            <pre class="num mt-4 overflow-x-auto rounded-lg border border-linha bg-cartao p-4 text-sm">./.venv/bin/uvicorn scraper.api:app --port 8001</pre>
            <p class="mt-4 text-sm text-tinta-2">
                Se a API roda em outro endereço, ajuste <code class="num">SCRAPER_API_URL</code> no <code class="num">.env</code> do Laravel.
            </p>
        @else
            <h1 class="titulo mt-2 text-5xl">A API do scraper devolveu um erro</h1>
            <p class="mt-4 text-tinta-2">
                Resposta HTTP <span class="num">{{ $status ?? '?' }}</span>. Veja o log da API (a saída do uvicorn) para o detalhe.
            </p>
        @endif
        <a href="{{ url()->current() }}" class="mt-6 inline-block rounded-md bg-tinta px-4 py-2 text-sm font-medium text-papel no-underline">Tentar de novo</a>
    </div>
@endsection
