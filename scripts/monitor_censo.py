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
O pacote tem 537 MB e o painel usa um arquivo de 123 MB de dentro dele. O
servidor aceita requisição por faixa de bytes, então o zip é lido pelo índice e
só o membro necessário é trazido: 134 MB em 19 requisições, em vez de 537 MB.

O certificado do INEP
---------------------
O `download.inep.gov.br` publica o certificado com a cadeia incompleta: falta o
intermediário. Navegador e curl não reclamam porque buscam sozinhos o pedaço que
falta — o endereço vem dentro do próprio certificado. O Python não faz isso, e
recusava a conexão. `contexto_tls()` faz essa busca à mão. A verificação
continua inteira: só o elo que o servidor esqueceu é suprido.
"""
import argparse, io, json, os, re, ssl, sys, tempfile, unicodedata, zipfile
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


# ------------------------------------------- consertar a cadeia do certificado
_CONTEXTO = {}


def contexto_tls(host):
    """
    Contexto TLS que completa a cadeia que o servidor do INEP não manda.

    O `download.inep.gov.br` apresenta só o certificado dele, sem o intermediário
    que liga esse certificado a uma autoridade conhecida. Navegador nenhum
    reclama porque o navegador vai buscar o pedaço que falta: o endereço dele
    vem dentro do próprio certificado, no campo "CA Issuers". O Python e o curl
    não fazem essa busca e recusam a conexão.

    Aqui a busca é feita à mão, uma vez, e o resultado entra no contexto. Repare
    que isto NÃO afrouxa a verificação: continua exigindo certificado válido,
    assinado por uma autoridade confiável. Só supre o elo que o servidor
    esqueceu. Desligar a verificação seria a saída preguiçosa e abriria a porta
    para alguém no meio do caminho servir dados falsos ao painel.
    """
    if host in _CONTEXTO:
        return _CONTEXTO[host]
    ctx = ssl.create_default_context()
    passos = []
    extras = _intermediarios(host, diagnostico=passos)
    _CONTEXTO[host + '/passos'] = passos
    if extras:
        with tempfile.NamedTemporaryFile('w', suffix='.pem', delete=False) as f:
            f.write('\n'.join(extras))
            caminho = f.name
        ctx.load_verify_locations(cafile=caminho)
    _CONTEXTO[host] = (ctx, len(extras))
    return _CONTEXTO[host]


def _cert_do_servidor(host, porta=443, espera=20):
    """
    Pega o certificado que o servidor apresenta, em DER.

    A verificação é desligada NESTA conexão de propósito, e só aqui: o objetivo
    é ler o certificado, não buscar dado. Nada do conteúdo desta conexão é
    usado. Depois de completar a cadeia, o download real acontece numa conexão
    plenamente verificada — se o certificado for falso, a verificação de lá
    reprova, porque um intermediário forjado não fecha com nenhuma raiz
    confiável do sistema.
    """
    import socket, time
    # Parte-se do contexto PADRÃO e só então a verificação é afrouxada. Um
    # SSLContext cru tem outra lista de cifras e não anuncia ALPN, e o servidor
    # do INEP derrubava a conexão por causa disso ("connection reset") — enquanto
    # aceitava normalmente as conexões feitas com o contexto padrão. Diferença
    # sutil e cara: custou algumas rodadas até o diagnóstico apontar para cá.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    erro = None
    for tentativa in range(3):
        try:
            with socket.create_connection((host, porta), timeout=espera) as cru:
                with ctx.wrap_socket(cru, server_hostname=host) as tls:
                    return tls.getpeercert(binary_form=True)
        except Exception as e:
            erro = e
            time.sleep(1)
    raise erro


def _uris_do_emissor(der):
    """
    Endereços onde pode estar o certificado que assinou este.

    O campo se chama "Authority Information Access — CA Issuers" e é o que o
    navegador consulta quando o servidor esquece de mandar a cadeia. Procuro as
    URLs como texto dentro do DER em vez de decodificar ASN.1: elas aparecem ali
    literalmente, e assim o script não depende de biblioteca extra nem do
    openssl de linha de comando.

    Devolvo uma LISTA, e não um palpite. Cada autoridade escreve esse endereço
    de um jeito — uns terminam em `.crt`, outros em `.cer`, outros em nada — e
    exigir uma terminação específica foi justamente o que fez a primeira versão
    não achar nada num certificado que tinha o campo. Fora as de OCSP e de lista
    de revogação, que servem para outra coisa, todas são tentadas na ordem.
    """
    vistas, candidatas = set(), []
    for u in re.findall(rb'https?://[A-Za-z0-9\-\._~:/\?#\[\]@!\$&\'\(\)\*\+,;=%]+', der):
        texto = u.decode('ascii', 'ignore').rstrip('.,;')
        # O DER não delimita a URL: logo depois dela vêm os bytes da próxima
        # estrutura ASN.1, e alguns deles são imprimíveis, então grudam no fim
        # do endereço. Foi exatamente isso que aconteceu aqui — o certificado
        # aponta para "…/rnpicpedugr46ovtlsca2025.crt" e a leitura crua trazia
        # "…crt0?", dando 404. Quando há extensão de certificado, corto ali.
        corte = re.search(r'\.(crt|cer|der|p7c|p7b)', texto, re.I)
        if corte:
            texto = texto[:corte.end()]
        baixo = texto.lower()
        if texto in vistas or 'ocsp' in baixo or baixo.endswith('.crl') or '/crl' in baixo:
            continue
        vistas.add(texto)
        candidatas.append(texto)
    # as que declaram extensão de certificado vêm primeiro
    candidatas.sort(key=lambda t: 0 if re.search(r'\.(crt|cer|der|p7c|p7b)$', t, re.I) else 1)
    return candidatas


def _intermediarios(host, limite=4, diagnostico=None):
    """Segue o campo 'CA Issuers' até fechar a cadeia. Devolve PEMs."""
    import base64
    achados = []
    anota = diagnostico.append if diagnostico is not None else (lambda *_: None)
    try:
        der = _cert_do_servidor(host)
        anota('certificado do servidor lido: %d bytes' % len(der))
    except Exception as e:
        anota('não consegui ler o certificado do servidor: %s' % e)
        return achados

    for volta in range(limite):
        candidatas = _uris_do_emissor(der)
        if not candidatas:
            anota('o certificado não traz endereço de emissor (fim da busca)')
            break
        anota('endereços no certificado: %s' % ', '.join(candidatas[:4]))
        novo_der = None
        for uri in candidatas:
            try:
                with urllib.request.urlopen(
                        urllib.request.Request(uri, headers=UAS[1]), timeout=20) as r:
                    bruto = r.read()
            except Exception as e:
                anota('  %s -> %s' % (uri, e))
                continue
            try:
                if bruto.lstrip().startswith(b'-----BEGIN'):
                    pem = bruto.decode('ascii', 'ignore').strip()
                    novo_der = base64.b64decode(''.join(
                        l for l in pem.splitlines() if not l.startswith('-----')))
                else:
                    novo_der = bruto
                    pem = ssl.DER_cert_to_PEM_cert(novo_der).strip()
            except Exception as e:
                anota('  %s -> não é um certificado (%s)' % (uri, e))
                novo_der = None
                continue
            anota('  %s -> certificado de %d bytes' % (uri, len(novo_der)))
            achados.append(pem)
            break
        if novo_der is None:
            break
        der = novo_der
    return achados


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
            alvo = urllib.parse.urlparse(url).hostname or ''
            # só o host de download precisa do remendo de cadeia; o portal do
            # INEP tem certificado bem configurado e usa o contexto padrão
            ctx = contexto_tls(alvo)[0] if 'download.inep' in alvo else None
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=h, method=metodo),
                timeout=espera, context=ctx)
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
        with busca(url, {'Range': 'bytes=0-1'}, ua=UAS[1], espera=15, tentativas=1) as r:
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


def zip_remoto(url, buffer=8 * 1024 * 1024):
    """
    O zip aberto sobre leitura por faixas, com buffer grande.

    O buffer não é detalhe de desempenho, é o que torna a ideia viável: o
    `zipfile` pede o arquivo em pedacinhos, e sem buffer cada pedacinho vira uma
    requisição HTTP própria — dezenas de milhares delas para um CSV de 123 MB,
    o que demora mais do que baixar o pacote inteiro. Com 8 MB por requisição
    são umas 16 idas ao servidor.
    """
    cru = ZipRemoto(url)
    return zipfile.ZipFile(io.BufferedReader(cru, buffer_size=buffer)), cru


def escolhe_membro(z, colunas_exigidas=('CO_ENTIDADE', 'QT_MAT_BAS')):
    """
    Acha, PELO CONTEÚDO, o CSV que tem as matrículas por escola.

    A escolha é pela primeira linha de cada candidato, não pelo nome — e essa
    decisão se pagou na primeira vez que foi usada. Até 2024 o arquivo se
    chamava `microdados_ed_basica_<ano>.csv`; em 2025 o INEP dividiu o pacote em
    tabelas por assunto, e as matrículas foram parar num arquivo chamado
    `Tabela_Matricula_2025_V2.csv` — enquanto `Tabela_Escola`, que pelo nome
    parecia o certo, tem infraestrutura e nenhuma coluna de matrícula. Procurar
    pelo nome teria pegado o arquivo errado com a maior naturalidade.
    """
    csvs = sorted((i for i in z.infolist() if i.filename.lower().endswith('.csv')),
                  key=lambda i: -i.file_size)
    for info in csvs:
        try:
            with z.open(info.filename) as f:
                # lê um bloco e corta na primeira quebra, em vez de usar
                # readline(): num stream que descomprime por cima de requisições
                # HTTP, o readline às vezes devolve a linha pela metade, e o
                # cabeçalho truncado faz o arquivo certo ser descartado como se
                # não tivesse as colunas. Aconteceu num ensaio com a base de 2024.
                bloco = b''
                while b'\n' not in bloco and len(bloco) < 1 << 20:
                    pedaco = f.read(65536)
                    if not pedaco:
                        break
                    bloco += pedaco
            cab = bloco.split(b'\n', 1)[0].decode('latin-1', 'replace')
        except Exception:
            continue
        cols = {c.strip().strip('﻿').upper() for c in re.split(r'[;,]', cab)}
        if all(c in cols for c in colunas_exigidas):
            return info.filename
    raise SystemExit('Nenhum CSV do pacote tem as colunas %s. O INEP mudou a '
                     'estrutura de novo — arquivos vistos: %s'
                     % (', '.join(colunas_exigidas), [i.filename for i in csvs][:12]))


# ------------------------------------------------------------------ sondar
def sondar():
    """
    Investiga e conta o que achou. Não baixa o pacote inteiro nem grava nada.

    Duas coisas aqui são deliberadas e foram aprendidas na marra:

    1. A saída é destravada (`line_buffering`). Sem isso, o Python segura tudo
       num buffer e só descarrega no fim — então, quando a execução era morta
       por tempo, o relatório inteiro se perdia e o log ficava em branco. Uma
       sonda que só fala se terminar bem não serve para investigar travamento.
    2. Todo teste tem prazo curto, e a soma de todos cabe folgada dentro do
       limite de 5 minutos do workflow. Diagnóstico incompleto é informação;
       diagnóstico pendurado não é.
    """
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    anos = anos_publicados()
    print('Anos disponíveis no INEP: %s' % ', '.join(str(a) for a in sorted(anos)))
    ano = max(anos)
    url = anos[ano]
    print('Mais recente: %d' % ano)
    print('  %s' % url)

    import time
    alvo_host = urllib.parse.urlparse(url).hostname
    t0 = time.time()
    _, n_extras = contexto_tls(alvo_host)
    print('  cadeia do certificado: %d intermediário(s) adicionado(s) (%.1fs)'
          % (n_extras, time.time() - t0))
    for passo in _CONTEXTO.get(alvo_host + '/passos', []):
        print('    · %s' % passo)

    # Cada teste abaixo tem prazo curto e uma tentativa só. Uma sondagem tem de
    # terminar rápido, mesmo (principalmente) quando tudo dá errado.
    for i, ua in enumerate(UAS):
        rotulo = 'sóbrio' if i == 0 else 'navegador'
        for nome, kw in (('Range', {'cabecalhos': {'Range': 'bytes=0-1'}}),
                         ('HEAD ', {'metodo': 'HEAD'})):
            t0 = time.time()
            try:
                with busca(url, ua=ua, espera=10, tentativas=1, **kw) as r:
                    n = r.headers.get('Content-Length')
                    print('  UA %-9s %s -> HTTP %s · Content-Range=%r · tamanho=%s '
                          '· Accept-Ranges=%r (%.1fs)'
                          % (rotulo, nome, r.status, r.headers.get('Content-Range'),
                             ('%.0f MB' % (int(n) / 1e6)) if n else '?',
                             r.headers.get('Accept-Ranges'), time.time() - t0))
            except Exception as e:
                print('  UA %-9s %s -> falhou em %.1fs: %s'
                      % (rotulo, nome, time.time() - t0, e))

    # O certificado do download.inep.gov.br vem com a cadeia incompleta: falta o
    # certificado intermediário. Navegadores e o curl buscam o que falta sozinhos
    # (o endereço vem dentro do próprio certificado); o urllib do Python não faz
    # isso e recusa a conexão. Por isso vale medir os dois transportes antes de
    # decidir como o robô vai baixar.
    import shutil, subprocess
    if shutil.which('curl'):
        t0 = time.time()
        p = subprocess.run(['curl', '-sS', '-L', '--max-time', '20', '-r', '0-1048575',
                            '-o', '/tmp/fatia.bin', '-w', '%{http_code} %{size_download}',
                            '-A', UAS[1]['User-Agent'], url],
                           capture_output=True, text=True, timeout=40)
        print('  curl + Range -> %s (%.1fs) %s'
              % (p.stdout.strip() or 'sem saída', time.time() - t0, p.stderr.strip()[:160]))
        t0 = time.time()
        p = subprocess.run(['curl', '-sSI', '-L', '--max-time', '20',
                            '-A', UAS[1]['User-Agent'], url], capture_output=True, text=True, timeout=40)
        cab = [l for l in p.stdout.splitlines()
               if re.match(r'(?i)^(http/|content-length|accept-ranges|content-range)', l)]
        print('  curl + HEAD  -> %s (%.1fs) %s'
              % (' | '.join(cab) or 'sem cabeçalhos', time.time() - t0, p.stderr.strip()[:160]))

    try:
        remoto = ZipRemoto(url)
    except Exception as e:
        print('  Leitura por faixas indisponível pelo Python (%s).' % e)
        print('  Caminho alternativo: baixar o pacote inteiro. Medindo a vazão…')
        try:
            t0 = time.time()
            lidos = 0
            with busca(url, ua=UAS[1], espera=30, tentativas=1) as r:
                total = r.headers.get('Content-Length')
                # para no que vier primeiro: 40 MB ou 45 segundos. Sem o limite
                # de tempo, uma conexão lenta seguraria a sondagem sem informar
                # mais nada do que ela já informou.
                while lidos < 40 * 1024 * 1024 and time.time() - t0 < 30:
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


# ------------------------------------------------------ extrair e conferir
def colunas_do_painel():
    """
    A lista de colunas vem do `preparar_fonte_edu.py`, não daqui.

    Essa lista também define a ORDEM em que as etapas aparecem na tela: o
    build_edu.py e o index.html a leem de lá. Mantê-la em dois lugares seria
    garantir que um dia as duas discordassem e a tela mudasse sozinha.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import preparar_fonte_edu as prep
    return prep.IDENT, prep.MAT


