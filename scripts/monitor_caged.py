#!/usr/bin/env python3
"""
Vigia a divulgação mensal do Novo CAGED e atualiza os dados de emprego.

    python scripts/monitor_caged.py            # verifica e, se houver mês novo, grava
    python scripts/monitor_caged.py --forcar   # regrava mesmo sem mês novo
    python scripts/monitor_caged.py --so-checar  # só diz se mudou, não baixa nada

De onde vem o dado
------------------
NÃO do painel Power BI do MTE. Aquele painel é alimentado por uma API interna,
não documentada, que pode mudar sem aviso — e, pior, passar a devolver número
errado em vez de erro. O caminho usado aqui é o arquivo oficial:

  1. a página de divulgação do Novo CAGED redireciona sozinha para o mês mais
     recente (…/novo-caged → …/2026/julho/pagina-inicial), o que entrega o mês
     de referência de graça, numa requisição de alguns KB;
  2. essa página traz o link da pasta do Google Drive com os anexos;
  3. de lá sai o `3-tabelas_<mês>.xlsx`, cuja **Tabela 8.1** já vem agregada
     por município, com estoque, admissões, desligamentos e saldo, e com a
     série inteira desde jan/2020 num único arquivo de ~42 MB.

O recorte de tempo
------------------
Cada indicador tem a natureza dele, e forçar os dois no mesmo período estragava
um dos dois:

  estoque de empregos   é uma fotografia -> vale o mês mais recente publicado
  admissões, desligamentos, saldo   são fluxos -> soma dos ÚLTIMOS 12 MESES

A janela móvel de 12 meses substitui o ano civil. Ano civil tinha dois defeitos:
em setembro o dado já estava com 9 meses de atraso, e a virada do ano fazia o
número dar um salto sem que nada tivesse acontecido no mundo. Com 12 meses
móveis o período tem sempre o mesmo tamanho — logo é sempre comparável — e anda
junto com a fonte. A variação relativa compara o estoque de hoje com o de 12
meses atrás, o mesmo intervalo dos fluxos.

O que é gravado
---------------
  fonte/auto/auto_caged.csv        um município por linha, colunas com o id do
                                   indicador — o build.py já aceita o id como
                                   nome de coluna, então nada muda na planilha
  fonte/auto/auto_caged.meta.json  período de cada indicador e citação da fonte
  fonte/auto/auto_caged.estado.json  último mês visto, para detectar novidade

Salvaguarda
-----------
Antes de gravar, a soma nacional do último mês é conferida contra o intervalo
plausível. Desalinhamento de coluna é o modo de falha mais provável desta
planilha (o bloco mensal tem 4 colunas em jan/2020 e 5 nos demais meses), e é
silencioso: sem essa conferência, publicaria número errado com cara de certo.
"""
import argparse, csv, io, json, os, re, sys, unicodedata
from datetime import datetime, timezone

import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAIDA = os.path.join(RAIZ, 'fonte', 'auto')

PAGINA = ('https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/'
          'acoes-e-programas/programas-projetos-acoes-obras-e-atividades/'
          'estatisticas-trabalho/novo-caged')

# id do indicador no painel -> rótulo da métrica na Tabela 8.1
METRICAS = {
    'caged_estoque':   'estoque',
    'caged_admissoes': 'admissoes',
    'caged_deslig':    'desligamentos',
    'caged_saldo':     'saldos',
}
# as chaves ficam SEM acento porque tudo passa por chave() antes de ser
# procurado aqui — com 'março' acentuado, o mês de março nunca casaria
MESES = {m: i + 1 for i, m in enumerate(
    'janeiro fevereiro marco abril maio junho julho agosto setembro '
    'outubro novembro dezembro'.split())}

UA = {'User-Agent': 'painel-socioambiental/1.0 (+github actions; dados publicos)'}


def chave(s):
    t = unicodedata.normalize('NFKD', str(s or '').lower())
    return re.sub(r'\s+', ' ', ''.join(c for c in t if not unicodedata.combining(c))).strip()


