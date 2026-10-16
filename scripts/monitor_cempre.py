#!/usr/bin/env python3
"""
Vigia do CEMPRE (Cadastro Central de Empresas, IBGE).

O CEMPRE sai uma vez por ano e é de onde vem o salário médio mensal do painel.
A consulta é feita pela API do SIDRA, que devolve o dado já por município — não
há planilha para baixar nem arquivo para descompactar.

Um detalhe que custou caro quando o painel foi montado: a tabela antiga (1685)
foi encerrada em 2021 e a série nova mora na 9509, que começa em 2022. Quem
procurar o ano mais recente na 1685 encontra 2021 e conclui, errado, que o IBGE
parou de publicar. Por isso as duas ficam na lista abaixo: o script pergunta o
último ano de cada uma e usa a que estiver mais à frente. Quando o IBGE abrir a
próxima tabela, basta acrescentar o número aqui.

    python scripts/monitor_cempre.py --so-checar    # só diz se mudou
    python scripts/monitor_cempre.py                # consulta e grava fonte/auto/
    python scripts/monitor_cempre.py --forcar       # reprocessa mesmo sem ano novo

Saída: fonte/auto/auto_cempre.csv + auto_cempre.meta.json + auto_cempre.estado.json
"""
import argparse, gzip, io, json, os, zlib
from datetime import datetime, timezone
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTO = os.path.join(RAIZ, 'fonte', 'auto')
PAGINA = ('https://www.ibge.gov.br/estatisticas/economicas/comercio/'
          '9016-estatisticas-do-cadastro-central-de-empresas.html')

# Tabelas do SIDRA que já serviram ou servem à série municipal, da mais nova
# para a mais velha. A escolha é pelo ano, não pela ordem.
TABELAS = (9509, 1685)
VARIAVEL = 1606          # Salário médio mensal, em salários mínimos
IND = 'salario_medio'
NOME = 'Salário médio mensal'

AUSENTES = ('...', '..', '-', 'X', '')


def busca(url, espera=300):
    """
    JSON de uma URL, aguentando resposta comprimida.

    O IBGE às vezes devolve gzip mesmo sem Accept-Encoding pedindo — e um
    proxy no caminho pode fazer o mesmo. O urllib não descomprime sozinho, e
    o resultado seria um `json.loads` reclamando do primeiro caractere, que
    parece erro de API e não é.
    """
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=espera) as r:
        dados = r.read()
        codificacao = (r.headers.get('Content-Encoding') or '').lower()
    if 'gzip' in codificacao or dados[:2] == b'\x1f\x8b':
        dados = gzip.GzipFile(fileobj=io.BytesIO(dados)).read()
    elif 'deflate' in codificacao:
        dados = zlib.decompress(dados, -zlib.MAX_WBITS)
    return json.loads(dados.decode('utf-8', 'ignore'))


def ultimo_ano(tabela):
    """Ano final da tabela, segundo os metadados do próprio IBGE."""
    meta = busca('https://servicodados.ibge.gov.br/api/v3/agregados/'
                 '%d/metadados' % tabela, espera=120)
    fim = meta.get('periodicidade', {}).get('fim')
    return int(fim) if fim else None


def melhor_tabela():
    """Tabela com o ano mais recente, e esse ano."""
    achados = []
    for t in TABELAS:
        try:
            ano = ultimo_ano(t)
        except Exception as erro:
            print('  aviso: não consegui ler os metadados da tabela %d (%s)'
                  % (t, erro))
            continue
        if ano:
            print('  tabela %d vai até %d' % (t, ano))
            achados.append((ano, t))
    if not achados:
        raise SystemExit('Nenhuma tabela do CEMPRE respondeu. Confira ' + PAGINA)
    ano, tabela = max(achados)
    return tabela, ano


