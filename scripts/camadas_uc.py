#!/usr/bin/env python3
"""
Unidades de conservação para a aba Mapas, uma camada por estado.

    python scripts/camadas_uc.py                     # baixa o CNUC mais recente
    python scripts/camadas_uc.py caminho/cnuc.shp    # usa um arquivo já baixado

Por que hospedar estas, e não as outras
---------------------------------------
Quase todas as camadas da aba Mapas vêm direto do servidor de mapas do IBGE
(geoservicos.ibge.gov.br), que aceita pedidos do navegador e recorta pela área
do município na hora. As unidades de conservação não estão lá: o cadastro
oficial é o CNUC, do Ministério do Meio Ambiente, publicado como shapefile em
dados.mma.gov.br, sem serviço de mapa. Então o painel guarda uma cópia.

O que é feito
-------------
1. Lê o shapefile do CNUC (o .dbf vem com UTF-8 gravado como latin1, e é
   desfeito aqui).
2. Fica só com as unidades de situação "Ativo".
3. Simplifica as linhas a 0,0004° (uns 40 m), que some na escala de um mapa
   municipal e corta o tamanho do arquivo em mais de 70%.
4. Divide por estado pela interseção com o limite estadual, para a página
   baixar só o arquivo do estado do município aberto. Unidade que atravessa
   divisa entra nos dois estados.

Saída: dados/camadas/uc/{UF}.json (GeoJSON) e dados/camadas/uc/fonte.json.
"""
import io, json, os, re, sys, tempfile, urllib.request, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rede                                    # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAIDA = os.path.join(RAIZ, 'dados', 'camadas', 'uc')
CKAN = 'https://dados.mma.gov.br/api/3/action/package_show?id=unidadesdeconservacao'
UFS_API = ('https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR'
           '?intrarregiao=UF&formato=application/vnd.geo%2Bjson&qualidade=intermediaria')
SIMPLIFICA = 0.0004
MINUSCULAS = {'de', 'da', 'do', 'das', 'dos', 'e', 'a', 'o', 'em', 'na', 'no', 'nas', 'nos'}
ROMANOS = re.compile(r'^(i{1,3}|iv|v|vi{0,3}|ix|x{1,3})$', re.I)


def conserta(t):
    """O .dbf traz UTF-8 lido como latin1: 'Ã\\x81REA' em vez de 'ÁREA'."""
    if not isinstance(t, str):
        return t
    try:
        return t.encode('latin1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return t


def titulo(t):
    if not isinstance(t, str):
        return t
    out = []
    for k, p in enumerate(t.lower().split()):
        if ROMANOS.match(p):
            out.append(p.upper())
        elif k and p in MINUSCULAS:
            out.append(p)
        else:
            out.append(p[:1].upper() + p[1:])
    return ' '.join(out)


def ultimo_cnuc():
    """O zip mais novo do CNUC que esteja no próprio dados.mma.gov.br.

    Desde 2026 alguns cortes saem só por um link de SharePoint, que pede
    navegador; esses ficam de fora e o script avisa qual foi pulado."""
    pacote = json.loads(rede.le(CKAN).decode('utf-8'))['result']
    zips = []
    for r in pacote['resources']:
        nome, url = r.get('name') or '', r.get('url') or ''
        if 'zip' not in (r.get('format') or '').lower():
            continue
        data = r.get('last_modified') or r.get('created') or ''
        if 'dados.mma.gov.br' not in url:
            print('  pulado (fora do dados.mma.gov.br): %s' % nome)
            continue
        zips.append((data, nome, url))
    if not zips:
        raise SystemExit('Nenhum shapefile do CNUC baixável em %s' % CKAN)
    zips.sort()
    return zips[-1]


def main():
    import geopandas as gpd

    if len(sys.argv) > 1:
        shp, rotulo = sys.argv[1], os.path.basename(sys.argv[1])
        dados = gpd.read_file(shp, encoding='latin1')
    else:
        data, rotulo, url = ultimo_cnuc()
        print('Baixando %s (%s)' % (rotulo, data[:10]))
        bruto = rede.le(url, espera=600)
        with tempfile.TemporaryDirectory() as tmp:
            zipfile.ZipFile(io.BytesIO(bruto)).extractall(tmp)
            shps = [os.path.join(d, f) for d, _, fs in os.walk(tmp) for f in fs
                    if f.endswith('.shp') and 'ponto' not in f.lower()]
            dados = gpd.read_file(shps[0], encoding='latin1')

    for c in ('nome_uc', 'categoria', 'grupo', 'esfera', 'situacao'):
        dados[c] = dados[c].map(conserta)
    dados = dados[dados['situacao'] == 'Ativo'].copy()
    dados['nome'] = dados['nome_uc'].map(titulo)
    dados['ano'] = dados['cria_ano'].astype(str).str[-4:]
    dados = dados[['nome', 'categoria', 'grupo', 'esfera', 'ano', 'geometry']]
    dados = dados.to_crs(4674)
    dados['geometry'] = dados.geometry.simplify(SIMPLIFICA, preserve_topology=True)
    dados = dados[~dados.geometry.is_empty]
    print('  %d unidades ativas' % len(dados))

    ufs = gpd.read_file(io.BytesIO(rede.le(UFS_API))).to_crs(4674)
    estados = json.loads(rede.le(
        'https://servicodados.ibge.gov.br/api/v1/localidades/estados').decode('utf-8'))
    siglas = {str(e['id']): e['sigla'] for e in estados}
    ufs['sigla'] = ufs['codarea'].astype(str).map(siglas)

    junto = gpd.sjoin(dados, ufs[['sigla', 'geometry']], predicate='intersects')
    os.makedirs(SAIDA, exist_ok=True)
    for sigla, grupo in junto.groupby('sigla'):
        g = grupo.drop(columns=['index_right', 'sigla'])
        caminho = os.path.join(SAIDA, '%s.json' % sigla)
        g.to_file(caminho, driver='GeoJSON', COORDINATE_PRECISION=5)
        print('  %s %4d unidades %6.0f KB' % (sigla, len(g), os.path.getsize(caminho) / 1024))

    with open(os.path.join(SAIDA, 'fonte.json'), 'w', encoding='utf-8') as f:
        json.dump({'fonte': 'MMA — Cadastro Nacional de Unidades de Conservação (CNUC)',
                   'arquivo': rotulo, 'situacao': 'Ativo',
                   'simplificacao_graus': SIMPLIFICA}, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
