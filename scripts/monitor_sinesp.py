#!/usr/bin/env python3
"""
Vigia do SINESP VDE (Ministério da Justiça) — o indicador de segurança comum
aos 27 estados.

    python scripts/monitor_sinesp.py --so-checar    # só diz se mudou
    python scripts/monitor_sinesp.py                # baixa e grava fonte/auto/
    python scripts/monitor_sinesp.py --forcar       # reprocessa mesmo sem mudança

Por que existe
--------------
Os indicadores de segurança do painel vinham das secretarias estaduais, cada
uma com o seu portal, o seu calendário e a sua lista de crimes. Resultado: 15
estados sem série nenhuma e, entre os que tinham, tipos de roubo que não se
comparam de um estado para outro.

O SINESP VDE é a base em que os próprios gestores estaduais lançam os dados
para o Ministério da Justiça, com definições nacionais. Para o painel, o que
importa é que ela desce ao MUNICÍPIO, nos 27 estados, mês a mês. Mas só para os
eventos com vítima — homicídio, feminicídio, latrocínio, lesão seguida de morte,
tentativas. Roubos e furtos o SINESP publica apenas por estado. Por isso o
indicador comum é de mortes, não de patrimônio: não existe, numa fonte
nacional, roubo por município para o país inteiro.

O que é somado: CVLI
--------------------
Crimes Violentos Letais Intencionais, a soma de vítimas de

    homicídio doloso + feminicídio + latrocínio + lesão corporal seguida de morte

Feminicídio entra como parcela própria porque no SINESP ele NÃO está dentro do
homicídio doloso: o dicionário do Ministério define o homicídio doloso "exceto
feminicídio, lesão corporal seguida de morte e latrocínio". Somar só o
homicídio deixaria de fora umas 1.500 mulheres por ano.

Mortes por intervenção de agente do Estado ficam fora: o SINESP só as publica
por estado, e incluí-las em uns lugares e não em outros quebraria a
comparação.

A taxa
------
Por 100 mil habitantes, com a ESTIMATIVA de população do IBGE do MESMO ano
(SIDRA 6579) — nunca de outro; se ela faltar, o script para —, e não com o Censo 2022 — três anos de diferença mudam a taxa de
município que cresce rápido. Em município pequeno ela oscila muito de um ano
para o outro: duas mortes numa cidade de 4 mil habitantes já dão 50 por 100
mil. A contagem absoluta vai junto para quem lê poder pesar isso.

Ano completo
------------
O arquivo do ano corrente existe desde janeiro e vai sendo preenchido mês a
mês. O painel só usa ano com os 12 meses de todos os estados; se o ano mais
recente ainda não fechou, fica o anterior.

O arquivo traz o NOME do município, não o código do IBGE
---------------------------------------------------------
O casamento é por UF + nome normalizado (sem acento, caixa e pontuação). Seis
grafias diferem da malha do IBGE e estão em GRAFIAS. Se aparecer nome novo sem
par, o script avisa e conta a vítima só no total do estado — que é onde ela
de fato está. As linhas "NÃO INFORMADO" entram igualmente só no estado.

Saída: fonte/auto/auto_sinesp.csv + auto_sinesp.meta.json + auto_sinesp.estado.json
"""
import argparse, collections, html, io, json, os, re, sys, unicodedata
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rede                                    # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTO = os.path.join(RAIZ, 'fonte', 'auto')
PAGINA = ('https://www.gov.br/mj/pt-br/assuntos/sua-seguranca/seguranca-publica/'
          'estatistica/dados-nacionais-1/base-de-dados-e-notas-metodologicas-dos-'
          'gestores-estaduais-sinesp-vde-2022-e-2023')
ARQUIVO = ('https://www.gov.br/mj/pt-br/assuntos/sua-seguranca/seguranca-publica/'
           'estatistica/download/dnsp-base-de-dados/bancovde-%d.xlsx/@@download/file')

