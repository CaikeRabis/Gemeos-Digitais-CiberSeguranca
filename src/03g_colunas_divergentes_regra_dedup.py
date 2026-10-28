"""03g - auditoria somente-leitura de divergências e regras de deduplicação."""
from __future__ import annotations
import hashlib, logging, sys, time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
import pandas as pd
import pyogrio

BASE=Path(__file__).resolve().parent.parent; RAW=BASE/'data'/'raw'; PRO=BASE/'data'/'processed'; LOGS=BASE/'logs'
RUN_TAG=datetime.now().strftime('%Y%m%d_%H%M%S'); BATCH=25_000
PROFILE=PRO/'perfil_ucs_entorno_hrc.csv'; AUD=PRO/'auditoria_fonte_duplicidade_gdb_20261016_171724.csv'; SUB=PRO/'auditoria_sub_poligonos_hrc_20261016_171724.csv'
OUT={n:PRO/f'{n}_{RUN_TAG}.csv' for n in ('colunas_divergentes_gdb','regras_dedup_testadas','rastreio_linhas_identicas_perfil','distribuicao_area_sub','ucs_cnae86_linhas_gdb')}
REPORT=PRO/f'relatorio_colunas_dedup_hrc_{RUN_TAG}.txt'; LOG=LOGS/f'colunas_dedup_hrc_{RUN_TAG}.log'; L=logging.getLogger('03g')
TARGETS=('a368a7ce','01d6dfec','fb21e7e2')

def setup()->None:
 LOGS.mkdir(exist_ok=True); L.handlers.clear(); L.setLevel(logging.INFO); L.propagate=False; f=logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
 for h in (logging.StreamHandler(sys.stdout),logging.FileHandler(LOG,encoding='utf-8')): h.setFormatter(f); L.addHandler(h)
