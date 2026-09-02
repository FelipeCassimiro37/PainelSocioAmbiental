#!/usr/bin/env python3
"""
Vigia a divulgação anual do Censo Escolar (INEP) e atualiza as matrículas.

    python scripts/monitor_censo.py --sondar   # só investiga e conta o que achou
    python scripts/monitor_censo.py --so-checar  # diz se saiu ano novo
    python scripts/monitor_censo.py            # baixa e grava, se houver ano novo

De onde vem o dado
------------------
Do INEP, direto. NÃO do QEdu.

O QEdu não produz dado nenhum: ele exibe o Censo Escolar do INEP. Puxar de lá
seria pegar de segunda mão o que a fonte publica de primeira, herdando qualquer
recorte ou arredondamento que eles tenham feito pelo caminho — e sem a coluna
por escola que este painel já mostra. Além disso o site fica atrás de um WAF que
devolve 403 para qualquer coisa que não seja um navegador de verdade, então
"trocar o código do município na URL" não funcionaria nem se fosse a melhor
ideia.

O caminho oficial é um arquivo só:

  1. a página de microdados do Censo Escolar lista um .zip por ano;
  2. o ano mais novo é o maior que aparecer nessa lista — é assim que se detecta
     divulgação nova, já que aqui não há redirecionamento como no CAGED;
  3. dentro do .zip, o painel precisa de UM arquivo: `microdados_ed_basica_<ano>.csv`,
     uma linha por escola, com as colunas QT_MAT_*. Os arquivos `matricula_*.csv`
     (dezenas de milhões de linhas, uma por matrícula) não são necessários.

O endereço é sempre lido da página, nunca montado à mão. O de 2025, por exemplo,
saiu como `microdados_censo_escolar_2025_.zip`, com um sublinhado sobrando antes
do `.zip`; qualquer padrão que a gente inventasse daria link quebrado.

Baixar só o que interessa
-------------------------
O .zip inteiro é grande e quase todo ele é matrícula individual, que não usamos.
Se o servidor aceitar requisição por faixa de bytes (`Range`), dá para ler só o
índice do zip e depois só o pedaço do arquivo que interessa — alguns MB em vez
do pacote inteiro. Se não aceitar, cai no download completo. O `--sondar` existe
para descobrir qual dos dois caminhos vale, sem gravar nada.
"""
import argparse, io, json, os, re, sys, unicodedata, zipfile
from datetime import datetime, timezone

import urllib.parse, urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAIDA = os.path.join(RAIZ, 'fonte', 'auto')

PAGINA = ('https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/'
          'microdados/censo-escolar')

# O servidor do INEP derruba a conexão para alguns clientes. Tentamos primeiro
# um User-Agent honesto; se ele for recusado, repetimos com um de navegador,
# que é o que o próprio site usa para servir o mesmo arquivo público.
UAS = [
    {'User-Agent': 'painel-socioambiental/1.0 (+github actions; dados publicos)'},
    {'User-Agent': ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/128.0 Safari/537.36'),
     'Accept': '*/*', 'Accept-Encoding': 'identity', 'Connection': 'keep-alive'},
]
UA = UAS[0]


def chave(s):
    t = unicodedata.normalize('NFKD', str(s or '').lower())
    return re.sub(r'\s+', ' ', ''.join(c for c in t if not unicodedata.combining(c))).strip()


def busca(url, cabecalhos=None, metodo='GET', ua=None, espera=60, tentativas=2):
    """
    Requisição com repetição, e com prazo curto por padrão.

    O prazo importa mais do que parece. O servidor do INEP às vezes aceita a
    conexão e simplesmente não responde; com prazo de 5 minutos e 4 tentativas,
    UMA sondagem que devia levar segundos ficava 20 minutos pendurada — foi
    exatamente o que aconteceu na primeira versão disto. Prazo curto transforma
    "travou" em "falhou e seguiu adiante", que é o comportamento útil.

    Quem vai baixar o arquivo de verdade passa um `espera` maior de propósito.
    """
    ultimo = None
    for tentativa in range(tentativas):
        h = dict(ua or UAS[min(tentativa, len(UAS) - 1)])
        h.update(cabecalhos or {})
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=h, method=metodo), timeout=espera)
        except Exception as e:
            ultimo = e
    raise ultimo


