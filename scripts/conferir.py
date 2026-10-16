#!/usr/bin/env python3
"""
Varredura de consistência dos dados publicados em dados/.

Não substitui o relatório do `build.py`, que confere a LEITURA das fontes. Este
olha o resultado já publicado e procura o que só aparece cruzando um número com
outro: um agregado que não fecha com os municípios, uma soma de partes maior
que o todo, uma densidade que não bate com população dividida por área.

    python scripts/conferir.py            # roda tudo e resume
    python scripts/conferir.py --detalhe  # lista os municípios de cada achado

A saída é dividida em ERRO (número errado no ar), AVISO (suspeito, confira) e
NOTA (esperado, registrado para não assustar quem ler). Sai com código 1 se
houver ERRO, para poder entrar no CI algum dia.
"""
import argparse, json, os, sys
from collections import defaultdict

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DADOS = os.path.join(RAIZ, 'dados')

achados = {'ERRO': [], 'AVISO': [], 'NOTA': []}
DETALHE = False


def conta(nivel, titulo, detalhe=None):
    achados[nivel].append((titulo, detalhe or []))


def carrega():
    meta = json.load(open(os.path.join(DADOS, 'meta.json'), encoding='utf-8'))
    series = {}
    for ind in meta['dicionario']:
        caminho = os.path.join(DADOS, 'ind', ind + '.json')
        if os.path.exists(caminho):
            series[ind] = json.load(open(caminho, encoding='utf-8'))
    return meta, series


def num(v):
    return v if isinstance(v, (int, float)) else None


# ----------------------------------------------------------- as conferências
# Agregados que são RAZÃO, não média: o numerador e o denominador se somam
# pelos municípios e só então se dividem. Densidade do Brasil é população do
# Brasil dividida pela área do Brasil — e não a média das densidades
# municipais, que dá 1.574 hab/km² contra os 23,9 reais, porque as capitais
# pesam igual aos municípios enormes e vazios. Foi essa confusão que esta
# tabela existe para evitar, aqui e na cabeça de quem for mexer depois.
COMO_AGREGA = {
    'dens_dem':      ('pop_total', 'area_km2', 1),
    'pib_pc':        ('pib_total', 'pop_total', 1),
    'prop_pop_urb':  ('pop_urbana', 'pop_total', 100),
    'part_vab_agro': ('vab_agro', 'vab_total', 100),
    'part_vab_ind':  ('vab_ind', 'vab_total', 100),
    'part_vab_serv': ('vab_serv', 'vab_total', 100),
    'part_vab_adm':  ('vab_adm', 'vab_total', 100),
    'pct_homens':    ('pop_homens', 'pop_total', 100),
    'pct_mulheres':  ('pop_mulheres', 'pop_total', 100),
}
# Índices que não se agregam de jeito nenhum a partir dos municípios: o IDHM
# do Brasil é calculado pelo PNUD com os microdados, não com os 5.570 IDHMs.
# Conferi-los contra uma conta nossa só produziria alarme falso.
NAO_AGREGAVEIS = {'idhm', 'gini', 'ifdm', 'salario_medio', 'caged_var',
                  'tx_homicidios', 'tx_roubos', 'prop_area_urb', 'pct_ocupada',
                  'res_massa_pc', 'consumo', 'perdas'}


