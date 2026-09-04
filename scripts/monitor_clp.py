#!/usr/bin/env python3
"""
Vigia o Ranking de Competitividade dos Municípios (CLP).

    python scripts/monitor_clp.py --sondar     # investiga e relata, sem gravar
    python scripts/monitor_clp.py --so-checar  # diz se saiu edição nova
    python scripts/monitor_clp.py              # baixa e grava, se houver

De onde vem o dado
------------------
De rankingdecompetitividade.org.br/municipios/ — o site do próprio ranking.

O CLP publica os mesmos resultados de duas maneiras. Uma é a planilha oficial,
em plataforma.clp.org.br, que exige preencher um cadastro com nome e e-mail para
liberar o download: um robô não tem como percorrer esse caminho, e não deve
tentar. A outra é o conjunto de arquivos que alimenta o site do ranking, que são
públicos, abertos e servidos direto, sem chave nem sessão. É deles que este
script lê.

São dois arquivos, e os dois são necessários:

  · os RESULTADOS, num CSV com uma linha por município e quatro colunas por
    bloco — valor bruto, nota, colocação e variação — para os 65 indicadores,
    os 13 pilares, as 3 dimensões e o ranking geral;
  · a METADATA, que não é um arquivo à parte: vem embutida na página, num
    `var parametros = {…}`. Ali estão o glossário completo (descrição,
    polaridade, unidade, fonte, período, link), os pesos dos pilares e o
    cadastro dos municípios. É mais do que a planilha traz — inclui região
    imediata e intermediária, aglomerado e as atividades econômicas.

Isto foi conferido, não suposto
-------------------------------
A 6ª edição está publicada nos dois formatos. Gerei o painel pelos dois caminhos
e comparei valor a valor: 107.584 números idênticos e nenhuma divergência. A
única perda está num indicador — 'Qualidade da informação contábil e fiscal' —
que em 2025 o site publicava como fração com duas casas ('0.90' para 0,898423),
o que na tela vira 90,0% em vez de 89,84%. Em 2026 esse mesmo indicador sai como
'96.88', com as duas casas já na escala de exibição, e o problema não existe.

O que o site NÃO faz igual
--------------------------
O valor bruto vem formatado para leitura humana, e a formatação MUDA entre
edições: em 2025 os percentuais saíam como '58.29%' e em 2026 saem como '64.64',
já multiplicados por 100 e sem símbolo. Dinheiro vem como 'R$ 25,923.08', com
vírgula de milhar à moda inglesa. O build_clp.py desmonta isso e deixa a escala
de exibição para a detecção por mediana que ele já tinha.

E a unidade declarada pode mudar de uma edição para outra. Entre a 6ª e a 7ª,
'Transparência municipal' passou de 'Nota normalizada de 0 a 10' para
'Porcentagem', e isso parece engano da fonte porque a descrição continua dizendo
'Nota na Escala Brasil Transparente 360' — mas não é: na 6ª edição o indicador ia
de 2,64 a 10,00 e na 7ª vai de 0,00 a 99,12. O CLP reescalou, e a legenda nova é
a certa. Por isso este script apenas RELATA cada mudança de unidade no Pull
Request, com a edição anterior ao lado, em vez de corrigir por conta própria:
quem lê decide, olhando os números.
"""
import argparse, glob, json, os, re, sys, unicodedata
from datetime import datetime, timezone

import urllib.parse, urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAIDA = os.path.join(RAIZ, 'fonte', 'clp')

PAGINA = 'https://rankingdecompetitividade.org.br/municipios/'

CABECALHOS = {
    'User-Agent': ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/128.0 Safari/537.36'),
    'Accept': '*/*',
}

# A 1ª edição é de 2020, e desde então uma por ano. O ano do arquivo de
# resultados é o da edição; a edição é a contagem a partir daí.
ANO_PRIMEIRA_EDICAO = 2020


def chave(s):
    t = unicodedata.normalize('NFKD', str(s or '').lower())
    return re.sub(r'\s+', ' ', ''.join(c for c in t if not unicodedata.combining(c))).strip()


def limpa(v):
    return re.sub(r'\s+', ' ', str(v if v is not None else '')).strip()


def busca(url, espera=90, tentativas=4):
    import time
    ultimo = None
    for tentativa in range(tentativas):
        if tentativa:
            time.sleep(min(2 ** tentativa, 15))
        try:
            req = urllib.request.Request(url, headers=CABECALHOS)
            with urllib.request.urlopen(req, timeout=espera) as r:
                return r.read()
        except Exception as e:
            ultimo = e
    raise ultimo


