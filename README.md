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
| `dicionario` | uma linha por indicador |
| `agregados` | uma linha para o Brasil (`BR`) e uma por UF (código de 2 dígitos) |
| `AC`, `AL`, … `TO` | uma linha por município; o cabeçalho é o **id** do indicador |
| `fonte_alguma_coisa` | tabela nacional de uma fonte, **no formato em que ela publica** |

As abas por estado servem para o que é coletado estado a estado — a segurança,
que vem de 27 secretarias e não tem arquivo nacional. As abas `fonte_*` servem
para tudo que sai num arquivo único cobrindo o Brasil inteiro: IBGE, SIDRA,
Ipea, SINISA, CAGED, INEP.

Os dois tipos convivem. As abas `fonte_*` são lidas **depois**, então prevalecem
se houver conflito, e o relatório avisa quando isso acontece.

## A aba `dicionario`

| campo | o que é |
|---|---|
| `id` | identificador interno, sem espaço nem acento (`pib_pc`, `taxa_analf`) |
| `nome` | como aparece na tela |
| `tema` | `demografia`, `economia`, `educacao`, `saneamento` ou `seguranca` |
| `unidade` | rótulo curto (`hab`, `%`, `pessoas`). Vazio quando não se aplica |
| `formato` | `int`, `dec1`–`dec4`, `pct`, `brl`, `brl_c` (compacto em mi/bi), `texto` |
| `somavel` | `1` se pode ser somado entre municípios; `0` para índices, taxas e percentuais |
| `ano` | ano de referência |
| `fonte` | citação que aparece embaixo do valor no painel |
| `coluna` | **só para abas `fonte_*`**: o nome da coluna no arquivo original. Aceita alternativas separadas por `\|` |
| `escala` | **só para abas `fonte_*`**: multiplicador. `100` converte fração em percentual; `1000` converte R$ mil em reais. Vazio ou `1` não mexe |
| `aba` | **só para abas `fonte_*`**: o nome da aba onde a coluna está |
| `grupo` | opcional: junta vários indicadores num item só, com seletor de recorte |
| `recorte` | opcional: o valor da dimensão dentro do grupo (`18 a 24 anos`, `Mulheres`) |

O `somavel` é o campo que mais importa. Ele decide como o valor de uma UF é
calculado quando a fonte não publica um valor próprio: soma direta ou média
ponderada pela população. Marcar errado produz números plausíveis e falsos —
um IDHM estadual de 15, por exemplo.

O campo `aba` é obrigatório para indicadores que vêm de abas `fonte_*`. É por
ele que a automação sabe quais abas existem, porque o Google Sheets não permite
listar as abas de fora.

## Indicadores em matriz: `grupo` e `recorte`

Algumas fontes publicam o mesmo indicador repetido por uma dimensão. A
escolaridade do SIDRA, por exemplo, cruza 4 níveis de instrução com 5 faixas
etárias: 20 colunas que sozinhas encheriam a lista lateral.

Preenchendo `grupo` e `recorte`, o painel junta tudo num item só, com um
seletor. Em vez de 20 linhas, aparece o bloco **Escolaridade** com uma caixa de
seleção da faixa etária e as 4 linhas dos níveis. Trocar a faixa troca os
valores no lugar, e se o mapa estiver mostrando um indicador do grupo, ele
acompanha a troca.

| id | nome | grupo | recorte |
|---|---|---|---|
| `esc_sup_total` | Superior completo | Escolaridade | 18 anos ou mais |
| `esc_sup_18_24` | Superior completo | Escolaridade | 18 a 24 anos |
| `esc_medio_18_24` | Médio completo ou superior incompleto | Escolaridade | 18 a 24 anos |

O `nome` passa a ser **só a parte que varia dentro do grupo** — o nível de
instrução, no exemplo. O painel monta o nome completo sozinho, juntando nome e
recorte, e usa essa forma longa em todo lugar onde o indicador aparece fora do
bloco: título do mapa, ranking, tabela de comparação, CSV, PDF e a lista do
relatório. Ali continuam existindo os 20 indicadores separados, para você poder
exportar as faixas que quiser.

A ordem dos recortes no seletor é a ordem em que aparecem no dicionário, e o
primeiro é o que abre selecionado.

Serve para qualquer dimensão: sexo, cor ou raça, situação do domicílio, porte.
Basta que os indicadores compartilhem `tema`, `grupo` e o mesmo conjunto de
`nome`.

---

# Atualizar os dados

## Caso 1 — corrigir um valor solto

Edite a célula na aba do estado ou na aba de fonte correspondente. Na próxima
rodada da automação o site reflete a mudança. Para sair na hora:
**Actions → Atualizar dados do painel → Run workflow**.

## Caso 2 — recarregar uma fonte que publicou edição nova

