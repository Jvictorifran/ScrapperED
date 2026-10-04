# Scraping de lojas de suplementos

Coleta o catálogo de lojas brasileiras de suplementos (nome, preço, marca, EAN,
categorias, imagens, descrição, ingredientes e tabela nutricional) e grava em
SQLite com histórico de preços por coleta.

20 lojas são coletadas por HTTP puro. A Dr. Peanut tem proteção anti-bot que
exige navegador e fica de fora por enquanto (veja `sites.yaml`, chave
`bloqueados`).

## Instalação

Requer Python 3.12+ (desenvolvido em 3.14).

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

### Windows (máquina do cliente)

Passo a passo completo, com links de tudo que precisa instalar e configurar:
**[INSTALACAO.md](INSTALACAO.md)**.

## Uso

```bash
# coleta todas as lojas (leva ~25 min, a maior parte nas lojas sem API)
./.venv/bin/python -m scraper run -v

# só algumas lojas
./.venv/bin/python -m scraper run vitafor dux -v

# teste rápido: no máximo 5 produtos por loja
./.venv/bin/python -m scraper run --limit 5 -v

# ignora o cache HTTP (por padrão as respostas valem 24h)
./.venv/bin/python -m scraper run --no-cache

# lista as lojas e seus adapters
./.venv/bin/python -m scraper sites

# resumo do banco: produtos, cobertura de EAN/ingredientes/nutricional, preço médio
./.venv/bin/python -m scraper stats

# reaplica as palavras-chave de categorias.yaml (sem recoletar)
./.venv/bin/python -m scraper classificar

# exporta para data/produtos.csv e data/produtos.json
./.venv/bin/python -m scraper export

# testes
./.venv/bin/python -m unittest discover tests
```

`run` imprime um resumo em JSON no stdout e sai com código 1 se algum site deu erro.

## Saída

### SQLite (`data/produtos.sqlite3`)

| Tabela | Conteúdo |
|---|---|
| `runs` | uma linha por execução |
| `products` | catálogo deduplicado por `(site, url)`, com o conteúdo mais recente |
| `price_history` | preço, preço de tabela e disponibilidade de cada produto em cada execução |
| `v_catalogo` | view com a última foto de cada produto; é o que o `export` lê |

Rodar a coleta de novo não duplica produtos: atualiza o catálogo e acrescenta
uma linha de preço. Assim dá para analisar variação de preço ao longo do tempo:

```sql
SELECT p.name, h.scraped_at, h.price
FROM price_history h JOIN products p ON p.id = h.product_id
WHERE p.site = 'vitafor'
ORDER BY p.name, h.scraped_at;
```

### Classificação por palavra-chave

Cada produto recebe uma `categoria` (whey, creatina, barra_proteica,
vestuario...) e um `grupo`:

| grupo | o que é |
|---|---|
| `proteina` | whey, proteína vegetal, barras e snacks proteicos, hipercalórico |
| `suplemento` | creatina, pré-treino, aminoácidos, vitaminas, ômega, colágeno... |
| `alimento` | snacks e alimentos sem apelo proteico |
| `fora` | vestuário, acessórios e cosméticos |

As palavras-chave ficam em `categorias.yaml`; as regras de desempate estão
no topo do arquivo. Ao alterar o arquivo, rode `scraper classificar`. A
coleta também reclassifica ao terminar.

`classificacao_fonte` diz de onde veio a categoria: `nome` (a maioria),
`categoria_loja`, `descricao` ou `ingredientes`. Pela rotulagem da Anvisa, os
ingredientes vêm em ordem decrescente de quantidade, então o início da lista
indica o componente principal.

`peso_g` é lido do nome ("Display c/12 Barras 40g" → 480 g) e alimenta
`preco_por_kg`. É heurístico: fica vazio em kits e em nomes que não dizem o
peso total. Para comparar preços, prefira a mediana à média, porque sobram
outliers como "Caixa Mista (30g/Un)", que traz o peso de uma unidade e não o da caixa.

### CSV / JSON

O CSV tem uma linha por produto. A tabela nutricional vira uma única célula
`nutriente=quantidade; ...` para caber numa planilha. O JSON mantém a
estrutura completa.

### Confiabilidade da tabela nutricional

O campo `origem_nutricional` (ou `nutrition.origem` no banco) diz de onde o dado veio:

| origem | significado |
|---|---|
| `tabela` | tabela HTML da página — confiável |
| `json` | dado estruturado da loja — confiável |
| `prosa` | números garimpados de texto corrido — **tratar como estimativa** |

Quando a tabela só existe como imagem da embalagem (caso da Vitafor), ela não é
extraída; a URL da imagem fica em `nutrition.imagens`.

## Sistema web (Laravel)

Duas peças, cada uma no seu processo:

```
[scraper Python] -> SQLite <- [API FastAPI :8001] <-HTTP/JSON- [Laravel + Blade :8000]
```

O Laravel não acessa o banco: só consome a API, que abre o SQLite em modo
somente leitura. Assim o scraper e a API podem rodar numa VPS e o Laravel em
qualquer lugar que alcance a API (`SCRAPER_API_URL` no `.env` do Laravel).

```bash
# 1. API (na raiz do projeto) — documentação em http://localhost:8001/docs
./.venv/bin/uvicorn scraper.api:app --port 8001

# 2. Laravel (em web/)
cd web
composer install && npm install && npm run build
cp .env.example .env && php artisan key:generate   # só na primeira vez
php artisan serve                                  # http://localhost:8000
```