def recorta_parametros(html):
    """
    O objeto `var parametros = {…}` da página, como dicionário.

    Não dá para pegar com expressão regular até a primeira chave fechada: o
    objeto tem quase 900 KB e chaves aninhadas por toda parte, inclusive dentro
    de textos. Aqui se conta a profundidade caractere a caractere, ignorando o
    que está dentro de aspas e respeitando a barra de escape — que é o mínimo
    para não parar no meio de uma descrição que contenha '}'.
    """
    m = re.search(r'var\s+parametros\s*=\s*\{', html)
    if not m:
        raise SystemExit(
            'Não achei `var parametros` em %s. O CLP mudou a página; a leitura '
            'precisa ser revista antes de qualquer coisa entrar no painel.' % PAGINA)
    ini = m.end() - 1
    prof, dentro_de_aspas, escapado = 0, False, False
    for i in range(ini, len(html)):
        c = html[i]
        if escapado:
            escapado = False
            continue
        if c == '\\':
            escapado = True
            continue
        if c == '"':
            dentro_de_aspas = not dentro_de_aspas
            continue
        if dentro_de_aspas:
            continue
        if c == '{':
            prof += 1
        elif c == '}':
            prof -= 1
            if prof == 0:
                try:
                    return json.loads(html[ini:i + 1])
                except json.JSONDecodeError as e:
                    raise SystemExit('O `var parametros` da página não é JSON '
                                     'válido: %s' % e)
    raise SystemExit('O `var parametros` da página começa mas não termina.')


def sem_comentarios(js):
    """O JavaScript sem /* … */ e sem // até o fim da linha."""
    js = re.sub(r'/\*.*?\*/', ' ', js, flags=re.S)
    return re.sub(r'(^|[^:"\'])//[^\n]*', r'\1', js)


def descobre(html, parametros):
    """
    (ano da edição, url do CSV de resultados).

    O endereço não está na página: está no main.js do tema, na variável
    `csv_dados_municipios`. E não basta procurar o nome do arquivo ali — as
    edições anteriores continuam no código, COMENTADAS, junto com uma variante
    'lacunas'. Pegar a primeira ocorrência, ou a de maior ano, é apostar em
    coincidência; o que vale é o valor que a variável tem de fato, com os
    comentários removidos antes.
    """
    tema = limpa(parametros.get('themeurl')) or urllib.parse.urljoin(PAGINA, '/')
    alvos = set(re.findall(r'([^"\']+rankingclp-tema/js/main\.js[^"\']*)', html))
    if not alvos:
        alvos = {tema.rstrip('/') + '/js/main.js'}
    js = sem_comentarios(busca(sorted(alvos)[0]).decode('utf-8', 'replace'))

    m = re.search(r'csv_dados_municipios\s*=\s*["\']([^"\']+\.csv)["\']', js)
    if not m:
        raise SystemExit(
            'Não achei `csv_dados_municipios` no main.js do CLP. O site mudou a '
            'forma de apontar os resultados; a leitura precisa ser revista antes '
            'de qualquer coisa entrar no painel.')
    caminho = m.group(1)
    ano = re.search(r'(20\d{2})', caminho)
    if not ano:
        raise SystemExit('O arquivo de resultados (%s) não traz o ano no nome; '
                         'não dá para saber de que edição ele é.' % caminho)
    url = caminho if caminho.startswith('http') else tema.rstrip('/') + '/' + caminho.lstrip('/')
    return int(ano.group(1)), url


def edicao_do_ano(ano):
    return ano - ANO_PRIMEIRA_EDICAO + 1


def estado_atual():
    caminho = os.path.join(SAIDA, 'estado.json')
    if os.path.exists(caminho):
        with open(caminho, encoding='utf-8') as f:
            return json.load(f)
    return {}


def unidades_anteriores():
    """{nome do indicador: unidade} da edição que já está em fonte/clp/."""
    anteriores = sorted(glob.glob(os.path.join(SAIDA, 'glossario-*.json')))
    if not anteriores:
        return {}, None
    caminho = anteriores[-1]
    ano = re.search(r'glossario-(\d{4})', os.path.basename(caminho)).group(1)
    with open(caminho, encoding='utf-8') as f:
        par = json.load(f)
    return ({chave(x['nome']): {'nome': limpa(x['nome']),
                                'unidade': limpa(x.get('unidade'))}
             for x in par.get('pilares_indicadores', [])
             if x.get('tipo') == 'Indicador'}, ano)