É o caso do SINISA, que publica uma vez por ano, por volta de dezembro.

1. Baixe o arquivo novo da fonte.
2. Abra a aba correspondente no Sheets, por exemplo `fonte_sinisa`.
3. Selecione tudo (Ctrl+A), apague, e cole o arquivo novo **do jeito que veio**.
4. Confira se os nomes das colunas continuam os mesmos do campo `coluna` do
   dicionário. Fontes mudam rótulo de vez em quando; se mudou, atualize a linha
   do dicionário ou acrescente o nome novo depois de uma barra vertical:
   `Cobertura de água|% Cobertura Água|Atendimento total de água`.
5. Se o ano de referência mudou, atualize o campo `ano` do dicionário.
6. **Actions → Run workflow.**
7. Leia o relatório. Ele diz quantos municípios cada aba de fonte cobriu.

Não precisa recortar por estado, não precisa PROCV, não precisa mexer nas 27
abas de UF.

## Caso 3 — acrescentar um indicador novo

1. Crie uma aba com nome começando por **`fonte_`** e cole a tabela.
2. Acrescente uma linha no `dicionario` para cada coluna que você quer no painel,
   preenchendo `coluna` com o nome exato da coluna no arquivo e `aba` com o nome
   da aba que você criou.
3. **Actions → Run workflow.**

O script cuida sozinho de:

- **encontrar a linha de cabeçalho**, ignorando títulos e notas acima dela;
- **cabeçalho em dois níveis**, como nas exportações do SIDRA em que `Total` e
  `18 a 24 anos` se repetem sob cada nível de instrução. Ele compõe o nome final
  juntando as duas linhas: `Superior completo - 18 a 24 anos`;
- **vírgula decimal, ponto de milhar, `R$` e `%`** nas células;
- **notação de ausência do SIDRA** (`-`, `..`, `...`, `X`);
- **linhas de rodapé** e notas de fim de arquivo;
- **códigos que não são de município**: 7 dígitos é município, 2 dígitos é UF,
  e `1` ou `BR` é o Brasil — as linhas de UF e de país viram valores oficiais
  dos agregados, exibidos no painel como "valor da fonte";
- **municípios extintos**, que o Atlas do Desenvolvimento Humano mantém na lista.

### Exemplo real: escolaridade do SIDRA

A tabela 10061 do SIDRA vem com seis linhas de cabeçalho e as faixas etárias
repetidas sob cada nível de instrução. Cole o CSV inteiro numa aba
`fonte_escolaridade`, sem limpar nada, e escreva no dicionário:

| id | nome | tema | unidade | formato | somavel | ano | coluna | aba |
|---|---|---|---|---|---|---|---|---|
| `esc_sup_18_24` | Superior completo — 18 a 24 anos | educacao | pessoas | int | 1 | 2022 | `Superior completo - 18 a 24 anos` | `fonte_escolaridade` |

Repare que o `coluna` usa o nome composto pelas duas linhas de cabeçalho,
separadas por ` - `. O relatório do ETL mostra um exemplo do nome composto
sempre que detecta esse formato, então rode uma vez e copie de lá.

### Exemplo real: analfabetismo do Ipea

O arquivo do Atlas traz o título na primeira linha e a coluna de valor com o
nome do ano. Como esse nome muda a cada edição, vale listar as alternativas:

| id | nome | tema | unidade | formato | somavel | ano | coluna | aba |
|---|---|---|---|---|---|---|---|---|
| `taxa_analf` | Taxa de analfabetismo (15 anos ou mais) | educacao | % | pct | 0 | 2022 | `taxa_analf\|2022\|2023` | `fonte_analfabetismo` |

## O que conferir no relatório

O `build.py` não falha em silêncio. Depois de cada execução, leia:

- **quantos municípios cada aba de fonte cobriu.** Se der muito menos que 5.570,
  a coluna de código provavelmente não foi reconhecida;
- **colunas que não estão no dicionário** — ignoradas, o que pode ser proposital;
- **indicadores sem nenhum dado** — estão no dicionário mas não apareceram em
  nenhuma aba, e vão aparecer como "sem dado" no painel;
- **sobrescritas**, quando uma aba de fonte substituiu valores das abas de estado;
- **colunas zeradas**, quando um indicador de segurança está a zero em todos os
  municípios de um estado. Nesse caso o script converte para "sem dado", porque
  série real de ocorrências varia entre municípios;
- **taxas zeradas nos agregados**, que quase sempre são célula vazia exportada
  como zero. Apague a célula e o painel calcula a partir dos municípios.

Avisos não interrompem a geração. Erros — tema inexistente, aba de fonte sem
coluna de código — interrompem, e a automação fica vermelha na aba Actions.

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
