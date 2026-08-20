#!/usr/bin/env python3
"""
Reduz o CSV do Censo Escolar ao que o painel usa e comprime.

O arquivo original do INEP tem 263 colunas e ~124 MB — grande demais para o
repositório, e 200 dessas colunas são desdobramentos que não vão para a tela.
Este script fica de fora da automação: roda uma vez, na máquina de quem prepara
a base, e o resultado (~7 MB) é o que entra no repositório.

    python scripts/preparar_fonte_edu.py "_fonte/Tabela Matriculas.csv"

Gera fonte/matriculas-<ano>.csv.gz, que é o que build_edu.py lê.
"""
import csv, gzip, io, os, sys

csv.field_size_limit(10**9)

IDENT = ['NU_ANO_CENSO', 'CO_MUNICIPIO', 'SG_UF', 'NO_ENTIDADE', 'CO_ENTIDADE',
         'TP_DEPENDENCIA', 'TP_LOCALIZACAO']

# Ordem de exibição no painel. Mudar aqui muda a tela: build_edu.py e o
# index.html leem a ordem daqui, não têm lista própria.
MAT = [
    'QT_MAT_BAS',
    'QT_MAT_INF', 'QT_MAT_INF_CRE', 'QT_MAT_INF_PRE',
    'QT_MAT_FUND',
    'QT_MAT_FUND_AI', 'QT_MAT_FUND_AI_1', 'QT_MAT_FUND_AI_2', 'QT_MAT_FUND_AI_3',
    'QT_MAT_FUND_AI_4', 'QT_MAT_FUND_AI_5',
    'QT_MAT_FUND_AF', 'QT_MAT_FUND_AF_6', 'QT_MAT_FUND_AF_7', 'QT_MAT_FUND_AF_8',
    'QT_MAT_FUND_AF_9',
    'QT_MAT_MED', 'QT_MAT_MED_1', 'QT_MAT_MED_2', 'QT_MAT_MED_3', 'QT_MAT_MED_4',
    'QT_MAT_MED_NS', 'QT_MAT_MED_IFTP_CT',
    'QT_MAT_EJA', 'QT_MAT_EJA_FUND', 'QT_MAT_EJA_MED',
    'QT_MAT_PROF', 'QT_MAT_PROF_TEC', 'QT_MAT_PROF_NAO_TEC',
    'QT_MAT_ESP', 'QT_MAT_ESP_CC', 'QT_MAT_ESP_CE',
    'QT_MAT_ESP_INF', 'QT_MAT_ESP_FUND', 'QT_MAT_ESP_MED', 'QT_MAT_ESP_EJA',
    'QT_MAT_ESP_PROF',
    'QT_MAT_BAS_FEM', 'QT_MAT_BAS_MASC',
    'QT_MAT_ZR_URB', 'QT_MAT_ZR_RUR', 'QT_MAT_ZR_NA',
]


def main(origem, destino_dir='fonte'):
    f = open(origem, encoding='utf-8-sig', newline='')
    r = csv.reader(f, delimiter=';')
    hdr = next(r)
    ix = {c: i for i, c in enumerate(hdr)}

    faltam = [c for c in IDENT + MAT if c not in ix]
    if faltam:
        raise SystemExit('Colunas ausentes no arquivo de origem: ' + ', '.join(faltam))

    manter = [ix[c] for c in IDENT + MAT]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=';', lineterminator='\n')
    w.writerow(IDENT + MAT)

    ano, n = None, 0
    for row in r:
        if ano is None:
            ano = row[ix['NU_ANO_CENSO']].strip()
        w.writerow([row[j] for j in manter])
        n += 1

    os.makedirs(destino_dir, exist_ok=True)
    saida = os.path.join(destino_dir, f'matriculas-{ano}.csv.gz')
    dados = buf.getvalue().encode('utf-8')
    with gzip.open(saida, 'wb', compresslevel=9) as g:
        g.write(dados)

    print(f'{n:,} escolas · ano {ano}'.replace(',', '.'))
    print(f'{len(IDENT) + len(MAT)} colunas mantidas de {len(hdr)}')
    print(f'{saida} — {os.path.getsize(saida) / 1e6:.1f} MB '
          f'(de {os.path.getsize(origem) / 1e6:.0f} MB)')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else 'fonte')
