#!/usr/bin/env python3
"""
Gera os dados de matrículas do painel a partir do Censo Escolar.

    python scripts/build_edu.py

Lê  fonte/matriculas-<ano>.csv.gz  (um arquivo por ano, gerado por
preparar_fonte_edu.py) e  fonte/legendas.csv  (o dicionário do INEP).

Escreve:
    dados/edu/meta.json         dicionário, blocos e rótulos — poucos KB
    dados/edu/uf/<SIGLA>.json   consolidado por município e rede
    dados/edu/mun/<CODIGO>.json detalhe escola por escola

A divisão em três arquivos não é capricho: o painel só baixa o consolidado
quando alguém abre a Visão Detalhada, e só baixa o detalhe por escola quando
alguém pede a lista de escolas daquele município. Quem nunca clicar não paga
por nada disso. Metade dos municípios cabe em 1,3 KB; o maior (São Paulo,
7.187 escolas) fica em 650 KB.
"""
import csv, glob, gzip, json, os, re, sys
from collections import defaultdict

csv.field_size_limit(10**9)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTE = os.path.join(RAIZ, 'fonte')
SAIDA = os.path.join(RAIZ, 'dados', 'edu')

REDES = {1: 'Federal', 2: 'Estadual', 3: 'Municipal', 4: 'Privada'}
LOCAL = {1: 'Urbana', 2: 'Rural'}

# A estrutura da tela, em três grupos:
#
#   etapa       o caminho do aluno pela educação básica; um bloco não repete
#               o aluno do outro
#   transversal outro corte dos MESMOS alunos — o do técnico integrado está no
#               Ensino Médio e na Educação Profissional ao mesmo tempo
#   perfil      quebras do total geral por característica do aluno
#
# `itens` são as linhas que somam o total do bloco. `extras` são linhas que
# NÃO somam: existem para localizar a sobreposição, e por isso aparecem
# separadas, depois do total.
#
# Os rótulos NÃO estão aqui: vêm do dicionário do INEP, em fonte/legendas.csv.
BLOCOS = [
    ('Educação Infantil', 'etapa', 'QT_MAT_INF',
     ['QT_MAT_INF_CRE', 'QT_MAT_INF_PRE'], [], None),

    ('Ensino Fundamental — Anos Iniciais', 'etapa', 'QT_MAT_FUND_AI',
     ['QT_MAT_FUND_AI_%d' % n for n in range(1, 6)], [], None),

    ('Ensino Fundamental — Anos Finais', 'etapa', 'QT_MAT_FUND_AF',
     ['QT_MAT_FUND_AF_%d' % n for n in range(6, 10)], [], None),

    ('Ensino Médio', 'etapa', 'QT_MAT_MED',
     ['QT_MAT_MED_%s' % n for n in (1, 2, 3, 4, 'NS')],
     ['QT_MAT_MED_IFTP_CT'],
     None),

    ('Educação de Jovens e Adultos', 'etapa', 'QT_MAT_EJA',
     ['QT_MAT_EJA_FUND', 'QT_MAT_EJA_MED'], [], None),

    ('Educação Profissional', 'transversal', 'QT_MAT_PROF',
     ['QT_MAT_PROF_TEC', 'QT_MAT_PROF_NAO_TEC'], [],
     'Quem faz curso técnico integrado ao Ensino Médio está contado aqui e lá.'),

    ('Educação Especial', 'transversal', 'QT_MAT_ESP',
     ['QT_MAT_ESP_CC', 'QT_MAT_ESP_CE'],
     ['QT_MAT_ESP_INF', 'QT_MAT_ESP_FUND', 'QT_MAT_ESP_MED', 'QT_MAT_ESP_EJA',
      'QT_MAT_ESP_PROF'],
     'Estes alunos já estão contados nas etapas acima; abaixo, em quais.'),

    ('Sexo dos alunos', 'perfil', None,
     ['QT_MAT_BAS_FEM', 'QT_MAT_BAS_MASC'], [], None),

    ('Onde o aluno mora', 'perfil', None,
     ['QT_MAT_ZR_URB', 'QT_MAT_ZR_RUR', 'QT_MAT_ZR_NA'], [], None),
]