EVENTOS = ('Homicídio doloso', 'Feminicídio',
           'Roubo seguido de morte (latrocínio)', 'Lesão corporal seguida de morte')

# Nome no SINESP -> nome na malha do IBGE, por UF. Conferido em nov/2026 com a
# base de 2025: são as únicas seis diferenças entre 5.570 municípios.
GRAFIAS = {
    ('MG', 'BARAO DE MONTE ALTO'): 'BARAO DO MONTE ALTO',
    ('MT', 'SANTO ANTONIO DO LEVERGER'): 'SANTO ANTONIO DE LEVERGER',
    ('RN', 'ARES'): 'AREZ',
    ('RN', 'ACU'): 'ASSU',
    ('RR', 'SAO LUIZ'): 'SAO LUIZ DO ANAUA',
    ('SE', 'GRACHO CARDOSO'): 'GRACCHO CARDOSO',
}

UF_SIGLA = {'11': 'RO', '12': 'AC', '13': 'AM', '14': 'RR', '15': 'PA', '16': 'AP',
            '17': 'TO', '21': 'MA', '22': 'PI', '23': 'CE', '24': 'RN', '25': 'PB',
            '26': 'PE', '27': 'AL', '28': 'SE', '29': 'BA', '31': 'MG', '32': 'ES',
            '33': 'RJ', '35': 'SP', '41': 'PR', '42': 'SC', '43': 'RS', '50': 'MS',
            '51': 'MT', '52': 'GO', '53': 'DF'}
SIGLA_UF = {s: c for c, s in UF_SIGLA.items()}


def norm(t):
    t = unicodedata.normalize('NFKD', str(t)).encode('ascii', 'ignore').decode().upper()
    return re.sub(r'\s+', ' ', re.sub(r'[^A-Z0-9]+', ' ', t)).strip()


def anos_publicados():
    """Anos com arquivo na página, lidos dos links — nunca de uma lista fixa."""
    pag = rede.le(PAGINA, espera=90).decode('utf-8', 'ignore')
    anos = sorted({int(a) for a in re.findall(r'bancovde-(\d{4})\.xlsx', html.unescape(pag))})
    if not anos:
        raise SystemExit('Nenhum bancovde-AAAA.xlsx na página. Confira ' + PAGINA)
    return anos


def assinatura(ano):
    """Tamanho e data do arquivo, sem baixá-lo: os estados revisam números
    antigos, e uma revisão muda o arquivo sem mudar o ano."""
    # O gov.br recusa HEAD (403). Abre com GET e fecha antes de ler o corpo:
    # os cabeçalhos chegam, os 26 MB não.
    with rede.abre(ARQUIVO % ano, espera=60) as r:
        return '%s|%s' % (r.headers.get('Content-Length'), r.headers.get('Last-Modified'))


def le_ano(ano):
    """Vítimas de CVLI por (UF, nome normalizado), total por UF e meses por UF."""
    import openpyxl
    print('  baixando bancovde-%d.xlsx…' % ano)
    dados = rede.le(ARQUIVO % ano, espera=600)
    print('  %.1f MB; lendo' % (len(dados) / 1e6))
    ws = openpyxl.load_workbook(io.BytesIO(dados), read_only=True).worksheets[0]
    linhas = ws.iter_rows(values_only=True)
    cab = [str(c or '').strip().lower() for c in next(linhas)]
    for c in ('uf', 'municipio', 'evento', 'data_referencia', 'total_vitima'):
        if c not in cab:
            raise SystemExit("Coluna '%s' sumiu do arquivo de %d. Colunas: %s"
                             % (c, ano, cab))
    ix = {c: cab.index(c) for c in cab}
    por_mun = collections.Counter()
    por_uf = collections.Counter()
    meses = collections.defaultdict(set)
    vistos = set()
    for r in linhas:
        ev = r[ix['evento']]
        if ev not in EVENTOS:
            continue
        uf = str(r[ix['uf']] or '').strip()
        mun = norm(r[ix['municipio']] or '')
        v = r[ix['total_vitima']]
        v = float(v) if v not in (None, '') else 0.0
        dt = r[ix['data_referencia']]
        if hasattr(dt, 'month'):
            meses[uf].add(dt.month)
        vistos.add(ev)
        por_uf[uf] += v
        if mun and mun != 'NAO INFORMADO':
            por_mun[(uf, GRAFIAS.get((uf, mun), mun))] += v
    faltam = set(EVENTOS) - vistos
    if faltam:
        raise SystemExit('O arquivo de %d não tem %s. O SINESP mudou o nome do '
                         'evento? Confira %s' % (ano, ', '.join(sorted(faltam)), PAGINA))
    return por_mun, por_uf, meses


