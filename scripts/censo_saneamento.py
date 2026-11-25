#!/usr/bin/env python3
"""
Saneamento pelo Censo 2022: água, esgoto e lixo declarados pelos moradores,
para os 5.570 municípios.

    python scripts/censo_saneamento.py

Por que, se o painel já tem o SINISA
------------------------------------
São duas perguntas diferentes, e as duas servem a um diagnóstico.

O SINISA é o que o PRESTADOR declara ao Ministério das Cidades: população
atendida pela rede que ele opera. Cobre bem a água, mas o módulo de esgoto
traz menos da metade dos municípios — onde não há prestador de esgoto
declarando, fica vazio. E o número depende de quem preenche.

O Censo é o que o MORADOR responde ao recenseador, domicílio por domicílio, em
todos os municípios. Não depende de prestador existir nem de ele declarar.
Por isso é o que fecha a lacuna do esgoto, e serve de conferência para a
água: quando os dois divergem muito, vale perguntar por quê.

O preço é a data. É 2022, e não muda até o próximo Censo — por isso não há
vigia semanal: o script roda uma vez e o resultado fica em fonte/auto/.

O que é medido
--------------
Percentual de MORADORES (não de domicílios), para ficar na mesma unidade do
SINISA, que fala em população atendida:

  censo_agua_rede    ligação à rede geral de água usada como forma principal
                     (tabela 6894). Quem tem ligação mas bebe de poço fica
                     fora — é a mesma linha que o IBGE usa na divulgação.
  censo_esgoto_rede  rede geral, rede pluvial ou fossa ligada à rede (7555).
  censo_esgoto_fossa fossa séptica ou fossa filtro NÃO ligada à rede (7555).
                     Fica separado porque o Plansab a considera solução
                     adequada onde não há rede; somá-la à rede apagaria a
                     diferença entre ter rede e não ter.
  censo_lixo_coleta  lixo coletado, no domicílio ou em caçamba (9541).

Idade e cor ou raça entram no Total. O valor é o percentual que o próprio
IBGE publica (variável 1000382), não uma conta feita aqui.

Saída: fonte/auto/auto_censo_san.csv + auto_censo_san.meta.json
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rede                                    # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTO = os.path.join(RAIZ, 'fonte', 'auto')
TOTAIS = 'c58/95253/c86/95251'                  # idade Total, cor ou raça Total

INDICADORES = {
    # id: (tabela, classificação, categoria, nome)
    'censo_agua_rede': (6894, 1821, 72144,
                        'Moradores com água da rede geral (Censo)'),
    'censo_esgoto_rede': (7555, 11558, 46290,
                          'Moradores com esgoto ligado à rede (Censo)'),
    'censo_esgoto_fossa': (7555, 11558, 72112,
                           'Moradores com fossa séptica sem rede (Censo)'),
    'censo_lixo_coleta': (9541, 67, 2520,
                          'Moradores com lixo coletado (Censo)'),
}
NIVEIS = (('n6', 7), ('n3', 2), ('n1', 1))
# No SIDRA, '-' é ZERO ABSOLUTO ("dado numérico igual a zero não resultante
# de arredondamento"), não ausência. Município sem rede de esgoto vem com '-',
# e tratá-lo como vazio esconderia justamente os que mais importam num
# diagnóstico. Ausência de verdade é '...', '..' ou 'X'.
AUSENTES = ('...', '..', 'X', '')


def consulta(tabela, classif, cat, nivel, tam):
    url = ('https://apisidra.ibge.gov.br/values/t/%d/%s/all/v/1000382/p/2022/'
           'c%d/%d/%s?formato=json' % (tabela, nivel, classif, cat, TOTAIS))
    bruto = json.loads(rede.le(url, espera=300).decode('utf-8'))
    if len(bruto) < 2:
        raise SystemExit('A tabela %d não devolveu linhas em %s.' % (tabela, nivel))
    if 'percent' not in bruto[1].get('MN', '').lower() and '%' not in bruto[1].get('MN', ''):
        raise SystemExit('A tabela %d voltou em "%s", não em percentual.'
                         % (tabela, bruto[1].get('MN')))
    out = {}
    for l in bruto[1:]:
        cod = str(l.get('D1C', ''))
        if len(cod) != tam:
            continue
        v = str(l.get('V', '')).strip()
        if v in AUSENTES:
            continue
        out['BR' if nivel == 'n1' else cod] = 0.0 if v == '-' else round(float(v), 2)
    return out


def main():
    os.makedirs(AUTO, exist_ok=True)
    valores = {}
    for ind, (tab, cl, cat, _) in INDICADORES.items():
        valores[ind] = {}
        for nivel, tam in NIVEIS:
            valores[ind].update(consulta(tab, cl, cat, nivel, tam))
        mun = [v for k, v in valores[ind].items() if len(k) == 7]
        print('  %-20s %d municípios · Brasil %.2f%%'
              % (ind, len(mun), valores[ind]['BR']))
        if len(mun) < 5500:
            raise SystemExit('%s: só %d municípios.' % (ind, len(mun)))

    codigos = sorted({c for v in valores.values() for c in v},
                     key=lambda c: (c == 'BR', len(c) != 7, c))
    caminho = os.path.join(AUTO, 'auto_censo_san.csv')
    with open(caminho, 'w', encoding='utf-8', newline='') as f:
        f.write('codigo;%s\n' % ';'.join(INDICADORES))
        for cod in codigos:
            f.write('%s;%s\n' % (cod, ';'.join(
                repr(valores[i][cod]) if cod in valores[i] else ''
                for i in INDICADORES)))

    meta = {ind: {'nome': nome, 'tema': 'saneamento', 'unidade': '%',
                  'formato': 'pct', 'somavel': '0', 'ano': '2022',
                  'fonte': 'IBGE — Censo Demográfico 2022 (SIDRA, tabela %d)' % tab}
            for ind, (tab, _, _, nome) in INDICADORES.items()}
    with open(os.path.join(AUTO, 'auto_censo_san.meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print('Gravado em fonte/auto/auto_censo_san.csv (%d linhas)' % len(codigos))


if __name__ == '__main__':
    main()