def busca(url, binario=False, limite=None):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as r:
        dados = r.read(limite) if limite else r.read()
        return (dados, r.geturl()) if binario else (dados.decode('utf-8', 'replace'), r.geturl())


# ------------------------------------------------------- descobrir o mês novo
def mes_publicado():
    """Mês de referência da divulgação mais recente, via redirecionamento."""
    html, final = busca(PAGINA)
    m = re.search(r'/novo-caged/(\d{4})/([a-zç]+)', final, re.I)
    if not m:
        m = re.search(r'/novo-caged/(\d{4})/([a-zç]+)/pagina-inicial', html, re.I)
    if not m:
        raise SystemExit('Não consegui identificar o mês de divulgação a partir de '
                         + final + '. A página do MTE provavelmente mudou de formato.')
    ano, nome = int(m.group(1)), chave(m.group(2))
    if nome not in MESES:
        raise SystemExit("Mês '%s' não reconhecido na URL %s" % (nome, final))
    return ano, MESES[nome], final


def link_planilha(url_mes):
    """Endereço direto do 3-tabelas_*.xlsx, achado pela pasta do Drive."""
    html, _ = busca(url_mes)
    pasta = re.search(r'drive\.google\.com/drive/folders/([A-Za-z0-9_-]{20,})', html)
    if not pasta:
        raise SystemExit('Não achei a pasta do Google Drive em ' + url_mes +
                         '. O MTE mudou a forma de publicar os anexos.')
    listagem, _ = busca('https://drive.google.com/drive/folders/' + pasta.group(1))
    ids = re.findall(r'data-id="([A-Za-z0-9_-]{20,})"[^>]*>.*?([^<>"]*?3-?tabelas[^<>"]*?\.xlsx)',
                     listagem, re.I | re.S)
    if not ids:
        # a listagem do Drive muda de formato; segunda tentativa, mais frouxa
        blocos = re.findall(r'\["([A-Za-z0-9_-]{25,})",[^]]*?"([^"]*?\.xlsx)"', listagem)
        ids = [(i, n) for i, n in blocos if 'tabela' in chave(n)]
    if not ids:
        raise SystemExit('A pasta do Drive não trouxe nenhum arquivo "3-tabelas*.xlsx". '
                         'Confira ' + url_mes + ' antes de mexer no script.')
    fid, nome = ids[0]
    return 'https://drive.google.com/uc?export=download&id=' + fid, nome


# ------------------------------------------------------------- ler a Tabela 8.1
def mapa_codigos():
    """
    A Tabela 8.1 traz o código IBGE de 6 dígitos; o painel usa o de 7. O sétimo
    é o dígito verificador, então a conversão é uma busca na lista de municípios
    que o próprio painel já publica — nada de recalcular dígito à mão.
    """
    caminho = os.path.join(RAIZ, 'dados', 'meta.json')
    if not os.path.exists(caminho):
        raise SystemExit('Preciso de dados/meta.json para converter o código de 6 '
                         'para 7 dígitos. Rode o build.py antes.')
    with open(caminho, encoding='utf-8') as f:
        municipios = json.load(f)['municipios']
    return {str(c)[:6]: str(c) for c in municipios}