def populacao(ano):
    """Estimativa do IBGE por município, UF e Brasil (SIDRA 6579), SÓ do ano
    pedido. Vítimas de um ano divididas pela população de outro dão uma taxa
    que não descreve ano nenhum; se a estimativa do ano ainda não saiu, o
    script para em vez de misturar. Na prática não deve acontecer: o IBGE
    publica a estimativa de um ano em agosto desse mesmo ano, e o ano do
    SINESP só fecha no começo do ano seguinte."""
    saida = {}
    for nivel, tam in (('n6', 7), ('n3', 2), ('n1', 1)):
        url = ('https://apisidra.ibge.gov.br/values/t/6579/%s/all/v/9324/p/%d'
               % (nivel, ano))
        try:
            bruto = json.loads(rede.le(url, espera=300).decode('utf-8'))
        except Exception as erro:
            raise SystemExit('A estimativa de população de %d (%s) não veio: %s. '
                             'Sem ela a taxa misturaria anos; tente de novo mais '
                             'tarde.' % (ano, nivel, erro))
        for l in bruto[1:]:
            cod = str(l.get('D1C', ''))
            if len(cod) != tam or str(l.get('D3C')) != str(ano):
                continue
            try:
                saida['BR' if nivel == 'n1' else cod] = float(l['V'])
            except (ValueError, KeyError):
                pass
    if len(saida) < 5500:
        raise SystemExit('A estimativa de população de %d trouxe só %d territórios. '
                         'Sem ela a taxa misturaria anos.' % (ano, len(saida)))
    print('  população: estimativa IBGE %d (%d territórios)' % (ano, len(saida)))
    return saida


