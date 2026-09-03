#!/usr/bin/env python3
"""
Vigia as divulgações do SINISA e atualiza os indicadores de saneamento.

    python scripts/monitor_sinisa.py --sondar     # investiga e relata, sem gravar
    python scripts/monitor_sinisa.py --so-checar  # diz se saiu edição nova
    python scripts/monitor_sinisa.py              # baixa e grava, se houver

De onde vem o dado
------------------
Do SINISA — Sistema Nacional de Informações em Saneamento Básico, do Ministério
das Cidades. Ele substituiu o SNIS, que encerrou as atividades em 2023.

A edição é descoberta navegando, nunca por caminho fixo, e há um motivo
concreto: a página `resultados-sinisa` é a edição de 2024 (referência 2023), e
a de 2025 (referência 2024) apareceu como SUBPÁGINA dela,
`resultados-sinisa/resultados-sinisa-2025`. Quem fosse pelo endereço óbvio
pegaria dados um ano mais velhos sem perceber — foi o que aconteceu comigo na
primeira leitura. Então aqui se procura a maior edição publicada.

O que é lido
------------
Por enquanto só o módulo de **Resíduos Sólidos**, que é o que o painel não tem.
Dentro do pacote, a planilha de indicadores é achada pelo conteúdo, não pelo
nome: procura-se a que tem uma coluna de código do IBGE e os indicadores de
cobertura de coleta.

Zero não é o mesmo que ausência
-------------------------------
Este é o cuidado central deste script. Dos 5.570 municípios, cerca de 13% não
respondem ao módulo — e uma linha em branco NÃO significa "não tem coleta
seletiva". Se as duas coisas virassem zero, o mapa acusaria centenas de
municípios de algo que eles nunca declararam. Município que não respondeu sai
como célula vazia, que o painel mostra como "sem dado"; só quem declarou zero
recebe zero.
"""
import argparse, csv, io, json, os, re, ssl, sys, tempfile, unicodedata, zipfile
from datetime import datetime, timezone

import urllib.parse, urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAIDA = os.path.join(RAIZ, 'fonte', 'auto')

PAGINA = ('https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/'
          'saneamento/sinisa')

UAS = [
    {'User-Agent': ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/128.0 Safari/537.36'),
     'Accept': '*/*', 'Accept-Encoding': 'identity',
     'Referer': 'https://www.gov.br/cidades/'},
    {'User-Agent': 'painel-socioambiental/1.0 (+github actions; dados publicos)'},
]

# id no painel -> (trecho do rótulo na planilha do SINISA, definição do indicador)
# O casamento é pelo começo do rótulo porque os nomes são longos e o SINISA já
# mudou pontuação entre edições; o começo é a parte estável.
INDICADORES = [
    ('res_cob_total', 'Cobertura da população total com coleta de resíduos sólidos domiciliares',
     dict(nome='Cobertura de coleta de resíduos', tema='saneamento', unidade='%',
          formato='pct', somavel='0')),
    ('res_cob_rural', 'Cobertura da população rural com coleta de resíduos sólidos domiciliares',
     dict(nome='Coleta de resíduos na zona rural', tema='saneamento', unidade='%',
          formato='pct', somavel='0')),
    ('res_seletiva', 'Cobertura da população total com coleta seletiva de resíduos sólidos',
     dict(nome='Cobertura de coleta seletiva', tema='saneamento', unidade='%',
          formato='pct', somavel='0')),
    ('res_disp_inad', 'Disposição final inadequada de resíduos sólidos urbanos',
     dict(nome='Disposição final inadequada', tema='saneamento', unidade='%',
          formato='pct', somavel='0')),
    ('res_massa_pc', 'Massa média per capita de resíduos sólidos urbanos coletados',
     dict(nome='Resíduos coletados por habitante', tema='saneamento',
          unidade='kg/hab.dia', formato='dec2', somavel='0')),
]

FONTE = 'SINISA — Ministério das Cidades'


def chave(s):
    t = unicodedata.normalize('NFKD', str(s or '').lower())
    return re.sub(r'\s+', ' ', ''.join(c for c in t if not unicodedata.combining(c))).strip()


def busca(url, cabecalhos=None, ua=None, espera=90, tentativas=4):
    """Requisição com repetição e pausa crescente."""
    import time
    ultimo = None
    for tentativa in range(tentativas):
        if tentativa:
            time.sleep(min(2 ** tentativa, 15))
        h = dict(ua or UAS[min(tentativa, len(UAS) - 1)])
        h.update(cabecalhos or {})
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=h), timeout=espera)
        except Exception as e:
            ultimo = e
    raise ultimo