def le_tabela(conteudo):
    """
    Devolve {codigo_ibge7: {ano_mes: {metrica: valor}}} e a lista de meses.

    O bloco de cada mês NÃO tem largura fixa: jan/2020 tem 4 colunas e os meses
    seguintes têm 5 (ganharam 'Variação Relativa'). Por isso as colunas são
    localizadas pelo par (rótulo do mês, rótulo da métrica) lido do cabeçalho,
    e não por passo fixo — assumir passo fixo desalinha tudo a partir de 2020.
    """
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    nome = next((s for s in wb.sheetnames if chave(s).startswith('tabela 8.1')), None)
    if not nome:
        nome = next((s for s in wb.sheetnames if chave(s).startswith('tabela 8')), None)
    if not nome:
        raise SystemExit('A planilha não tem a aba "Tabela 8.1". Abas: %s' % wb.sheetnames)
    ws = wb[nome]

    linhas = ws.iter_rows(values_only=True)
    cab_mes = cab_met = None
    dados = {}
    cols = {}                       # (ano_mes, metrica) -> índice da coluna
    ordem_meses = []
    i_cod = i_uf = None

    for row in linhas:
        vals = ['' if v is None else v for v in row]
        txt = [chave(v) for v in vals]

        if cab_met is None:
            # a linha de métricas é a que repete 'estoque' várias vezes
            if txt.count('estoque') >= 2:
                cab_met = txt
                # o rótulo do mês está na linha anterior, com células mescladas
                mes_atual = None
                for j, t in enumerate(cab_mes or []):
                    if re.fullmatch(r'[a-z]+/\d{4}', t or ''):
                        mes_atual = t          # começa um bloco mensal
                    elif t:
                        # rótulo que NÃO é mês encerra o bloco. É o que separa os
                        # blocos-resumo do fim ('Acumulado do Ano', 'Últimos 12
                        # Meses') dos meses de verdade: sem isso, as colunas do
                        # resumo entram como se fossem do último mês e o total
                        # nacional sai ~3x maior.
                        mes_atual = None
                    if cab_met[j] in ('estoque', 'admissoes', 'desligamentos', 'saldos') \
                       and mes_atual:
                        nome_mes, ano_mes = mes_atual.split('/')
                        if nome_mes in MESES:
                            k = '%s-%02d' % (ano_mes, MESES[nome_mes])
                            if (k, cab_met[j]) not in cols:   # a primeira vence
                                cols[(k, cab_met[j])] = j
                            if k not in ordem_meses:
                                ordem_meses.append(k)
                    cab_mes[j] = mes_atual or cab_mes[j]
                # o rótulo da coluna de código está na linha DOS MESES (linha 5),
                # não na das métricas — as três primeiras colunas ficam vazias ali
                i_cod = next((j for j, t in enumerate(cab_mes or [])
                              if 'codigo' in t and 'munic' in t), None)
                if i_cod is None:
                    raise SystemExit('Não achei a coluna de código do município na Tabela 8.1')
                continue
            cab_mes = txt[:]        # guarda como possível linha de meses
            continue

        cod = str(vals[i_cod]).split('.')[0].strip()
        if not cod.isdigit() or len(cod) < 6:
            continue                 # rodapés e notas caem aqui
        reg = dados.setdefault(cod, {})
        for (k, met), j in cols.items():
            v = vals[j]
            if isinstance(v, (int, float)):
                reg.setdefault(k, {})[met] = int(round(v))
    if not cols:
        raise SystemExit('Não consegui mapear as colunas de mês da Tabela 8.1 — '
                         'o cabeçalho da planilha provavelmente mudou.')

    de6 = mapa_codigos()
    convertidos, sobraram = {}, []
    for cod, serie in dados.items():
        sete = de6.get(cod[:6])
        if sete:
            convertidos[sete] = serie
        elif cod.startswith('999999'):
            # linha "município não identificado" da própria tabela: some gente
            # cujo vínculo não tem município declarado. Não pertence a nenhum
            # município, então fica de fora — é por isso que os totais daqui
            # ficam alguns milhares abaixo do Sumário Executivo do MTE.
            continue
        else:
            sobraram.append(cod)
    if sobraram:
        print('  aviso: %d códigos do CAGED não existem na lista do painel (ex.: %s)'
              % (len(sobraram), ', '.join(sobraram[:3])))
    return convertidos, sorted(ordem_meses)


# ------------------------------------------------------------------ o recorte
JANELA = 12            # meses somados nos fluxos


