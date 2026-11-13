import json
import numpy as np
from sqlalchemy import select,func
from src.config.database import Base,engine,SessionLocal
from src.models import *
from src.utils.security import hash_password
from src.services.snapshots import get_utterances
from src.services.import_batches import create_batch
from src.schemas.import_batch import BatchInput
from src.services.comparison import compare_snapshots
from src.constants.features import FEATURES

def seed():
 Base.metadata.create_all(engine)
 with SessionLocal() as db:
  for role,name in [('admin','叶砚 · 语料负责人'),('analyst','梁栩 · 分布研究员'),('viewer','唐禾 · 采集观察员')]:
   email=role+'@yanyu.demo'
   if not db.scalar(select(User).where(User.email==email)):db.add(User(email=email,name=name,role=role,password_hash=hash_password('Yanyu2026!')))
  db.commit();rng=np.random.default_rng(113)
  for kind,title in [('reference','参考训练语料 · 秋季冻结'),('candidate','候选新增语料 · 十一月')]:
   generated=[]
   for i in range(900):
    candidate=kind=='candidate';duration=float(rng.lognormal(np.log(2.5 if candidate else 3.2),.5 if candidate else .45));noise=max(0.,float(rng.normal(10.2 if candidate else 10,3)));rate=max(.1,float(rng.normal(5.2 if candidate else 4.8,.9 if candidate else .8)))
    language=str(rng.choice(['zh','en','ja','ko'] if candidate else ['zh','en','ja'],p=[.5,.35,.1,.05] if candidate else [.65,.25,.1]));device=str(rng.choice(['studio','mobile','field','wearable'] if candidate else ['studio','mobile','field'],p=[.15,.65,.15,.05] if candidate else [.55,.3,.15]))
    features={'duration':round(duration,5) if rng.random()>(.04 if candidate else .02) else None,'noise':round(noise,5),'token_rate':round(rate,5),'language':language if rng.random()>.01 else None,'device':device if rng.random()>.01 else None}
    generated.append({'reference':('NEW' if candidate else 'REF')+f'-{i+1:04d}','features':features})
   if not db.scalar(select(CorpusSnapshot).where(CorpusSnapshot.name==title)):
    snap=CorpusSnapshot(name=title,kind=kind,filename=f'yy-corpus-202611-{kind}.csv',description='匿名片段元特征；不含字幕正文；固定seed113。');db.add(snap);db.flush();db.add_all([Utterance(snapshot_id=snap.id,**x) for x in generated]);db.commit()
  if not db.scalar(select(ComparisonRun).where(ComparisonRun.name=='十一月采集分布初校')):
   ref=db.scalar(select(CorpusSnapshot).where(CorpusSnapshot.kind=='reference'));cand=db.scalar(select(CorpusSnapshot).where(CorpusSnapshot.kind=='candidate'));admin=db.scalar(select(User).where(User.role=='admin'));config={'features':list(FEATURES),'bins':6,'smoothing':.5,'fdr_alpha':.05,'slice_language':None,'slice_device':None};result=compare_snapshots(get_utterances(db,ref.id),get_utterances(db,cand.id),config)
   run=ComparisonRun(name='十一月采集分布初校',reference_id=ref.id,candidate_id=cand.id,config=config,status='succeeded',result={k:v for k,v in result.items() if k!='findings'},creator_id=admin.id);db.add(run);db.flush()
   for f in result['findings']:db.add(DriftFinding(run_id=run.id,**f))
   db.flush();ids=list(db.scalars(select(DriftFinding.id).where(DriftFinding.run_id==run.id,DriftFinding.status=='review')))
   db.add(ResamplingPlan(name='移动设备与短片段补采草案',run_id=run.id,finding_ids=ids or list(db.scalars(select(DriftFinding.id).where(DriftFinding.run_id==run.id).limit(1))),target_slice='studio / 长时片段覆盖复核',sample_target=200,rationale='先核对来源和采样口径，再讨论补采，漂移不等于模型质量下降。',creator_id=admin.id));db.add(AuditLog(actor='seed',action='demo.created',detail={'seed':113,'utterances':1800}));db.commit()
  if not db.scalar(select(ImportBatch).where(ImportBatch.name=='十一月补采片段 · 待校验批次')):
   demo=[]
   for i in range(12):
    features={'duration':round(float(rng.lognormal(np.log(2.4),.5)),5),'noise':round(max(0.,float(rng.normal(10.4,3))),5),'token_rate':round(max(.1,float(rng.normal(5.0,.9))),5),'language':str(rng.choice(['zh','en','ja'])),'device':str(rng.choice(['studio','mobile','field'])),}
    demo.append(json.dumps({'reference':f'BAT-{i+1:03d}','features':features},ensure_ascii=False))
   demo[4]='{"reference":"BAT-005","features":{"duration":"3.2","noise":10,"token_rate":5.1,"language":"zh","device":"mobile"}}'
   demo[11]=demo[7]
   admin=db.scalar(select(User).where(User.role=='admin'))
   create_batch(db,BatchInput(name='十一月补采片段 · 待校验批次',kind='candidate',filename='yy-corpus-202611-supplement.json',description='逐行校验演示：第5行类型错误、第12行与第8行编号重复。',content='\n'.join(demo)),admin)
  counts={t.__tablename__:db.scalar(select(func.count()).select_from(t)) for t in [User,CorpusSnapshot,ImportBatch,ImportBatchRow,Utterance,ComparisonRun,DriftFinding,ResamplingPlan]};print(json.dumps(counts));return counts
if __name__=='__main__':seed()
