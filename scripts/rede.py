#!/usr/bin/env python3
"""
Busca na rede com nova tentativa, para os vigias.

Por que existe
--------------
Os servidores das fontes caem. Não é hipótese: em novembro de 2026, três
execuções do CAGED, duas do CEMPRE e uma do CLP morreram com "Connection reset
by peer" ou "timed out" — nenhuma por defeito do script, todas por queda
momentânea do outro lado. Uma falha dessas pinta um X vermelho no Actions, e um
X vermelho que não quer dizer nada é pior que inútil: ensina a ignorar o painel
de execuções, e aí o X que importa passa batido junto.

O que repete e o que não
------------------------
Repetir tudo seria igualmente ruim. Um 404 repetido quatro vezes gasta um
minuto para chegar à mesma conclusão e, pior, disfarça de instabilidade o que é
mudança de endereço na fonte — exatamente o tipo de coisa que o vigia existe
para descobrir. Então:

  repete   queda de conexão, prazo estourado, erro de DNS, 5xx, 429
  desiste  qualquer outro 4xx — 404, 403, 410: a fonte respondeu, e a
           resposta é que aquilo não está lá

Uso
---
    from rede import abre, le

    with abre(url) as r: ...          # resposta aberta, como urlopen
    dados = le(url)                   # bytes, já lidos
"""
import socket
import time
import urllib.error
import urllib.request

PADRAO_UA = {'User-Agent': 'Mozilla/5.0'}

# 429 é "devagar aí", não "não existe": espera e tenta de novo.
HTTP_QUE_REPETE = {429, 500, 502, 503, 504, 507, 509, 522, 524}


def _vale_repetir(erro):
    if isinstance(erro, urllib.error.HTTPError):
        return erro.code in HTTP_QUE_REPETE
    # URLError embrulha recusa de conexão, DNS e prazo; socket.timeout e
    # ConnectionError chegam soltos conforme o ponto onde a conexão caiu.
    return isinstance(erro, (urllib.error.URLError, socket.timeout,
                             ConnectionError, TimeoutError, OSError))


def abre(url, cabecalhos=None, espera=120, tentativas=4, pausa_max=20,
         avisa=print):
    """
    Abre a URL e devolve a resposta, repetindo quando a falha é de rede.

    A pausa dobra a cada tentativa (2s, 4s, 8s…) até `pausa_max`. Dobrar
    importa: quando a fonte está sobrecarregada, insistir de imediato só
    acrescenta carga, e a janela de instabilidade costuma ser de segundos.

    `avisa` recebe uma linha por tentativa perdida, para o log do Actions
    mostrar que houve tropeço mesmo quando a execução termina bem — passe
    `avisa=None` para silenciar.
    """
    cab = dict(PADRAO_UA)
    cab.update(cabecalhos or {})
    ultimo = None
    for n in range(tentativas):
        if n:
            time.sleep(min(2 ** n, pausa_max))
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=cab), timeout=espera)
        except Exception as erro:
            ultimo = erro
            if not _vale_repetir(erro):
                raise
            if avisa and n < tentativas - 1:
                avisa('  rede instável (%s) — tentativa %d de %d'
                      % (type(erro).__name__, n + 1, tentativas))
    # Esgotadas as tentativas, o erro sobe como sempre subiu: quem chama
    # continua livre para tratar ou deixar estourar.
    raise ultimo


def le(url, cabecalhos=None, espera=120, tentativas=4, limite=None,
       avisa=print):
    """Os bytes da URL, com a mesma política de repetição de `abre`."""
    with abre(url, cabecalhos, espera, tentativas, avisa=avisa) as r:
        return r.read(limite) if limite else r.read()