def sha(p:Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()
def hashes(g:Path)->dict[str,str]: return {str(p.relative_to(g)):sha(p) for p in sorted(g.rglob('*')) if p.is_file()} | {'PROFILE':sha(PROFILE),'AUD':sha(AUD),'SUBCSV':sha(SUB)}
def gdb()->Path:
 a=list(RAW.glob('*.gdb'))
 if len(a)!=1: raise RuntimeError(f'Esperada uma GDB, encontradas: {a}')
 return a[0]
def cmap(cols:list[str], wanted:str)->str:
 x=[c for c in cols if c.lower()==wanted.lower()]
 if len(x)!=1: raise ValueError(f'Coluna {wanted} não encontrada/ambígua: {x}')
 return x[0]
def val(x:Any)->str: return '<NA>' if pd.isna(x) else str(x)
def group(c:str)->str:
 u=c.upper()
 if any(x in u for x in ('CTMT','SUB','PAC','UNI_TR','PN_CON')): return 'vínculo de rede (inferido)'
 if 'CLAS' in u or 'CNAE' in u:return 'cadastro de consumo (inferido)'
 if 'CAR' in u or 'DEM' in u:return 'carga (inferido)'
 if any(x in u for x in ('SIT','DAT','VERS','ATIV')):return 'situação ou data (inferido)'
 return 'outra (inferido)'
def read(g:Path,layer:str,off:int,cols:list[str]|None=None)->pd.DataFrame:
 return pyogrio.read_dataframe(g,layer=layer,columns=cols,read_geometry=False,skip_features=off,max_features=BATCH).astype('string')
def uc_audit(g:Path,layer:str)->tuple[list[dict[str,Any]],list[dict[str,Any]],list[pd.DataFrame]]:
 info=pyogrio.read_info(g,layer=layer); n=int(info['features']); cols=list(info['fields']); ident=cmap(cols,'cod_id'); cnt=Counter()
 for o in range(0,n,BATCH):
  z=read(g,layer,o,[ident]);cnt.update(z[ident].map(val));L.info('%s ids lote %d',layer,o//BATCH+1)
 rep={k for k,v in cnt.items() if v>1}; first={}; dif=defaultdict(lambda:defaultdict(set)); null=Counter(); total=Counter(); rule_cols=[c for c in cols if any(k in c.upper() for k in ('SIT','DAT','CAR'))]; rule_rows=defaultdict(list); picked=[]
 for o in range(0,n,BATCH):
  z=read(g,layer,o); codes=z[ident].map(val); q=z[codes.isin(rep)]
  for code,row in zip(codes.loc[q.index],q.itertuples(index=False,name=None)):
   r=tuple(map(val,row)); base=first.get(code)
   if base is None:first[code]=r
   else:
    for i,(a,b) in enumerate(zip(base,r)):
     if a!=b:dif[code][cols[i]].update((a,b))
   rule_rows[code].append(tuple(r[cols.index(c)] for c in rule_cols))
  for c in cols:
   total[c]+=len(q); null[c]+=int(q[c].isna().sum()+q[c].eq('').sum())
  target=z[codes.str.lower().str.startswith(TARGETS,na=False)].copy()
  if not target.empty: picked.append(target)
 rows=[]
 for c in cols:
  ds=[len(v[c]) for v in dif.values() if c in v]
  rows.append({'tabela':layer,'coluna':c,'cod_id_em_que_varia':len(ds),'media_valores_distintos':round(sum(ds)/len(ds),4) if ds else 0,'max_valores_distintos':max(ds) if ds else 0,'pct_nulos_ou_vazios_duplicatas':round(100*null[c]/total[c],4) if total[c] else 0,'grupo_inferido':group(c)})
 rules=[]
 for label,key,mode in [('situacao_atividade','SIT','active'),('data_mais_recente','DAT','max'),('carga_maxima','CAR','max')]:
  candidates=[c for c in cols if key in c.upper()]
  if not candidates: continue
  c=candidates[0]; pos=rule_cols.index(c);one=amb=zero=0
  for records in rule_rows.values():
   vals=[r[pos] for r in records if r[pos] not in ('<NA>','')]
   if not vals:zero+=1;continue
   chosen=[x for x in vals if ('ATIV' in x.upper() or 'VIG' in x.upper())] if mode=='active' else [max(vals)]
   if len(chosen)==1:one+=1
   else:amb+=1
  rules.append({'tabela':layer,'regra':label,'coluna':c,'cod_id_resolvidos_uma_linha':one,'cod_id_ambiguos':amb,'cod_id_sem_linha':zero,'classificacao':'teste exploratório; não selecionada como regra oficial'})
 return rows,rules,picked
def profile_trace(g:Path)->pd.DataFrame:
 p=pd.read_csv(PROFILE,dtype=str); origin=cmap(list(p.columns),'tabela_origem'); ident=cmap(list(p.columns),'cod_id'); mt=p[p[origin].str.upper().eq('UCMT_TAB',na=False)].copy(); du=mt[mt.duplicated(keep=False)]
 info=pyogrio.read_info(g,layer='UCMT_tab'); cols=list(info['fields']); gid=cmap(cols,'cod_id'); base=pyogrio.read_dataframe(g,layer='UCMT_tab',read_geometry=False).astype('string'); out=[]
 for _,grp in du.groupby(list(mt.columns),dropna=False):
  ids=grp[ident].dropna().unique().tolist(); b=base[base[gid].isin(ids)]; common=[c for c in mt.columns if c.lower() in {x.lower() for x in cols}]; derived=[c for c in mt.columns if c not in common]
  cls='ORIGEM_BASE' if len(b)>len(b[gid].drop_duplicates()) else ('PIPELINE_JUNCAO' if len(b)==len(ids) else 'INDETERMINADO')
  out.append({'cod_ids':';'.join(ids),'linhas_perfil':len(grp),'linhas_gdb':len(b),'colunas_comuns':';'.join(common),'colunas_derivadas_ou_ausentes_na_gdb':';'.join(derived),'classificacao':cls})
 return pd.DataFrame(out)
def areas()->pd.DataFrame:
 s=pd.read_csv(SUB,dtype=str); a=cmap(list(s.columns),'area_m2'); d=cmap(list(s.columns),'distancia_hrc_m'); contains=cmap(list(s.columns),'contem_hrc'); x=pd.to_numeric(s[a]); qs=x.quantile([0,.1,.25,.5,.75,.9,1]); rows=[{'tipo':'quantil','faixa':str(k),'valor':v} for k,v in qs.items()]
 for name,mask in [('abaixo_5000',x<5000),('5000_a_20000',(x>=5000)&(x<20000)),('20000_a_100000',(x>=20000)&(x<=100000)),('acima_100000',x>100000)]:rows.append({'tipo':'faixa','faixa':name,'valor':int(mask.sum())})
 rows += [{'tipo':'hrc_contido','faixa':'algum','valor':str(s[contains].str.lower().eq('true').any())},{'tipo':'distancia','faixa':'mais_proximo_m','valor':pd.to_numeric(s[d]).min()}];return pd.DataFrame(rows)
def save(x:pd.DataFrame,p:Path)->None:
 with p.open('x',encoding='utf-8',newline='') as f:x.to_csv(f,index=False)
def main()->int:
 setup()
 try:
  if any(p.exists() for p in (*OUT.values(),REPORT)):raise FileExistsError(f'Colisão RUN_TAG {RUN_TAG}')
  g=gdb(); before=hashes(g); allc=[]; allr=[]; picks=[]
  for t in ('UCMT_tab','UCBT_tab'):
   c,r,u=uc_audit(g,t);allc+=c;allr+=r;picks+=u
  trace=profile_trace(g); ar=areas(); candidates=pd.concat(picks,ignore_index=True) if picks else pd.DataFrame()
  after=hashes(g)
  if before!=after:raise RuntimeError('Hash de entrada alterado')
  save(pd.DataFrame(allc),OUT['colunas_divergentes_gdb']);save(pd.DataFrame(allr),OUT['regras_dedup_testadas']);save(trace,OUT['rastreio_linhas_identicas_perfil']);save(ar,OUT['distribuicao_area_sub']);save(candidates,OUT['ucs_cnae86_linhas_gdb'])
  text=['RELATÓRIO 03g',f'RUN_TAG: {RUN_TAG}',f'Data: {datetime.now().isoformat()}',f'Hashes: {"INALTERADOS" if before==after else "ALTERADOS"}','Mapeamento de colunas: case-insensitive registrado nas saídas.', 'Passo 1: leitura em duas passagens, lote=25000.', 'Passo 2: regras são testes exploratórios; nenhuma foi escolhida.', 'Passo 3: rastreio no CSV correspondente.', 'Passo 4: distribuição no CSV correspondente.', 'Passo 5: candidatos são cadastrais; não identificam HRC.', 'Limitações: classificação de grupos é inferida por nome/conteúdo; nenhuma topologia ou atendimento foi concluído.']
  with REPORT.open('x',encoding='utf-8') as f:f.write('\n'.join(text)+'\n')
  L.info('Concluído');return 0
 except (OSError,RuntimeError,ValueError,MemoryError,FileExistsError) as e:L.exception('Falha: %s',e);return 1
if __name__=='__main__':raise SystemExit(main())
