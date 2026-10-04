<?php

use App\Http\Controllers\PainelController;
use App\Http\Controllers\ProdutoController;
use Illuminate\Support\Facades\Route;

Route::get('/', PainelController::class)->name('painel');
Route::get('/produtos', [ProdutoController::class, 'index'])->name('produtos.index');
Route::get('/produtos/exportar.xlsx', [ProdutoController::class, 'exportar'])->name('produtos.exportar');
Route::get('/produtos/{id}', [ProdutoController::class, 'show'])->whereNumber('id')->name('produtos.show');