def baixa(url, tentativas=6):
    """
    Baixa o arquivo inteiro, retomando de onde parou quando a conexão cai.

    O servidor do Ministério das Cidades corta a transferência no meio com
    alguma frequência (`IncompleteRead`). Como ele aceita `Range`, dá para pedir
    só o pedaço que falta em vez de recomeçar os 18 MB — e, mais importante, o
    tamanho anunciado é conferido no fim: sem isso, um arquivo cortado viraria
    um zip corrompido, ou pior, um zip que abre e vem incompleto.
    """
    import time
    dados = b''
    total = None
    for tentativa in range(tentativas):
        cab = {'Range': 'bytes=%d-' % len(dados)} if dados else {}
        try:
            with busca(url, cab, espera=300, tentativas=2) as r:
                if total is None:
                    n = r.headers.get('Content-Length')
                    faixa = r.headers.get('Content-Range') or ''
                    m = re.search(r'/(\d+)$', faixa)
                    total = int(m.group(1)) if m else (int(n) if n else None)
                while True:
                    pedaco = r.read(1024 * 1024)
                    if not pedaco:
                        break
                    dados += pedaco
            if total is None or len(dados) >= total:
                break
        except Exception:
            if tentativa == tentativas - 1:
                raise
        time.sleep(min(2 ** tentativa, 20))
    if total is not None and len(dados) != total:
        raise SystemExit('O download veio incompleto: %d de %d bytes. Nada foi '
                         'gravado.' % (len(dados), total))
    return dados


# --------------------------------------------------------- achar a edição nova
def edicoes():
    """
    {ano da edição: url da página de resultados}, descoberto navegando.

    Começa na página do SINISA, junta os links de 'resultados-sinisa' e desce
    um nível para achar as subpáginas por ano. A edição sem ano no endereço é a
    primeira (2024); as seguintes vêm com o ano no fim.
    """
    with busca(PAGINA) as r:
        html = r.read().decode('utf-8', 'replace')
    achadas = {}
    vistas = set()
    candidatas = set(re.findall(r'href="([^"]*resultados-sinisa[^"]*)"', html))

    def registra(url):
        m = re.search(r'resultados-sinisa-(20\d{2})/?$', url)
        achadas[int(m.group(1)) if m else 2024] = url.rstrip('/')

    for u in list(candidatas):
        u = urllib.parse.urljoin(PAGINA + '/', u).split('?')[0]
        if '/resultados-sinisa' not in u or u in vistas:
            continue
        vistas.add(u)
        registra(u)
        # desce um nível: a edição nova é subpágina da anterior
        try:
            with busca(u, espera=60, tentativas=2) as r:
                filho = r.read().decode('utf-8', 'replace')
        except Exception:
            continue
        for v in re.findall(r'href="([^"]*resultados-sinisa-20\d{2}[^"]*)"', filho):
            v = urllib.parse.urljoin(u + '/', v).split('?')[0].rstrip('/')
            if v not in vistas:
                vistas.add(v)
                registra(v)
    if not achadas:
        raise SystemExit('Não achei nenhuma página de resultados em ' + PAGINA +
                         '. O Ministério das Cidades mudou o formato do site.')
    return achadas


def pacote_de_residuos(url_edicao):
    """Endereço do .zip de resíduos daquela edição, lido dos links da página."""
    with busca(url_edicao) as r:
        html = r.read().decode('utf-8', 'replace')
    candidatos = []
    for href in re.findall(r'href="([^"]+\.(?:zip|rar))"', html, re.I):
        nome = chave(href.rsplit('/', 1)[-1])
        if 'residuo' in nome:
            candidatos.append(urllib.parse.urljoin(url_edicao + '/', href))
    if not candidatos:
        raise SystemExit('A página %s não traz pacote de resíduos. Links de '
                         'arquivo vistos: %s'
                         % (url_edicao,
                            re.findall(r'href="([^"]+\.(?:zip|rar|xlsx))"', html)[:8]))
    return candidatos[0]


# ------------------------------------------------------------ ler a planilha
def acha_planilha(z):
    """
    A planilha de indicadores, achada pelo CONTEÚDO.

    Mesmo princípio usado no Censo Escolar e pelo mesmo motivo: nome de arquivo
    é a coisa que os órgãos mais mudam entre edições. O que não muda é a
    planilha ter o código do IBGE e os indicadores de cobertura.
    """
    from openpyxl import load_workbook
    for info in sorted(z.infolist(), key=lambda i: -i.file_size):
        if not info.filename.lower().endswith(('.xlsx', '.xls')):
            continue
        if 'indicador' not in chave(info.filename):
            continue
        try:
            wb = load_workbook(io.BytesIO(z.read(info.filename)),
                               read_only=True, data_only=True)
        except Exception:
            continue
        return info.filename, wb
    raise SystemExit('Nenhuma planilha de indicadores no pacote. Arquivos: %s'
                     % [i.filename for i in z.infolist()][:10])


