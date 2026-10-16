#!/usr/bin/env python3
"""
Vigia das escolas do Censo Escolar (INEP) — o bloco `escolas_*` do painel.

Irmão do `monitor_censo.py`, que cuida das matrículas do subpainel de educação.
Este cuida das contagens de escolas que aparecem na ficha do município. Os dois
leem o mesmo pacote anual; a divisão é por assunto, não por arquivo.

    python scripts/monitor_escolas.py --so-checar   # diz se saiu ano novo
    python scripts/monitor_escolas.py               # baixa e grava fonte/auto/
    python scripts/monitor_escolas.py --forcar      # reprocessa mesmo sem ano novo

Saída: fonte/auto/auto_escolas.csv + auto_escolas.meta.json + .estado.json

De onde vem o dado
------------------
Do INEP, direto, pelos microdados. Até 2026 esses números vinham do QEdu, que
não produz dado nenhum — exibe o Censo Escolar. Ler a fonte primária tira um
intermediário do caminho e, principalmente, deixa a definição de cada indicador
escrita aqui, em vez de dependente de uma escolha que o QEdu nunca documentou.

O pacote traz duas tabelas de que se precisa:

  * `Tabela_Escola`    — uma linha por escola: rede, localização, situação de
                         funcionamento e atendimento especializado;
  * `Tabela_Matricula` — uma linha por escola com `QT_MAT_BAS`, usada só para
                         classificar o porte.

Ambas são escolhidas pelo CONTEÚDO (colunas que precisam ter), nunca pelo nome:
em 2025 o INEP reorganizou o pacote e `Tabela_Escola` passou a existir — quem
procurasse `microdados_ed_basica_<ano>.csv` não acharia nada.

As definições, e por que são estas
----------------------------------
1. **Só escolas em atividade** (`TP_SITUACAO_FUNCIONAMENTO = 1`). O censo
   registra também paralisadas e extintas — em 2025 foram 33.652 das 214.192
   linhas. Contá-las infla o número de escolas de um município em cerca de 16%
   com estabelecimentos que não atendem ninguém, o que num diagnóstico
   socioambiental é pior que inútil: é enganoso. Era o que o número do QEdu
   fazia, e é a diferença que explica a queda ao trocar de fonte.

2. **Rede e localização repartem o total exatamente.** Mesmo universo das
   escolas em atividade, então `federais + estaduais + municipais + privadas`
   e `urbanas + rurais` fecham com `escolas_total`. Dá para conferir.

3. **Porte por faixa de matrículas:** até 50, de 51 a 500, acima de 500. Estas
   faixas não foram inventadas: foram deduzidas da própria série que estava no
   painel. Aplicadas ao censo, reproduzem a distribuição do número anterior com
   erro de 0,7 ponto percentual nas três faixas, enquanto o segundo candidato
   mais próximo erra 4,6 vezes mais. Manter as faixas antigas preserva a
   comparabilidade com o que já foi publicado em relatórios.
   O porte cobre só escolas com matrícula declarada: as poucas que estão em
   atividade e não declararam não entram em faixa nenhuma, então a soma das
   três fica um pouco abaixo do total. É o mesmo comportamento de antes.

4. **Atendimento especializado = escolas que oferecem AEE** (`TP_AEE` 1 ou 2:
   exclusivamente ou não exclusivamente). O painel tinha um `atend_especializado`
   sem definição registrada, e o microdado oferece dois candidatos parecidos e
   diferentes: oferecer o serviço (`TP_AEE`) e ter sala de recursos
   multifuncionais (`IN_SALA_ATENDIMENTO_ESPECIAL`) — o segundo é
   infraestrutura, não atendimento. Como o rótulo fala em atendimento, vale o
   serviço; e o `meta.json` renomeia o indicador para dizer isso na cara, para
   ninguém ter de adivinhar de novo.
"""
import argparse, collections, io, json, os, re, sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monitor_censo as mc          # noqa: E402  (precisa do sys.path acima)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTO = os.path.join(RAIZ, 'fonte', 'auto')

ATIVA = '1'                         # TP_SITUACAO_FUNCIONAMENTO: em atividade
REDES = {'1': 'escolas_federais', '2': 'escolas_estaduais',
         '3': 'escolas_municipais', '4': 'escolas_privadas'}
LOCAIS = {'1': 'escolas_urbanas', '2': 'escolas_rurais'}
AEE_OFERECE = ('1', '2')            # TP_AEE: exclusivamente / não exclusivamente
PORTE = (('porte_pequeno', 0, 50), ('porte_medio', 51, 500),
         ('porte_grande', 501, 10 ** 9))