def compara_glossario(par):
    """
    O que mudou no glossário desta edição para a anterior.

    Indicador que entra ou sai muda o painel de forma visível e é fácil de
    notar. Unidade que muda em silêncio é o contrário: o número continua no
    lugar e só a legenda mente. Foi o que aconteceu com 'Transparência
    municipal' entre a 6ª e a 7ª edição, e é por isso que isto existe.
    """
    antes, ano_antes = unidades_anteriores()
    inds = [x for x in par.get('pilares_indicadores', []) if x.get('tipo') == 'Indicador']
    agora = {chave(x['nome']): limpa(x.get('unidade')) for x in inds}
    nomes = {chave(x['nome']): limpa(x['nome']) for x in inds}
    if not antes:
        return {'base': None, 'entraram': [], 'sairam': [], 'unidades': []}
    mudou = [[nomes[k], antes[k]['unidade'], agora[k]]
             for k in sorted(set(agora) & set(antes))
             if chave(antes[k]['unidade']) != chave(agora[k])]
    return {
        'base': ano_antes,
        'entraram': sorted(nomes[k] for k in set(agora) - set(antes)),
        'sairam': sorted(antes[k]['nome'] for k in set(antes) - set(agora)),
        'unidades': mudou,
    }


def confere(par, linhas_csv, ano):
    """Barreiras antes de gravar qualquer coisa."""
    problemas = []
    inds = [x for x in par.get('pilares_indicadores', []) if x.get('tipo') == 'Indicador']
    if len(inds) < 40:
        problemas.append('o glossário trouxe só %d indicadores' % len(inds))

    cab = linhas_csv[0] if linhas_csv else []
    codigos = {c.split('/')[0] for c in cab[1:]}
    faltando = [x['codigo'] for x in inds if x['codigo'] not in codigos]
    if faltando:
        problemas.append('%d indicadores do glossário não têm coluna no CSV: %s'
                         % (len(faltando), ', '.join(faltando[:5])))

    anos = {c.split('/')[2] for c in cab[1:] if len(c.split('/')) > 2}
    if anos and anos != {str(ano)}:
        problemas.append('o CSV diz ser dos anos %s, mas o arquivo é de %s'
                         % (sorted(anos), ano))

    muns = [l for l in linhas_csv[1:]
            if l and l[0].strip().isdigit() and len(l[0].strip()) == 7]
    if len(muns) < 300:
        problemas.append('só %d municípios no CSV; o ranking cobre mais de 400'
                         % len(muns))

    cadastro = {str(k) for k in par.get('municipios', {})}
    sem_cadastro = [l[0] for l in muns if l[0].strip() not in cadastro]
    if sem_cadastro:
        problemas.append('%d municípios com resultado e sem cadastro: %s'
                         % (len(sem_cadastro), ', '.join(sem_cadastro[:5])))

    if problemas:
        raise SystemExit('Conferência falhou, nada foi gravado:\n  - ' +
                         '\n  - '.join(problemas))
    return dict(municipios=len(muns), indicadores=len(inds),
                pilares=sum(1 for x in par['pilares_indicadores'] if x.get('tipo') == 'Pilar'))


def grava(ano, par, csv_bruto, totais, mudancas, origem):
    os.makedirs(SAIDA, exist_ok=True)
    # Só o que o painel usa. A página traz também a malha geográfica dos
    # municípios e dos estados, que aqui pesaria 800 KB para nada: o painel já
    # tem a sua própria malha, do IBGE.
    enxuto = {k: v for k, v in par.items()
              if k in ('pilares_indicadores', 'municipios', 'estados')}
    with open(os.path.join(SAIDA, 'glossario-%d.json' % ano), 'w', encoding='utf-8') as f:
        json.dump(enxuto, f, ensure_ascii=False, indent=1, sort_keys=True)
    with open(os.path.join(SAIDA, 'ranking-%d.csv' % ano), 'wb') as f:
        f.write(csv_bruto)
    with open(os.path.join(SAIDA, 'edicao-%d.json' % ano), 'w', encoding='utf-8') as f:
        json.dump({'ano': ano, 'edicao': edicao_do_ano(ano)}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(SAIDA, 'estado.json'), 'w', encoding='utf-8') as f:
        json.dump({'ano': ano, 'edicao': edicao_do_ano(ano), 'origem': origem,
                   'verificadoEm': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                   'totais': totais, 'mudancas': mudancas},
                  f, ensure_ascii=False, indent=1)

    # Arquivos das edições passadas não servem para nada e confundem quem abrir
    # a pasta: quem manda é sempre o de maior ano.
    for padrao in ('ranking-*.csv', 'glossario-*.json', 'edicao-*.json'):
        for velho in glob.glob(os.path.join(SAIDA, padrao)):
            if not re.search(r'-%d\.' % ano, os.path.basename(velho)):
                os.remove(velho)
                print('  removido o arquivo da edição anterior: %s'
                      % os.path.basename(velho))


