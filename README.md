# Painel Socioambiental

Painel interativo de indicadores municipais do Brasil, com mapa coroplético e
recorte por País, UF e Município. Publicado como site estático no GitHub Pages
e alimentado por uma planilha no Google Sheets.

## Como funciona

```
Google Sheets  ──►  GitHub Actions  ──►  dados/*.json  ──►  index.html
 (você edita)       (roda de 6 em         (arquivos           (o site)
                     6 horas)              estáticos)
```

Você edita a planilha. De 6 em 6 horas — ou quando você aperta o botão — uma
rotina do GitHub lê a planilha, converte para os arquivos de dados e publica.
O site lê arquivos estáticos, então continua rápido para quem acessa.

## Estrutura

```
├── index.html                  o painel (≈50 KB, só código)
├── dados/
│   ├── meta.json               dicionário, lista de municípios, agregados
│   ├── ind/<indicador>.json    o valor de um indicador nos 5.570 municípios
│   └── uf/<SIGLA>.json         todos os indicadores dos municípios de uma UF
├── malha/                      contornos dos municípios e das UFs
├── vendor/                     bibliotecas de mapa
├── scripts/build.py            lê a planilha e gera dados/
├── .github/workflows/          a automação
└── ver-local.bat               servidor local para testar antes de publicar
```

O `index.html` carrega `meta.json` e a malha na abertura, e busca os demais
arquivos só quando você seleciona um indicador ou entra num estado. Nada é
baixado duas vezes: o navegador guarda em cache.

## Configurar o Google Sheets (uma vez só)

1. Suba `base-painel-socioambiental.xlsx` para o Google Drive, clique com o
   botão direito e escolha **Abrir com → Planilhas Google**. As 29 abas são
   criadas prontas.
2. Em **Compartilhar**, mude o acesso geral para **Qualquer pessoa com o link →
   Leitor**. Sem isso a automação não consegue ler.
3. Copie o ID da planilha, que fica na URL entre `/d/` e `/edit`:
   `docs.google.com/spreadsheets/d/`**`1AbC...XyZ`**`/edit`
4. No repositório do GitHub, vá em **Settings → Secrets and variables →
   Actions → aba Variables → New repository variable**. Nome: `SHEET_ID`.
   Valor: o ID copiado.
5. Vá na aba **Actions**, escolha *Atualizar dados do painel* e clique em
   **Run workflow**. Em cerca de um minuto os dados são publicados.

Como o repositório é público, qualquer pessoa pode ver os dados publicados —
o que já era verdade antes, já que o painel exibe todos eles.

## Atualizar os dados no dia a dia

Edite a planilha e pronto. A publicação sai na próxima rodada, no máximo 6
horas depois. Para sair na hora, vá em **Actions → Atualizar dados do painel →
Run workflow**.

Se nada mudou na planilha, a rotina roda e não publica nada — a versão dos
dados é um resumo do conteúdo, não do relógio.

## As abas da planilha

| Aba | Conteúdo |
|---|---|
| `dicionario` | uma linha por indicador: id, nome, tema, unidade, formato, somável, ano, fonte |
| `agregados` | uma linha para o Brasil (`BR`) e uma para cada UF (código de 2 dígitos) |
| `AC`, `AL`, … | uma linha por município: `id` (código IBGE de 7 dígitos), `nome` e uma coluna por indicador |

Nas abas de município e em `agregados`, **o cabeçalho é o `id` do indicador**,
não o nome de exibição. A aba `dicionario` é a legenda que liga um ao outro.

Os valores já estão na unidade final: percentual é percentual, real é real.
Não existe mais coluna de escala para acertar.

### Acrescentar um indicador

1. Uma linha nova na aba `dicionario`.
2. Uma coluna nova, com o mesmo `id` no cabeçalho, nas abas de UF e em `agregados`.

Formatos aceitos: `int`, `dec1` a `dec4`, `pct`, `brl`, `brl_c` (compacto,
em mi/bi), `texto`.

O campo `somavel` é o que mais importa: `1` para o que pode ser somado entre
municípios (população, PIB, número de escolas), `0` para índices, taxas e
percentuais. Ele decide como o valor de uma UF é calculado quando a fonte não
publica um valor próprio — soma direta ou média ponderada pela população.

### Agregados

Onde a aba `agregados` tiver valor, o painel usa esse número e marca na ficha
como *valor da fonte*. Onde a célula estiver **vazia**, ele calcula a partir
dos municípios e marca como *agregado dos municípios*.

Deixe vazio em vez de zero. Uma taxa ou percentual zerado é quase sempre uma
célula que veio vazia do dashboard, e o `build.py` avisa quando encontra isso.

## Testar antes de publicar

Dê duplo clique em **`ver-local.bat`**. Ele sobe um servidor na sua máquina e
abre `http://localhost:8000`.

Abrir o `index.html` com duplo clique **não funciona**: o navegador bloqueia a
leitura dos arquivos de dados quando a página vem do disco. O painel detecta
essa situação e explica na tela.

Para gerar os dados a partir da planilha local, sem passar pelo Google:

```bash
pip install openpyxl
python scripts/build.py
```

## Atualizar a malha

Os arquivos em `malha/` vêm da malha municipal do IBGE, simplificada no
[mapshaper](https://mapshaper.org) para caber no navegador. Para trocar por uma
edição mais recente, importe o shapefile do IBGE e rode no console:

```
-each 'id=String(CD_MUN), name=NM_MUN, uf=String(CD_MUN).substr(0,2)'
-filter-fields id,name,uf
-clean
-simplify 4% keep-shapes
-o format=topojson quantization=1e4 mun.topo.json
-dissolve2 uf
-o format=topojson quantization=1e4 uf.topo.json
```

A ordem dos municípios na malha define a ordem dos vetores em `dados/ind/`, e o
`build.py` refaz tudo a partir dela. Trocar a malha exige rodar o build de novo.

Se o total não fechar em 5.570, sobraram polígonos que não são municípios — as
áreas operacionais das lagoas do Rio Grande do Sul, por exemplo. Filtre pelos
códigos antes de exportar.
