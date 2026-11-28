/* Painel Socioambiental — aba Mapas.
 *
 * Carregado só quando a aba abre (junto com vendor/maplibre-gl.js). Expõe
 * window.PainelMapas = { abrir(ctx), fechar() }.
 *
 * De onde vem cada camada
 * -----------------------
 * Quase tudo sai do servidor de mapas do IBGE (geoservicos.ibge.gov.br), que
 * responde a pedidos do navegador: o painel pede só o retângulo do município
 * e desenha aqui mesmo, com cores próprias e uma legenda que lista apenas as
 * classes que de fato aparecem dentro do limite municipal, com a parcela da
 * área de cada uma. As unidades de conservação são a exceção: o CNUC, do MMA,
 * não tem serviço de mapa, então o painel guarda uma cópia por estado em
 * dados/camadas/uc/ (ver scripts/camadas_uc.py).
 *
 * A folha na tela é a mesma que sai na imagem: título, quadro com
 * coordenadas, norte, escala, legenda e fontes. "Baixar imagem" redesenha
 * tudo num canvas, em dobro da resolução da tela.
 */
(function(){
'use strict';

const WFS='https://geoservicos.ibge.gov.br/geoserver/wfs';
const WMS='https://geoservicos.ibge.gov.br/geoserver/wms';
const MAXF=15000;
const AGUA='#A9D3F2', AGUA_L='#3C84C5';
const F_BC250='IBGE — Base Cartográfica Contínua do Brasil 1:250.000 (BC250), 2025';
const F_BDIA='IBGE — Banco de Dados de Informações Ambientais (BDiA), 1:250.000';
const MARGEM=22;                 // faixa das coordenadas em volta do mapa
const FONTE_UI='Archivo, system-ui, sans-serif';

/* ============================ cores ============================ */
function hsl2hex(h,s,l){
  s/=100; l/=100;
  const k=n=>(n+h/30)%12, a=s*Math.min(l,1-l);
  const f=n=>l-a*Math.max(-1,Math.min(k(n)-3,Math.min(9-k(n),1)));
  return '#'+[f(0),f(8),f(4)].map(x=>Math.round(x*255).toString(16).padStart(2,'0')).join('');
}
function hash(s){
  let h=2166136261>>>0;
  for(const c of String(s)){ h^=c.codePointAt(0); h=Math.imul(h,16777619)>>>0; }
  return h;
}
// Uma família de cor por grupo, e cada classe do grupo num tom vizinho: dá
// para ver que dois arenitos são parentes e ainda assim separá-los.
function varia(base,chave,amp){
  const [h,s,l]=base, x=hash(chave), a=amp||1;
  const dh=((x%23)-11)*a, dl=(((x>>>7)%19)-9)*a;
  return hsl2hex((h+dh+360)%360, s, Math.max(22,Math.min(88,l+dl)));
}
const ehAgua = t => /corpo d.?água|massa d.?água/i.test(String(t||''));

/* ======================= classes por camada ======================= */
const ERAS=[
  ['Quaternário',[54,100,79]],['Neógeno',[46,95,68]],['Paleógeno',[32,90,66]],
  ['Cretáceo',[100,45,60]],['Jurássico',[190,55,56]],['Triássico',[285,35,60]],
  ['Permiano',[8,60,63]],['Carbonífero',[170,35,52]],['Devoniano',[30,50,56]],
  ['Siluriano',[155,40,64]],['Ordoviciano',[165,50,42]],['Cambriano',[95,30,55]],
  ['Cenozoic',[50,90,72]],['Mesozoic',[105,40,58]],['Paleozoic',[175,35,52]],
  ['Neoproterozoic',[40,92,62]],['Mesoproterozoic',[24,88,70]],
  ['Paleoproterozoic',[345,78,70]],['Arqueano',[322,72,60]],['Proterozoic',[30,80,66]]
];
function corGeologia(p){
  if(ehAgua(p.nm_tempo_g)||ehAgua(p.nm_unidade)) return AGUA;
  const t=String(p.nm_tempo_g||'');
  const e=ERAS.find(([k])=>t.includes(k));
  return varia(e?e[1]:[0,0,70], p.letra_simb||p.nm_unidade, 1);
}
const FAMILIA_VEG=[
  ['Ombrófila Densa',[130,45,32]],['Ombrófila Aberta',[118,40,40]],['Ombrófila Mista',[150,38,34]],
  ['Estacional Semidecidual',[100,40,42]],['Estacional Decidual',[78,42,48]],
  ['Estacional Sempre-Verde',[112,40,36]],['Campinarana',[70,30,56]],['Savana-Estépica',[34,50,60]],
  ['Savana',[56,52,58]],['Estepe',[45,45,66]],['Pioneira',[178,35,52]],['Refúgio',[205,20,62]],
  ['Contato',[78,28,54]]
];
function corVegetacao(p){
  const l2=String(p.legenda_2||p.legenda||'');
  if(ehAgua(p.leg_sup)||ehAgua(p.legenda_1)) return AGUA;
  if(/antr[óo]pica/i.test(p.leg_sup||'')||p.nm_uantr){
    if(/urban/i.test(l2)) return '#E07A6F';
    if(/secund/i.test(l2)) return '#B9DB9E';
    if(/reflorest|silvic/i.test(l2)) return '#6E9F58';
    if(/pecu|pastag/i.test(l2)) return '#F4E6B0';
    if(/agricult/i.test(l2)) return '#F4E27C';
    if(/agropec/i.test(l2)) return '#E0B455';
    if(/miner/i.test(l2)) return '#A3A3A3';
    return '#E6D3B3';
  }
  const f=FAMILIA_VEG.find(([k])=>String(p.legenda_1||l2).includes(k));
  return varia(f?f[1]:[90,25,55], l2, .8);
}
const ORDENS_SOLO={LATOSSOLO:[14,62,56],ARGISSOLO:[26,55,64],CAMBISSOLO:[40,48,62],
  NEOSSOLO:[50,55,76],NITOSSOLO:[4,48,42],GLEISSOLO:[200,30,62],PLINTOSSOLO:[285,25,66],
  ESPODOSSOLO:[0,0,72],PLANOSSOLO:[160,25,62],CHERNOSSOLO:[30,35,38],VERTISSOLO:[260,25,52],
  LUVISSOLO:[85,40,58],ORGANOSSOLO:[0,0,32]};
function corSolo(p){
  const lg=String(p.legenda||'');
  if(ehAgua(lg)) return AGUA;
  if(/urbana/i.test(lg)) return '#D5D5D5';
  if(/aflorament/i.test(lg)) return '#B3B3B3';
  const b=ORDENS_SOLO[String(p.ordem||p.leg_ordem||'').toUpperCase()];
  return varia(b||[35,20,60], p.legenda_2||lg, .9);
}
const NATUREZA_GMF={dissecação:[25,38,60],acumulação:[72,45,74],aplanamento:[42,50,78],
  dissolução:[280,25,66]};
function corGeomorf(p){
  if(ehAgua(p.nm_unidade)||ehAgua(p.nm_dominio)) return AGUA;
  const b=NATUREZA_GMF[String(p.natureza||'').toLowerCase()]||[200,10,70];
  return varia(b, p.nm_unidade, 1.4);
}
const USO=[
  ['#FF0000','Área artificial'],['#EBE628','Área agrícola'],['#CD8900','Pastagem com manejo'],
  ['#D4E885','Mosaico de ocupações em área florestal'],['#009059','Silvicultura'],
  ['#73A800','Vegetação florestal'],['#BEB9F5','Área úmida'],['#CEB464','Vegetação campestre'],
  ['#D79964','Mosaico de ocupações em área campestre'],['#8CFFFF','Corpo d’água continental'],
  ['#2D98DA','Corpo d’água costeiro'],['#888888','Área descoberta']
].map(([c,n])=>({cor:c,rotulo:n,rgb:[1,3,5].map(k=>parseInt(c.slice(k,k+2),16))}));

const UC_COR={'Proteção Integral':['#2E7D32','#1B5E20'],'Uso Sustentável':['#9CCC65','#558B2F']};

/* =========================== camadas ===========================
 * tipo: 'area' (polígonos que dividem o território: sai % por classe),
 *       'sobre' (polígonos que se sobrepõem: sai a lista de áreas),
 *       'linha', 'ponto', 'wms'.                                   */
const CAMADAS=[
  {id:'viz',grupo:'Referência',nome:'Municípios vizinhos',tipo:'ref',fonte:F_BC250,
   amostra:['linha','#8C98A4']},
  {id:'sede',grupo:'Referência',nome:'Sedes municipais',tipo:'ponto',fonte:F_BC250,
   wfs:'CCAR:BC250_2025_lml_cidade_p',amostra:['ponto','#1A1A1A']},
  {id:'rod',grupo:'Referência',nome:'Rodovias',tipo:'linha',fonte:F_BC250,
   wfs:'CCAR:BC250_2025_rod_trecho_rodoviario_l',amostra:['linha','#C0392B'],
   classe:p=>{ const j=String(p.jurisdicao||'');
     return /federal/i.test(j)?{k:'f',rotulo:'Rodovia federal',cor:'#C0392B',w:2.2}
          : /estadual/i.test(j)?{k:'e',rotulo:'Rodovia estadual',cor:'#E08A1E',w:1.7}
          : {k:'m',rotulo:'Outras rodovias',cor:'#8A8F94',w:1.1}; }},
  {id:'fer',grupo:'Referência',nome:'Ferrovias',tipo:'linha',fonte:F_BC250,
   wfs:'CCAR:BC250_2025_fer_trecho_ferroviario_l',amostra:['linha','#2B2B2B'],
   classe:()=>({k:'fer',rotulo:'Ferrovia',cor:'#2B2B2B',w:1.4})},
  {id:'hid',grupo:'Água',nome:'Cursos d’água',tipo:'linha',fonte:F_BC250,
   wfs:'CCAR:BC250_2025_hid_trecho_drenagem_l',amostra:['linha',AGUA_L],
   classe:p=>/intermit|temporár/i.test(p.regime||'')
     ?{k:'int',rotulo:'Curso d’água intermitente',cor:AGUA_L,w:.9,tracejado:true}
     :{k:'per',rotulo:'Curso d’água permanente',cor:AGUA_L,w:1.1}},
  {id:'mda',grupo:'Água',nome:'Massas d’água',tipo:'area',fonte:F_BC250,
   wfs:'CCAR:BC250_2025_hid_massa_dagua_a',amostra:['area',AGUA],
   classe:p=>({k:p.tipomassadagua||'Massa d’água',rotulo:p.tipomassadagua||'Massa d’água',cor:AGUA})},
  {id:'uc',grupo:'Áreas protegidas e territórios',nome:'Unidades de conservação',tipo:'sobre',
   fonte:'MMA — Cadastro Nacional de Unidades de Conservação (CNUC), ago. 2025',
   local:'dados/camadas/uc/{UF}.json',amostra:['area','#7CB342'],
   classe:p=>{ const g=UC_COR[p.grupo]?p.grupo:'Uso Sustentável';
     return {k:g,rotulo:g,cor:UC_COR[g][0],borda:UC_COR[g][1],tracejado:g==='Uso Sustentável'}; },
   nomeDe:p=>p.nome+(p.esfera?' ('+p.esfera.toLowerCase()+')':'')},
  {id:'ti',grupo:'Áreas protegidas e territórios',nome:'Terras indígenas',tipo:'sobre',
   fonte:'IBGE — Terras indígenas da base territorial do Censo 2022 (fonte original: FUNAI)',
   wfs:'CGMAT:qg_2022_610_terraindigena__v02',amostra:['area','#C98B4F'],
   classe:()=>({k:'ti',rotulo:'Terra indígena',cor:'#D9A46C',borda:'#8D5524'}),
   nomeDe:p=>(p.nm_ti||p.nm_funai)+(p.fase?' — '+String(p.fase).toLowerCase():'')},
  {id:'tq',grupo:'Áreas protegidas e territórios',nome:'Territórios quilombolas',tipo:'sobre',
   fonte:'IBGE — Territórios quilombolas da base territorial do Censo 2022 (fontes originais: INCRA e órgãos estaduais)',
   wfs:'CGMAT:qg_2022_620_territorioquilombola__v02',amostra:['area','#9A7FD1'],
   classe:()=>({k:'tq',rotulo:'Território quilombola',cor:'#B39DDB',borda:'#5E35B1'}),
   nomeDe:p=>p.nm_tq},
  {id:'uso',grupo:'Meio físico e biótico',nome:'Cobertura e uso da terra',tipo:'wms',
   fonte:'IBGE — Monitoramento da Cobertura e Uso da Terra, 2020 (grade de 1 km)',
   wms:'CREN:Cobertura_uso_terra_2020_Brasil_serie_revisada',amostra:['area','#CD8900']},
  {id:'veg',grupo:'Meio físico e biótico',nome:'Vegetação',tipo:'area',fonte:F_BDIA,
   wfs:'BDIA:vege_area',amostra:['area','#7FA35B'],
   classe:p=>{ const r=ehAgua(p.leg_sup)?'Corpo d’água':(p.legenda_2||p.legenda||'—');
     return {k:r,rotulo:r,cor:corVegetacao(p)}; }},
  {id:'geo',grupo:'Meio físico e biótico',nome:'Geologia (litologia)',tipo:'area',fonte:F_BDIA,
   wfs:'BDIA:geol_area',amostra:['area','#F3A4B8'],
   classe:p=>{ if(ehAgua(p.nm_tempo_g)||ehAgua(p.nm_unidade))
       return {k:'agua',rotulo:'Corpo d’água',cor:AGUA};
     const k=p.letra_simb||p.nm_unidade;
     return {k,rotulo:(p.letra_simb?p.letra_simb+' — ':'')+(p.nm_unidade||''),cor:corGeologia(p)}; }},
  {id:'sol',grupo:'Meio físico e biótico',nome:'Solos',tipo:'area',fonte:F_BDIA,
   wfs:'BDIA:pedo_area',amostra:['area','#D98B5F'],
   classe:p=>{ const r=ehAgua(p.legenda)?'Corpo d’água':(p.legenda||'—');
     return {k:r,rotulo:r,cor:corSolo(p)}; }},
  {id:'gmf',grupo:'Meio físico e biótico',nome:'Geomorfologia',tipo:'area',fonte:F_BDIA,
   wfs:'BDIA:geom_area',amostra:['area','#C9A27E'],
   classe:p=>{ const r=ehAgua(p.nm_unidade)?'Corpo d’água':(p.nm_unidade||'—');
     return {k:r,rotulo:r,cor:corGeomorf(p)}; }},
];
const CAM=Object.fromEntries(CAMADAS.map(c=>[c.id,c]));
// ordem de desenho, de baixo para cima
const ORDEM=['uso','geo','sol','gmf','veg','mda','uc','ti','tq','hid','fer','rod','sede'];

const PRESETS=[
  {id:'loc',nome:'Localização',cam:['viz','sede','rod','fer','mda'],fundo:'claro',fora:'mostrar',
   els:['loc']},
  {id:'uso',nome:'Uso e cobertura',cam:['viz','uso','sede'],fundo:'nenhum',fora:'ocultar'},
  {id:'veg',nome:'Vegetação',cam:['viz','veg','sede'],fundo:'nenhum',fora:'ocultar'},
  {id:'hid',nome:'Hidrografia',cam:['viz','hid','mda','sede'],fundo:'relevo',fora:'esmaecer'},
  {id:'ap',nome:'Áreas protegidas',cam:['viz','uc','sede'],fundo:'claro',fora:'esmaecer'},
  {id:'ct',nome:'Comunidades tradicionais',cam:['viz','ti','tq','sede'],fundo:'claro',fora:'esmaecer'},
  {id:'geo',nome:'Geologia',cam:['viz','geo','sede'],fundo:'nenhum',fora:'ocultar'},
  {id:'sol',nome:'Solos',cam:['viz','sol','sede'],fundo:'nenhum',fora:'ocultar'},
  {id:'gmf',nome:'Geomorfologia',cam:['viz','gmf','sede'],fundo:'nenhum',fora:'ocultar'},
];
const TITULOS={loc:'Mapa de localização',uso:'Cobertura e uso da terra',veg:'Vegetação',
  hid:'Hidrografia',ap:'Unidades de conservação',ct:'Terras indígenas e territórios quilombolas',
  geo:'Geologia',sol:'Solos',gmf:'Geomorfologia'};

const FUNDOS={
  claro:{nome:'Claro',url:'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    attr:'Mapa de fundo: Esri, HERE, Garmin, © OpenStreetMap'},
  ruas:{nome:'Ruas',url:'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attr:'Mapa de fundo: © colaboradores do OpenStreetMap'},
  sat:{nome:'Satélite',url:'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attr:'Imagem de fundo: Esri, Maxar, Earthstar Geographics'},
  relevo:{nome:'Relevo',url:'https://server.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}',
    attr:'Relevo sombreado: Esri, USGS, NASA'},
  nenhum:{nome:'Nenhum'}
};
const FORA={mostrar:['Mostrar',0],esmaecer:['Esmaecer',.62],ocultar:['Ocultar',1]};
const ELEMENTOS=[['tit','Título'],['leg','Legenda'],['nor','Norte'],['esc','Escala'],
  ['coo','Coordenadas'],['gra','Grade'],['rot','Rótulos'],['loc','Localização'],['fon','Fontes']];
const ELS_PADRAO=['tit','leg','nor','esc','coo','rot','fon'];

/* ============================ estado ============================ */
let pronto=false;
let ctx=null, mapa=null, el=null, est=null, munGeo=null, grade=null, bbMun=null, bbPed=null, bbTema=null;
let dados={}, status={}, legendas={}, rotulos=[], pedidos=0, tituloLivre=false, alimentados=new Set();
const cache=new Map();        // chave cod|camada -> dados processados

function estadoPadrao(p){
  const pr=PRESETS.find(x=>x.id===p)||PRESETS[0];
  return {p:pr.id,c:new Set(pr.cam),f:pr.fundo,o:pr.fora,
          e:new Set([...ELS_PADRAO,...(pr.els||[])]),t:''};
}
function serializa(){
  return [est.p,[...est.c].join('.'),est.f,est.o,[...est.e].join('.'),
          tituloLivre?est.t:''].join('~');
}
function desserializa(s){
  if(!s) return estadoPadrao('loc');
  const [p,c,f,o,e,t]=String(s).split('~');
  const base=estadoPadrao(p);
  if(c!==undefined) base.c=new Set(c.split('.').filter(x=>CAM[x]));
  if(FUNDOS[f]) base.f=f;
  if(FORA[o]) base.o=o;
  if(e!==undefined) base.e=new Set(e.split('.').filter(x=>ELEMENTOS.some(([k])=>k===x)));
  if(t){ base.t=t; tituloLivre=true; } else tituloLivre=false;
  return base;
}
const aviso=()=>ctx&&ctx.aoMudar&&ctx.aoMudar(serializa());
const tem=k=>est.e.has(k);
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

/* ======================== geometria simples ======================== */
function bboxDe(geom){
  let w=180,s=90,e=-180,n=-90;
  const v=c=>{ if(c[0]<w)w=c[0]; if(c[0]>e)e=c[0]; if(c[1]<s)s=c[1]; if(c[1]>n)n=c[1]; };
  andaCoords(geom,v);
  return [w,s,e,n];
}
function andaCoords(g,fn){
  if(!g) return;
  const t=g.type, c=g.coordinates;
  if(t==='Point') fn(c);
  else if(t==='MultiPoint'||t==='LineString') c.forEach(fn);
  else if(t==='MultiLineString'||t==='Polygon') c.forEach(r=>r.forEach(fn));
  else if(t==='MultiPolygon') c.forEach(p=>p.forEach(r=>r.forEach(fn)));
  else if(t==='GeometryCollection') g.geometries.forEach(x=>andaCoords(x,fn));
}
function poligonos(g){
  if(!g) return [];
  if(g.type==='Polygon') return [g.coordinates];
  if(g.type==='MultiPolygon') return g.coordinates;
  return [];
}
function linhas(g){
  if(!g) return [];
  if(g.type==='LineString') return [g.coordinates];
  if(g.type==='MultiLineString') return g.coordinates;
  return [];
}
function noAnel(pt,anel){
  let d=false;
  for(let i=0,j=anel.length-1;i<anel.length;j=i++){
    const a=anel[i],b=anel[j];
    if(((a[1]>pt[1])!==(b[1]>pt[1]))&&(pt[0]<(b[0]-a[0])*(pt[1]-a[1])/(b[1]-a[1])+a[0])) d=!d;
  }
  return d;
}
function noPoligono(pt,polys){
  for(const p of polys){
    if(!noAnel(pt,p[0])) continue;
    let buraco=false;
    for(let k=1;k<p.length;k++) if(noAnel(pt,p[k])){ buraco=true; break; }
    if(!buraco) return true;
  }
  return false;
}
const cruza=(a,b)=>a[0]<=b[2]&&a[2]>=b[0]&&a[1]<=b[3]&&a[3]>=b[1];

/* Grade: o município rasterizado num canvas de até 600 px. Serve para dizer
 * se um ponto está dentro (consulta de um pixel) e para medir a parcela da
 * área de cada classe sem biblioteca de geometria. Lat/lon é linear dentro
 * da grade, com a largura corrigida pelo cosseno da latitude média. */
function criaGrade(bb,polys){
  const lat0=(bb[1]+bb[3])/2, kx=Math.cos(lat0*Math.PI/180);
  const sw=(bb[2]-bb[0])*kx, sh=bb[3]-bb[1], R=600/Math.max(sw,sh);
  const W=Math.max(16,Math.round(sw*R)), H=Math.max(16,Math.round(sh*R));
  const g={W,H,bb,px:lon=>(lon-bb[0])/(bb[2]-bb[0])*W,py:lat=>(bb[3]-lat)/(bb[3]-bb[1])*H};
  const cv=document.createElement('canvas'); cv.width=W; cv.height=H;
  const c=cv.getContext('2d',{willReadFrequently:true});
  g.cv=cv; g.c=c;
  c.fillStyle='#fff'; desenhaPolys(c,polys,g); c.fill('evenodd');
  const px=c.getImageData(0,0,W,H).data;
  g.mask=new Uint8Array(W*H); let n=0;
  for(let i=0;i<W*H;i++){ if(px[i*4+3]>127){ g.mask[i]=1; n++; } }
  g.n=n;
  g.dentro=(lon,lat)=>{ const x=Math.floor(g.px(lon)), y=Math.floor(g.py(lat));
    return x>=0&&y>=0&&x<W&&y<H&&g.mask[y*W+x]===1; };
  // pontos de amostra dentro do município, para o teste ao contrário
  // (polígono enorme que cobre o município sem ter vértice nenhum dentro)
  g.amostras=[];
  for(let j=1;j<6;j++) for(let i=1;i<6;i++){
    const x=Math.floor(W*i/6), y=Math.floor(H*j/6);
    if(g.mask[y*W+x]) g.amostras.push([bb[0]+(x+.5)/W*(bb[2]-bb[0]), bb[3]-(y+.5)/H*(bb[3]-bb[1])]);
  }
  return g;
}
function desenhaPolys(c,polys,g){
  c.beginPath();
  for(const p of polys) for(const r of p){
    r.forEach((pt,i)=>{ const x=g.px(pt[0]), y=g.py(pt[1]);
      if(i) c.lineTo(x,y); else c.moveTo(x,y); });
    c.closePath();
  }
}
// pixels de dentro do município cobertos pelo que estiver desenhado no canvas
function contaCobertos(){
  const d=grade.c.getImageData(0,0,grade.W,grade.H).data; let n=0;
  for(let i=0;i<grade.W*grade.H;i++) if(grade.mask[i]&&d[i*4+3]>127) n++;
  return n;
}
function tocaMunicipio(f){
  const g=f.geometry; if(!g) return false;
  const bb=f._bb||(f._bb=bboxDe(g));
  if(!cruza(bb,bbMun)) return false;
  let achou=false, k=0;
  const passo=Math.max(1,Math.floor(contaVertices(g)/400));
  andaCoords(g,c=>{ if(achou) return; if((k++%passo)===0&&grade.dentro(c[0],c[1])) achou=true; });
  if(achou) return true;
  const polys=poligonos(g);
  return polys.length>0 && grade.amostras.some(a=>noPoligono(a,polys));
}
function contaVertices(g){ let n=0; andaCoords(g,()=>n++); return n; }

/* =========================== rede ============================ */
async function pegaJSON(url){
  const r=await fetch(url,{mode:'cors'});
  if(!r.ok) throw new Error('HTTP '+r.status);
  return r.json();
}
const bbTexto=b=>b.map(x=>x.toFixed(5)).join(',');
async function wfs(tipo,bb,filtro){
  // Retângulo grande vai em quatro pedaços paralelos: o servidor do IBGE
  // corta em 60 s, e um pedido único de um município amazônico passa disso.
  const area=(bb[2]-bb[0])*(bb[3]-bb[1]);
  if(area>6){
    const mx=(bb[0]+bb[2])/2, my=(bb[1]+bb[3])/2;
    const partes=await Promise.all([[bb[0],bb[1],mx,my],[mx,bb[1],bb[2],my],
      [bb[0],my,mx,bb[3]],[mx,my,bb[2],bb[3]]].map(b=>wfs1(tipo,b,filtro)));
    const vistos=new Set(), out=[];
    for(const fs of partes) for(const f of fs){ const k=f.id||JSON.stringify(f.properties);
      if(!vistos.has(k)){ vistos.add(k); out.push(f); } }
    out.parcial=partes.some(p=>p.length>=MAXF);
    return out;
  }
  const fs=await wfs1(tipo,bb,filtro); fs.parcial=fs.length>=MAXF; return fs;
}
async function wfs1(tipo,bb,filtro){
  // Com filtro, o recorte vai dentro da CQL: o GeoServer não aceita bbox e
  // CQL_FILTER no mesmo pedido.
  const u=WFS+'?service=WFS&version=1.0.0&request=GetFeature&outputFormat=application/json'+
    '&srsName=EPSG:4326&maxFeatures='+MAXF+'&typeName='+encodeURIComponent(tipo)+
    (filtro?'&CQL_FILTER='+encodeURIComponent('BBOX(geom,'+bbTexto(bb)+') AND '+filtro)
           :'&bbox='+bbTexto(bb));
  let erro;
  for(let k=0;k<2;k++){
    try{ const j=await pegaJSON(u); return j.features||[]; }
    catch(e){ erro=e; await new Promise(r=>setTimeout(r,1500)); }
  }
  throw erro;
}

/* ===================== carga e processamento ===================== */
async function carregaBase(){
  // O limite e os vizinhos vêm da BC250, que traz nome e geocódigo. Se o
  // município não estiver lá (criado depois da edição), fica a malha do painel.
  bbMun=ctx.bbox;
  const dx=(bbMun[2]-bbMun[0]), dy=(bbMun[3]-bbMun[1]), pad=Math.max(dx,dy)*.45;
  bbPed=[bbMun[0]-pad,bbMun[1]-pad,bbMun[2]+pad,bbMun[3]+pad];
  let feats=[];
  try{ feats=await wfs('CCAR:BC250_2025_lml_municipio_a',bbPed); }
  catch(e){ console.warn('BC250 municípios:',e); }
  const alvo=feats.find(f=>String(f.properties.geocodigo)===String(ctx.cod));
  munGeo = alvo ? alvo.geometry : ctx.feature.geometry;
  bbMun=bboxDe(munGeo);
  grade=criaGrade(bbMun,poligonos(munGeo));
  // Camadas de referência vêm com folga em volta (para dar contexto); as
  // temáticas, só com uma margem curta: o que interessa é dentro do limite, e
  // num município grande a folga multiplicaria o volume baixado.
  const m=Math.max(bbMun[2]-bbMun[0],bbMun[3]-bbMun[1])*.08;
  bbTema=[bbMun[0]-m,bbMun[1]-m,bbMun[2]+m,bbMun[3]+m];
  dados.viz=feats.filter(f=>f!==alvo&&String(f.properties.geocodigo)!==String(ctx.cod));
  status.viz={n:dados.viz.length};
}

async function carrega(id){
  const cam=CAM[id];
  if(!cam||cam.tipo==='ref'||dados[id]!==undefined||status[id]&&status[id].carregando) return;
  const chave=ctx.cod+'|'+id;
  if(cache.has(chave)){ dados[id]=cache.get(chave); processa(id); return; }
  status[id]={carregando:true}; desenhaPainelCamadas(); mostraCarregando(+1);
  try{
    let feats;
    if(cam.tipo==='wms'){ feats=await medeUso(); }
    else if(cam.local){
      const j=await pegaJSON(cam.local.replace('{UF}',ctx.sigla));
      feats=(j.features||[]).filter(f=>cruza(f._bb=bboxDe(f.geometry),bbPed));
    }else if(id==='hid'&&(bbTema[2]-bbTema[0])*(bbTema[3]-bbTema[1])>1.2){
      // Município grande: a drenagem inteira passa de 15 mil trechos e vira
      // um borrão azul na escala do mapa. Ficam só os cursos com nome — e,
      // nos gigantes da Amazônia, só os que a BC250 chama de rio.
      const gigante=(bbTema[2]-bbTema[0])*(bbTema[3]-bbTema[1])>8;
      feats=await wfs(cam.wfs,bbTema,gigante?"strStartsWith(nome,'Rio ') = true":"nome <> ''");
      feats.soNomeados=gigante?'rios':'nomeados';
    }else feats=await wfs(cam.wfs,['sede','rod','fer'].includes(id)?bbPed:bbTema);
    dados[id]=feats; cache.set(chave,feats);
    status[id]={nomeados:feats.soNomeados||''};
    if(feats.parcial) status[id].parcial=true;
    processa(id);
  }catch(e){
    console.error(id,e);
    status[id]={erro:true};
  }finally{
    mostraCarregando(-1);
    desenhaPainelCamadas();
  }
}

function processa(id){
  const cam=CAM[id], fs=dados[id];
  if(cam.tipo==='wms'){ legendas[id]=fs; status[id].n=fs.itens.length; atualizaFonte(id); return; }
  for(const f of fs){
    const c=cam.classe?cam.classe(f.properties||{}):{k:'x',rotulo:cam.nome,cor:'#333'};
    f.properties._k=c.k; f.properties._c=c.cor; f.properties._b=c.borda||c.cor;
    f.properties._w=c.w||1; f.properties._r=c.rotulo; f._cl=c;
    f._dentro=tocaMunicipio(f);
  }
  const dentro=fs.filter(f=>f._dentro);
  status[id].n=dentro.length;
  if(cam.tipo==='area') legendas[id]=legendaArea(fs.filter(f=>f._dentro));
  else if(cam.tipo==='sobre') legendas[id]=legendaSobre(cam,dentro);
  else if(cam.tipo==='linha') legendas[id]=legendaLinha(dentro);
  else if(cam.tipo==='ponto') legendas[id]={itens:dentro.length?[{tipo:'ponto',cor:'#1A1A1A',rotulo:'Sede municipal'}]:[]};
  atualizaFonte(id);
}

// Parcela da área: cada classe pintada sozinha no canvas da grade.
function legendaArea(fs){
  const por=new Map();
  for(const f of fs){ const k=f._cl.k; if(!por.has(k)) por.set(k,{c:f._cl,fs:[]}); por.get(k).fs.push(f); }
  const itens=[];
  for(const [,{c,fs:lista}] of por){
    grade.c.clearRect(0,0,grade.W,grade.H); grade.c.fillStyle='#000';
    desenhaPolys(grade.c,lista.flatMap(f=>poligonos(f.geometry)),grade); grade.c.fill('evenodd');
    const n=contaCobertos();
    itens.push({tipo:'area',cor:c.cor,rotulo:c.rotulo,pct:n/grade.n});
  }
  itens.sort((a,b)=>b.pct-a.pct);
  return {itens,pct:true};
}
function legendaSobre(cam,fs){
  const grupos=new Map(), lista=[];
  for(const f of fs){
    const c=f._cl; if(!grupos.has(c.k)) grupos.set(c.k,{c,n:0});
    grade.c.clearRect(0,0,grade.W,grade.H); grade.c.fillStyle='#000';
    desenhaPolys(grade.c,poligonos(f.geometry),grade); grade.c.fill('evenodd');
    lista.push({k:c.k,nome:cam.nomeDe(f.properties),pct:contaCobertos()/grade.n});
  }
  grade.c.clearRect(0,0,grade.W,grade.H); grade.c.fillStyle='#000';
  desenhaPolys(grade.c,fs.flatMap(f=>poligonos(f.geometry)),grade); grade.c.fill('nonzero');
  const total=fs.length?contaCobertos()/grade.n:0;
  lista.sort((a,b)=>b.pct-a.pct);
  const itens=[...grupos.values()].map(({c})=>({tipo:'area',cor:c.cor,borda:c.borda,
    tracejado:c.tracejado,rotulo:c.rotulo,lista:lista.filter(x=>x.k===c.k)}));
  return {itens,total};
}
function legendaLinha(fs){
  const vistos=new Map();
  for(const f of fs) if(!vistos.has(f._cl.k)) vistos.set(f._cl.k,f._cl);
  const ordem=['f','e','m','per','int','fer'];
  return {itens:[...vistos.values()].sort((a,b)=>ordem.indexOf(a.k)-ordem.indexOf(b.k))
    .map(c=>({tipo:'linha',cor:c.cor,w:c.w,tracejado:c.tracejado,rotulo:c.rotulo}))};
}

// A cobertura do solo é imagem (grade de 1 km), não vetor: a parcela de cada
// classe sai dos pixels de uma imagem do retângulo do município, do mesmo
// tamanho da grade, comparando cada cor com as 12 da legenda do IBGE.
async function medeUso(){
  const cam=CAM.uso;
  const u=WMS+'?service=WMS&version=1.1.1&request=GetMap&styles=&format=image/png&transparent=true'+
    '&srs=EPSG:4326&layers='+encodeURIComponent(cam.wms)+'&bbox='+bbTexto(bbMun)+
    '&width='+grade.W+'&height='+grade.H;
  const r=await fetch(u,{mode:'cors'}); if(!r.ok) throw new Error('HTTP '+r.status);
  const img=await createImageBitmap(await r.blob());
  const c=document.createElement('canvas'); c.width=grade.W; c.height=grade.H;
  const cc=c.getContext('2d',{willReadFrequently:true}); cc.drawImage(img,0,0,grade.W,grade.H);
  const d=cc.getImageData(0,0,grade.W,grade.H).data, n=new Array(USO.length).fill(0);
  let tot=0;
  for(let i=0;i<grade.W*grade.H;i++){
    if(!grade.mask[i]||d[i*4+3]<200) continue;
    let melhor=-1, dm=1e9;
    for(let k=0;k<USO.length;k++){
      const q=USO[k].rgb, dd=Math.abs(q[0]-d[i*4])+Math.abs(q[1]-d[i*4+1])+Math.abs(q[2]-d[i*4+2]);
      if(dd<dm){ dm=dd; melhor=k; }
    }
    if(dm<40){ n[melhor]++; tot++; }
  }
  const itens=USO.map((u,k)=>({tipo:'area',cor:u.cor,rotulo:u.rotulo,pct:tot?n[k]/tot:0}))
    .filter(x=>x.pct>0).sort((a,b)=>b.pct-a.pct);
  return {itens,pct:true,cobertura:tot/grade.n};
}

/* ========================= mapa (MapLibre) ========================= */
function estiloBase(){
  return {version:8,sources:{},layers:[{id:'fundo-branco',type:'background',paint:{'background-color':'#fff'}}]};
}
function montaMapa(){
  mapa=new maplibregl.Map({container:el.querySelector('.mapa'),style:estiloBase(),
    bounds:[[bbMun[0],bbMun[1]],[bbMun[2],bbMun[3]]],fitBoundsOptions:{padding:28},
    preserveDrawingBuffer:true,attributionControl:false,dragRotate:false,pitchWithRotate:false,
    maxPitch:0,cooperativeGestures:false});
  mapa.touchZoomRotate.disableRotation();
  mapa.on('load',()=>{
    for(const [k,f] of Object.entries(FUNDOS)) if(f.url){
      mapa.addSource('fundo-'+k,{type:'raster',tiles:[f.url],tileSize:256,maxzoom:19});
      mapa.addLayer({id:'fundo-'+k,type:'raster',source:'fundo-'+k,layout:{visibility:'none'}});
    }
    mapa.addSource('uso',{type:'raster',tileSize:256,tiles:[WMS+'?service=WMS&version=1.1.1&request=GetMap'+
      '&layers='+encodeURIComponent(CAM.uso.wms)+'&styles=&format=image/png&transparent=true'+
      '&srs=EPSG:3857&width=256&height=256&bbox={bbox-epsg-3857}']});
    mapa.addLayer({id:'uso',type:'raster',source:'uso',layout:{visibility:'none'},paint:{'raster-opacity':.92,'raster-resampling':'nearest'}});
    const vazio={type:'FeatureCollection',features:[]};
    for(const id of ORDEM){ if(id==='uso') continue; mapa.addSource(id,{type:'geojson',data:vazio}); }
    for(const id of ['geo','sol','gmf','veg','mda']){
      mapa.addLayer({id:id+'-f',type:'fill',source:id,layout:{visibility:'none'},
        paint:{'fill-color':['get','_c'],'fill-opacity':.9}});
      mapa.addLayer({id:id+'-l',type:'line',source:id,layout:{visibility:'none'},
        paint:{'line-color':id==='mda'?AGUA_L:'#ffffff','line-width':id==='mda'?.6:.4,'line-opacity':.8}});
    }
    for(const id of ['uc','ti','tq']){
      mapa.addLayer({id:id+'-f',type:'fill',source:id,layout:{visibility:'none'},
        paint:{'fill-color':['get','_c'],'fill-opacity':.38}});
      mapa.addLayer({id:id+'-l',type:'line',source:id,layout:{visibility:'none'},
        paint:{'line-color':['get','_b'],'line-width':1.4}});
    }
    mapa.addLayer({id:'hid-per',type:'line',source:'hid',filter:['==',['get','_k'],'per'],
      layout:{visibility:'none','line-cap':'round'},paint:{'line-color':AGUA_L,'line-width':1.1}});
    mapa.addLayer({id:'hid-int',type:'line',source:'hid',filter:['==',['get','_k'],'int'],
      layout:{visibility:'none'},paint:{'line-color':AGUA_L,'line-width':.9,'line-dasharray':[3,2]}});
    mapa.addLayer({id:'fer-l',type:'line',source:'fer',layout:{visibility:'none'},
      paint:{'line-color':'#2B2B2B','line-width':1.6,'line-dasharray':[4,2]}});
    mapa.addLayer({id:'rod-c',type:'line',source:'rod',layout:{visibility:'none','line-cap':'round','line-join':'round'},
      paint:{'line-color':'#ffffff','line-width':['+',['get','_w'],1.6]}});
    mapa.addLayer({id:'rod-l',type:'line',source:'rod',layout:{visibility:'none','line-cap':'round','line-join':'round'},
      paint:{'line-color':['get','_c'],'line-width':['get','_w']}});
    // máscara de fora do município, vizinhos por cima dela, limite por cima de tudo
    mapa.addSource('mascara',{type:'geojson',data:mascara()});
    mapa.addLayer({id:'mascara',type:'fill',source:'mascara',paint:{'fill-color':'#ffffff','fill-opacity':0}});
    mapa.addSource('viz',{type:'geojson',data:{type:'FeatureCollection',features:dados.viz||[]}});
    mapa.addLayer({id:'viz-l',type:'line',source:'viz',layout:{visibility:'none'},
      paint:{'line-color':'#8C98A4','line-width':.9}});
    mapa.addSource('lim',{type:'geojson',data:{type:'Feature',properties:{},geometry:munGeo}});
    mapa.addLayer({id:'lim-h',type:'line',source:'lim',paint:{'line-color':'#ffffff','line-width':4.2,'line-opacity':.85}});
    mapa.addLayer({id:'lim-l',type:'line',source:'lim',paint:{'line-color':'#1A1A1A','line-width':2}});
    mapa.addLayer({id:'sede-p',type:'circle',source:'sede',layout:{visibility:'none'},
      paint:{'circle-radius':['case',['get','_alvo'],5,3],'circle-color':['case',['get','_alvo'],'#1A1A1A','#ffffff'],
        'circle-stroke-color':['case',['get','_alvo'],'#ffffff','#5B6670'],'circle-stroke-width':['case',['get','_alvo'],1.8,1.2]}});
    pronto=true;
    aplicaEstado(true);
  });
  mapa.on('render',agendaSobre);
  mapa.on('moveend',()=>{ calculaRotulos(); agendaSobre(); });
  mapa.on('mousemove',e=>{ const c=el.querySelector('.cursor');
    if(c) c.textContent=fmtCoord(e.lngLat.lat,'lat',true)+'  '+fmtCoord(e.lngLat.lng,'lon',true); });
  mapa.on('mouseout',()=>{ const c=el.querySelector('.cursor'); if(c) c.textContent=''; });
  mapa.on('click',clique);
}
function mascara(){
  const furos=poligonos(munGeo).map(p=>p[0].slice().reverse());
  return {type:'Feature',properties:{},geometry:{type:'Polygon',
    coordinates:[[[-180,-85],[180,-85],[180,85],[-180,85],[-180,-85]],...furos]}};
}
const CAMADAS_MAPA={uso:['uso'],geo:['geo-f','geo-l'],sol:['sol-f','sol-l'],gmf:['gmf-f','gmf-l'],
  veg:['veg-f','veg-l'],mda:['mda-f','mda-l'],uc:['uc-f','uc-l'],ti:['ti-f','ti-l'],tq:['tq-f','tq-l'],
  hid:['hid-per','hid-int'],fer:['fer-l'],rod:['rod-c','rod-l'],sede:['sede-p'],viz:['viz-l']};

function aplicaEstado(reenquadra){
  if(!mapa||!pronto) return;
  for(const k of Object.keys(FUNDOS)) if(FUNDOS[k].url)
    mapa.setLayoutProperty('fundo-'+k,'visibility',est.f===k?'visible':'none');
  mapa.setPaintProperty('mascara','fill-opacity',FORA[est.o][1]);
  mapa.setFilter('sede-p',est.o==='ocultar'?['==',['get','_alvo'],true]:null);
  for(const [id,ls] of Object.entries(CAMADAS_MAPA)){
    const on=est.c.has(id);
    ls.forEach(l=>mapa.getLayer(l)&&mapa.setLayoutProperty(l,'visibility',on?'visible':'none'));
    if(on&&!alimentados.has(id)) carrega(id).then(()=>alimenta(id));
  }
  el.querySelector('.geo-quadro').classList.toggle('sem-borda',!tem('coo'));
  mapa.resize();
  if(reenquadra) mapa.fitBounds([[bbMun[0],bbMun[1]],[bbMun[2],bbMun[3]]],{padding:28,duration:0});
  calculaRotulos(); desenhaLegenda(); desenhaTitulo(); desenhaRodape(); agendaSobre();
}
function alimenta(id){
  if(!mapa||!dados[id]||id==='viz') return;
  if(CAM[id].tipo==='wms'){ alimentados.add(id); desenhaLegenda(); desenhaPainelCamadas(); return; }
  let fs=dados[id];
  if(id==='sede') fs=fs.map(f=>{ f.properties._alvo=String(f.properties.geocodigo)===String(ctx.cod); return f; });
  const s=mapa.getSource(id); if(s){ s.setData({type:'FeatureCollection',features:fs}); alimentados.add(id); }
  calculaRotulos(); desenhaLegenda(); desenhaRodape(); agendaSobre();
}

function clique(e){
  const ids=['uc-f','ti-f','tq-f','geo-f','sol-f','gmf-f','veg-f','mda-f','hid-per','hid-int','rod-l','fer-l']
    .filter(l=>mapa.getLayer(l)&&mapa.getLayoutProperty(l,'visibility')==='visible');
  const fs=mapa.queryRenderedFeatures([[e.point.x-3,e.point.y-3],[e.point.x+3,e.point.y+3]],{layers:ids});
  const vistos=new Set(), partes=[];
  for(const f of fs){
    const cam=f.layer.id.split('-')[0]; if(vistos.has(cam)) continue; vistos.add(cam);
    const p=f.properties;
    let txt='';
    if(cam==='uc') txt=esc(p.nome)+'<br>'+esc(p.categoria)+' · '+esc(p.grupo)+' · '+esc(p.esfera)+(p.ano?' · '+esc(p.ano):'');
    else if(cam==='ti') txt=esc(p.nm_ti||p.nm_funai)+(p.fase?'<br>Fase: '+esc(p.fase):'');
    else if(cam==='tq') txt=esc(p.nm_tq)+(p.status?'<br>Situação: '+esc(String(p.status).toLowerCase()):'');
    else if(cam==='geo') txt=esc(p._r)+(p.nm_tempo_g?'<br>'+esc(p.nm_tempo_g):'')+
      ([p.nm_lito1,p.nm_lito2,p.nm_lito3,p.nm_lito4].filter(Boolean).length?'<br>Litologia: '+
       esc([p.nm_lito1,p.nm_lito2,p.nm_lito3,p.nm_lito4].filter(Boolean).join(', ')):'');
    else if(cam==='sol') txt=esc(p._r)+(p.textura?'<br>Textura: '+esc(p.textura):'')+(p.relevo?'<br>Relevo: '+esc(String(p.relevo).replace(/\s+/g,' ')):'');
    else if(cam==='gmf') txt=esc(p._r)+(p.nm_dominio?'<br>'+esc(p.nm_dominio):'')+(p.categoria&&p.categoria!=='null'?'<br>Modelado: '+esc(p.categoria):'');
    else if(cam==='veg') txt=esc(p.legenda||p._r);
    else if(cam==='hid') txt=esc(p.nome||'Curso d’água sem nome')+'<br>'+esc(p.regime||'');
    else if(cam==='rod') txt=esc(p.sigla||'Rodovia sem sigla')+'<br>'+esc(p.jurisdicao||'')+' · '+esc(p.revestimento||'');
    else if(cam==='fer') txt=esc(p.nome||'Ferrovia')+(p.concessionaria?'<br>'+esc(p.concessionaria):'');
    else if(cam==='mda') txt=esc(p.nome||p.tipomassadagua||'Massa d’água');
    partes.push('<b>'+esc(CAM[cam].nome)+'</b>'+txt);
  }
  if(partes.length) new maplibregl.Popup({closeButton:true,maxWidth:'300px'})
    .setLngLat(e.lngLat).setHTML(partes.join('')).addTo(mapa);
}

/* ============================ rótulos ============================ */
function calculaRotulos(){
  rotulos=[];
  if(!mapa||!tem('rot')) return;
  const b=mapa.getBounds(), vb=[b.getWest(),b.getSouth(),b.getEast(),b.getNorth()];
  // vizinhos: o ponto mais "fundo" de cada um dentro da parte visível
  if(est.c.has('viz')&&dados.viz) for(const f of dados.viz){
    const bb=f._bb||(f._bb=bboxDe(f.geometry)); if(!cruza(bb,vb)) continue;
    const polys=poligonos(f.geometry), w=Math.max(bb[0],vb[0]), e=Math.min(bb[2],vb[2]),
          s=Math.max(bb[1],vb[1]), n=Math.min(bb[3],vb[3]);
    const vert=[]; polys.forEach(p=>p.forEach(r=>{ const k=Math.max(1,Math.floor(r.length/250)); for(let i=0;i<r.length;i+=k) vert.push(r[i]); }));
    let melhor=null, dm=-1;
    for(let j=1;j<12;j++) for(let i=1;i<12;i++){
      const pt=[w+(e-w)*i/12, s+(n-s)*j/12];
      if(!noPoligono(pt,polys)) continue;
      const P=mapa.project(pt);
      let d=Math.min(P.x,P.y,mapa.getCanvas().clientWidth-P.x,mapa.getCanvas().clientHeight-P.y)*1.4;
      for(const v of vert){ const Q=mapa.project(v); const dd=Math.hypot(P.x-Q.x,P.y-Q.y); if(dd<d) d=dd; if(d<dm) break; }
      if(d>dm){ dm=d; melhor=pt; }
    }
    if(melhor&&dm>18) rotulos.push({tipo:'viz',ll:melhor,txt:f.properties.nome});
  }
  if(est.c.has('sede')&&dados.sede){
    const s=dados.sede.find(f=>String(f.properties.geocodigo)===String(ctx.cod));
    if(s) rotulos.push({tipo:'sede',ll:s.geometry.coordinates,txt:s.properties.nome||ctx.nome});
  }
  if(est.c.has('rod')&&dados.rod){
    const por=new Map();
    for(const f of dados.rod){ const sg=f.properties.sigla; if(!sg||!f._dentro) continue;
      if(!por.has(sg)) por.set(sg,[]); linhas(f.geometry).forEach(l=>l.forEach(c=>{ if(grade.dentro(c[0],c[1])) por.get(sg).push(c); })); }
    [...por.entries()].sort((a,b)=>b[1].length-a[1].length).slice(0,8).forEach(([sg,pts])=>{
      if(pts.length) rotulos.push({tipo:'rod',ll:pts[Math.floor(pts.length/2)],txt:sg.split(/[;,]/)[0].trim()}); });
  }
  if(est.c.has('hid')&&dados.hid){
    const por=new Map();
    for(const f of dados.hid){ const nm=f.properties.nome; if(!nm||!f._dentro) continue;
      for(const l of linhas(f.geometry)){ const dentro=l.filter(c=>grade.dentro(c[0],c[1]));
        if(!por.has(nm)) por.set(nm,[]); if(dentro.length>por.get(nm).length) por.set(nm,dentro); } }
    [...por.entries()].sort((a,b)=>b[1].length-a[1].length).slice(0,5).forEach(([nm,pts])=>{
      if(pts.length<3) return;
      const i=Math.floor(pts.length/2), a=pts[Math.max(0,i-1)], c=pts[Math.min(pts.length-1,i+1)];
      rotulos.push({tipo:'rio',ll:pts[i],txt:nm,de:a,ate:c}); });
  }
}

/* ======================= sobreposição (canvas) =======================
 * Moldura, coordenadas, grade, norte, escala e rótulos. A mesma função
 * desenha na tela e na imagem exportada. */
let pedidoSobre=0;
function agendaSobre(){ if(pedidoSobre) return; pedidoSobre=requestAnimationFrame(()=>{ pedidoSobre=0; desenhaSobreTela(); }); }
function desenhaSobreTela(){
  if(!mapa||!el) return;
  const q=el.querySelector('.geo-quadro'), cv=el.querySelector('canvas.geo-sobre');
  const W=q.clientWidth, H=q.clientHeight, r=window.devicePixelRatio||1;
  if(cv.width!==Math.round(W*r)||cv.height!==Math.round(H*r)){ cv.width=Math.round(W*r); cv.height=Math.round(H*r); }
  const c=cv.getContext('2d'); c.setTransform(r,0,0,r,0,0); c.clearRect(0,0,W,H);
  desenhaSobre(c,W,H);
}
function intervalo(span,alvo){
  const op=[1/60,2/60,5/60,10/60,15/60,20/60,30/60,1,2,5,10];
  return op.find(x=>span/x<=alvo)||10;
}
function fmtCoord(v,eixo,segundos){
  const h=eixo==='lat'?(v<0?'S':'N'):(v<0?'W':'E');
  let a=Math.abs(v), g=Math.floor(a), m=(a-g)*60, s=Math.round((m-Math.floor(m))*60);
  m=Math.floor(m); if(s===60){ s=0; m++; } if(m===60){ m=0; g++; }
  return segundos ? g+'°'+String(m).padStart(2,'0')+'′'+String(s).padStart(2,'0')+'″'+h
                  : g+'°'+String(m).padStart(2,'0')+'′'+h;
}
function desenhaSobre(c,W,H){
  const M=tem('coo')?MARGEM:0, mw=W-2*M, mh=H-2*M;
  const proj=ll=>{ const p=mapa.project(ll); return [p.x+M,p.y+M]; };
  c.save();
  c.font='11px '+FONTE_UI; c.textBaseline='middle';
  const b=mapa.getBounds(), w=b.getWest(), e=b.getEast(), s=b.getSouth(), n=b.getNorth();
  const passo=intervalo(Math.max(e-w,n-s),5);
  const lons=[], lats=[];
  for(let x=Math.ceil(w/passo)*passo;x<=e;x+=passo) lons.push(x);
  for(let y=Math.ceil(s/passo)*passo;y<=n;y+=passo) lats.push(y);
  // grade
  if(tem('gra')){
    c.save(); c.beginPath(); c.rect(M,M,mw,mh); c.clip();
    c.strokeStyle='rgba(30,40,50,.35)'; c.lineWidth=.6; c.setLineDash([3,3]);
    lons.forEach(x=>{ const p=proj([x,(s+n)/2])[0]; c.beginPath(); c.moveTo(p,M); c.lineTo(p,M+mh); c.stroke(); });
    lats.forEach(y=>{ const p=proj([(w+e)/2,y])[1]; c.beginPath(); c.moveTo(M,p); c.lineTo(M+mw,p); c.stroke(); });
    c.restore();
  }
  // rótulos
  if(tem('rot')) desenhaRotulos(c,proj,M,mw,mh);
  // moldura e coordenadas
  if(M){
    c.fillStyle='#fff';
    c.fillRect(0,0,W,M); c.fillRect(0,H-M,W,M); c.fillRect(0,0,M,H); c.fillRect(W-M,0,M,H);
    c.strokeStyle='#1A1A1A'; c.lineWidth=1; c.strokeRect(M+.5,M+.5,mw-1,mh-1);
    c.fillStyle='#3A454C'; c.strokeStyle='#1A1A1A';
    const seg=passo<1/60*5;
    c.textAlign='center';
    lons.forEach(x=>{ const p=proj([x,(s+n)/2])[0]; if(p<M+20||p>M+mw-20) return;
      c.beginPath(); c.moveTo(p,M); c.lineTo(p,M-4); c.moveTo(p,M+mh); c.lineTo(p,M+mh+4); c.stroke();
      const t=fmtCoord(x,'lon',seg); c.fillText(t,p,M/2-1); c.fillText(t,p,H-M/2+1); });
    lats.forEach(y=>{ const p=proj([(w+e)/2,y])[1]; if(p<M+30||p>M+mh-30) return;
      c.beginPath(); c.moveTo(M,p); c.lineTo(M-4,p); c.moveTo(M+mw,p); c.lineTo(M+mw+4,p); c.stroke();
      const t=fmtCoord(y,'lat',seg);
      c.save(); c.translate(M/2-1,p); c.rotate(-Math.PI/2); c.fillText(t,0,0); c.restore();
      c.save(); c.translate(W-M/2+1,p); c.rotate(Math.PI/2); c.fillText(t,0,0); c.restore(); });
  }
  if(tem('nor')) desenhaNorte(c,M+mw-34,M+14);
  if(tem('esc')) desenhaEscala(c,M+12,M+mh-14);
  c.restore();
}
function halo(c,txt,x,y,cor,largura){
  c.lineJoin='round'; c.strokeStyle='rgba(255,255,255,.92)'; c.lineWidth=largura||3.2;
  c.strokeText(txt,x,y); c.fillStyle=cor; c.fillText(txt,x,y);
}
function desenhaRotulos(c,proj,M,mw,mh){
  // Caixas ocupadas: escala, norte e cada rótulo já posto. Rótulo que bateria
  // em outro não sai; a prioridade é sede, rodovia, rio e por fim vizinho.
  const ocup=[]; if(tem('esc')) ocup.push([M,M+mh-44,M+190,M+mh]); if(tem('nor')) ocup.push([M+mw-46,M,M+mw,M+56]);
  const bate=b=>ocup.some(o=>b[0]<o[2]&&b[2]>o[0]&&b[1]<o[3]&&b[3]>o[1]);
  const fora=b=>b[0]<M||b[2]>M+mw||b[1]<M||b[3]>M+mh;
  const prio={sede:0,rod:1,rio:2,viz:3};
  c.save(); c.beginPath(); c.rect(M,M,mw,mh); c.clip();
  c.textAlign='center'; c.textBaseline='middle';
  for(const r of [...rotulos].sort((a,b)=>prio[a.tipo]-prio[b.tipo])){
    const [x,y]=proj(r.ll);
    if(r.tipo==='viz'){
      c.font='italic 11px '+FONTE_UI; const tw=c.measureText(r.txt).width/2+3, b=[x-tw,y-8,x+tw,y+8];
      if(fora(b)||bate(b)) continue; ocup.push(b); halo(c,r.txt,x,y,'#66727D');
    }else if(r.tipo==='sede'){
      c.font='600 12.5px '+FONTE_UI; const tw=c.measureText(r.txt).width;
      ocup.push([x-7,y-9,x+12+tw,y+8]);
      c.textAlign='left'; halo(c,r.txt,x+8,y-1,'#10161C',3.6); c.textAlign='center';
    }else if(r.tipo==='rio'){
      const [ax,ay]=proj(r.de), [bx,by]=proj(r.ate);
      let ang=Math.atan2(by-ay,bx-ax); if(ang>Math.PI/2) ang-=Math.PI; if(ang<-Math.PI/2) ang+=Math.PI;
      c.font='italic 11px '+FONTE_UI;
      const hw=c.measureText(r.txt).width/2, ca=Math.abs(Math.cos(ang)), sa=Math.abs(Math.sin(ang));
      const ex=hw*ca+8*sa, ey=hw*sa+8*ca, ox=6*Math.sin(ang), oy=-6*Math.cos(ang);
      const b=[x+ox-ex,y+oy-ey,x+ox+ex,y+oy+ey];
      if(fora(b)||bate(b)) continue; ocup.push(b);
      c.save(); c.translate(x,y); c.rotate(ang); halo(c,r.txt,0,-6,'#22639E'); c.restore();
    }else if(r.tipo==='rod'){
      c.font='700 9.5px '+FONTE_UI; const tw=c.measureText(r.txt).width+8, b=[x-tw/2,y-7,x+tw/2,y+7];
      if(fora(b)||bate(b)) continue; ocup.push(b);
      c.fillStyle='#fff'; c.strokeStyle='#5B6670'; c.lineWidth=1;
      c.beginPath(); c.roundRect?c.roundRect(b[0],b[1],tw,14,3):c.rect(b[0],b[1],tw,14); c.fill(); c.stroke();
      c.fillStyle='#2B2B2B'; c.fillText(r.txt,x,y+.5);
    }
  }
  c.restore();
}
function desenhaNorte(c,x,y){
  c.save(); c.translate(x+11,y);
  c.fillStyle='#fff'; c.globalAlpha=.85; c.beginPath(); c.arc(0,22,17,0,Math.PI*2); c.fill(); c.globalAlpha=1;
  c.beginPath(); c.moveTo(0,8); c.lineTo(7,34); c.lineTo(0,28); c.closePath(); c.fillStyle='#1A1A1A'; c.fill();
  c.beginPath(); c.moveTo(0,8); c.lineTo(-7,34); c.lineTo(0,28); c.closePath(); c.fillStyle='#fff'; c.fill();
  c.strokeStyle='#1A1A1A'; c.lineWidth=1; c.beginPath(); c.moveTo(0,8); c.lineTo(7,34); c.lineTo(0,28); c.lineTo(-7,34); c.closePath(); c.stroke();
  c.font='700 11px '+FONTE_UI; c.textAlign='center'; c.textBaseline='alphabetic'; c.fillStyle='#1A1A1A'; c.fillText('N',0,5);
  c.restore();
}
function desenhaEscala(c,x,y){
  const cv=mapa.getCanvas(), ch=cv.clientHeight, cw=cv.clientWidth;
  const a=mapa.unproject([cw/2-50,ch-30]), b=mapa.unproject([cw/2+50,ch-30]);
  const mpp=distancia(a,b)/100;
  const alvo=mpp*130, p10=Math.pow(10,Math.floor(Math.log10(alvo)));
  const nice=[1,2,2.5,5,10].map(k=>k*p10).filter(v=>v<=alvo).pop()||p10;
  const px=nice/mpp, km=nice>=1000;
  const rot=v=>km?(v/1000).toLocaleString('pt-BR',{maximumFractionDigits:2}):Math.round(v).toLocaleString('pt-BR');
  c.save();
  c.fillStyle='rgba(255,255,255,.85)'; c.fillRect(x-6,y-24,px+44,32);
  for(let i=0;i<4;i++){ c.fillStyle=i%2?'#fff':'#1A1A1A'; c.fillRect(x+i*px/4,y-4,px/4,5); }
  c.strokeStyle='#1A1A1A'; c.lineWidth=.8; c.strokeRect(x,y-4,px,5);
  c.font='10px '+FONTE_UI; c.fillStyle='#1A1A1A'; c.textAlign='center'; c.textBaseline='alphabetic';
  c.fillText('0',x,y-8); c.fillText(rot(nice/2),x+px/2,y-8); c.fillText(rot(nice),x+px,y-8);
  c.textAlign='left'; c.fillText(km?'km':'m',x+px+8,y+1);
  c.restore();
}
function distancia(a,b){
  const R=6371008.8, r=Math.PI/180, dl=(b.lat-a.lat)*r, dg=(b.lng-a.lng)*r;
  const h=Math.sin(dl/2)**2+Math.cos(a.lat*r)*Math.cos(b.lat*r)*Math.sin(dg/2)**2;
  return 2*R*Math.asin(Math.sqrt(h));
}

/* ====================== legenda, título, fontes ====================== */
function itensLegenda(){
  const blocos=[];
  const ref=[{tipo:'linha',cor:'#1A1A1A',w:2,rotulo:'Limite municipal'}];
  if(est.c.has('viz')) ref.push({tipo:'linha',cor:'#8C98A4',w:1,rotulo:'Limite dos municípios vizinhos'});
  if(est.c.has('sede')&&legendas.sede&&legendas.sede.itens.length){
    ref.push({tipo:'ponto',cor:'#1A1A1A',rotulo:'Sede municipal'});
    if(est.o!=='ocultar'&&dados.sede&&dados.sede.length>1) ref.push({tipo:'ponto',cor:'#ffffff',borda:'#5B6670',rotulo:'Sede de município vizinho'});
  }
  for(const id of ['rod','fer']) if(est.c.has(id)&&legendas[id]) ref.push(...legendas[id].itens);
  blocos.push({tit:'Convenções',itens:ref});
  if((est.c.has('hid')&&legendas.hid)||(est.c.has('mda')&&legendas.mda)){
    const it=[]; if(est.c.has('hid')&&legendas.hid) it.push(...legendas.hid.itens);
    if(est.c.has('mda')&&legendas.mda&&legendas.mda.itens.length) it.push({tipo:'area',cor:AGUA,borda:AGUA_L,rotulo:'Massa d’água'});
    if(it.length) blocos.push({tit:'Hidrografia',itens:it,
      nota:!dados.hid||!dados.hid.soNomeados?'':dados.hid.soNomeados==='rios'
        ?'Município muito extenso: só os cursos d’água chamados de rio na BC250.'
        :'Município extenso: só os cursos d’água com nome na BC250.'});
  }
  for(const id of ['uso','veg','geo','sol','gmf','uc','ti','tq']){
    if(!est.c.has(id)) continue;
    const cam=CAM[id], lg=legendas[id];
    const tit={uso:'Cobertura e uso da terra (2020)',veg:'Vegetação',geo:'Unidades geológicas',
      sol:'Solos',gmf:'Unidades geomorfológicas',uc:'Unidades de conservação',ti:'Terras indígenas',
      tq:'Territórios quilombolas'}[id];
    if(!lg){ blocos.push({tit,itens:[],nota:status[id]&&status[id].erro?'não foi possível carregar':'carregando…'}); continue; }
    if(cam.tipo==='sobre'){
      blocos.push({tit,itens:lg.itens,nota:lg.itens.length?'Ocupam '+pct(lg.total)+' do território municipal.'
        :'Nenhuma no território municipal.'});
    }else blocos.push({tit,itens:lg.itens,pct:true,nota:lg.itens.length?'':'Sem dados para o município.'});
  }
  return blocos;
}
function pct(v){
  if(v===undefined||v===null) return '';
  // só entra na legenda o que toca o município; parcela zero é lasca menor que um pixel da grade
  if(v<.005) return '<1%';
  return (v*100).toLocaleString('pt-BR',{maximumFractionDigits:v<.1?1:0})+'%';
}
function amostraHTML(it){
  if(it.tipo==='linha') return '<i class="linha" style="border-top:'+Math.max(1.5,it.w||1)+'px '+(it.tracejado?'dashed':'solid')+' '+it.cor+'"></i>';
  if(it.tipo==='ponto') return '<i class="ponto" style="background:'+it.cor+(it.borda?';box-shadow:inset 0 0 0 1.3px '+it.borda:'')+'"></i>';
  return '<i style="background:'+it.cor+(it.borda?';box-shadow:inset 0 0 0 1.5px '+it.borda:'')+
    ';opacity:'+(it.borda?.85:1)+'"></i>';
}
function desenhaLegenda(){
  const L=el.querySelector('.geo-leg');
  L.hidden=!tem('leg')&&!tem('loc');
  let h='';
  if(tem('loc')) h+='<div class="insets"><div><canvas data-inset="br" width="240" height="230"></canvas><p>'+esc(ctx.ufNome)+' no Brasil</p></div>'+
    '<div><canvas data-inset="uf" width="240" height="230"></canvas><p>'+esc(ctx.nome)+' em '+esc(ctx.sigla)+'</p></div></div>';
  if(tem('leg')) for(const b of itensLegenda()){
    h+='<h4>'+esc(b.tit)+'</h4>';
    if(b.nota&&!b.itens.length){ h+='<p class="vazio">'+esc(b.nota)+'</p>'; continue; }
    for(const it of b.itens){
      h+='<div class="it">'+amostraHTML(it)+'<span>'+esc(it.rotulo)+'</span><span class="pct">'+(b.pct?pct(it.pct):'')+'</span></div>';
      if(it.lista&&it.lista.length) h+='<ul class="lista">'+it.lista.map(x=>'<li>'+esc(x.nome)+' · '+pct(x.pct)+'</li>').join('')+'</ul>';
    }
    if(b.nota&&b.itens.length) h+='<p class="vazio" style="margin-top:4px">'+esc(b.nota)+'</p>';
  }
  L.innerHTML=h;
  if(tem('loc')) L.querySelectorAll('canvas[data-inset]').forEach(cv=>{
    const c=cv.getContext('2d'); desenhaInset(c,cv.dataset.inset,cv.width,cv.height); });
  if(mapa) setTimeout(()=>mapa.resize(),0);
}
function desenhaInset(c,qual,W,H){
  if(!window.d3) return;
  c.fillStyle='#fff'; c.fillRect(0,0,W,H);
  const proj=d3.geoMercator(), path=d3.geoPath(proj,c);
  if(qual==='br'){
    proj.fitExtent([[8,8],[W-8,H-8]],{type:'FeatureCollection',features:ctx.ufs});
    c.lineWidth=.6; c.strokeStyle='#9AA6B2';
    for(const f of ctx.ufs){ c.beginPath(); path(f);
      c.fillStyle=String(f.properties.uf)===String(ctx.ufCod)?'#163E6C':'#E8ECF1'; c.fill(); c.stroke(); }
  }else{
    const uf=ctx.ufs.find(f=>String(f.properties.uf)===String(ctx.ufCod));
    proj.fitExtent([[8,8],[W-8,H-8]],uf);
    c.lineWidth=.35; c.strokeStyle='#C3CBD3';
    for(const f of ctx.munsUF){ c.beginPath(); path(f); c.fillStyle='#F2F4F7'; c.fill(); c.stroke(); }
    c.beginPath(); path(uf); c.lineWidth=.9; c.strokeStyle='#5B6670'; c.stroke();
    c.beginPath(); path(ctx.feature); c.fillStyle='#C4452B'; c.fill();
    const [x,y]=proj(d3.geoCentroid(ctx.feature)); c.beginPath(); c.arc(x,y,6,0,Math.PI*2);
    c.strokeStyle='#C4452B'; c.lineWidth=1.4; c.stroke();
  }
}
function tituloPadrao(){ return (TITULOS[est.p]||'Mapa')+' — '+ctx.nome+' ('+ctx.sigla+')'; }
function desenhaTitulo(){
  const t=el.querySelector('.geo-folha .tit'); t.hidden=!tem('tit');
  if(!tituloLivre) est.t=tituloPadrao();
  t.textContent=est.t;
  const inp=el.querySelector('.geo-titulo'); if(inp&&document.activeElement!==inp) inp.value=est.t;
}
function fontes(){
  const fs=new Set([F_BC250]);
  for(const id of est.c) if(CAM[id]) fs.add(CAM[id].fonte);
  return [...fs];
}
function textoRodape(){
  const partes=['Fontes: '+fontes().join('; ')+'.'];
  if(FUNDOS[est.f].attr) partes.push(FUNDOS[est.f].attr+'.');
  partes.push('Coordenadas geográficas, datum SIRGAS 2000, projeção Web Mercator. Elaborado no Painel Socioambiental em '+
    new Date().toLocaleDateString('pt-BR')+'.');
  return partes.join(' ');
}
function desenhaRodape(){
  const r=el.querySelector('.geo-folha .rodape'); r.hidden=!tem('fon'); r.textContent=textoRodape();
}
function atualizaFonte(){ /* a fonte vem da definição da camada; nada a fazer por ora */ }

/* ============================ painel ============================ */
function desenhaPainel(){
  const P=el.querySelector('.geo-painel');
  P.querySelector('.geo-presets').innerHTML=PRESETS.map(p=>
    '<button type="button" data-p="'+p.id+'" aria-pressed="'+(p.id===est.p)+'">'+esc(p.nome)+'</button>').join('');
  P.querySelectorAll('.geo-presets button').forEach(b=>b.onclick=()=>{
    const novo=estadoPadrao(b.dataset.p); const els=est.e;
    // elementos escolhidos à mão continuam; o mapa de localização entra e sai com o filtro
    novo.e=new Set([...els].filter(k=>k!=='loc')); if((PRESETS.find(x=>x.id===novo.p).els||[]).includes('loc')) novo.e.add('loc');
    est=novo; tituloLivre=false; desenhaPainel(); aplicaEstado(true); aviso(); });
  desenhaPainelCamadas();
  P.querySelector('.geo-fundo').innerHTML=Object.entries(FUNDOS).map(([k,f])=>
    '<button type="button" data-f="'+k+'" aria-pressed="'+(est.f===k)+'">'+f.nome+'</button>').join('');
  P.querySelectorAll('.geo-fundo button').forEach(b=>b.onclick=()=>{ est.f=b.dataset.f; desenhaPainel(); aplicaEstado(); aviso(); });
  P.querySelector('.geo-fora').innerHTML=Object.entries(FORA).map(([k,f])=>
    '<button type="button" data-o="'+k+'" aria-pressed="'+(est.o===k)+'">'+f[0]+'</button>').join('');
  P.querySelectorAll('.geo-fora button').forEach(b=>b.onclick=()=>{ est.o=b.dataset.o; desenhaPainel(); aplicaEstado(); aviso(); });
  P.querySelector('.geo-els').innerHTML=ELEMENTOS.map(([k,n])=>
    '<label><input type="checkbox" data-e="'+k+'"'+(tem(k)?' checked':'')+'>'+n+'</label>').join('');
  P.querySelectorAll('.geo-els input').forEach(i=>i.onchange=()=>{
    if(i.checked) est.e.add(i.dataset.e); else est.e.delete(i.dataset.e); aplicaEstado(); aviso(); });
}
function desenhaPainelCamadas(){
  const P=el&&el.querySelector('.geo-camadas'); if(!P) return;
  const grupos=[...new Set(CAMADAS.map(c=>c.grupo))];
  P.innerHTML=grupos.map(g=>'<div class="geo-grupo"><p>'+esc(g)+'</p>'+
    CAMADAS.filter(c=>c.grupo===g).map(c=>{
      const s=status[c.id]||{}, on=est.c.has(c.id);
      let st='';
      if(on){
        if(s.carregando) st='carregando…';
        else if(s.erro) st='<button type="button" data-tenta="'+c.id+'">tentar de novo</button>';
        else if(c.tipo==='wms'&&legendas.uso) st=legendas.uso.itens.length+' classes';
        else if(s.n!==undefined) st=s.n?(s.n.toLocaleString('pt-BR')+(s.parcial?'+':'')+(s.nomeados==='rios'?' rios':s.nomeados?' com nome':'')):'nenhuma aqui';
      }
      const [t,cor]=c.amostra;
      return '<label class="geo-cam"><input type="checkbox" data-c="'+c.id+'"'+(on?' checked':'')+'>'+
        '<span class="amostra'+(t==='linha'?' linha':'')+'" style="'+(t==='linha'?'border-color:'+cor:'background:'+cor)+
        (t==='ponto'?';border-radius:50%;width:9px;height:9px;margin-left:2px':'')+'"></span>'+
        '<span>'+esc(c.nome)+'</span><span class="est'+(s.erro?' erro':'')+'">'+st+'</span></label>';
    }).join('')+'</div>').join('')+
    '<div class="geo-grupo"><p>Em estudo</p><div class="geo-cam indisp"><span></span><span></span>'+
    '<span>Hidrogeologia</span><span class="est">só NE e SE</span></div></div>';
  P.querySelectorAll('input[data-c]').forEach(i=>i.onchange=()=>{
    if(i.checked) est.c.add(i.dataset.c); else est.c.delete(i.dataset.c);
    aplicaEstado(); desenhaPainelCamadas(); aviso(); });
  P.querySelectorAll('button[data-tenta]').forEach(b=>b.onclick=e=>{ e.preventDefault();
    const id=b.dataset.tenta; delete dados[id]; delete status[id]; alimentados.delete(id); aplicaEstado(); });
}
let lento=0;
function mostraCarregando(d){
  pedidos+=d; const x=el&&el.querySelector('.geo-quadro .geo-carga');
  if(!x) return;
  x.hidden=pedidos<=0;
  clearTimeout(lento);
  if(pedidos>0){
    x.textContent='Carregando camadas…';
    // o servidor do IBGE às vezes leva mais de um minuto; melhor dizer de quem é a demora
    lento=setTimeout(()=>{ x.textContent='O servidor do IBGE está demorando — continua carregando…'; },15000);
  }
}

/* ============================ exportar ============================ */
async function exportar(botao){
  if(!mapa) return;
  const rotuloBtn=botao.textContent; botao.disabled=true; botao.textContent='Gerando imagem…';
  const R=2, pr0=mapa.getPixelRatio();
  try{
    mapa.setPixelRatio(R);
    await new Promise(r=>{ mapa.once('idle',r); mapa.triggerRepaint(); });
    const q=el.querySelector('.geo-quadro'), QW=q.clientWidth, QH=q.clientHeight;
    const LW=(tem('leg')||tem('loc'))?272:0, G=LW?18:0, P=22;
    const titH=tem('tit')?34:0;
    // medir a legenda e o rodapé antes de dimensionar a folha
    const med=document.createElement('canvas').getContext('2d');
    const legH=LW?desenhaLegendaCanvas(med,0,0,LW,true):0;
    med.font='10.5px '+FONTE_UI;
    const rod=tem('fon')?quebra(med,textoRodape(),QW+G+LW):[];
    const rodH=rod.length?rod.length*14+12:0;
    const W=P*2+QW+G+LW, H=P*2+titH+Math.max(QH,legH)+rodH;
    const cv=document.createElement('canvas'); cv.width=W*R; cv.height=H*R;
    const c=cv.getContext('2d'); c.scale(R,R);
    c.fillStyle='#fff'; c.fillRect(0,0,W,H);
    if(titH){ c.font='700 18px '+FONTE_UI; c.fillStyle='#10161C'; c.textBaseline='top'; c.fillText(est.t,P,P); }
    const qx=P, qy=P+titH, M=tem('coo')?MARGEM:0;
    const mc=mapa.getCanvas();
    c.drawImage(mc,qx+M,qy+M,mc.clientWidth,mc.clientHeight);
    c.save(); c.translate(qx,qy); desenhaSobre(c,QW,QH); c.restore();
    if(LW) desenhaLegendaCanvas(c,qx+QW+G,qy,LW,false);
    if(rod.length){
      c.font='10.5px '+FONTE_UI; c.fillStyle='#6E787E'; c.textBaseline='top';
      c.strokeStyle='#EDF0F4'; c.beginPath(); c.moveTo(P,H-P-rodH+4); c.lineTo(W-P,H-P-rodH+4); c.stroke();
      rod.forEach((l,i)=>c.fillText(l,P,H-P-rodH+12+i*14));
    }
    const blob=await new Promise(r=>cv.toBlob(r,'image/png'));
    const a=document.createElement('a');
    a.href=URL.createObjectURL(blob);
    a.download=nomeArquivo(); document.body.appendChild(a); a.click(); a.remove();
    setTimeout(()=>URL.revokeObjectURL(a.href),4000);
  }catch(e){
    console.error(e); alert('Não foi possível gerar a imagem: '+(e.message||e));
  }finally{
    mapa.setPixelRatio(pr0); botao.disabled=false; botao.textContent=rotuloBtn;
  }
}
function nomeArquivo(){
  const s=(TITULOS[est.p]||'mapa')+' '+ctx.nome+' '+ctx.sigla;
  return 'mapa-'+s.normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase()
    .replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'')+'.png';
}
function quebra(c,txt,larg){
  const out=[]; let l='';
  for(const p of String(txt).split(' ')){
    const t=l?l+' '+p:p;
    if(c.measureText(t).width>larg&&l){ out.push(l); l=p; } else l=t;
  }
  if(l) out.push(l);
  return out;
}
// Desenha a legenda no canvas; com `so_mede` só devolve a altura.
function desenhaLegendaCanvas(c,x,y,w,so_mede){
  let yy=y;
  c.textBaseline='top';
  if(tem('loc')){
    const iw=(w-8)/2, ih=iw*230/240;
    if(!so_mede){
      el.querySelectorAll('canvas[data-inset]').forEach((cv,i)=>{
        const ox=x+i*(iw+8); c.drawImage(cv,ox,yy,iw,ih);
        c.strokeStyle='#DCE1E8'; c.lineWidth=1; c.strokeRect(ox+.5,yy+.5,iw-1,ih-1);
        c.font='10px '+FONTE_UI; c.fillStyle='#6E787E'; c.textAlign='center';
        c.fillText(i?ctx.nome+' em '+ctx.sigla:ctx.ufNome+' no Brasil',ox+iw/2,yy+ih+3,iw);
        c.textAlign='left';
      });
    }
    yy+=ih+22;
  }
  if(!tem('leg')) return yy-y;
  for(const b of itensLegenda()){
    c.font='700 12.5px '+FONTE_UI; if(!so_mede){ c.fillStyle='#10161C'; c.fillText(b.tit,x,yy); }
    yy+=18;
    if(b.nota&&!b.itens.length){ c.font='11.5px '+FONTE_UI; if(!so_mede){ c.fillStyle='#6E787E'; c.fillText(b.nota,x,yy); } yy+=17; continue; }
    for(const it of b.itens){
      c.font='12px '+FONTE_UI;
      const pc=b.pct?pct(it.pct):'', pw=pc?c.measureText(pc).width+6:0;
      const ls=quebra(c,it.rotulo,w-26-pw);
      if(!so_mede){
        amostraCanvas(c,it,x,yy);
        c.fillStyle='#3A454C'; ls.forEach((l,i)=>c.fillText(l,x+26,yy+i*15));
        if(pc){ c.fillStyle='#6E787E'; c.textAlign='right'; c.fillText(pc,x+w,yy); c.textAlign='left'; }
      }
      yy+=ls.length*15+3;
      if(it.lista) for(const z of it.lista){
        c.font='11px '+FONTE_UI;
        const zs=quebra(c,z.nome+' · '+pct(z.pct),w-26);
        if(!so_mede){ c.fillStyle='#6E787E'; zs.forEach((l,i)=>c.fillText(l,x+26,yy+i*14)); }
        yy+=zs.length*14+1;
      }
    }
    if(b.nota&&b.itens.length){ c.font='11px '+FONTE_UI; const ns=quebra(c,b.nota,w);
      if(!so_mede){ c.fillStyle='#6E787E'; ns.forEach((l,i)=>c.fillText(l,x,yy+2+i*14)); } yy+=ns.length*14+4; }
    yy+=8;
  }
  return yy-y;
}
function amostraCanvas(c,it,x,y){
  c.save();
  if(it.tipo==='linha'){
    c.strokeStyle=it.cor; c.lineWidth=Math.max(1.5,it.w||1); if(it.tracejado) c.setLineDash([4,3]);
    c.beginPath(); c.moveTo(x,y+7); c.lineTo(x+18,y+7); c.stroke();
  }else if(it.tipo==='ponto'){
    c.fillStyle=it.cor; c.beginPath(); c.arc(x+9,y+7,4.5,0,Math.PI*2); c.fill();
    if(it.borda){ c.strokeStyle=it.borda; c.lineWidth=1.3; c.stroke(); }
  }else{
    c.fillStyle=it.cor; c.globalAlpha=it.borda?.85:1; c.fillRect(x,y+1,18,11); c.globalAlpha=1;
    if(it.borda){ c.strokeStyle=it.borda; c.lineWidth=1.5; if(it.tracejado) c.setLineDash([3,2]); c.strokeRect(x+.75,y+1.75,16.5,9.5); }
  }
  c.restore();
}

/* ===================== pacote de camadas (teste) =====================
 * Um .zip com um GeoJSON por camada ligada, só com as feições que tocam o
 * município, mais o limite municipal. Abre direto no QGIS (arrastar o
 * arquivo). As feições vêm inteiras, não cortadas no limite: o corte exato
 * pede uma biblioteca de geometria e fica para depois, se o pacote servir. */
const CRC=(()=>{ const t=new Uint32Array(256); for(let n=0;n<256;n++){ let c=n;
  for(let k=0;k<8;k++) c=c&1?0xEDB88320^(c>>>1):c>>>1; t[n]=c>>>0; } return t; })();
function crc32(b){ let c=0xFFFFFFFF; for(let i=0;i<b.length;i++) c=CRC[(c^b[i])&255]^(c>>>8); return (c^0xFFFFFFFF)>>>0; }
function zip(arquivos){
  // zip sem compressão ("store"): simples, e o GeoJSON já sai pequeno por município
  const enc=new TextEncoder(), partes=[], central=[]; let pos=0;
  const u16=v=>[v&255,(v>>>8)&255], u32=v=>[v&255,(v>>>8)&255,(v>>>16)&255,(v>>>24)&255];
  for(const [nome,texto] of arquivos){
    const n=enc.encode(nome), d=enc.encode(texto), crc=crc32(d);
    const cab=[...u32(0x04034b50),...u16(20),...u16(0x0800),...u16(0),...u16(0),...u16(0x21),
      ...u32(crc),...u32(d.length),...u32(d.length),...u16(n.length),...u16(0)];
    partes.push(new Uint8Array(cab),n,d);
    central.push([...u32(0x02014b50),...u16(20),...u16(20),...u16(0x0800),...u16(0),...u16(0),...u16(0x21),
      ...u32(crc),...u32(d.length),...u32(d.length),...u16(n.length),...u16(0),...u16(0),...u16(0),...u16(0),
      ...u32(0),...u32(pos)],n);
    pos+=cab.length+n.length+d.length;
  }
  let tam=0; const cen=[]; for(let i=0;i<central.length;i+=2){ const a=new Uint8Array(central[i]); cen.push(a,central[i+1]); tam+=a.length+central[i+1].length; }
  const fim=new Uint8Array([...u32(0x06054b50),...u16(0),...u16(0),...u16(arquivos.length),...u16(arquivos.length),...u32(tam),...u32(pos),...u16(0)]);
  return new Blob([...partes,...cen,fim],{type:'application/zip'});
}
function limpaProps(p){ const o={}; for(const [k,v] of Object.entries(p||{})) if(!k.startsWith('_')) o[k]=v; return o; }
function baixaPacote(){
  const slug=(ctx.nome+' '+ctx.sigla).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,'-');
  const fc=fs=>JSON.stringify({type:'FeatureCollection',features:fs.map(f=>({type:'Feature',properties:limpaProps(f.properties),geometry:f.geometry}))});
  const arq=[['limite_municipal.geojson',fc([{properties:{geocodigo:ctx.cod,nome:ctx.nome,uf:ctx.sigla},geometry:munGeo}])]];
  const nomes={sede:'sedes',rod:'rodovias',fer:'ferrovias',hid:'cursos_dagua',mda:'massas_dagua',uc:'unidades_conservacao',
    ti:'terras_indigenas',tq:'territorios_quilombolas',veg:'vegetacao',geo:'geologia',sol:'solos',gmf:'geomorfologia'};
  const leia=['Camadas do município de '+ctx.nome+' ('+ctx.sigla+'), baixadas do Painel Socioambiental em '+
    new Date().toLocaleDateString('pt-BR')+'.','',
    'Coordenadas geográficas, SIRGAS 2000 (as feições estão em graus; no QGIS, EPSG:4674 ou 4326).',
    'Cada arquivo traz as feições que tocam o município, inteiras (não cortadas no limite).','','Fontes:'];
  for(const id of Object.keys(nomes)){
    if(!est.c.has(id)||!Array.isArray(dados[id])) continue;
    arq.push([nomes[id]+'.geojson',fc(dados[id].filter(f=>f._dentro))]);
    leia.push('- '+nomes[id]+': '+CAM[id].fonte);
  }
  if(est.c.has('uso')) leia.push('','A cobertura e uso da terra é imagem (WMS do IBGE), não vetor, e não entra no pacote.');
  arq.push(['LEIA-ME.txt',leia.join('\r\n')]);
  const a=document.createElement('a'); a.href=URL.createObjectURL(zip(arq));
  a.download='camadas-'+slug.replace(/^-|-$/g,'')+'.zip'; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(a.href),4000);
}

/* ============================ entrada ============================ */
async function abrir(c){
  fechar();
  ctx=c; el=c.el; dados={}; status={}; legendas={}; rotulos=[]; pedidos=0; alimentados=new Set();
  est=desserializa(c.estado);
  el.innerHTML=
   '<aside class="geo-painel">'+
     '<button class="volta" type="button">&larr; voltar à ficha</button>'+
     '<h2>Mapas de '+esc(c.nome)+'</h2><p class="uf">'+esc(c.ufNome)+' · '+esc(c.sigla)+'</p>'+
     '<div class="geo-sec"><h3>Mapa</h3><div class="geo-presets"></div></div>'+
     '<div class="geo-sec"><h3>Camadas</h3><div class="geo-camadas"></div></div>'+
     '<div class="geo-sec"><h3>Fundo</h3><div class="geo-chips geo-fundo"></div></div>'+
     '<div class="geo-sec"><h3>Fora do município</h3><div class="geo-chips geo-fora"></div></div>'+
     '<div class="geo-sec"><h3>Imagem</h3><input class="geo-titulo" type="text" aria-label="Título do mapa">'+
       '<div class="geo-els"></div>'+
       '<button class="btn geo-baixar" type="button">Baixar imagem (PNG)</button>'+
       '<button class="btn sec geo-pacote" type="button">Baixar camadas para o QGIS</button>'+
       '<p class="geo-nota">Clique no mapa para ver os atributos do que está ali. Arraste e use a roda do mouse para enquadrar: a imagem sai do jeito que está na tela.</p></div>'+
   '</aside>'+
   '<div class="geo-mesa"><div class="geo-folha">'+
     '<p class="tit"></p>'+
     '<div class="geo-corpo"><div class="geo-quadro"><div class="mapa"></div><canvas class="geo-sobre"></canvas>'+
       '<div class="geo-carga" hidden>Carregando camadas…</div><div class="cursor"></div></div>'+
       '<div class="geo-leg"></div></div>'+
     '<p class="rodape"></p>'+
   '</div></div>';
  el.querySelector('.volta').onclick=()=>c.aoVoltar&&c.aoVoltar();
  el.querySelector('.geo-baixar').onclick=e=>exportar(e.currentTarget);
  el.querySelector('.geo-pacote').onclick=baixaPacote;
  const ti=el.querySelector('.geo-titulo');
  ti.oninput=()=>{ est.t=ti.value; tituloLivre=ti.value.trim()!==''&&ti.value!==tituloPadrao();
    if(!ti.value.trim()){ tituloLivre=false; } desenhaTitulo(); aviso(); };
  desenhaPainel();
  mostraCarregando(+1);
  try{ await carregaBase(); }
  finally{ mostraCarregando(-1); }
  if(ctx!==c) return;
  desenhaTitulo(); desenhaLegenda(); desenhaRodape();
  montaMapa();
  if(window.ResizeObserver){
    abrir.ro=new ResizeObserver(()=>{ if(mapa){ mapa.resize(); agendaSobre(); } });
    abrir.ro.observe(el.querySelector('.geo-quadro'));
  }
}
function fechar(){
  if(abrir.ro){ abrir.ro.disconnect(); abrir.ro=null; }
  if(mapa){ mapa.remove(); mapa=null; }
  pronto=false;
  ctx=null;
}

window.PainelMapas={abrir,fechar};
})();
