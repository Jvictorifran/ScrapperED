<?php

namespace App\Support;

use Illuminate\Support\Carbon;

/** Formatação de valores para as views, no padrão brasileiro. */
class Formato
{
    public static function brl(?float $valor): string
    {
        return $valor === null ? '—' : 'R$ '.number_format($valor, 2, ',', '.');
    }

    /** R$/kg sem centavos: é número de comparação, não de etiqueta. */
    public static function porKg(?float $valor): string
    {
        return $valor === null ? '—' : 'R$ '.number_format($valor, 0, ',', '.');
    }

    public static function peso(?float $gramas): string
    {
        if ($gramas === null) {
            return '—';
        }

        return $gramas >= 1000
            ? rtrim(rtrim(number_format($gramas / 1000, 2, ',', '.'), '0'), ',').' kg'
            : number_format($gramas, 0, ',', '.').' g';
    }

    public static function inteiro(?int $n): string
    {
        return $n === null ? '—' : number_format($n, 0, ',', '.');
    }

    public static function data(?string $iso): string
    {
        return $iso ? Carbon::parse($iso)->timezone('America/Sao_Paulo')->format('d/m/Y H:i') : '—';
    }

    public static function categoria(?string $chave): string
    {
        return $chave ? (config("catalogo.categorias.$chave") ?? $chave) : 'Sem categoria';
    }

    public static function grupo(?string $chave): string
    {
        return $chave ? (config("catalogo.grupos.$chave") ?? $chave) : 'Sem grupo';
    }

    /** Percentual inteiro, para as colunas de cobertura. */
    public static function pct(int $parte, int $total): string
    {
        return $total ? round($parte / $total * 100).'%' : '—';
    }
}