def extrai(z, membro):
    """Devolve (cabeçalho, linhas) do CSV de matrículas, já em memória."""
    import csv as _csv
    _csv.field_size_limit(10 ** 9)
    with z.open(membro) as bruto:
        texto = io.TextIOWrapper(bruto, encoding='latin-1', newline='')
        r = _csv.reader(texto, delimiter=';')
        cab = [c.strip().strip('﻿') for c in next(r)]
        linhas = [l for l in r if len(l) >= len(cab)]
    return cab, linhas


def confere_censo(cab, linhas, anterior=None):
    """
    Barreiras antes de gravar.

    A régua principal é a edição anterior, quando existe: um pacote lido errado
    quase nunca erra pouco, então uma variação grande no total de matrículas ou
    no número de escolas denuncia o problema. As faixas absolutas ficam como
    rede para o primeiro uso, quando não há com o que comparar.
    """
    i = {c: k for k, c in enumerate(cab)}
    problemas = []
    escolas = len(linhas)
    municipios = {l[i['CO_MUNICIPIO']] for l in linhas}
    total = ativas = 0
    for l in linhas:
        v = (l[i['QT_MAT_BAS']] or '').strip()
        n = 0
        if v:
            try:
                n = int(float(v))
            except ValueError:
                n = 0
        total += n
        if n > 0:
            ativas += 1

    if escolas < 150000:
        problemas.append('só %d escolas; esperava mais de 150 mil' % escolas)
    if len(municipios) < 5400:
        problemas.append('só %d municípios; esperava perto de 5.570' % len(municipios))
    if not (35e6 <= total <= 60e6):
        problemas.append('total de %s matrículas na educação básica fora da faixa '
                         'plausível' % f'{total:,}')

    if anterior:
        # A comparação usa escolas COM MATRÍCULA, não o total de linhas. O
        # formato antigo (até 2024) listava também as escolas cadastradas sem
        # nenhum aluno — 36 mil delas em 2024 — e o formato novo não lista. Em
        # cima do total de linhas isso parecia uma queda de 20% de um ano para o
        # outro; em cima das escolas com aluno, a variação real é de 0,3%.
        # Comparar grandezas de escopos diferentes daria alarme falso todo ano em
        # que o INEP mexesse no recorte.
        for rotulo, agora, antes in (('escolas com matrícula', ativas, anterior['ativas']),
                                     ('matrículas', total, anterior['matriculas'])):
            if antes and abs(agora - antes) / antes > 0.15:
                problemas.append('%s variou %+.1f%% em relação à base anterior '
                                 '(%s -> %s) — variação demais para um ano'
                                 % (rotulo, 100 * (agora - antes) / antes,
                                    f'{antes:,}', f'{agora:,}'))
    if problemas:
        raise SystemExit('Conferência falhou, nada foi gravado:\n  - ' +
                         '\n  - '.join(problemas))
    return dict(escolas=escolas, ativas=ativas, municipios=len(municipios),
                matriculas=total)