# ------------------------------------------------------ achar a divulgação
def anos_publicados():
    """
    {ano: url do zip}, lido da página de microdados.

    A detecção de novidade é "apareceu um ano maior do que o que já processei",
    e não uma data no calendário: se o INEP atrasar ou antecipar a divulgação,
    o vigia se ajusta sozinho.
    """
    with busca(PAGINA) as r:
        html = r.read().decode('utf-8', 'replace')
    achados = {}
    for href in re.findall(r'href="([^"]+\.zip)"', html, re.I):
        nome = chave(href.rsplit('/', 1)[-1])
        if 'censo_escolar' not in nome and 'censo-escolar' not in nome:
            continue
        m = re.search(r'(20\d{2})', nome)
        if not m:
            continue
        ano = int(m.group(1))
        url = href if href.startswith('http') else urllib.parse.urljoin(PAGINA, href)
        achados.setdefault(ano, url)
    if not achados:
        raise SystemExit('Não achei nenhum .zip de microdados em ' + PAGINA +
                         '. O INEP provavelmente mudou o formato da página.')
    return achados


# --------------------------------------------- ler um zip remoto por faixas
class ZipRemoto(io.RawIOBase):
    """
    Um arquivo que mora no servidor e é lido em pedaços, sob demanda.

    O `zipfile` só precisa de `seek` e `read`. Dando isso a ele por cima de
    requisições HTTP com `Range`, ele lê o índice no fim do pacote e depois só
    os bytes do membro pedido. Resultado: dá para tirar um CSV de 100 MB de
    dentro de um zip de vários GB sem baixar o resto.

    Se o servidor ignorar o `Range` (devolve 200 em vez de 206), isso é
    detectado na hora e o chamador cai para o download completo — ler o pacote
    inteiro fingindo que são faixas seria muito pior do que baixá-lo de uma vez.
    """

    def __init__(self, url):
        self.url = url
        self.pos = 0
        self.baixado = 0
        self.pedidos = 0
        with busca(url, {'Range': 'bytes=0-1'}, ua=UAS[1]) as r:
            if r.status != 206:
                raise ValueError('servidor não aceita Range (devolveu %s)' % r.status)
            faixa = r.headers.get('Content-Range', '')
            m = re.search(r'/(\d+)$', faixa)
            if not m:
                raise ValueError('Content-Range sem tamanho total: %r' % faixa)
            self.tamanho = int(m.group(1))

    def seekable(self):
        return True

    def readable(self):
        return True

    def seek(self, pos, whence=0):
        base = {0: 0, 1: self.pos, 2: self.tamanho}[whence]
        self.pos = max(0, min(self.tamanho, base + pos))
        return self.pos

    def tell(self):
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.tamanho - self.pos
        n = min(n, self.tamanho - self.pos)
        if n <= 0:
            return b''
        fim = self.pos + n - 1
        with busca(self.url, {'Range': 'bytes=%d-%d' % (self.pos, fim)}, ua=UAS[1]) as r:
            dados = r.read()
        self.pos += len(dados)
        self.baixado += len(dados)
        self.pedidos += 1
        return dados

    def readinto(self, b):
        dados = self.read(len(b))
        b[:len(dados)] = dados
        return len(dados)


def escolhe_membro(nomes, ano):
    """O CSV de escolas dentro do zip, sem depender do nome exato."""
    candidatos = [n for n in nomes if n.lower().endswith('.csv')
                  and 'ed_basica' in chave(n).replace('-', '_')]
    if not candidatos:
        # fallback: qualquer csv com o ano no nome que não seja de matrícula
        candidatos = [n for n in nomes if n.lower().endswith('.csv')
                      and str(ano) in n and 'matricula' not in chave(n)
                      and 'docente' not in chave(n) and 'turma' not in chave(n)]
    if not candidatos:
        raise SystemExit('Não achei o CSV de escolas (ed_basica) dentro do zip. '
                         'Membros: %s' % nomes[:20])
    return sorted(candidatos, key=len)[0]


