# Instalação no Windows

Guia para deixar o scraper rodando sozinho, todo dia, num computador Windows:
coleta as lojas, lê por IA as tabelas nutricionais que só existem em imagem e
exporta CSV/JSON. Tempo total: uns 20 minutos.

## 1. O que instalar

### Obrigatório

| Programa | Versão | Para quê | Download |
|---|---|---|---|
| **Python** | 3.12 ou 3.13 (recomendado: 3.13) | roda o scraper | <https://www.python.org/downloads/windows/> |
| **Chave de API de IA** (qualquer provedor da tabela abaixo) | — | leitura das tabelas nutricionais em imagem | ver tabela abaixo |

Na instalação do Python, **marque "Add python.exe to PATH"** na primeira tela.
O lançador `py` vem junto e é o que o instalador do projeto procura primeiro.

#### Chave de IA: qualquer um destes provedores

Basta **uma** chave. O provedor é reconhecido pelo formato dela; para trocar
de provedor, é só trocar a chave no `.env`.

| Provedor | A chave começa com | Criar a chave | Colocar crédito | Modelo usado (padrão) |
|---|---|---|---|---|
| DeepSeek | `sk-` + 32 letras/números | <https://platform.deepseek.com/api_keys> | <https://platform.deepseek.com/top_up> | `deepseek-chat` |
| Anthropic (Claude) | `sk-ant-` | <https://console.anthropic.com/settings/keys> | <https://console.anthropic.com/settings/billing> | `claude-opus-5-5` |
| OpenAI | `sk-proj-` | <https://platform.openai.com/api-keys> | <https://platform.openai.com/settings/organization/billing> | `gpt-4.1` |
| Google Gemini | `AIza` | <https://aistudio.google.com/app/apikey> | (tem cota gratuita) | `gemini-2.5-flash` |
| OpenRouter (acesso a vários) | `sk-or-` | <https://openrouter.ai/keys> | <https://openrouter.ai/credits> | `openai/gpt-4.1` |

O modelo precisa **ler imagem**. Para usar outro modelo do mesmo provedor,
coloque `IA_MODELO=nome-do-modelo` no `.env` (veja `.env.example`).

A chave DeepSeek do cliente foi testada em 2026-10-02 contra leituras já
conferidas: 20 de 20 rótulos idênticos (352 de 352 campos), incluindo fotos de
embalagem. Leituras guardadas em `data\rotulos_ia\deepseek\`.

As bibliotecas Python (requests, lxml, brotli, anthropic etc.) **não** precisam
ser instaladas à mão: o script do passo 3 instala tudo de `requirements.txt`.

### — só para o sistema web (navegar pelo catálogo, baixar planilha)

| Programa | Versão | Download |
|---|---|---|
| **Laravel Herd** (traz PHP 8.4 e Composer prontos) | — | <https://herd.laravel.com/windows> |
| **Node.js** | 22 LTS ou mais novo | <https://nodejs.org/pt/download> |

Sem o Herd, dá para instalar separado:
PHP 8.3+ (<https://windows.php.net/download/>, versão *Thread Safe* x64) e
Composer (<https://getcomposer.org/Composer-Setup.exe>). Nesse caso, ative no
`php.ini` as extensões `pdo_sqlite`, `sqlite3`, `zip`, `fileinfo` e `mbstring`.

### Opcional — Git

Só se for baixar o projeto por `git clone` em vez de copiar a pasta:
<https://git-scm.com/download/win>.

## 2. Copiar o projeto

Copie a pasta do projeto para um lugar **fora** do OneDrive/Google Drive (por
exemplo `C:\ScrappingTcc`). Pastas sincronizadas tiram arquivos do disco e
corrompem o banco SQLite enquanto ele está aberto.

Não precisa copiar `.venv`, `web\vendor` nem `web\node_modules`: são recriadas
na instalação (e as de outro sistema operacional não funcionam no Windows).

Para manter o histórico de preços já coletado, copie também
`data\produtos.sqlite3`. Sem ele, a primeira coleta começa um banco novo.

## 3. Instalar

Abra o **PowerShell** na pasta do projeto (no Explorer: clique com o botão
direito numa área vazia da pasta → "Abrir no Terminal") e rode:

```powershell
powershell -ExecutionPolicy Bypass -File windows\instalar.ps1
```

O script, em ordem:

1. procura o Python 3.12+;
2. cria o ambiente `.venv` e instala as dependências;
3. pede a chave da API (cole e tecle Enter; ela não aparece na tela) e grava
   no arquivo `.env`;
4. testa o scraper (lista as lojas cadastradas);
5. cria a tarefa **"ScrappingTcc - coleta diaria"** no Agendador de Tarefas,
   todo dia às **03:00**.

Pode rodar o script de novo quantas vezes quiser: ele reaproveita o que já existe.

Opções:

```powershell
# outro horário
powershell -ExecutionPolicy Bypass -File windows\instalar.ps1 -Horario 06:30
# só instalar, sem agendar
powershell -ExecutionPolicy Bypass -File windows\instalar.ps1 -SemAgendamento
```

## 4. Configuração

| O quê | Onde | Observação |
|---|---|---|
| Chave de IA | `.env` na raiz: `IA_CHAVE=...` | O instalador grava. Para trocar (inclusive de provedor), edite a linha no `.env` (Bloco de Notas serve). Nunca mande este arquivo para ninguém. |
| Modelo de IA (opcional) | `.env`: `IA_MODELO=...` | Só se quiser outro modelo que não o padrão do provedor. |
| Horário da coleta | Agendador de Tarefas → "ScrappingTcc - coleta diaria" → Disparadores | Ou rode o instalador com `-Horario`. |
| Lojas coletadas | `sites.yaml` | Já vem configurado. |
| Categorias | `categorias.yaml` | Palavras-chave que classificam os produtos. |

Como a tarefa se comporta:

- **PC desligado às 03:00:** a coleta roda assim que o computador ligar e o
  usuário entrar. Fica em segundo plano, sem janela, por uns 20–30 minutos.
- **Usuário deslogado:** a tarefa só roda com o usuário logado (assim o Windows
  não precisa guardar a senha). Ao entrar, ela roda a coleta atrasada.
- **Notebook na bateria:** roda mesmo assim.
- **Duas coletas ao mesmo tempo:** não acontece; a segunda sai na hora (as
  lojas recusam requisições paralelas).

Cada coleta faz, em ordem:

1. `run`: coleta todas as lojas e grava em `data\produtos.sqlite3`;
2. `ler-rotulos`: manda para a IA **só as imagens de rótulo ainda não lidas**
   (cada imagem é lida uma vez; nas coletas seguintes, só produtos novos geram
   custo). Sem chave no `.env`, esta etapa é pulada;
3. `export`: gera `data\produtos.csv` e `data\produtos.json`.

## 5. Conferir se está funcionando

Rodar uma coleta agora, à mão:

```powershell
powershell -ExecutionPolicy Bypass -File windows\coletar.ps1
```

- **Log:** pasta `logs\`, um arquivo por execução
  (`coleta-AAAA-MM-DD_HHMM.log`), guardado por 60 dias. No fim de cada etapa
  aparece "terminou com código 0" (tudo certo) ou "código 1" (alguma loja ou
  imagem falhou; o resto foi gravado normalmente).
- **Resumo do banco:** `.venv\Scripts\python.exe -m scraper stats`
- **Tarefa:** Agendador de Tarefas → Biblioteca → "ScrappingTcc - coleta
  diaria" → aba Histórico / coluna "Resultado da última execução" (`0x0` = ok).

## 6. Sistema web (opcional)

São dois processos: a API (Python) lê o banco, e o Laravel mostra as páginas.
Com o Herd (ou PHP + Composer) e o Node.js instalados, na primeira vez:

```powershell
cd web
composer install
npm install
npm run build
copy .env.example .env
php artisan key:generate
cd ..
```

Para usar (dois terminais abertos, na pasta do projeto):

```powershell
# terminal 1: API
.venv\Scripts\uvicorn.exe scraper.api:app --port 8001