def base_anterior():
    """Totais da base que já está no repositório, para servir de comparação."""
    import csv as _csv, gzip, glob
    arquivos = sorted(glob.glob(os.path.join(RAIZ, 'fonte', 'matriculas-*.csv.gz')))
    if not arquivos:
        return None
    caminho = arquivos[-1]
    _csv.field_size_limit(10 ** 9)
    with gzip.open(caminho, 'rt', encoding='utf-8', newline='') as f:
        r = _csv.reader(f, delimiter=';')
        cab = next(r)
        i = {c: k for k, c in enumerate(cab)}
        escolas = ativas = total = 0
        for l in r:
            escolas += 1
            v = (l[i['QT_MAT_BAS']] or '').strip()
            n = int(float(v)) if v else 0
            total += n
            if n > 0:
                ativas += 1
    m = re.search(r'matriculas-(\d{4})', os.path.basename(caminho))
    return dict(arquivo=os.path.basename(caminho), ano=m.group(1) if m else '?',
                escolas=escolas, ativas=ativas, matriculas=total)


def grava_censo(cab, linhas, ano, totais, membro, anterior):
    """Escreve fonte/matriculas-<ano>.csv.gz no mesmo formato de sempre."""
    import csv as _csv, gzip
    ident, mat = colunas_do_painel()
    i = {c: k for k, c in enumerate(cab)}
    faltam = [c for c in ident + mat if c not in i]
    if faltam:
        raise SystemExit('O arquivo do INEP não tem estas colunas que o painel '
                         'usa: %s' % ', '.join(faltam))
    manter = [i[c] for c in ident + mat]

    buf = io.StringIO()
    w = _csv.writer(buf, delimiter=';', lineterminator='\n')
    w.writerow(ident + mat)
    for l in linhas:
        w.writerow([l[j] for j in manter])

    destino = os.path.join(RAIZ, 'fonte', 'matriculas-%s.csv.gz' % ano)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    # mtime=0 faz o .gz sair sempre igual para o mesmo conteúdo. Sem isso o gzip
    # carimba a hora da geração dentro do arquivo, e o robô abriria um Pull
    # Request "com mudanças" todo ano mesmo quando o INEP republicasse dado
    # idêntico — um alarme falso que gasta a confiança de quem revisa.
    with open(destino, 'wb') as bruto:
        with gzip.GzipFile(fileobj=bruto, mode='wb', compresslevel=9, mtime=0) as g:
            g.write(buf.getvalue().encode('utf-8'))

    os.makedirs(SAIDA, exist_ok=True)
    with open(os.path.join(SAIDA, 'auto_censo.estado.json'), 'w', encoding='utf-8') as f:
        json.dump({'ano': int(ano), 'arquivoNoPacote': membro,
                   'colunasMantidas': len(ident + mat), 'colunasNaOrigem': len(cab),
                   'verificadoEm': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                   'totais': totais, 'baseAnterior': anterior},
                  f, ensure_ascii=False, indent=2)
    return destino