def recorte(meses):
    """
    Dois períodos, um para cada natureza de indicador.

    Estoque é uma fotografia: vale o mês mais recente publicado, e não faz
    sentido envelhecê-lo de propósito.

    Admissões, desligamentos e saldo são fluxos: só significam alguma coisa
    somados sobre um período. A soma é dos **últimos 12 meses**, não do ano
    civil fechado. Ano civil tinha dois defeitos: em setembro o dado já estava
    com 9 meses de atraso, e virar o ano fazia o número dar um salto sem que
    nada tivesse acontecido no mundo. Com 12 meses móveis o período tem sempre
    o mesmo tamanho — logo é sempre comparável — e anda junto com a fonte.
    """
    if not meses:
        raise SystemExit('Nenhum mês encontrado na planilha.')
    ultimo = max(meses)
    janela = sorted(meses)[-JANELA:]
    if len(janela) < JANELA:
        raise SystemExit('A planilha só trouxe %d meses; preciso de %d para a '
                         'janela de fluxos.' % (len(janela), JANELA))
    return ultimo, janela


def rotulo_mes(k):
    nome = [m for m, i in sorted(MESES.items(), key=lambda kv: kv[1])][int(k[5:]) - 1]
    return '%s/%s' % (nome[:3], k[:4])


def acumula(dados, ultimo, janela, meses):
    """Estoque = mês mais recente; fluxos = soma da janela; variação = 12 meses."""
    # a base da variação é o mês ANTERIOR ao primeiro da janela: entre ele e o
    # último mês cabem exatamente os 12 meses somados nos fluxos
    todos = sorted(meses)
    i = todos.index(janela[0])
    anterior = todos[i - 1] if i > 0 else None
    saida = {}
    for cod, serie in dados.items():
        linha = {}
        est = (serie.get(ultimo) or {}).get('estoque')
        if est is not None:
            linha['caged_estoque'] = est
        for ind, met in METRICAS.items():
            if met == 'estoque':
                continue
            vals = [serie[k][met] for k in janela if k in serie and met in serie[k]]
            if vals:
                linha[ind] = sum(vals)
        # variação do estoque no mesmo período dos fluxos: comparo a fotografia
        # de hoje com a de 12 meses atrás. Poderia sair de saldo/estoque, mas aí
        # dependeria de as duas séries estarem na mesma revisão — e o estoque é
        # justamente a série que o MTE mais revisa.
        base = (serie.get(anterior) or {}).get('estoque') if anterior else None
        if est is not None and base:
            linha['caged_var'] = round((est - base) / base * 100, 4)
        if linha:
            saida[cod] = linha
    return saida


def agrega(dados, consolidado, ultimo, janela, meses):
    """
    Soma por UF e para o Brasil.

    Sem isso o painel ficaria incoerente: os municípios viriam do robô e os
    cartões de estado e de Brasil continuariam com os números antigos digitados
    na aba 'agregados' da planilha. O build.py dá preferência ao que a fonte
    declara para UF e país, então basta mandar essas linhas junto.

    A variação relativa NÃO é média das variações municipais — é a variação do
    estoque do próprio agregado, calculada dos dois extremos da janela.
    """
    todos = sorted(meses)
    anterior = todos[todos.index(janela[0]) - 1] if todos.index(janela[0]) > 0 else None
    grupos = {'BR': []}
    for cod in consolidado:
        grupos.setdefault(cod[:2], []).append(cod)
        grupos['BR'].append(cod)

    linhas = {}
    for chave, cods in grupos.items():
        linha = {}
        for ind in METRICAS:
            vals = [consolidado[c][ind] for c in cods if ind in consolidado[c]]
            if vals:
                linha[ind] = sum(vals)
        if anterior:
            base = sum((dados[c].get(anterior) or {}).get('estoque', 0)
                       for c in cods if c in dados)
            if base and linha.get('caged_estoque'):
                linha['caged_var'] = round(
                    (linha['caged_estoque'] - base) / base * 100, 4)
        if linha:
            linhas[chave] = linha
    return linhas