def le_indicadores(wb):
    """
    Devolve {codigo_ibge: {id_do_indicador: valor}} e um relatório da leitura.

    O cabeçalho do SINISA ocupa umas doze linhas, com título, legenda, grupos e
    só então os rótulos. Em vez de fixar o número da linha — que já mudou entre
    edições — procuro a linha que tem 'Cod' e o código do IBGE, e leio os
    rótulos a partir dali.
    """
    ws = wb[wb.sheetnames[0]]
    linhas = list(ws.iter_rows(values_only=True))

    i_cab = None
    for n, linha in enumerate(linhas[:25]):
        textos = [chave(v) for v in linha]
        if any('cod' in t and 'ibge' in t for t in textos):
            i_cab = n
    if i_cab is None:
        raise SystemExit('Não achei a linha de cabeçalho com o código do IBGE.')

    rotulos = linhas[i_cab - 1] if i_cab else ()
    cods_col = linhas[i_cab]
    i_cod = next(j for j, v in enumerate(cods_col)
                 if 'cod' in chave(v) and 'ibge' in chave(v))
    i_resp = next((j for j, v in enumerate(linhas[i_cab])
                   if chave(v) in ('sim/nao', 'sim/não')), None)

    colunas, faltando = {}, []
    for ident, rotulo, _ in INDICADORES:
        alvo = chave(rotulo)[:55]
        achou = None
        for j, nm in enumerate(rotulos):
            if nm and chave(nm).startswith(alvo):
                achou = j
                break
        if achou is None:
            faltando.append(ident)
        else:
            colunas[ident] = achou
    if faltando:
        raise SystemExit('A planilha do SINISA não traz estes indicadores: %s. '
                         'Os rótulos podem ter mudado — confira antes de mexer '
                         'no script.' % ', '.join(faltando))

    dados, respondentes, sem_resposta = {}, 0, 0
    for linha in linhas[i_cab + 1:]:
        cod = str(linha[i_cod] or '').split('.')[0].strip()
        if not (cod.isdigit() and len(cod) == 7):
            continue
        respondeu = True
        if i_resp is not None:
            respondeu = chave(linha[i_resp]).startswith('sim')
        if not respondeu:
            sem_resposta += 1
            continue                       # NÃO vira zero: fica sem dado
        respondentes += 1
        reg = {}
        for ident, j in colunas.items():
            v = linha[j]
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                reg[ident] = round(float(v), 4)
        if reg:
            dados[cod] = reg
    return dados, dict(respondentes=respondentes, sem_resposta=sem_resposta)