ORDEM = (['escolas_total'] + list(REDES.values()) + list(LOCAIS.values())
         + [p[0] for p in PORTE] + ['atend_especializado'])

NOMES = {
    'escolas_total': 'Escolas em atividade',
    'escolas_federais': 'Escolas federais',
    'escolas_estaduais': 'Escolas estaduais',
    'escolas_municipais': 'Escolas municipais',
    'escolas_privadas': 'Escolas privadas',
    'escolas_urbanas': 'Escolas urbanas',
    'escolas_rurais': 'Escolas rurais',
    'porte_pequeno': 'Escolas de pequeno porte (até 50 matrículas)',
    'porte_medio': 'Escolas de médio porte (51 a 500 matrículas)',
    'porte_grande': 'Escolas de grande porte (mais de 500 matrículas)',
    'atend_especializado': 'Escolas com atendimento educacional especializado (AEE)',
}


def cabecalho(linha):
    return [c.strip().strip('﻿').upper() for c in re.split(r'[;,]', linha)]


def le_membro(z, membro, colunas):
    """
    Gera dicionários {coluna: valor} para cada linha do CSV, só com as colunas
    pedidas. Ler linha a linha, e não com uma biblioteca de tabelas, é de
    propósito: são 214 mil linhas por 290 colunas chegando por HTTP, e carregar
    tudo na memória de uma vez custaria caro sem nenhum ganho.
    """
    with z.open(membro) as f:
        texto = io.TextIOWrapper(f, encoding='latin-1', newline='')
        cab = cabecalho(texto.readline())
        ix = {c: i for i, c in enumerate(cab)}
        faltam = [c for c in colunas if c not in ix]
        if faltam:
            raise SystemExit('A tabela %s não tem as colunas %s. O INEP mudou a '
                             'estrutura; confira %s.'
                             % (membro, ', '.join(faltam), mc.PAGINA))
        for linha in texto:
            p = linha.rstrip('\r\n').split(';')
            if len(p) < len(cab):
                continue
            yield {c: p[ix[c]].strip() for c in colunas}


def conta_escolas(z):
    """Contagens por município, a partir da tabela de escolas."""
    membro = mc.escolhe_membro(z, colunas_exigidas=(
        'CO_ENTIDADE', 'TP_DEPENDENCIA', 'TP_LOCALIZACAO',
        'TP_SITUACAO_FUNCIONAMENTO'))
    print('  tabela de escolas: %s' % membro.rsplit('/', 1)[-1])
    por_mun = collections.defaultdict(collections.Counter)
    total = situacoes = 0
    cont_sit = collections.Counter()
    for r in le_membro(z, membro, ('CO_MUNICIPIO', 'TP_DEPENDENCIA',
                                   'TP_LOCALIZACAO',
                                   'TP_SITUACAO_FUNCIONAMENTO', 'TP_AEE')):
        total += 1
        cont_sit[r['TP_SITUACAO_FUNCIONAMENTO']] += 1
        if r['TP_SITUACAO_FUNCIONAMENTO'] != ATIVA:
            continue
        cod = r['CO_MUNICIPIO']
        if len(cod) != 7:
            continue
        situacoes += 1
        c = por_mun[cod]
        c['escolas_total'] += 1
        if r['TP_DEPENDENCIA'] in REDES:
            c[REDES[r['TP_DEPENDENCIA']]] += 1
        if r['TP_LOCALIZACAO'] in LOCAIS:
            c[LOCAIS[r['TP_LOCALIZACAO']]] += 1
        if r['TP_AEE'] in AEE_OFERECE:
            c['atend_especializado'] += 1
    print('  %d linhas no censo · %d em atividade (situações: %s)'
          % (total, situacoes, dict(cont_sit.most_common())))
    return por_mun, total, situacoes


def conta_porte(z, por_mun):
    """Acrescenta as faixas de porte, a partir da tabela de matrículas."""
    membro = mc.escolhe_membro(z, colunas_exigidas=('CO_ENTIDADE', 'QT_MAT_BAS'))
    print('  tabela de matrículas: %s' % membro.rsplit('/', 1)[-1])
    classificadas = 0
    for r in le_membro(z, membro, ('CO_MUNICIPIO', 'QT_MAT_BAS')):
        cod = r['CO_MUNICIPIO']
        if len(cod) != 7 or cod not in por_mun:
            continue
        try:
            m = int(r['QT_MAT_BAS'] or 0)
        except ValueError:
            continue
        for nome, piso, teto in PORTE:
            if piso <= m <= teto:
                por_mun[cod][nome] += 1
                classificadas += 1
                break
    print('  %d escolas classificadas por porte' % classificadas)
    return classificadas


