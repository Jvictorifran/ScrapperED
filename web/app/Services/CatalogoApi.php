<?php

namespace App\Services;

use Illuminate\Http\Client\PendingRequest;
use Illuminate\Http\Client\Response;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Http;

/**
 * Cliente da API do scraper (scraper/api.py).
 *
 * O Laravel não acessa o banco do scraper: tudo passa por aqui. Se a API
 * estiver fora do ar, as chamadas lançam ConnectionException, que o
 * bootstrap/app.php transforma numa página explicando como subi-la.
 */
class CatalogoApi
{
    /** Listas que mudam só quando o scraper roda: vale guardar um pouco. */
    private const CACHE_SEGUNDOS = 300;

    private function http(): PendingRequest
    {
        return Http::baseUrl(config('services.scraper.url'))
            ->timeout(config('services.scraper.timeout'))
            ->acceptJson();
    }

    private function get(string $caminho, array $query = []): array
    {
        return $this->http()->get($caminho, $query)->throw()->json();
    }

    public function resumo(): array
    {
        return Cache::remember('catalogo.resumo', self::CACHE_SEGUNDOS, fn () => $this->get('/resumo'));
    }

    public function lojas(): array
    {
        return Cache::remember('catalogo.lojas', self::CACHE_SEGUNDOS, fn () => $this->get('/lojas'));
    }

    public function categorias(): array
    {
        return Cache::remember('catalogo.categorias', self::CACHE_SEGUNDOS, fn () => $this->get('/categorias'));
    }

    public function comparativo(string $categoria = 'whey'): array
    {
        return Cache::remember(
            "catalogo.comparativo.$categoria",
            self::CACHE_SEGUNDOS,
            fn () => $this->get('/comparativo', ['categoria' => $categoria]),
        );
    }

    /** @param  array<string, mixed>  $filtros  já validados pelo controller */
    public function produtos(array $filtros): array
    {
        return $this->get('/produtos', $this->query($filtros));
    }

    /** Tira os vazios e manda booleanos como "true"/"false", que é o que a API entende. */
    private function query(array $filtros): array
    {
        return array_map(
            fn ($v) => is_bool($v) ? ($v ? 'true' : 'false') : $v,
            array_filter($filtros, fn ($v) => $v !== null && $v !== ''),
        );
    }

    /**
     * Todos os produtos do filtro, completos, para exportar. Pode ser lento
     * em filtros grandes: o timeout é maior que o das outras chamadas.
     */
    public function exportacao(array $filtros): Response
    {
        return $this->http()
            ->timeout(max(60, config('services.scraper.timeout')))
            ->get('/exportacao', $this->query($filtros));
    }

    /** Devolve null quando o produto não existe (404 na API). */
    public function produto(int $id): ?array
    {
        $resposta = $this->http()->get("/produtos/$id");
        if ($resposta->notFound()) {
            return null;
        }

        return $resposta->throw()->json();
    }

    public function precos(int $id): array
    {
        return $this->get("/produtos/$id/precos");
    }
}