# ------------------------------------------------------------------ conferir
def confere(dados, relatorio):
    """
    Barreiras antes de gravar.

    Sem uma régua externa como a do CAGED, o que dá para exigir é coerência:
    percentual tem de ficar entre 0 e 100, a cobertura rural não pode passar da
    total, e a quantidade de municípios tem de ser compatível com a coleta.
    """
    problemas = []
    if len(dados) < 3000:
        problemas.append('só %d municípios com dado; esperava mais de 3.000'
                         % len(dados))

    fora = []
    for cod, reg in dados.items():
        for ident in ('res_cob_total', 'res_cob_rural', 'res_seletiva', 'res_disp_inad'):
            v = reg.get(ident)
            if v is not None and not (-0.01 <= v <= 100.01):
                fora.append('%s %s=%s' % (cod, ident, v))
    if fora:
        problemas.append('%d percentuais fora de 0–100 (ex.: %s)'
                         % (len(fora), ', '.join(fora[:3])))

    massa = [r['res_massa_pc'] for r in dados.values() if 'res_massa_pc' in r]
    if massa:
        mediana = sorted(massa)[len(massa) // 2]
        if not (0.2 <= mediana <= 3.0):
            problemas.append('massa per capita com mediana de %.2f kg/hab.dia — '
                             'fora do plausível' % mediana)

    if problemas:
        raise SystemExit('Conferência falhou, nada foi gravado:\n  - ' +
                         '\n  - '.join(problemas))

    resumo = dict(municipios=len(dados), **relatorio)
    for ident, _, _ in INDICADORES:
        vals = sorted(r[ident] for r in dados.values() if ident in r)
        if vals:
            resumo[ident] = dict(com_dado=len(vals),
                                 mediana=round(vals[len(vals) // 2], 2),
                                 zeros=sum(1 for v in vals if v == 0))
    return resumo


# --------------------------------------------------------------------- saída
def estado_atual():
    caminho = os.path.join(SAIDA, 'auto_sinisa.estado.json')
    if os.path.exists(caminho):
        with open(caminho, encoding='utf-8') as f:
            return json.load(f)
    return {}


def grava(dados, edicao, referencia, totais, origem):
    os.makedirs(SAIDA, exist_ok=True)
    ids = [i for i, _, _ in INDICADORES]

    with open(os.path.join(SAIDA, 'auto_sinisa.csv'), 'w',
              encoding='utf-8', newline='') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['codigo'] + ids)
        for cod in sorted(dados):
            reg = dados[cod]
            # célula vazia onde não há dado; zero só quando o município
            # declarou zero de verdade
            w.writerow([cod] + ['' if reg.get(i) is None else reg[i] for i in ids])

    meta = {}
    for ident, _, definicao in INDICADORES:
        meta[ident] = dict(definicao)
        meta[ident].update(ano=str(referencia), fonte=FONTE)
    with open(os.path.join(SAIDA, 'auto_sinisa.meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    with open(os.path.join(SAIDA, 'auto_sinisa.estado.json'), 'w', encoding='utf-8') as f:
        json.dump({'edicao': edicao, 'referencia': referencia, 'origem': origem,
                   'verificadoEm': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                   'totais': totais},
                  f, ensure_ascii=False, indent=2)


def resumo_markdown():
    e = estado_atual()
    if not e:
        return 'Sem estado gravado.'
    t = e.get('totais', {})
    f = lambda n: '{:,}'.format(n).replace(',', '.')
    linhas = [
        '**SINISA %s** · ano de referência %s · módulo de Resíduos Sólidos'
        % (e.get('edicao'), e.get('referencia')),
        '',
        '%s municípios responderam ao módulo; %s não responderam e ficam **sem '
        'dado** — não como zero.'
        % (f(t.get('respondentes', 0)), f(t.get('sem_resposta', 0))),
        '', '| indicador | municípios com dado | mediana | em zero |',
        '|---|---:|---:|---:|',
    ]
    for ident, _, definicao in INDICADORES:
        d = t.get(ident)
        if d:
            linhas.append('| %s | %s | %s | %s |'
                          % (definicao['nome'], f(d['com_dado']), d['mediana'],
                             f(d['zeros'])))
    linhas += ['',
               'Estes cinco indicadores são **novos** no painel — nenhum valor '
               'que já estava no ar muda por causa deste PR.',
               '',
               'Assim que for aceito, o *Atualizar dados do painel* dispara '
               'sozinho e eles aparecem no mapa, no tema Saneamento.']
    return '\n'.join(linhas)


# --------------------------------------------------------------------- sondar
def sondar():
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    eds = edicoes()
    print('Edições publicadas: %s' % ', '.join(str(a) for a in sorted(eds)))
    ed = max(eds)
    print('Mais recente: SINISA %d' % ed)
    print('  %s' % eds[ed])
    url = pacote_de_residuos(eds[ed])
    print('  pacote de resíduos: %s' % url.rsplit('/', 1)[-1])
    conteudo = baixa(url)
    print('  %.1f MB baixados' % (len(conteudo) / 1e6))
    z = zipfile.ZipFile(io.BytesIO(conteudo))
    nome, wb = acha_planilha(z)
    print('  planilha escolhida: %s' % nome.rsplit('/', 1)[-1])
    dados, rel = le_indicadores(wb)
    print('  %d municípios com dado · %d responderam · %d não responderam'
          % (len(dados), rel['respondentes'], rel['sem_resposta']))
    totais = confere(dados, rel)
    for ident, _, definicao in INDICADORES:
        d = totais.get(ident)
        if d:
            print('    %-34s %5d com dado · mediana %7.2f · %4d em zero'
                  % (definicao['nome'][:34], d['com_dado'], d['mediana'], d['zeros']))


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
    if args.sondar:
        sondar()
        return

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    eds = edicoes()
    ed = max(eds)
    antes = estado_atual().get('edicao')
    print('Edição mais recente do SINISA: %d' % ed)
    print('Último processado aqui: %s' % (antes or '(nenhum)'))
    novidade = ed != antes
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write('novidade=%s\n' % ('true' if (novidade or args.forcar) else 'false'))
            f.write('edicao=%d\n' % ed)
    if args.so_checar:
        print('MUDOU' if novidade else 'sem novidade')
        return
    if not novidade and not args.forcar:
        print('Nada a fazer.')
        return

    url = pacote_de_residuos(eds[ed])
    print('Baixando %s' % url.rsplit('/', 1)[-1])
    conteudo = baixa(url)
    print('  %.1f MB' % (len(conteudo) / 1e6))
    z = zipfile.ZipFile(io.BytesIO(conteudo))
    nome, wb = acha_planilha(z)
    print('  planilha: %s' % nome.rsplit('/', 1)[-1])
    dados, rel = le_indicadores(wb)
    print('  %d municípios com dado · %d sem resposta ao módulo'
          % (len(dados), rel['sem_resposta']))
    totais = confere(dados, rel)
    grava(dados, ed, ed - 1, totais, url)
    print('Gravado em fonte/auto/auto_sinisa.csv')


if __name__ == '__main__':
    main()