def confere(por_mun, classificadas):
    """
    Conferências que falham alto em vez de publicar número errado em silêncio.
    """
    soma = collections.Counter()
    for c in por_mun.values():
        soma.update(c)
    t = soma['escolas_total']
    redes = sum(soma[i] for i in REDES.values())
    locais = sum(soma[i] for i in LOCAIS.values())
    print('  BR: %d escolas · redes somam %d · localizações somam %d · AEE %d'
          % (t, redes, locais, soma['atend_especializado']))
    if redes != t:
        raise SystemExit('As redes somam %d e o total é %d. Apareceu código de '
                         'dependência fora de 1-4 — confira antes de publicar.'
                         % (redes, t))
    if locais != t:
        raise SystemExit('As localizações somam %d e o total é %d. Apareceu '
                         'código fora de 1-2 — confira antes de publicar.'
                         % (locais, t))
    portes = sum(soma[p[0]] for p in PORTE)
    if portes > t:
        raise SystemExit('O porte classificou %d escolas, mais que as %d em '
                         'atividade. A tabela de matrículas traz escola que a '
                         'de escolas não traz.' % (portes, t))
    fora = t - portes
    if fora:
        print('  %d escolas em atividade sem matrícula declarada ficam fora '
              'das faixas de porte' % fora)
    if not 150000 < t < 250000:
        print('  AVISO: %d escolas em atividade está fora da faixa histórica '
              '(150 a 250 mil). Confira antes de publicar.' % t)
    return soma


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--so-checar', action='store_true')
    ap.add_argument('--forcar', action='store_true')
    args = ap.parse_args()

    os.makedirs(AUTO, exist_ok=True)
    caminho_estado = os.path.join(AUTO, 'auto_escolas.estado.json')
    estado = {}
    if os.path.exists(caminho_estado):
        estado = json.loads(open(caminho_estado, encoding='utf-8').read())

    links = mc.anos_publicados()
    ano = max(links)
    anterior = estado.get('ano')
    print('Ano mais recente no INEP: %s' % ano)
    print('Último processado aqui: %s' % (anterior or 'nenhum'))

    novidade = (anterior != ano)
    if args.so_checar:
        print('MUDOU' if novidade else 'sem novidade')
        saida = os.environ.get('GITHUB_OUTPUT')
        if saida:
            with open(saida, 'a', encoding='utf-8') as f:
                f.write('novidade=%s\n' % ('true' if novidade else 'false'))
                f.write('ano=%s\n' % ano)
        return
    if not novidade and not args.forcar:
        print('Nada a fazer.')
        return

    print('Lendo %s' % links[ano].rsplit('/', 1)[-1])
    z, cru = mc.zip_remoto(links[ano])
    por_mun, total, ativas = conta_escolas(z)
    classificadas = conta_porte(z, por_mun)
    print('  baixado %.0f MB em %d pedidos' % (cru.baixado / 1e6, cru.pedidos))
    soma = confere(por_mun, classificadas)

    caminho_csv = os.path.join(AUTO, 'auto_escolas.csv')
    with open(caminho_csv, 'w', encoding='utf-8', newline='') as f:
        f.write('codigo;' + ';'.join(ORDEM) + '\n')
        for cod in sorted(por_mun):
            c = por_mun[cod]
            # Zero explícito, não vazio: um município pode legitimamente não ter
            # escola federal nenhuma, e deixar em branco faria o painel exibir
            # "sem dado" onde o dado existe e é zero.
            f.write(cod + ';' + ';'.join(str(c.get(i, 0)) for i in ORDEM) + '\n')

    fonte = 'INEP — Censo Escolar %d' % ano
    meta = {ind: {'nome': NOMES[ind], 'ano': str(ano), 'fonte': fonte}
            for ind in ORDEM}
    with open(os.path.join(AUTO, 'auto_escolas.meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    estado = {
        'ano': ano,
        'origem': mc.PAGINA,
        'definicoes': {
            'universo': 'TP_SITUACAO_FUNCIONAMENTO = 1 (em atividade)',
            'porte': 'QT_MAT_BAS: até 50 / 51 a 500 / acima de 500',
            'atend_especializado': 'TP_AEE em (1, 2) — oferece AEE',
        },
        'verificadoEm': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
        'totais': {'municipios': len(por_mun), 'linhasNoCenso': total,
                   'emAtividade': ativas,
                   'classificadasPorPorte': classificadas,
                   **{i: soma[i] for i in ORDEM}},
    }
    with open(caminho_estado, 'w', encoding='utf-8') as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)
    print('Gravado em fonte/auto/auto_escolas.csv (%d municípios)' % len(por_mun))


if __name__ == '__main__':
    main()