def municipios():
    """Código, UF e nome normalizado dos 5.570 da malha, pelo meta.json."""
    meta = json.load(open(os.path.join(RAIZ, 'dados', 'meta.json'), encoding='utf-8'))
    out = {}
    for cod, nome, uf in zip(meta['municipios'], meta['nomes'], meta['uf']):
        out[(UF_SIGLA[str(uf).zfill(2)], norm(nome))] = str(cod)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--so-checar', action='store_true')
    ap.add_argument('--forcar', action='store_true')
    args = ap.parse_args()

    os.makedirs(AUTO, exist_ok=True)
    cam_estado = os.path.join(AUTO, 'auto_sinesp.estado.json')
    estado = json.load(open(cam_estado, encoding='utf-8')) if os.path.exists(cam_estado) else {}

    agora = datetime.now(timezone.utc)
    anos = [a for a in anos_publicados() if a < agora.year]
    if not anos:
        raise SystemExit('Nenhum ano fechado publicado ainda.')
    candidato = anos[-1]
    sig = assinatura(candidato)
    print('Último ano fechado com arquivo: %d (%s)' % (candidato, sig))
    print('Processado aqui: %s (%s)' % (estado.get('ano', 'nenhum'), estado.get('assinatura', '—')))
    novidade = (estado.get('ano') != candidato or estado.get('assinatura') != sig)

    if args.so_checar:
        print('MUDOU' if novidade else 'sem novidade')
        gh = os.environ.get('GITHUB_OUTPUT')
        if gh:
            with open(gh, 'a', encoding='utf-8') as f:
                f.write('novidade=%s\nano=%s\n' % ('true' if novidade else 'false', candidato))
        return
    if not novidade and not args.forcar:
        print('Nada a fazer.')
        return

    # Do ano mais novo para trás, até achar um com os 12 meses dos 27 estados.
    for ano in reversed(anos[-2:]):
        por_mun, por_uf, meses = le_ano(ano)
        incompletos = {uf: len(m) for uf, m in meses.items() if len(m) < 12}
        if len(meses) == 27 and not incompletos:
            break
        print('  %d ainda não fechou (estados com menos de 12 meses: %s)'
              % (ano, incompletos or 'faltam estados'))
    else:
        raise SystemExit('Nenhum dos dois últimos anos está completo.')

    mapa = municipios()
    cvli, sem_par = {}, []
    for (uf, nome), v in por_mun.items():
        cod = mapa.get((uf, nome))
        if cod:
            cvli[cod] = cvli.get(cod, 0) + v
        elif v:
            sem_par.append('%s/%s (%d)' % (uf, nome, v))
    if sem_par:
        print('  AVISO: nomes sem par na malha, contados só no estado: '
              + ', '.join(sorted(sem_par)))
    if len(cvli) < 5500:
        raise SystemExit('Só %d municípios casaram com a malha; esperado ~5.570. '
                         'A grafia do arquivo mudou?' % len(cvli))

    pop = populacao(ano)
    tx = {}
    for cod, v in cvli.items():
        if pop.get(cod):
            tx[cod] = round(v / pop[cod] * 1e5, 1)
    uf_cvli = {SIGLA_UF[s]: v for s, v in por_uf.items() if s in SIGLA_UF}
    total = sum(uf_cvli.values())

    caminho = os.path.join(AUTO, 'auto_sinesp.csv')
    with open(caminho, 'w', encoding='utf-8', newline='') as f:
        f.write('codigo;cvli;tx_cvli\n')
        for cod in sorted(cvli):
            f.write('%s;%d;%s\n' % (cod, cvli[cod], tx.get(cod, '')))
        for cod in sorted(uf_cvli):
            t = round(uf_cvli[cod] / pop[cod] * 1e5, 1) if pop.get(cod) else ''
            f.write('%s;%d;%s\n' % (cod, uf_cvli[cod], t))
        f.write('BR;%d;%s\n' % (total, round(total / pop['BR'] * 1e5, 1) if pop.get('BR') else ''))

    fonte = 'MJSP — SINESP VDE %d' % ano
    meta = {
        'cvli': {'nome': 'Crimes violentos letais (CVLI)', 'tema': 'seguranca',
                 'unidade': 'vítimas', 'formato': 'int', 'somavel': '1',
                 'ano': str(ano), 'fonte': fonte},
        'tx_cvli': {'nome': 'Taxa de CVLI', 'tema': 'seguranca',
                    'unidade': '/100 mil hab', 'formato': 'dec1', 'somavel': '0',
                    'ano': str(ano),
                    'fonte': '%s; população: IBGE, estimativa %d' % (fonte, ano)},
    }
    with open(os.path.join(AUTO, 'auto_sinesp.meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    estado = {'ano': ano, 'assinatura': assinatura(ano), 'origem': PAGINA,
              'eventos': list(EVENTOS),
              'verificadoEm': agora.strftime('%Y-%m-%d %H:%M UTC'),
              'totais': {'municipios': len(cvli), 'vitimas_brasil': int(total),
                         'taxa_brasil': round(total / pop['BR'] * 1e5, 1) if pop.get('BR') else None,
                         'sem_par': sem_par}}
    with open(cam_estado, 'w', encoding='utf-8') as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)
    print('Gravado: %d municípios · Brasil %d vítimas · %s por 100 mil'
          % (len(cvli), total, estado['totais']['taxa_brasil']))


if __name__ == '__main__':
    main()