def agregados_fecham(meta, series):
    """
    O agregado de UF e do Brasil tem de bater com os municípios.

    Só é possível conferir o que dá para recompor: soma, para os indicadores
    somáveis, e razão, para os de COMO_AGREGA. Um índice como o IDHM não entra
    — ver NAO_AGREGAVEIS.

    Uma diferença grande quer dizer que o total "oficial" da planilha
    envelheceu em relação aos municípios, que foi exatamente o que aconteceu
    com as escolas ao trocar o QEdu pelo INEP.
    """
    idx_uf = defaultdict(list)
    for i, u in enumerate(meta['uf']):
        idx_uf[u].append(i)

    def soma(ind, ids):
        vet = series.get(ind)
        if not vet:
            return None
        acc, achou = 0.0, False
        for i in ids:
            v = num(vet[i])
            if v is not None:
                acc += v
                achou = True
        return acc if achou else None

    for chave, ids in [('BR', list(range(len(meta['municipios']))))] + \
                      [(u, idx_uf[u]) for u in sorted(idx_uf)]:
        ag = meta['agregados'].get(chave, {})
        oficiais = set(meta['oficiais'].get(chave, []))
        for ind, dic in meta['dicionario'].items():
            publicado = num(ag.get(ind))
            if publicado is None or dic['formato'] == 'texto':
                continue
            if ind in NAO_AGREGAVEIS:
                continue
            if dic['somavel']:
                calc = soma(ind, ids)
            elif ind in COMO_AGREGA:
                cima, baixo, escala = COMO_AGREGA[ind]
                a, b = soma(cima, ids), soma(baixo, ids)
                calc = (a / b * escala) if (a is not None and b) else None
            else:
                continue
            if calc is None:
                continue
            base = max(abs(calc), abs(publicado), 1e-9)
            dif = abs(calc - publicado) / base
            # 2% de folga para arredondamento (o painel publica densidade com
            # uma casa, participações com duas) e para o fato de a fonte às
            # vezes calcular o total com mais precisão do que o que ela
            # publica por município.
            if dif > 0.02:
                # A área do Rio Grande do Sul é a exceção conhecida: a Lagoa
                # dos Patos e a Lagoa Mirim entram na área do estado e não
                # pertencem a município nenhum, então a soma dos municípios
                # fica uns 13 mil km² abaixo. O oficial é que está certo.
                if chave == '43' and ind in ('area_km2', 'dens_dem'):
                    conta('NOTA', '43/%s: a soma dos municípios fica abaixo do '
                                  'oficial porque a Lagoa dos Patos e a Lagoa '
                                  'Mirim entram na área do estado e não '
                                  'pertencem a município nenhum' % ind)
                    continue
                conta('ERRO' if ind in oficiais else 'AVISO',
                      '%s/%s: publicado %s, municípios dão %s (%.1f%% de '
                      'diferença)%s' % (chave, ind, fmt(publicado), fmt(calc),
                                        dif * 100,
                                        ' — valor oficial da planilha'
                                        if ind in oficiais else ''))


def fmt(v):
    if v is None:
        return '-'
    if abs(v) >= 1e9:
        return '%.3f bi' % (v / 1e9)
    if abs(v) >= 1e6:
        return '%.2f mi' % (v / 1e6)
    return ('%.2f' % v).rstrip('0').rstrip('.')


# Conjuntos que têm de somar um total, por município.
SOMAS = [
    ('escolas_total', ['escolas_federais', 'escolas_estaduais',
                       'escolas_municipais', 'escolas_privadas'], 'rede'),
    ('escolas_total', ['escolas_urbanas', 'escolas_rurais'], 'localização'),
    ('pop_total', ['pop_urbana', 'pop_rural'], 'situação do domicílio'),
    ('vab_total', ['vab_agro', 'vab_ind', 'vab_serv', 'vab_adm'], 'setores'),
]


def partes_somam(meta, series):
    for total, partes, rotulo in SOMAS:
        if total not in series or any(p not in series for p in partes):
            continue
        ruins = []
        for i, cod in enumerate(meta['municipios']):
            t = num(series[total][i])
            vs = [num(series[p][i]) for p in partes]
            if t is None or any(v is None for v in vs):
                continue
            s = sum(vs)
            if abs(s - t) > max(abs(t) * 0.005, 1):
                ruins.append('%s %s: total %s, partes somam %s'
                             % (cod, meta['nomes'][i], fmt(t), fmt(s)))
        if ruins:
            conta('ERRO', '%s por %s: %d municípios em que as partes não somam '
                          'o total' % (total, rotulo, len(ruins)), ruins[:12])