# ------------------------------------------------------------------ sondar
def sondar():
    """Investiga e conta o que achou. Não baixa o pacote inteiro nem grava nada."""
    anos = anos_publicados()
    print('Anos disponíveis no INEP: %s' % ', '.join(str(a) for a in sorted(anos)))
    ano = max(anos)
    url = anos[ano]
    print('Mais recente: %d' % ano)
    print('  %s' % url)

    # Cada teste abaixo tem prazo curto e uma tentativa só. Uma sondagem tem de
    # terminar rápido, mesmo (principalmente) quando tudo dá errado.
    import time
    for i, ua in enumerate(UAS):
        rotulo = 'sóbrio' if i == 0 else 'navegador'
        for nome, kw in (('Range', {'cabecalhos': {'Range': 'bytes=0-1'}}),
                         ('HEAD ', {'metodo': 'HEAD'})):
            t0 = time.time()
            try:
                with busca(url, ua=ua, espera=20, tentativas=1, **kw) as r:
                    n = r.headers.get('Content-Length')
                    print('  UA %-9s %s -> HTTP %s · Content-Range=%r · tamanho=%s '
                          '· Accept-Ranges=%r (%.1fs)'
                          % (rotulo, nome, r.status, r.headers.get('Content-Range'),
                             ('%.0f MB' % (int(n) / 1e6)) if n else '?',
                             r.headers.get('Accept-Ranges'), time.time() - t0))
            except Exception as e:
                print('  UA %-9s %s -> falhou em %.1fs: %s'
                      % (rotulo, nome, time.time() - t0, e))

    try:
        remoto = ZipRemoto(url)
    except Exception as e:
        print('  Leitura por faixas indisponível (%s).' % e)
        print('  Caminho alternativo: baixar o pacote inteiro. Medindo a vazão…')
        try:
            t0 = time.time()
            lidos = 0
            with busca(url, ua=UAS[1], espera=60, tentativas=2) as r:
                total = r.headers.get('Content-Length')
                # para no que vier primeiro: 40 MB ou 45 segundos. Sem o limite
                # de tempo, uma conexão lenta seguraria a sondagem sem informar
                # mais nada do que ela já informou.
                while lidos < 40 * 1024 * 1024 and time.time() - t0 < 45:
                    pedaco = r.read(1024 * 1024)
                    if not pedaco:
                        break
                    lidos += len(pedaco)
            dt = max(time.time() - t0, 0.001)
            print('    tamanho total: %s' % (('%.0f MB' % (int(total) / 1e6))
                                             if total else 'não informado'))
            print('    baixei %.1f MB em %.1f s (%.1f MB/s)'
                  % (lidos / 1e6, dt, lidos / 1e6 / dt))
            if total and lidos:
                print('    o pacote inteiro levaria ~%.0f s nesse ritmo'
                      % (int(total) / 1e6 / (lidos / 1e6 / dt)))
        except Exception as e2:
            print('    download completo também falhou: %s' % e2)
        return
    print('  tamanho do zip: %.0f MB · o servidor aceita leitura por faixas' %
          (remoto.tamanho / 1e6))

    z = zipfile.ZipFile(remoto)
    infos = sorted(z.infolist(), key=lambda i: -i.file_size)
    print('  %d arquivos dentro. Os maiores:' % len(infos))
    for i in infos[:8]:
        print('    %9.1f MB  %s' % (i.file_size / 1e6, i.filename))

    alvo = escolhe_membro([i.filename for i in infos], ano)
    info = z.getinfo(alvo)
    print('  arquivo que o painel usa: %s' % alvo)
    print('    %.1f MB descompactado, %.1f MB compactado'
          % (info.file_size / 1e6, info.compress_size / 1e6))
    print('  lidos até aqui: %.2f MB em %d requisições (só o índice do zip)'
          % (remoto.baixado / 1e6, remoto.pedidos))

    with z.open(alvo) as f:
        cabecalho = f.readline().decode('utf-8', 'replace').strip()
    cols = re.split(r'[;,]', cabecalho)
    qt = [c for c in cols if c.upper().startswith('QT_MAT')]
    print('  primeira linha lida: %d colunas, %d delas QT_MAT_*' % (len(cols), len(qt)))
    print('  exemplos: %s' % ', '.join(cols[:6]))
    print('  total baixado na sondagem: %.2f MB' % (remoto.baixado / 1e6))


def estado_atual():
    caminho = os.path.join(SAIDA, 'auto_censo.estado.json')
    if os.path.exists(caminho):
        with open(caminho, encoding='utf-8') as f:
            return json.load(f)
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sondar', action='store_true',
                    help='investiga a fonte e conta o que achou, sem gravar nada')
    ap.add_argument('--so-checar', action='store_true', help='diz se saiu ano novo')
    args = ap.parse_args()

    if args.sondar:
        sondar()
        return

    anos = anos_publicados()
    ano = max(anos)
    antes = estado_atual().get('ano')
    print('Ano mais recente no INEP: %d' % ano)
    print('Último processado aqui: %s' % (antes or '(nenhum)'))
    novidade = ano != antes
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write('novidade=%s\n' % ('true' if novidade else 'false'))
            f.write('ano=%d\n' % ano)
    if args.so_checar:
        print('MUDOU' if novidade else 'sem novidade')
        return
    raise SystemExit('A parte que grava ainda não está escrita — rode --sondar '
                     'primeiro e decida o caminho com base no que ele contar.')


if __name__ == '__main__':
    main()