GRUPOS = [
    ('etapa', 'Etapas de ensino',
     'O caminho do aluno pela educação básica. Um bloco não repete o aluno do outro.'),
    ('transversal', 'Recortes que atravessam as etapas',
     'Outro corte dos mesmos alunos — não some estes blocos com os de cima.'),
    ('perfil', 'Perfil dos alunos',
     'Quebras do total de matrículas da educação básica.'),
]

# O rótulo curto sai do dicionário do INEP, mas em alguns casos o último trecho
# da descrição fica ambíguo fora do contexto dela. "Urbana" e "Rural", por
# exemplo, aqui são a zona onde o ALUNO mora, não onde a escola fica — e o
# painel já tem um indicador de escolas rurais, então a confusão seria certa.
ROTULO = {
    'QT_MAT_ZR_URB': 'Mora em zona urbana',
    'QT_MAT_ZR_RUR': 'Mora em zona rural',
    'QT_MAT_ZR_NA': 'Não se aplica',
    'QT_MAT_PROF_TEC': 'Técnica',
    'QT_MAT_PROF_NAO_TEC': 'Não-técnica (qualificação profissional)',
    'QT_MAT_MED_1': '1ª série',
    'QT_MAT_MED_2': '2ª série',
    'QT_MAT_MED_3': '3ª série',
    'QT_MAT_MED_4': '4ª série',
    'QT_MAT_MED_NS': 'Não seriado',
    # a linha da sobreposição: o mesmo aluno aparece na Educação Profissional
    'QT_MAT_MED_IFTP_CT': 'das quais, articuladas a curso técnico',
    'QT_MAT_ESP_CC': 'Em classes comuns',
    'QT_MAT_ESP_CE': 'Em classes exclusivas',
    'QT_MAT_ESP_INF': 'na Educação Infantil',
    'QT_MAT_ESP_FUND': 'no Ensino Fundamental',
    'QT_MAT_ESP_MED': 'no Ensino Médio',
    'QT_MAT_ESP_EJA': 'na EJA',
    'QT_MAT_ESP_PROF': 'na Educação Profissional',
}
TOTAL_GERAL = 'QT_MAT_BAS'
TOTAL_FUND = 'QT_MAT_FUND'

avisos = []


def aviso(msg):
    avisos.append(msg)
    print('  aviso: ' + msg)


# ---------------------------------------------------------------- rótulos
def ler_legendas():
    """Descrição oficial de cada coluna, do dicionário do INEP."""
    caminho = os.path.join(FONTE, 'legendas.csv')
    if not os.path.exists(caminho):
        aviso('fonte/legendas.csv não encontrado — os rótulos vão sair como o '
              'nome cru da coluna. Coloque o dicionário do INEP nesse caminho.')
        return {}
    d = {}
    with open(caminho, encoding='utf-8-sig', newline='') as f:
        for linha in csv.reader(f, delimiter=';'):
            if len(linha) > 2 and linha[1].startswith('QT_MAT'):
                d[linha[1].strip()] = re.sub(r'\s+', ' ', linha[2]).strip()
    return d


def curto(col, desc):
    """
    O rótulo que aparece na tela.

    A descrição do INEP é longa e repete o caminho inteiro da etapa em cada
    linha ("Número de Matrículas do Ensino Fundamental - Anos Iniciais - 1º
    Ano"). Como o bloco já diz onde a pessoa está, na linha basta o último
    trecho: "1º Ano". Assim os rótulos saem prontos do dicionário e as colunas
    que aparecerem num censo futuro já nascem nomeadas.
    """
    if col in ROTULO:
        return ROTULO[col]
    if not desc:
        return col
    txt = re.sub(r'^N[úu]mero de Matr[íi]culas\s*(d[aeo]s?\s*)?', '', desc).strip()
    partes = [p.strip() for p in txt.split(' - ') if p.strip()]
    return partes[-1] if partes else txt


# ---------------------------------------------------------------- leitura
def arquivos_fonte():
    padrao = os.path.join(FONTE, 'matriculas-*.csv.gz')
    arqs = sorted(glob.glob(padrao))
    if not arqs:
        raise SystemExit(
            'Nenhum arquivo em fonte/matriculas-<ano>.csv.gz.\n'
            'Rode antes: python scripts/preparar_fonte_edu.py "<csv do INEP>"')
    return arqs