# Razões que o painel publica e que podem ser recalculadas do que ele mesmo tem.
# alvo, numerador, denominador, escala, rótulo, folga absoluta.
# A folga absoluta existe por causa do arredondamento de números pequenos: o
# painel publica densidade com duas casas, então Barcelos (AM) sai como 0,15
# enquanto 18.834/122.461 dá 0,1538 — 2,5% de diferença relativa que é só a
# vírgula, não erro. Em escala pequena, a diferença relativa engana.
RAZOES = [
    ('dens_dem', 'pop_total', 'area_km2', 1, 'densidade', 0.01),
    ('pib_pc', 'pib_total', 'pop_total', 1, 'PIB per capita', 1.0),
    ('prop_pop_urb', 'pop_urbana', 'pop_total', 100, 'proporção urbana', 0.1),
]


def razoes_batem(meta, series):
    for alvo, numerador, denominador, escala, rotulo, folga in RAZOES:
        if any(k not in series for k in (alvo, numerador, denominador)):
            continue
        ruins = []
        for i, cod in enumerate(meta['municipios']):
            a = num(series[alvo][i])
            n = num(series[numerador][i])
            d = num(series[denominador][i])
            if a is None or n is None or not d:
                continue
            esperado = n / d * escala
            base = max(abs(esperado), abs(a), 1e-9)
            if abs(esperado - a) <= folga:
                continue
            if abs(esperado - a) / base > 0.02:
                ruins.append('%s %s: publicado %s, calculado %s'
                             % (cod, meta['nomes'][i], fmt(a), fmt(esperado)))
        if ruins:
            # O PIB per capita tem uma explicação conhecida e não é erro: o
            # IBGE divide pela população ESTIMADA do ano de referência, e o
            # painel carrega a do Censo 2022. Onde a população mudou muito
            # entre um e outro, as duas contas divergem — e a do IBGE é a
            # certa, porque é a que ele publica.
            nivel = 'NOTA' if alvo == 'pib_pc' else 'AVISO'
            conta(nivel, '%s (%s): %d municípios fora de 2%% do recalculado'
                         '%s' % (alvo, rotulo, len(ruins),
                                 ' — esperado: o IBGE usa a população estimada '
                                 'do ano de referência, o painel usa a do Censo'
                                 if alvo == 'pib_pc' else ''), ruins[:12])


def percentuais_na_faixa(meta, series):
    for ind, dic in meta['dicionario'].items():
        if dic['formato'] != 'pct' or ind not in series:
            continue
        # Variação é percentual mas não é fatia de nada: o saldo do CAGED pode
        # cair 30% ou subir 300% num município pequeno, e as duas coisas são
        # verdade. Só entram aqui os percentuais que são parte de um todo.
        if ind.endswith('_var') or ind.startswith('tx_'):
            continue
        ruins = []
        for i, cod in enumerate(meta['municipios']):
            v = num(series[ind][i])
            if v is None:
                continue
            if v < 0 or v > 100:
                ruins.append('%s %s: %s%%' % (cod, meta['nomes'][i], fmt(v)))
        if ruins:
            conta('ERRO', '%s: %d municípios com percentual fora de 0 a 100'
                          % (ind, len(ruins)), ruins[:12])


def negativos_impossiveis(meta, series):
    """Contagens e valores de estoque não podem ser negativos."""
    for ind, dic in meta['dicionario'].items():
        if ind not in series or dic['formato'] == 'texto':
            continue
        # Saldo do CAGED e variações são negativos por natureza. O VAB também
        # pode ser: o IBGE publica valor adicionado negativo quando os
        # consumos intermediários de um setor superam a produção no ano — em
        # 2021, a indústria de Cachoeira Dourada (GO) saiu com -477 milhões.
        # É estranho, é raro, e é o que a fonte diz.
        if ('saldo' in ind or 'var' in ind or ind.startswith('tx_')
                or ind.startswith('vab_')):
            continue
        ruins = [('%s %s: %s' % (meta['municipios'][i], meta['nomes'][i], fmt(v)))
                 for i in range(len(meta['municipios']))
                 if (v := num(series[ind][i])) is not None and v < 0]
        if ruins:
            conta('ERRO', '%s: %d municípios com valor negativo'
                          % (ind, len(ruins)), ruins[:12])


