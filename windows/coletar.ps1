# Coleta completa: lojas -> rótulos em imagem (IA) -> exportação CSV/JSON.
# Chamado pela tarefa agendada (ver instalar.ps1); também pode rodar à mão:
#   powershell -ExecutionPolicy Bypass -File windows\coletar.ps1
#
# Cada execução grava um log em logs\coleta-AAAA-MM-DD_HHMM.log.

$ErrorActionPreference = 'Stop'
$Raiz = Split-Path -Parent $PSScriptRoot
Set-Location $Raiz

# os comandos usam caminhos relativos (data\, sites.yaml) e imprimem acentos;
# o console do Windows é cp1252 e quebraria no primeiro "≥"
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$Python = Join-Path $Raiz '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    throw "Ambiente Python não encontrado em $Python. Rode windows\instalar.ps1 primeiro."
}

New-Item -ItemType Directory -Force -Path (Join-Path $Raiz 'logs') | Out-Null
$Log = Join-Path $Raiz ("logs\coleta-{0}.log" -f (Get-Date -Format 'yyyy-MM-dd_HHmm'))

function Escrever([string]$Texto) {
    $linha = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $Texto
    Add-Content -Path $Log -Value $linha -Encoding UTF8
    Write-Host $linha
}

# Uma coleta por vez: as lojas VTEX devolvem vazio com requisições paralelas
# ao mesmo host. O arquivo fica aberto sem compartilhamento enquanto roda e o
# Windows o libera sozinho se o processo morrer.
New-Item -ItemType Directory -Force -Path (Join-Path $Raiz 'data') | Out-Null
$Trava = Join-Path $Raiz 'data\coleta.lock'
try {
    $handle = [System.IO.File]::Open($Trava, 'OpenOrCreate', 'ReadWrite', 'None')
} catch {
    Escrever "Outra coleta já está rodando; saindo."
    exit 0
}

function Etapa([string]$Nome, [string[]]$Argumentos) {
    Escrever "== $Nome"
    # cmd /c: o PowerShell 5 trata cada linha de stderr (o logging do Python)
    # como erro e abortaria a etapa
    $cmd = '"{0}" -m scraper {1} >> "{2}" 2>&1' -f $Python, ($Argumentos -join ' '), $Log
    cmd /c $cmd
    $codigo = $LASTEXITCODE
    # código 1 = alguma loja ou imagem falhou; o resto foi gravado
    Escrever "$Nome terminou com código $codigo"
    return $codigo
}

try {
    Escrever "Início da coleta em $Raiz"
    $falhas = 0
    $falhas += [int]((Etapa 'Coleta das lojas' @('run')) -ne 0)

    $temChave = $env:IA_CHAVE -or $env:ANTHROPIC_API_KEY -or (
        (Test-Path '.env') -and (Select-String -Path '.env' -Pattern '^\s*(IA_CHAVE|ANTHROPIC_API_KEY)\s*=\s*\S' -Quiet))
    if ($temChave) {
        $falhas += [int]((Etapa 'Leitura de rótulos (IA)' @('ler-rotulos')) -ne 0)
    } else {
        Escrever "Sem IA_CHAVE no .env: leitura de rótulos pulada."
    }

    $falhas += [int]((Etapa 'Exportação' @('export')) -ne 0)
    Escrever ("Fim. Etapas com falha parcial: {0}" -f $falhas)

    # logs com mais de 60 dias
    Get-ChildItem (Join-Path $Raiz 'logs') -Filter 'coleta-*.log' |
        Where-Object LastWriteTime -lt (Get-Date).AddDays(-60) |
        Remove-Item -ErrorAction SilentlyContinue
} finally {
    $handle.Close()
}