def valores(tabela, ano, nivel='n6'):
    """
    Salário médio por código territorial, para o ano pedido.

    `nivel` segue a notação do SIDRA: n6 município, n3 UF, n1 Brasil. Os três
    são gravados porque o `build.py` prefere um total vindo de linha de UF ou
    de país à média que ele mesmo calcularia dos municípios — e aqui a
    diferença é real, não arredondamento: o salário médio do país não é a média
    dos 5.570 salários médios municipais, é a razão entre a massa salarial e o
    pessoal assalariado do país inteiro. Deixar o painel calcular daria um
    número que o IBGE não publica.
    """
    url = ('https://apisidra.ibge.gov.br/values/t/%d/%s/all/v/%d/p/%d'
           '?formato=json' % (tabela, nivel, VARIAVEL, ano))
    bruto = busca(url)
    if len(bruto) < 2:
        raise SystemExit('A tabela %d não devolveu linhas de %s para %d.'
                         % (tabela, nivel, ano))

    unidade = bruto[1].get('MN', '')
    if 'alário' not in unidade and 'alario' not in unidade:
        # Trocar salários mínimos por reais mudaria a escala por mil e passaria
        # despercebido no painel, onde o número é só "4,1". Melhor parar aqui.
        raise SystemExit("A variável %d voltou em '%s', não em salários mínimos. "
                         "Confira %s." % (VARIAVEL, unidade, PAGINA))

    # Tamanho do código esperado em cada nível. O Brasil vem como "1" no SIDRA
    # e é gravado como "BR", que é o que o build.py entende.
    tamanho = {'n6': 7, 'n3': 2, 'n1': 1}[nivel]
    saida = {}
    for linha in bruto[1:]:
        cod = str(linha.get('D1C', '')).strip()
        if len(cod) != tamanho:
            continue
        if nivel == 'n1':
            cod = 'BR'
        v = str(linha.get('V', '')).strip()
        if v in AUSENTES:
            continue
        try:
            saida[cod] = round(float(v), 2)
        except ValueError:
            continue
    return saida


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--so-checar', action='store_true')
    ap.add_argument('--forcar', action='store_true')
    args = ap.parse_args()

    os.makedirs(AUTO, exist_ok=True)
    caminho_estado = os.path.join(AUTO, 'auto_cempre.estado.json')
    estado = {}
    if os.path.exists(caminho_estado):
        estado = json.loads(open(caminho_estado, encoding='utf-8').read())

    tabela, ano = melhor_tabela()
    anterior = estado.get('ano')
    print('Ano mais recente no CEMPRE: %s (tabela %d)' % (ano, tabela))
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

    dados = valores(tabela, ano)
    if len(dados) < 5000:
        raise SystemExit('Só %d municípios voltaram com salário médio em %d. '
                         'Esperado perto de 5.570 — a consulta veio incompleta.'
                         % (len(dados), ano))
    ufs = valores(tabela, ano, 'n3')
    pais = valores(tabela, ano, 'n1')
    if len(ufs) != 27 or len(pais) != 1:
        raise SystemExit('Vieram %d UFs e %d linha(s) de Brasil; esperado 27 e 1. '
                         'Confira %s.' % (len(ufs), len(pais), PAGINA))

    media = sum(dados.values()) / len(dados)
    print('  %d municípios · média das médias: %.2f sal. mín.' % (len(dados), media))
    print('  27 UFs · Brasil: %.2f sal. mín.' % pais['BR'])
    if not 1.0 < media < 6.0:
        print('  AVISO: a média saiu fora da faixa histórica (1 a 6 salários '
              'mínimos). Confira a unidade antes de publicar.')

    caminho_csv = os.path.join(AUTO, 'auto_cempre.csv')
    with open(caminho_csv, 'w', encoding='utf-8', newline='') as f:
        f.write('codigo;%s\n' % IND)
        for cod in sorted(dados):
            f.write('%s;%s\n' % (cod, repr(dados[cod])))
        # UF e Brasil fecham o arquivo, como no vigia das escolas.
        for cod in sorted(ufs):
            f.write('%s;%s\n' % (cod, repr(ufs[cod])))
        f.write('BR;%s\n' % repr(pais['BR']))

    meta = {IND: {'nome': NOME, 'ano': str(ano),
                  'fonte': 'IBGE — Cadastro Central de Empresas %d' % ano}}
    with open(os.path.join(AUTO, 'auto_cempre.meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    estado = {'ano': ano, 'tabela': tabela, 'variavel': VARIAVEL,
              'origem': PAGINA,
              'verificadoEm': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
              'totais': {'municipios': len(dados), 'media': round(media, 4)}}
    with open(caminho_estado, 'w', encoding='utf-8') as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)
    print('Gravado em fonte/auto/auto_cempre.csv (%d municípios)' % len(dados))


if __name__ == '__main__':
    main()