def cobertura(meta, series):
    """Quantos municípios cada indicador deixa sem dado."""
    n = len(meta['municipios'])
    vazios = []
    for ind in meta['dicionario']:
        if ind not in series:
            conta('AVISO', '%s está no dicionário mas não tem arquivo em '
                           'dados/ind/' % ind)
            continue
        faltam = sum(1 for v in series[ind] if num(v) is None
                     and not isinstance(v, str))
        if faltam == n:
            conta('ERRO', '%s: nenhum município tem valor' % ind)
        elif faltam > n * 0.5:
            vazios.append('%s: %d de %d sem dado (%.0f%%)'
                          % (ind, faltam, n, faltam / n * 100))
    if vazios:
        conta('NOTA', '%d indicadores cobrem menos de metade dos municípios'
                      % len(vazios), vazios)


def anos_coerentes(meta):
    """Indicadores da mesma fonte com anos diferentes merecem explicação."""
    por_fonte = defaultdict(set)
    for ind, d in meta['dicionario'].items():
        if d.get('fonte') and d.get('ano'):
            por_fonte[d['fonte'].split('—')[0].strip()].add(str(d['ano']))
    for fonte, anos in sorted(por_fonte.items()):
        if len(anos) > 1:
            conta('NOTA', '%s publica com anos diferentes no painel: %s'
                          % (fonte, ', '.join(sorted(anos))))


def malha_e_dicionario(meta, series):
    n = len(meta['municipios'])
    if len(set(meta['municipios'])) != n:
        conta('ERRO', 'há códigos de município repetidos na malha')
    for nome, vet in [('nomes', meta['nomes']), ('uf', meta['uf'])]:
        if len(vet) != n:
            conta('ERRO', 'meta.%s tem %d itens e a malha tem %d'
                          % (nome, len(vet), n))
    for ind, vet in series.items():
        if len(vet) != n:
            conta('ERRO', 'dados/ind/%s.json tem %d valores e a malha tem %d'
                          % (ind, len(vet), n))


def participacoes_vab(meta, series):
    """As quatro participações setoriais têm de somar 100%."""
    partes = ['part_vab_agro', 'part_vab_ind', 'part_vab_serv', 'part_vab_adm']
    if any(p not in series for p in partes):
        return
    ruins = []
    for i, cod in enumerate(meta['municipios']):
        vs = [num(series[p][i]) for p in partes]
        if any(v is None for v in vs):
            continue
        s = sum(vs)
        if abs(s - 100) > 1.5:
            ruins.append('%s %s: somam %s%%' % (cod, meta['nomes'][i], fmt(s)))
    if ruins:
        conta('AVISO', 'participações no VAB: %d municípios em que as quatro '
                       'não somam 100%%' % len(ruins), ruins[:12])


def main():
    global DETALHE
    ap = argparse.ArgumentParser()
    ap.add_argument('--detalhe', action='store_true')
    DETALHE = ap.parse_args().detalhe

    meta, series = carrega()
    print('Painel %s · %s · %d municípios · %d indicadores\n'
          % (meta['versao'], meta['atualizado'], len(meta['municipios']),
             len(meta['dicionario'])))

    malha_e_dicionario(meta, series)
    agregados_fecham(meta, series)
    partes_somam(meta, series)
    razoes_batem(meta, series)
    participacoes_vab(meta, series)
    percentuais_na_faixa(meta, series)
    negativos_impossiveis(meta, series)
    cobertura(meta, series)
    anos_coerentes(meta)

    for nivel in ('ERRO', 'AVISO', 'NOTA'):
        itens = achados[nivel]
        print('%s (%d)' % (nivel, len(itens)))
        if not itens:
            print('  nada')
        for titulo, detalhe in itens:
            print('  · ' + titulo)
            if DETALHE:
                for d in detalhe:
                    print('      ' + d)
        print()
    return 1 if achados['ERRO'] else 0


if __name__ == '__main__':
    sys.exit(main())