| Página | O que mostra |
|---|---|
| `/` | R$/kg mediano de whey por loja, cobertura de dados por loja, atalhos por categoria |
| `/produtos` | lista com busca (ignora acento), filtros por loja, grupo, categoria, preço, estoque e tabela nutricional; ordena por nome, preço ou R$/kg |
| `/produtos/exportar.xlsx` | baixa em planilha **todos** os produtos do filtro atual (mesmos parâmetros da lista), completos |
| `/produtos/{id}` | detalhe com ingredientes, tabela nutricional no padrão Anvisa, histórico de preço e de onde veio cada dado |

### Exportação em planilha (.xlsx)

O botão "Baixar planilha" na lista baixa todos os produtos do filtro, não só a
página. São quatro abas, ligadas pelo ID do produto:

| Aba | Uma linha por |
|---|---|
| Produtos | produto: loja, nome, categoria, preço, preço "de", estoque, peso, R$/kg, EAN, ingredientes, alérgicos, modo de uso, advertências, link; no fim, os detalhes da classificação |
| Tabela nutricional | produto **com tabela**: porção (g), kcal, carboidratos, açúcares totais e adicionados, proteínas, **proteína (% da porção)**, gorduras totais/saturadas/trans, fibras, sódio, outros nutrientes |
| Histórico de preços | coleta de cada produto |
| Filtros | filtro usado e data de geração |

Preços, pesos e nutrientes são células numéricas, primeira linha congelada e
filtro do Excel ligado. Os nutrientes são padronizados por
`scraper/core/nutricional_padrao.py`: nomes diferentes ("Proteínas (g)",
"proteínas") viram a mesma coluna, unidades são convertidas (sódio sempre em mg,
energia em kcal) e os valores são **por porção**. Tabelas fisicamente
impossíveis (mais kcal ou macronutrientes do que a porção comporta) ficam com
os números vazios e o motivo na coluna "Observação": acontece quando a página
mistura a tabela de outro produto. Gerado com OpenSpout em
arquivo temporário (apagado após o envio); o banco inteiro dá ~1,2 MB em ~1 s.

Endpoints da API: `/resumo`, `/lojas`, `/categorias`, `/comparativo?categoria=whey`,
`/produtos?q=&loja=&grupo=&categoria=&preco_min=&preco_max=&disponivel=&com_nutricional=&ordem=&direcao=&pagina=&por_pagina=`,
`/exportacao` (mesmos filtros, sem paginação, itens completos), `/produtos/{id}`, `/produtos/{id}/precos`.

## Lojas

| Adapter | Lojas | Fonte dos dados |
|---|---|---|
| `vtex` | Max Titanium, Probiótica, Black Skull, Vitafor, Atlhetica, Nutrify | API pública de catálogo VTEX |
| `shopify` | FTW, Soldiers, Bold, Urso | `/products.json` |
| `shopify_storefront` | Integralmédica | API Storefront GraphQL |
| `woo` | Adaptogen | WooCommerce Store API |
| `vtex` | Equaliv (`lojaequaliv.com.br`) | API pública de catálogo VTEX |
| `sitemap` | Dux, New Millen, Nutrata, Bodyaction, MixNutri | sitemap + JSON-LD/microdata da página |
| `sitemap` | Growth | idem, atrás da verificação noc.org (resolvida no `Client`, ver `core/desafios.py`) |
| `magento` | Essential | sitemap + HTML da página |

Para adicionar uma loja numa plataforma já suportada, basta uma entrada nova em
`sites.yaml`. Os parâmetros aceitos estão documentados no topo do arquivo.

## Limitações

- **EAN** não é exposto pelas lojas Shopify nem pela Adaptogen.
- **Essential Nutrition** renderiza parte do conteúdo no navegador: nome e
  preço sempre vêm, ingredientes e nutricional só em alguns produtos.
- **Tabela nutricional em imagem** exigiria OCR e não é extraída.
- **Growth**: roupas e acessórios não são baixados (filtro por URL em
  `sites.yaml`), ao contrário das outras lojas: são 916 páginas de ~800 KB que
  a classificação poria fora do escopo. O preço gravado é o do cartão (o do
  JSON-LD); a loja mostra também preço cheio e preço no pix. Muitos nomes não
  trazem o peso ("Daily Whey"), então poucos wheys têm R$/kg.
- A coleta é **serial** de propósito: a VTEX devolve respostas vazias quando
  recebe requisições paralelas no mesmo host.

## Estrutura

```
sites.yaml           registro das lojas
categorias.yaml      palavras-chave da classificação dos produtos
INSTALACAO.md        instalação no Windows (máquina do cliente)
.env.example         modelo do .env (chave de IA)
scraper/
  cli.py             comandos run | sites | stats | ler-rotulos | classificar | export
  runner.py          lê sites.yaml, roda os adapters, grava no banco
  rotulos.py         leitura por IA das tabelas nutricionais em imagem
  ia.py              provedores de IA (Anthropic, OpenAI, Gemini, DeepSeek, OpenRouter)
  api.py             API FastAPI consumida pelo sistema web
  core/              HTTP com cache e throttle, banco, parsers (JSON-LD, nutricional), exportação
  adapters/          um módulo por plataforma de e-commerce
windows/             instalar.ps1 e coletar.ps1 (instalação e coleta agendada)
web/                 sistema web (Laravel + Blade)
tests/               testes (python -m unittest discover tests)
data/rotulos_ia/     evidência da leitura de rótulos (transcrições e conferência)
```