def num(s):
    s = (s or '').strip()
    if not s:
        return 0
    try:
        return int(float(s.replace(',', '.')))
    except ValueError:
        return 0


def processar(caminho, cols):
    """Uma passada pelo arquivo de um ano. Devolve consolidado e detalhe."""
    consolidado = defaultdict(lambda: defaultdict(lambda: [0] * len(cols)))
    escolas = defaultdict(list)
    uf_do_mun, nome_mun = {}, {}
    n, sem_rede = 0, 0

    with gzip.open(caminho, 'rt', encoding='utf-8', newline='') as f:
        r = csv.reader(f, delimiter=';')
        hdr = next(r)
        ix = {c: i for i, c in enumerate(hdr)}
        faltam = [c for c in cols if c not in ix]
        if faltam:
            raise SystemExit('%s não tem as colunas: %s' % (caminho, ', '.join(faltam)))
        ci = [ix[c] for c in cols]

        for linha in r:
            n += 1
            mun = linha[ix['CO_MUNICIPIO']].strip()
            dep = num(linha[ix['TP_DEPENDENCIA']])
            if dep not in REDES:
                sem_rede += 1
                continue
            sig = linha[ix['SG_UF']].strip()
            if sig and mun not in uf_do_mun:
                uf_do_mun[mun] = sig
            vals = [num(linha[j]) for j in ci]

            alvo = consolidado[mun][dep]
            for k, v in enumerate(vals):
                alvo[k] += v

            escolas[mun].append(
                [linha[ix['NO_ENTIDADE']].strip(),
                 num(linha[ix['CO_ENTIDADE']]),
                 dep,
                 num(linha[ix['TP_LOCALIZACAO']])] + vals)

    if sem_rede:
        aviso('%d escolas com dependência administrativa fora de 1–4 foram ignoradas' % sem_rede)
    return consolidado, escolas, uf_do_mun, n


def grava(caminho, obj):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, 'w', encoding='utf-8') as f:
        json.dump(obj, f, separators=(',', ':'), ensure_ascii=False)