def resumo_markdown():
    """Corpo do Pull Request: o que mudou, para conferência humana."""
    e = estado_atual()
    if not e:
        return 'Sem estado gravado.'
    t = e.get('totais', {})
    ant = e.get('baseAnterior') or {}
    f = lambda n: '{:,}'.format(n).replace(',', '.')
    linhas = [
        '**Censo Escolar %s** · arquivo `%s` dentro do pacote do INEP'
        % (e.get('ano'), e.get('arquivoNoPacote', '?').rsplit('/', 1)[-1]),
        '', '| | base anterior | agora |', '|---|---:|---:|',
        '| Escolas no arquivo | %s | %s |' % (f(ant.get('escolas', 0)), f(t.get('escolas', 0))),
        '| Escolas com matrícula | %s | %s |' % (f(ant.get('ativas', 0)), f(t.get('ativas', 0))),
        '| Municípios | | %s |' % f(t.get('municipios', 0)),
        '| Matrículas na educação básica | %s | %s |'
        % (f(ant.get('matriculas', 0)), f(t.get('matriculas', 0))),
        '',
        'Mantive %s das %s colunas do arquivo original — as mesmas que o painel '
        'já usava, na mesma ordem.'
        % (e.get('colunasMantidas'), e.get('colunasNaOrigem')),
        '',
        'Assim que este PR for aceito, o **Atualizar matrículas (Censo Escolar)** '
        'dispara sozinho e o painel reprocessa as escolas — não precisa apertar '
        'nada na aba Actions.',
    ]
    return '\n'.join(linhas)


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
    ap.add_argument('--forcar', action='store_true', help='reprocessa mesmo sem ano novo')
    ap.add_argument('--resumo', action='store_true', help='imprime o corpo do Pull Request')
    args = ap.parse_args()

    if args.sondar:
        sondar()
        return
    if args.resumo:
        print(resumo_markdown())
        return

    anos = anos_publicados()
    ano = max(anos)
    antes = estado_atual().get('ano')
    print('Ano mais recente no INEP: %d' % ano)
    print('Último processado aqui: %s' % (antes or '(nenhum)'))
    novidade = ano != antes
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write('novidade=%s\n' % ('true' if (novidade or args.forcar) else 'false'))
            f.write('ano=%d\n' % ano)
    if args.so_checar:
        print('MUDOU' if novidade else 'sem novidade')
        return
    if not novidade and not args.forcar:
        print('Nada a fazer.')
        return

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    print('Abrindo o pacote de %d por leitura parcial…' % ano)
    z, cru = zip_remoto(anos[ano])
    print('  pacote de %.0f MB' % (cru.tamanho / 1e6))
    membro = escolhe_membro(z)
    info = z.getinfo(membro)
    print('  arquivo com as matrículas: %s (%.0f MB)' % (membro, info.file_size / 1e6))

    cab, linhas = extrai(z, membro)
    print('  %d escolas · %d colunas · %.0f MB trazidos da rede em %d requisições'
          % (len(linhas), len(cab), cru.baixado / 1e6, cru.pedidos))

    anterior = base_anterior()
    if anterior:
        print('  comparando com %s' % anterior['arquivo'])
    totais = confere_censo(cab, linhas, anterior)
    print('  conferência ok: %s matrículas em %s escolas, %d municípios'
          % (f"{totais['matriculas']:,}".replace(',', '.'),
             f"{totais['escolas']:,}".replace(',', '.'), totais['municipios']))

    destino = grava_censo(cab, linhas, str(ano), totais, membro, anterior)
    print('Gravado em %s (%.1f MB)'
          % (os.path.relpath(destino, RAIZ), os.path.getsize(destino) / 1e6))


if __name__ == '__main__':
    main()