# terminal 2: site
cd web
php artisan serve
```

Abra <http://localhost:8000>. A planilha completa sai pelo botão
"Baixar planilha" na lista de produtos.

## 7. Problemas comuns

| Sintoma | Causa e solução |
|---|---|
| "a execução de scripts foi desabilitada neste sistema" | Faltou o `-ExecutionPolicy Bypass` no comando. Use os comandos exatamente como estão acima. |
| "Python 3.12+ não encontrado" ou abre a Microsoft Store | Instale pelo python.org com "Add python.exe to PATH". Se ainda abrir a Store: Configurações → Aplicativos → Configurações avançadas de aplicativos → Aliases de execução de aplicativo → desligue `python.exe` e `python3.exe`. Feche e reabra o PowerShell. |
| Erro no `pip install` ao compilar `lxml` ou `brotli` | Versão de Python nova demais para as bibliotecas. Instale o Python 3.13 e rode o instalador de novo. |
| Log com "leitura interrompida" e HTTP 401 / "invalid" | Chave errada ou revogada. Gere outra no site do provedor (tabela do passo 1) e troque `IA_CHAVE` no `.env`. Nenhuma imagem é perdida: elas ficam na fila para a próxima coleta. |
| Log com "leitura interrompida" e HTTP 402 / "balance" / "credit" | Sem crédito na conta do provedor. Coloque crédito (tabela do passo 1). A coleta das lojas não depende disso e continua funcionando. |
| Log com "não aceita imagem" | O modelo configurado em `IA_MODELO` só lê texto. Apague a linha `IA_MODELO` para usar o padrão do provedor. |
| "não reconheci o provedor pela chave" | Chave de um provedor fora da tabela, ou formato novo. Acrescente no `.env` `IA_PROVEDOR=openai` (ou `anthropic`, `gemini`, `deepseek`, `openrouter`). |
| "Outra coleta já está rodando; saindo." | Normal se você rodou à mão durante a coleta agendada. Se persistir sem nenhuma coleta rodando, reinicie o computador. |
| Tarefa não roda | Confira no Agendador se ela está "Pronta" e o histórico. O PC precisa estar ligado e com o usuário logado. |
| Site mostra "API fora do ar" | O terminal 1 (uvicorn) não está aberto. |