def main():
    legendas = ler_legendas()

    cols = [TOTAL_GERAL, TOTAL_FUND]
    for _, _grupo, total, itens, extras, _nota in BLOCOS:
        if total and total not in cols:
            cols.append(total)
        for c in itens + extras:
            if c not in cols:
                cols.append(c)

    arqs = arquivos_fonte()
    if len(arqs) > 1:
        aviso('há %d anos em fonte/; o painel usa o mais recente (%s). Os demais '
              'ficam guardados mas não são publicados ainda.'
              % (len(arqs), os.path.basename(arqs[-1])))
    caminho = arqs[-1]
    ano = re.search(r'matriculas-(\d{4})', os.path.basename(caminho)).group(1)
    print('Lendo %s' % os.path.basename(caminho))

    consolidado, escolas, uf_do_mun, n = processar(caminho, cols)
    print('  %s escolas em %d municípios' % (format(n, ',').replace(',', '.'), len(consolidado)))

    # ---- confere contra a lista de municípios do painel
    meta_painel = os.path.join(RAIZ, 'dados', 'meta.json')
    if os.path.exists(meta_painel):
        with open(meta_painel, encoding='utf-8') as f:
            mp = json.load(f)
        do_painel = set(str(c) for c in mp['municipios'])
        # A sigla da UF sai do código do município, não da coluna SG_UF: basta
        # uma linha com a sigla em branco (há uma, em Sapiranga/RS) para o
        # município inteiro cair num arquivo sem nome.
        siglas = mp.get('ufSiglas', {})
        for mun in consolidado:
            s = siglas.get(str(mun)[:2])
            if s:
                uf_do_mun[mun] = s
        sem_uf = [m for m in consolidado if not uf_do_mun.get(m)]
        if sem_uf:
            aviso('%d municípios sem UF identificada (ex.: %s) — ficam de fora'
                  % (len(sem_uf), ', '.join(sem_uf[:3])))
        sobra = set(consolidado) - do_painel
        falta = do_painel - set(consolidado)
        if sobra:
            aviso('%d municípios do Censo não existem na lista do painel '
                  '(ex.: %s) — ficam de fora' % (len(sobra), ', '.join(sorted(sobra)[:3])))
        if falta:
            aviso('%d municípios do painel não têm nenhuma escola no Censo — a '
                  'Visão Detalhada vai aparecer vazia neles' % len(falta))
    else:
        do_painel = None

    # ---- meta
    idx = {c: i for i, c in enumerate(cols)}
    linha = lambda c: {'i': idx[c], 'n': curto(c, legendas.get(c)),
                       'd': legendas.get(c, ''), 'c': c}
    blocos = []
    for nome, grupo, total, itens, extras, nota in BLOCOS:
        blocos.append({
            'nome': nome,
            'grupo': grupo,
            'total': idx[total] if total else None,
            'itens': [linha(c) for c in itens],
            'extras': [linha(c) for c in extras],
            'nota': nota,
        })
    # Confere, no total nacional, a promessa que a tela faz: as linhas de um
    # bloco somam o total dele. Foi exatamente essa conta que não fechava
    # quando a Educação Profissional aparecia só com a linha "Técnica".
    nacional = [0] * len(cols)
    for redes in consolidado.values():
        for v in redes.values():
            for k in range(len(cols)):
                nacional[k] += v[k]
    for nome, _g, total, itens, _e, _n in BLOCOS:
        if not (total and itens):
            continue
        t = nacional[idx[total]]
        s = sum(nacional[idx[c]] for c in itens)
        if t != s:
            aviso('"%s": as linhas somam %s mas o total do bloco é %s (diferença de %s). '
                  'Falta uma linha para a conta fechar na tela.'
                  % (nome, format(s, ',').replace(',', '.'),
                     format(t, ',').replace(',', '.'),
                     format(t - s, ',').replace(',', '.')))
    sem_rotulo = [c for c in cols if c not in legendas]
    if sem_rotulo:
        aviso('sem descrição no dicionário: %s' % ', '.join(sem_rotulo))

    grava(os.path.join(SAIDA, 'meta.json'), {
        'ano': int(ano),
        'fonte': 'INEP — Censo Escolar %s' % ano,
        'redes': {str(k): v for k, v in REDES.items()},
        'local': {str(k): v for k, v in LOCAL.items()},
        'cols': cols,
        'total': idx[TOTAL_GERAL],
        'totalFund': idx[TOTAL_FUND],
        'grupos': [{'id': g, 'nome': n, 'nota': d} for g, n, d in GRUPOS],
        'blocos': blocos,
        'municipios': sorted(consolidado),
    })

    # ---- consolidado por UF
    porUF = defaultdict(dict)
    for mun, redes in consolidado.items():
        if do_painel is not None and mun not in do_painel:
            continue
        if not uf_do_mun.get(mun):
            continue
        porUF[uf_do_mun[mun]][mun] = {
            str(dep): v for dep, v in sorted(redes.items()) if any(v)
        }
    for sig, muns in porUF.items():
        grava(os.path.join(SAIDA, 'uf', sig + '.json'), {'ano': int(ano), 'mun': muns})
    print('  %d arquivos de UF' % len(porUF))

    # ---- detalhe por escola, um arquivo por município
    maior, maior_mun, total_bytes = 0, None, 0
    for mun, lista in escolas.items():
        if do_painel is not None and mun not in do_painel:
            continue
        # maiores primeiro: a lista da tela abre pelas escolas que mais pesam
        lista.sort(key=lambda e: -e[4 + idx[TOTAL_GERAL]])
        caminho_m = os.path.join(SAIDA, 'mun', mun + '.json')
        grava(caminho_m, {'ano': int(ano), 'escolas': lista})
        tam = os.path.getsize(caminho_m)
        total_bytes += tam
        if tam > maior:
            maior, maior_mun = tam, mun
    print('  %d arquivos de município · %.1f MB no total · maior %s com %.0f KB'
          % (len(escolas), total_bytes / 1e6, maior_mun, maior / 1e3))

    print('\n%d aviso(s).' % len(avisos) if avisos else '\nSem avisos.')


if __name__ == '__main__':
    main()