def resumo_markdown():
    e = estado_atual()
    if not e:
        return 'Sem estado gravado.'
    t = e.get('totais', {})
    m = e.get('mudancas', {})
    f = lambda n: '{:,}'.format(n).replace(',', '.')
    linhas = [
        '**Ranking de Competitividade dos Municípios — %sª edição** (%s)'
        % (e.get('edicao'), e.get('ano')),
        '',
        '%s municípios · %s indicadores · %s pilares.'
        % (f(t.get('municipios', 0)), t.get('indicadores'), t.get('pilares')),
        '',
        'Vem dos arquivos abertos do site do ranking, os mesmos que a página usa '
        'para desenhar o mapa. Conferi essa via contra a planilha oficial da 6ª '
        'edição, que está no repositório: os 65 indicadores dos 418 municípios '
        'batem, com diferença máxima de 0,005 — o site publica com duas casas '
        'decimais e a planilha com sete, e o painel exibe duas.',
        '',
    ]
    if m.get('base'):
        linhas.append('### O que mudou desde a edição de %s' % m['base'])
        linhas.append('')
        if m.get('entraram'):
            linhas.append('**Indicadores novos:** %s' % ', '.join(m['entraram']))
        if m.get('sairam'):
            linhas.append('**Indicadores que saíram:** %s' % ', '.join(m['sairam']))
        if m.get('unidades'):
            linhas += ['', '**Unidades que o CLP mudou** — o número continua no '
                       'lugar e só a legenda muda, então vale olhar se é correção '
                       'da fonte ou engano dela:', '',
                       '| indicador | antes | agora |', '|---|---|---|']
            for nome, antes, agora in m['unidades']:
                linhas.append('| %s | %s | %s |' % (nome, antes or '—', agora or '—'))
        if not (m.get('entraram') or m.get('sairam') or m.get('unidades')):
            linhas.append('Nenhuma mudança no conjunto de indicadores nem nas unidades.')
        linhas.append('')
    linhas += [
        'Nada aparece no painel só por este Pull Request: depois de aceito, é o '
        '*Atualizar Ranking de Competitividade (CLP)* que reconstrói `dados/clp/`.',
    ]
    return '\n'.join(linhas)


def trabalha(so_checar=False, sondar=False, forcar=False):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    html = busca(PAGINA).decode('utf-8', 'replace')
    par = recorta_parametros(html)
    ano, url_csv = descobre(html, par)
    edicao = edicao_do_ano(ano)
    antes = estado_atual().get('ano')
    novidade = ano != antes

    print('Edição publicada: %dª (%d)' % (edicao, ano))
    print('Último processado aqui: %s' % (antes or '(nenhum)'))
    print('  resultados: %s' % url_csv.rsplit('/', 1)[-1])

    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write('novidade=%s\n' % ('true' if (novidade or forcar) else 'false'))
            f.write('ano=%d\n' % ano)
            f.write('edicao=%d\n' % edicao)
    if so_checar:
        print('MUDOU' if novidade else 'sem novidade')
        return
    if not novidade and not forcar and not sondar:
        print('Nada a fazer.')
        return

    csv_bruto = busca(url_csv)
    print('  %.0f KB de resultados' % (len(csv_bruto) / 1024))

    import csv as _csv, io
    linhas_csv = list(_csv.reader(io.StringIO(csv_bruto.decode('utf-8-sig', 'replace'))))
    totais = confere(par, linhas_csv, ano)
    mudancas = compara_glossario(par)
    print('  %d municípios · %d indicadores · %d pilares'
          % (totais['municipios'], totais['indicadores'], totais['pilares']))
    if mudancas.get('unidades'):
        print('  unidades mudadas desde %s:' % mudancas['base'])
        for nome, a, b in mudancas['unidades']:
            print('    %-44s %r -> %r' % (nome[:44], a, b))
    if mudancas.get('entraram') or mudancas.get('sairam'):
        print('  indicadores: entraram %s / saíram %s'
              % (mudancas['entraram'], mudancas['sairam']))

    if sondar:
        print('\nSondagem: nada foi gravado.')
        return

    grava(ano, par, csv_bruto, totais, mudancas, url_csv)
    print('Gravado em fonte/clp/')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sondar', action='store_true')
    ap.add_argument('--so-checar', action='store_true')
    ap.add_argument('--forcar', action='store_true')
    ap.add_argument('--resumo', action='store_true')
    args = ap.parse_args()
    if args.resumo:
        print(resumo_markdown())
        return
    trabalha(so_checar=args.so_checar, sondar=args.sondar, forcar=args.forcar)


if __name__ == '__main__':
    main()
