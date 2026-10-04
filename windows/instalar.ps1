# Instalação no Windows: ambiente Python, chave da API e tarefa agendada.
#
#   powershell -ExecutionPolicy Bypass -File windows\instalar.ps1
#   powershell -ExecutionPolicy Bypass -File windows\instalar.ps1 -Horario 06:30
#   powershell -ExecutionPolicy Bypass -File windows\instalar.ps1 -SemAgendamento
#
# Pode rodar de novo sem problema: reaproveita o que já existe.

param(
    [string]$Horario = '03:00',
    [switch]$SemAgendamento
)

$ErrorActionPreference = 'Stop'
$Raiz = Split-Path -Parent $PSScriptRoot
Set-Location $Raiz
$NomeTarefa = 'ScrappingTcc - coleta diaria'

function Passo([string]$Texto) { Write-Host "`n>> $Texto" -ForegroundColor Cyan }

# --- 1. Python ---------------------------------------------------------------
Passo 'Procurando o Python (3.12 ou mais novo)'
$py = $null
foreach ($candidato in @(@('py', '-3'), @('python'))) {
    $exe = $candidato[0]
    $extra = @($candidato | Select-Object -Skip 1)
    if (Get-Command $exe -ErrorAction SilentlyContinue) {
        $versao = & $exe @extra -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $versao -and [version]$versao -ge [version]'3.12') {
            $py = $candidato
            break
        }
    }
}
if (-not $py) {
    throw ("Python 3.12+ não encontrado. Instale pelo site python.org (marque " +
           "'Add python.exe to PATH') e rode este script de novo.")
}
Write-Host "Usando: $($py -join ' ') ($versao)"

# --- 2. Ambiente virtual e dependências --------------------------------------
$Python = Join-Path $Raiz '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    Passo 'Criando o ambiente virtual (.venv)'
    $extra = @($py | Select-Object -Skip 1)
    & $py[0] @extra -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar o .venv' }
}
Passo 'Instalando dependências'
& $Python -m pip install --upgrade pip --quiet
& $Python -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { throw 'Falha no pip install' }

# --- 3. Chave da API (leitura de rótulos) -------------------------------------
$Env = Join-Path $Raiz '.env'
$temChave = (Test-Path $Env) -and (Select-String -Path $Env -Pattern '^\s*(IA_CHAVE|ANTHROPIC_API_KEY)\s*=\s*\S' -Quiet)
if ($temChave) {
    Write-Host "`n.env já tem a chave de IA; mantida."
} else {
    Passo 'Chave da API de IA (para ler tabelas nutricionais em imagem)'
    Write-Host 'Serve chave de Anthropic, OpenAI, Gemini, DeepSeek ou OpenRouter: o provedor é reconhecido pela chave.'
    Write-Host 'Cole a chave e tecle Enter (ela não aparece na tela). Enter vazio = pular.'
    $segura = Read-Host -AsSecureString 'Chave'
    $chave = [System.Net.NetworkCredential]::new('', $segura).Password.Trim()
    if ($chave) {
        $linhas = @()
        if (Test-Path $Env) { $linhas = Get-Content $Env | Where-Object { $_ -notmatch '^\s*(IA_CHAVE|ANTHROPIC_API_KEY)\s*=' } }
        $linhas += "IA_CHAVE=$chave"
        # UTF-8 sem BOM (o Set-Content do PowerShell 5 grava com BOM)
        [System.IO.File]::WriteAllLines($Env, [string[]]$linhas, [System.Text.UTF8Encoding]::new($false))
        Write-Host '.env gravado. Ele fica só nesta máquina.'
    } else {
        Write-Host 'Sem chave: a coleta roda, mas a leitura de rótulos fica desligada.'
    }
}

# --- 4. Teste rápido ------------------------------------------------------------
Passo 'Testando a instalação'
$env:PYTHONUTF8 = '1'
& $Python -m scraper sites
if ($LASTEXITCODE -ne 0) { throw 'O scraper não iniciou; veja a mensagem acima.' }

# --- 5. Tarefa agendada ------------------------------------------------------
if ($SemAgendamento) {
    Write-Host "`nAgendamento pulado (-SemAgendamento)."
} else {
    Passo "Agendando a coleta diária às $Horario"
    $script = Join-Path $Raiz 'windows\coletar.ps1'
    $acao = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`"" `
        -WorkingDirectory $Raiz
    $gatilho = New-ScheduledTaskTrigger -Daily -At $Horario
    # StartWhenAvailable: se o PC estava desligado no horário, roda assim que
    # ligar. IgnoreNew: nunca duas coletas ao mesmo tempo.
    $config = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Hours 6)
    Register-ScheduledTask -TaskName $NomeTarefa -Action $acao -Trigger $gatilho -Settings $config `
        -Description 'Coleta as lojas de suplementos, lê rótulos novos e exporta (ScrappingTcc).' -Force | Out-Null
    Write-Host "Tarefa '$NomeTarefa' criada. Ela roda com o seu usuário logado."
}

Write-Host "`nPronto." -ForegroundColor Green
Write-Host 'Rodar agora, à mão:   powershell -ExecutionPolicy Bypass -File windows\coletar.ps1'
Write-Host "Ver a tarefa:         Agendador de Tarefas > '$NomeTarefa'"
Write-Host 'Logs:                 pasta logs\'
