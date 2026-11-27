#!/usr/bin/env python3
"""
População de 0 a 3, 4 a 5 e 0 a 5 anos, pelo Censo 2022, para os 5.570
municípios, as UFs e o Brasil.

    python scripts/censo_idade.py

Por que estas faixas
--------------------
São as idades da Educação Infantil: 0 a 3 anos é a creche, 4 e 5 anos é a
pré-escola. As bonecas de Educação Infantil pedem as três (campos pop_0a3,
pop_4a5 e pop_0a5) para comparar a população em idade escolar com as
matrículas do Censo Escolar — e até aqui ficavam em branco.

Fonte: SIDRA, tabela 9514 (população residente por sexo, idade e forma de
declaração da idade), com sexo e forma de declaração no Total, somando as
idades simples. É o número que o IBGE publica, não uma estimativa.

Como o Censo 2022, não muda até o próximo; por isso não há vigia semanal.

Saída: fonte/auto/auto_censo_idade.csv + auto_censo_idade.meta.json
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rede                                    # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTO = os.path.join(RAIZ, 'fonte', 'auto')

# Categorias de idade da classificação 287 da tabela 9514.
IDADES = {0: 6557, 1: 6558, 2: 6559, 3: 6560, 4: 6561, 5: 6562}
FAIXAS = {
    'pop_0a3': ('População de 0 a 3 anos', (0, 1, 2, 3)),
    'pop_4a5': ('População de 4 e 5 anos', (4, 5)),
    'pop_0a5': ('População de 0 a 5 anos', (0, 1, 2, 3, 4, 5)),
}
NIVEIS = (('n6', 7), ('n3', 2), ('n1', 1))


def consulta(nivel, tam):
    """{código: {idade: pessoas}} para o nível pedido."""
    cats = ','.join(str(c) for c in IDADES.values())
    url = ('https://apisidra.ibge.gov.br/values/t/9514/%s/all/v/93/p/2022/'
           'c2/6794/c287/%s/c286/113635?formato=json' % (nivel, cats))
    bruto = json.loads(rede.le(url, espera=300).decode('utf-8'))
    por_cat = {v: k for k, v in IDADES.items()}
    out = {}
    for l in bruto[1:]:
        cod = str(l.get('D1C', ''))
        if len(cod) != tam:
            continue
        cod = 'BR' if nivel == 'n1' else cod
        idade = None
        for chave in ('D4C', 'D5C', 'D6C'):
            if l.get(chave) and int(l[chave]) in por_cat:
                idade = por_cat[int(l[chave])]
        if idade is None:
            continue
        v = str(l.get('V', '')).strip()
        if v in ('...', '..', 'X', ''):
            continue
        # '-' no SIDRA é zero absoluto, não ausência.
        out.setdefault(cod, {})[idade] = 0 if v == '-' else int(v)
    return out


def main():
    os.makedirs(AUTO, exist_ok=True)
    por_cod = {}
    for nivel, tam in NIVEIS:
        por_cod.update(consulta(nivel, tam))
    linhas = {}
    for cod, idades in por_cod.items():
        if len(idades) != len(IDADES):
            continue          # sem todas as idades, a soma sairia menor que a real
        linhas[cod] = {k: sum(idades[a] for a in anos) for k, (_, anos) in FAIXAS.items()}
    muns = [c for c in linhas if len(c) == 7]
    if len(muns) < 5560:
        raise SystemExit('Só %d municípios com as seis idades.' % len(muns))
    soma = sum(linhas[c]['pop_0a5'] for c in muns)
    print('  %d municípios · Brasil 0–5 anos: %d (soma dos municípios: %d)'
          % (len(muns), linhas['BR']['pop_0a5'], soma))

    ordem = sorted(linhas, key=lambda c: (c == 'BR', len(c) != 7, c))
    with open(os.path.join(AUTO, 'auto_censo_idade.csv'), 'w', encoding='utf-8', newline='') as f:
        f.write('codigo;%s\n' % ';'.join(FAIXAS))
        for cod in ordem:
            f.write('%s;%s\n' % (cod, ';'.join(str(linhas[cod][k]) for k in FAIXAS)))
    meta = {k: {'nome': nome, 'tema': 'demografia', 'unidade': 'pessoas',
                'formato': 'int', 'somavel': '1', 'ano': '2022',
                'fonte': 'IBGE — Censo Demográfico 2022 (SIDRA, tabela 9514)'}
            for k, (nome, _) in FAIXAS.items()}
    with open(os.path.join(AUTO, 'auto_censo_idade.meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print('Gravado em fonte/auto/auto_censo_idade.csv (%d linhas)' % len(ordem))


if __name__ == '__main__':
    main()