def confere(consolidado, n_meses):
    """
    Barreira contra desalinhamento de coluna, que é o erro mais provável e o
    mais silencioso: números fora de faixa plausível param a execução.
    """
    est = sum(v.get('caged_estoque', 0) for v in consolidado.values())
    adm = sum(v.get('caged_admissoes', 0) for v in consolidado.values())
    des = sum(v.get('caged_deslig', 0) for v in consolidado.values())
    sal = sum(v.get('caged_saldo', 0) for v in consolidado.values())
    problemas = []
    if not (30e6 <= est <= 80e6):
        problemas.append('estoque nacional de %s fora da faixa plausível' % f'{est:,}')
    if not (0.5e6 * n_meses <= adm <= 4e6 * n_meses):
        problemas.append('admissões (%s em %d meses) fora da faixa' % (f'{adm:,}', n_meses))
    if abs((adm - des) - sal) > 5:
        problemas.append('admissões − desligamentos (%s) não bate com o saldo (%s)'
                         % (f'{adm - des:,}', f'{sal:,}'))
    if len(consolidado) < 5000:
        problemas.append('só %d municípios lidos; esperava mais de 5.000' % len(consolidado))
    if problemas:
        raise SystemExit('Conferência falhou, nada foi gravado:\n  - ' +
                         '\n  - '.join(problemas))
    return dict(estoque=est, admissoes=adm, desligamentos=des, saldo=sal,
                municipios=len(consolidado))


# --------------------------------------------------------------------- saída
def estado_atual():
    caminho = os.path.join(SAIDA, 'auto_caged.estado.json')
    if os.path.exists(caminho):
        with open(caminho, encoding='utf-8') as f:
            return json.load(f)
    return {}


