import argparse, itertools, json, sqlite3
from collections import Counter
from pathlib import Path
import pandas as pd

def q(s): return '"'+str(s).replace('"','""')+'"'
def main():
 p=argparse.ArgumentParser(); p.add_argument('csv'); p.add_argument('--out',default='output'); p.add_argument('--engine',choices=['sqlite','duckdb'],default='duckdb'); p.add_argument('--miner',choices=['pandas','desbordante'],default='desbordante'); a=p.parse_args()
 out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
 df=pd.read_csv(a.csv,keep_default_na=False,dtype=str); cols=list(df); n=len(df)
 if not n: raise ValueError('Empty dataset')
 # Keep lexical values intact; infer only unambiguous integer/decimal columns.
 for c in cols:
  s=df[c]; numeric=pd.to_numeric(s,errors='coerce')
  if s.str.fullmatch(r'-?(0|[1-9][0-9]*)').all() and numeric.notna().all() and pd.api.types.is_integer_dtype(numeric) and numeric.astype(str).equals(s): df[c]=numeric
  elif s.str.fullmatch(r'-?(0|[1-9][0-9]*)\.[0-9]+').all() and numeric.notna().all() and numeric.astype(str).equals(s): df[c]=numeric
 cards={c:int(df[c].nunique()) for c in cols}; fds={}; library_fds=[]
 if a.miner=='desbordante':
  import desbordante
  algo=desbordante.fd.algorithms.Default(); algo.load_data(table=(str(Path(a.csv).resolve()),',',True)); algo.execute(); library_fds=[str(fd) for fd in algo.get_fds()]
  # Use discovered single-column dependencies as candidates; all are rechecked below.
  candidates=set()
  for fd in library_fds:
   if ' -> ' in fd:
    l,r=fd.split(' -> ',1); l=l.strip().strip('[]'); r=r.strip().strip('[]')
    if l in cols and r in cols: candidates.add((l,r))
  # Refuse to silently ignore a changed library output format.
  if library_fds and not candidates and any(cards[c]<n for c in cols):
   print('No parseable single-column library dependencies; verifying with pandas.')
 else: candidates=None
 for k in cols:
  if not 1<cards[k]<n or (df[k]=='').any(): continue
  g=df.groupby(k,dropna=False).nunique(dropna=False)
  fds[k]=[c for c in cols if c!=k and cards[c]>1 and g[c].max()==1 and (a.miner=='pandas' or not candidates or (k,c) in candidates)]
 # Prefer substantial determinants, then highest savings; names are deterministic, not semantic.
 remaining=cols.copy(); dims=[]
 while True:
  opts=[]
  for k,vs in fds.items():
   if k not in remaining: continue
   dependent=[v for v in vs if v in remaining and v!=k]
   if dependent: opts.append(((n-cards[k])*len(dependent)-cards[k],len(dependent),-cols.index(k),k,dependent))
  if not opts: break
  score,_,__,k,vs=max(opts)
  if score<=0: break
  name='dim_'+k; dims.append((name,k,vs)); remaining=[c for c in remaining if c not in vs]
 # Detect minimal keys up to width 2 (bounded on wide data).
 keys=[]
 for width in (1,2):
  for comb in itertools.combinations(remaining[:60],width):
   if any(set(k).issubset(comb) for k in keys): continue
   if any((df[c]=='').any() for c in comb): continue
   if not df.duplicated(list(comb)).any(): keys.append(comb)
 key=keys[0] if keys else (); dbpath=out/('dataset.duckdb' if a.engine=='duckdb' else 'dataset.sqlite');
 if dbpath.exists(): raise FileExistsError(dbpath)
 if a.engine=='duckdb':
  import duckdb
  con=duckdb.connect(str(dbpath))
 else:
  con=sqlite3.connect(dbpath); con.execute('PRAGMA foreign_keys=ON')
 def typ(c): return 'BIGINT' if pd.api.types.is_integer_dtype(df[c]) else 'DOUBLE' if pd.api.types.is_float_dtype(df[c]) else 'VARCHAR'
 sql=[]
 def create(name,cs,data,pk=(),fks=()):
  defs=[q(c)+' '+typ(c) for c in cs]
  if pk: defs.append('PRIMARY KEY ('+', '.join(map(q,pk))+')')
  for col,t in fks: defs.append(f'FOREIGN KEY ({q(col)}) REFERENCES {q(t)} ({q(col)})')
  stmt=f'CREATE TABLE {q(name)} ('+', '.join(defs)+');'; con.execute(stmt);sql.append(stmt)
  con.executemany(f'INSERT INTO {q(name)} VALUES ('+','.join('?' for _ in cs)+')',list(data[cs].itertuples(index=False,name=None)))
 for name,k,vs in dims: create(name,[k]+vs,df[[k]+vs].drop_duplicates(),(k,))
 create('records',remaining,df,key,[(k,name) for name,k,vs in dims]); owner={c:name for name,k,vs in dims for c in vs}
 stmt='CREATE VIEW dataset AS SELECT '+', '.join(q(owner.get(c,'records'))+'.'+q(c)+' AS '+q(c) for c in cols)+' FROM records '+ ' '.join(f'JOIN {q(name)} ON records.{q(k)} = {q(name)}.{q(k)}' for name,k,vs in dims)+';'; con.execute(stmt);sql.append(stmt)
 actual=Counter(con.execute('SELECT * FROM dataset').fetchall()); expected=Counter(df.itertuples(index=False,name=None)); valid=actual==expected
 if not valid: raise RuntimeError('Reconstruction mismatch')
 counts={name:con.execute(f'SELECT COUNT(*) FROM {q(name)}').fetchone()[0] for name in ['records']+[d[0] for d in dims]};
 if a.engine=='duckdb': con.execute('CHECKPOINT')
 else: con.commit()
 con.close(); (out/'schema.sql').write_text('\n'.join(sql)+'\n'); report={'input_rows':n,'columns':cols,'cardinality':cards,'dependencies':fds,'library_dependencies':library_fds,'miner':a.miner,'engine':a.engine,'primary_key_candidates':[list(k) for k in keys],'selected_key':list(key),'dimensions':[{'table':t,'key':k,'attributes':v} for t,k,v in dims],'records_columns':remaining,'table_rows':counts,'reconstruction_exact':valid,'database_bytes':dbpath.stat().st_size}; (out/'schema.json').write_text(json.dumps(report,indent=2)); print(json.dumps(report,indent=2))
if __name__=='__main__': main()