def grava(consolidado, agregados, ultimo, janela, totais, mes_pub, nome_arquivo):
    os.makedirs(SAIDA, exist_ok=True)
    cols = ['codigo'] + list(METRICAS) + ['caged_var']
    with open(os.path.join(SAIDA, 'auto_caged.csv'), 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(cols)
        # o painel usa o código IBGE de 7 dígitos (a Tabela 8.1 traz 6); as duas
        # últimas famílias de linhas são os agregados: 2 dígitos = UF, 'BR' = país
        for cod in sorted(consolidado) + sorted(k for k in agregados if k != 'BR') + ['BR']:
            linha = consolidado.get(cod) or agregados.get(cod) or {}
            w.writerow([cod] + ['' if linha.get(c) is None else linha[c] for c in cols[1:]])

    # cada indicador leva o rótulo do SEU período: o estoque é uma fotografia de
    # um mês, os fluxos são a soma de 12. Um rótulo só para os dois seria mentira
    # em metade dos casos.
    foto = rotulo_mes(ultimo)
    periodo = '%s a %s' % (rotulo_mes(janela[0]), rotulo_mes(ultimo))
    anos = {ind: (foto if ind == 'caged_estoque' else periodo)
            for ind in list(METRICAS) + ['caged_var']}
    with open(os.path.join(SAIDA, 'auto_caged.meta.json'), 'w', encoding='utf-8') as f:
        json.dump({ind: {'ano': ano,
                         'fonte': 'CAGED — Ministério do Trabalho e Emprego'}
                   for ind, ano in anos.items()},
                  f, ensure_ascii=False, indent=2)

    with open(os.path.join(SAIDA, 'auto_caged.estado.json'), 'w', encoding='utf-8') as f:
        json.dump({'divulgacao': '%04d-%02d' % mes_pub, 'arquivo': nome_arquivo,
                   'mesEstoque': ultimo, 'janelaFluxos': janela,
                   'rotulos': anos,
                   'verificadoEm': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                   'totais': totais},
                  f, ensure_ascii=False, indent=2)


def _per(janela):
    return ('%s a %s' % (rotulo_mes(janela[0]), rotulo_mes(janela[-1]))
            if janela and janela[0] != '?' else '?')


def resumo_markdown():
    """Corpo do Pull Request: os totais nacionais, para conferência humana."""
    e = estado_atual()
    if not e:
        return 'Sem estado gravado.'
    t = e.get('totais', {})
    f = lambda n: '{:,}'.format(n).replace(',', '.')
    jan = e.get('janelaFluxos') or ['?']
    linhas = [
        '**Divulgação:** %s  ·  arquivo `%s`' % (e.get('divulgacao'), e.get('arquivo')),
        '', '| indicador | período | Brasil |', '|---|---|---:|',
        '| Estoque de empregos | %s | %s |' % (
            rotulo_mes(e['mesEstoque']) if e.get('mesEstoque') else '?',
            f(t.get('estoque', 0))),
        '| Admissões | %s | %s |' % (_per(jan), f(t.get('admissoes', 0))),
        '| Desligamentos | %s | %s |' % (_per(jan), f(t.get('desligamentos', 0))),
        '| Saldo | %s | %s |' % (_per(jan), f(t.get('saldo', 0))),
        '| Municípios | | %s |' % f(t.get('municipios', 0)),
        '',
        'Confira esses totais contra o Sumário Executivo do MTE antes de aceitar. '
        'A linha "município não identificado" da tabela original fica de fora daqui, '
        'então o estoque some alguns milhares abaixo do total nacional do MTE — '
        'isso é esperado.',
        '',
        'Assim que este PR for aceito, o *Atualizar dados do painel* dispara '
        'sozinho e o site passa a mostrar estes números em poucos minutos.',
    ]
    return '\n'.join(linhas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--forcar', action='store_true', help='regrava mesmo sem mês novo')
    ap.add_argument('--so-checar', action='store_true', help='só reporta, não baixa a planilha')
    ap.add_argument('--resumo', action='store_true', help='imprime o corpo do Pull Request')
    args = ap.parse_args()

    if args.resumo:
        print(resumo_markdown())
        return

    ano_p, mes_p, url_mes = mes_publicado()
    atual = '%04d-%02d' % (ano_p, mes_p)
    antes = estado_atual().get('divulgacao')
    print('Divulgação mais recente do MTE: %s' % atual)
    print('Último processado aqui: %s' % (antes or '(nenhum)'))

    novidade = atual != antes
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write('novidade=%s\n' % ('true' if (novidade or args.forcar) else 'false'))
            f.write('divulgacao=%s\n' % atual)

    if args.so_checar:
        print('MUDOU' if novidade else 'sem novidade')
        return
    if not novidade and not args.forcar:
        print('Nada a fazer.')
        return

    url_xlsx, nome = link_planilha(url_mes)
    print('Baixando %s' % nome)
    conteudo, _ = busca(url_xlsx, binario=True)
    print('  %.1f MB' % (len(conteudo) / 1e6))

    dados, meses = le_tabela(conteudo)
    print('  %d municípios · %d meses (%s a %s)'
          % (len(dados), len(meses), meses[0], meses[-1]))

    ultimo, janela = recorte(meses)
    print('  estoque: %s   ·   fluxos: %s a %s (%d meses)'
          % (rotulo_mes(ultimo), rotulo_mes(janela[0]), rotulo_mes(ultimo), len(janela)))

    consolidado = acumula(dados, ultimo, janela, meses)
    agregados = agrega(dados, consolidado, ultimo, janela, meses)
    totais = confere(consolidado, len(janela))
    print('  conferência ok: estoque %s · admissões %s · desligamentos %s · saldo %s'
          % tuple(f'{totais[k]:,}'.replace(',', '.')
                  for k in ('estoque', 'admissoes', 'desligamentos', 'saldo')))

    grava(consolidado, agregados, ultimo, janela, totais, (ano_p, mes_p), nome)
    print('Gravado em fonte/auto/auto_caged.csv (%d municípios)' % len(consolidado))


if __name__ == '__main__':
    main()
