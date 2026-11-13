import json,math
from datetime import datetime,timezone
from sqlalchemy import select,func
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from src.models import ImportBatch,ImportBatchRow,ImportRowRevision,CorpusSnapshot,Utterance
from src.constants.features import FEATURES,NUMERIC,CATEGORICAL,MISSING,NEW
from src.constants.enums import BatchStatus,BatchRowStatus
from src.utils.serialize import row
from .audit import record

LINE_MAX=20000
CONTENT_MAX=5000000
ERROR_MAX=500

def _short(error):return error[:ERROR_MAX] if error else error

def _canonical(features):return json.dumps(features,sort_keys=True,separators=(',',':'),ensure_ascii=False)

def validate_line(raw_text):
 """只解析一行原文；返回(reference,features,error)。不检查与其他行的编号关系。"""
 raw=raw_text if isinstance(raw_text,str) else ''
 if len(raw)>LINE_MAX:return None,None,f'单行原文超过 {LINE_MAX} 字符'
 text=raw.strip()
 if not text:return None,None,'空行：片段必须为一行 JSON 对象'
 try:data=json.loads(text)
 except json.JSONDecodeError as exc:return None,None,f'JSON 解析失败：{exc.msg}（第{exc.lineno}行第{exc.colno}列）'
 except Exception:return None,None,'JSON 解析失败'
 if not isinstance(data,dict):return None,None,'片段必须为 JSON 对象'
 if 'reference' not in data:return None,None,'缺少片段编号 reference'
 ref=data['reference']
 if not isinstance(ref,str):return None,None,'片段编号 reference 必须为字符串'
 if not ref:return None,None,'片段编号 reference 不能为空'
 if len(ref)>80:return None,None,'片段编号 reference 超过80字符'
 if 'features' not in data:return ref,None,'缺少特征对象 features'
 feats=data['features']
 if not isinstance(feats,dict):return ref,None,'特征 features 必须为 JSON 对象'
 missing=[k for k in FEATURES if k not in feats]
 unknown=[k for k in feats if k not in FEATURES]
 errors=[]
 if missing:errors.append('缺少特征：'+'、'.join(missing))
 if unknown:errors.append('未知特征：'+'、'.join(str(k) for k in unknown))
 cleaned={}
 for key in FEATURES:
  if key not in feats:continue
  value=feats[key]
  if value is None:cleaned[key]=None;continue
  if key in NUMERIC:
   if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):errors.append(f'特征 {key} 必须为有限数字或null')
   else:cleaned[key]=value
  else:
   if not isinstance(value,str) or not 1<=len(value)<=40 or value in (MISSING,NEW):errors.append(f'特征 {key} 必须为非空字符串（1–40字符）且不可使用保留桶名')
   else:cleaned[key]=value
 if errors:return ref,None,'；'.join(errors)
 return ref,{key:cleaned[key] for key in FEATURES},None

def _conflict_error(row_no,ref,other_no,other_features,features):
 if _canonical(other_features)==_canonical(features):return f'编号重复：{ref} 与第 {other_no} 行内容相同'
 return f'编号冲突：{ref} 与第 {other_no} 行内容不一致'

def _group_conflicts(rows):
 """按编号分组，只有解析成功的行参与；组内行号最小者保留，其余明确隔离。"""
 groups={}
 for item in rows:
  if item.features is None:continue
  groups.setdefault(item.reference,[]).append(item)
 for ref,items in groups.items():
  items.sort(key=lambda x:x.line_no);first=items[0]
  first.error=None;first.status=BatchRowStatus.VALID
  for item in items[1:]:
   item.error=_short(_conflict_error(item.line_no,ref,first.line_no,first.features,item.features))
   item.status=BatchRowStatus.QUARANTINED

def _apply_conflicts(rows):
 for item in rows:
  if item.features is None:item.status=BatchRowStatus.QUARANTINED
 _group_conflicts(rows)

def _refresh_conflicts(db,batch_id,references):
 """不重新解析原文，只重算受影响编号组的派生冲突标记。"""
 if not references:return
 rows=list(db.scalars(select(ImportBatchRow).where(ImportBatchRow.batch_id==batch_id,ImportBatchRow.reference.in_(references))))
 for item in rows:
  if item.features is None:item.status=BatchRowStatus.QUARANTINED
 _group_conflicts(rows)

def _revalidate(db,batch_id,item):
 """只重新解析这一行；其他行原文不重新解析。改号时仅重算旧编号组的派生冲突标记。"""
 reference,features,error=validate_line(item.raw_text)
 old_reference=item.reference
 item.reference=reference;item.features=features
 item.error=_short(error);item.status=BatchRowStatus.QUARANTINED if error else BatchRowStatus.VALID
 db.flush()
 if old_reference and old_reference!=reference:_refresh_conflicts(db,batch_id,{old_reference})
 if error:return
 # 同编号冲突只判被修正行：既有合格行不被静默改判。
 others=list(db.scalars(select(ImportBatchRow).where(ImportBatchRow.batch_id==batch_id,ImportBatchRow.id!=item.id,ImportBatchRow.reference==reference,ImportBatchRow.features.is_not(None)).order_by(ImportBatchRow.line_no)))
 if others:
  first=others[0]
  item.error=_short(_conflict_error(item.line_no,reference,first.line_no,first.features,features))
  item.status=BatchRowStatus.QUARANTINED

def _input_lines(data):
 if data.lines is not None:lines=list(data.lines)
 else:
  if len(data.content)>CONTENT_MAX:raise HTTPException(422,'批次原文过大，请拆分为多个批次')
  lines=data.content.splitlines()
  while lines and not lines[-1].strip():lines.pop()
 if len(lines)>5000:raise HTTPException(422,'一个批次最多5000行片段')
 if not lines:raise HTTPException(422,'批次至少需要一行片段')
 total=sum(len(line) for line in lines)
 if total>CONTENT_MAX:raise HTTPException(422,'批次原文过大，请拆分为多个批次')
 for line in lines:
  if len(line)>LINE_MAX:raise HTTPException(422,f'存在超过 {LINE_MAX} 字符的行，请先在源文件中断行')
 return lines

def _counts(rows):
 valid=sum(1 for item in rows if item.status==BatchRowStatus.VALID)
 quarantined=sum(1 for item in rows if item.status==BatchRowStatus.QUARANTINED)
 return {'total':len(rows),'valid':valid,'quarantined':quarantined}

def _snapshot_brief(db,snapshot):
 if not snapshot:return None
 data=row(snapshot)
 data['count']=db.scalar(select(func.count()).select_from(Utterance).where(Utterance.snapshot_id==snapshot.id))
 return data

def _summary(db,batch,rows):
 counts=_counts(rows)
 return {**row(batch),'counts':counts,'row_count':counts['total'],'valid_count':counts['valid'],'quarantined_count':counts['quarantined'],'snapshot':_snapshot_brief(db,db.get(CorpusSnapshot,batch.published_snapshot_id) if batch.published_snapshot_id else None)}

def _revisions(db,batch_id):
 items=list(db.scalars(select(ImportRowRevision).join(ImportBatchRow,ImportRowRevision.row_id==ImportBatchRow.id).where(ImportBatchRow.batch_id==batch_id).order_by(ImportRowRevision.id)))
 grouped={}
 for item in items:grouped.setdefault(item.row_id,[]).append(row(item))
 return grouped

def detail(db,id):
 batch=db.get(ImportBatch,id)
 if not batch:raise HTTPException(404,'批次不存在')
 rows=list(db.scalars(select(ImportBatchRow).where(ImportBatchRow.batch_id==id).order_by(ImportBatchRow.line_no)))
 revisions=_revisions(db,id)
 payload=_summary(db,batch,rows)
 payload['rows']=[{**row(item),'revisions':revisions.get(item.id,[])} for item in rows]
 return payload

def list_batches(db):
 batches=list(db.scalars(select(ImportBatch).order_by(ImportBatch.id.desc())))
 grouped={}
 for batch_id,status,count in db.execute(select(ImportBatchRow.batch_id,ImportBatchRow.status,func.count()).group_by(ImportBatchRow.batch_id,ImportBatchRow.status)):
  grouped.setdefault(batch_id,{BatchRowStatus.VALID:0,BatchRowStatus.QUARANTINED:0})[status]=count
 result=[]
 for batch in batches:
  counts=grouped.get(batch.id,{BatchRowStatus.VALID:0,BatchRowStatus.QUARANTINED:0})
  valid=counts.get(BatchRowStatus.VALID,0);quarantined=counts.get(BatchRowStatus.QUARANTINED,0)
  result.append({**row(batch),'counts':{'total':valid+quarantined,'valid':valid,'quarantined':quarantined},'row_count':valid+quarantined,'valid_count':valid,'quarantined_count':quarantined,'snapshot':_snapshot_brief(db,db.get(CorpusSnapshot,batch.published_snapshot_id) if batch.published_snapshot_id else None)})
 return result

def create_batch(db,data,user):
 if db.scalar(select(ImportBatch).where(ImportBatch.name==data.name)):raise HTTPException(409,'批次名称已存在')
 if db.scalar(select(CorpusSnapshot).where(CorpusSnapshot.name==data.name)):raise HTTPException(409,'快照名称已存在')
 lines=_input_lines(data)
 batch=ImportBatch(name=data.name,kind=data.kind,filename=data.filename or f'{data.name}.json',description=data.description,status=BatchStatus.PENDING,created_by=user.id)
 db.add(batch)
 try:db.flush()
 except IntegrityError:
  db.rollback();raise HTTPException(409,'批次名称已存在')
 items=[]
 for line_no,raw in enumerate(lines,1):
  reference,features,error=validate_line(raw)
  items.append(ImportBatchRow(batch_id=batch.id,line_no=line_no,raw_text=raw,reference=reference,features=features,error=_short(error),status=BatchRowStatus.QUARANTINED if error else BatchRowStatus.VALID))
 _apply_conflicts(items)
 db.add_all(items)
 counts=_counts(items)
 record(db,user.email,'import_batch.created',{'batch_id':batch.id,'total':counts['total'],'valid':counts['valid'],'quarantined':counts['quarantined']})
 return detail(db,batch.id)

def correct_row(db,batch_id,row_id,raw_text,user):
 batch=db.scalar(select(ImportBatch).where(ImportBatch.id==batch_id).with_for_update().execution_options(populate_existing=True))
 if not batch:raise HTTPException(404,'批次不存在')
 if batch.status!=BatchStatus.PENDING:raise HTTPException(409,'批次已发布，内容已冻结，不能再修正')
 if len(raw_text)>LINE_MAX:raise HTTPException(422,f'单行原文最多 {LINE_MAX} 字符')
 item=db.get(ImportBatchRow,row_id)
 if not item or item.batch_id!=batch_id:raise HTTPException(404,'批次行不存在')
 previous_raw,previous_error,previous_status=item.raw_text,item.error,item.status
 item.raw_text=raw_text;item.corrected_at=datetime.now(timezone.utc)
 _revalidate(db,batch_id,item)
 db.add(ImportRowRevision(row_id=item.id,previous_raw=previous_raw,previous_error=previous_error,previous_status=previous_status,new_raw=item.raw_text,new_error=item.error,new_status=item.status,actor=user.email))
 db.flush()
 rows=list(db.scalars(select(ImportBatchRow).where(ImportBatchRow.batch_id==batch_id)))
 record(db,user.email,'import_batch.row_corrected',{'batch_id':batch_id,'row_id':row_id,'line_no':item.line_no,'status':item.status})
 return {**row(item),'revisions':_revisions(db,batch_id).get(item.id,[]),'counts':_counts(rows),'batch_status':batch.status}

def _publish_result(db,batch,snapshot,created):
 counts=_counts(list(db.scalars(select(ImportBatchRow).where(ImportBatchRow.batch_id==batch.id))))
 return {'batch_id':batch.id,'status':batch.status,'created':created,'snapshot_id':snapshot.id if snapshot else None,'published_snapshot_id':batch.published_snapshot_id,'published_at':batch.published_at.isoformat() if batch.published_at else None,'published_by':batch.publisher_id,'snapshot':_snapshot_brief(db,snapshot),'counts':counts}

def _existing_publish(db,batch,id):
 if batch and batch.status==BatchStatus.PUBLISHED and batch.published_snapshot_id:
  return _publish_result(db,batch,db.get(CorpusSnapshot,batch.published_snapshot_id),False)
 return None

def publish_batch(db,id,user):
 # 行锁把并发发布串行化；唯一约束(import_batch_id、快照名)是最后一道保险。
 batch=db.scalar(select(ImportBatch).where(ImportBatch.id==id).with_for_update().execution_options(populate_existing=True))
 if not batch:raise HTTPException(404,'批次不存在')
 existing=_existing_publish(db,batch,id)
 if existing:return existing
 if batch.status!=BatchStatus.PENDING:raise HTTPException(409,'批次状态不允许发布')
 rows=list(db.scalars(select(ImportBatchRow).where(ImportBatchRow.batch_id==id).order_by(ImportBatchRow.line_no)))
 counts=_counts(rows)
 if counts['quarantined']:
  raise HTTPException(409,f"仍有 {counts['quarantined']} 条隔离行未修正，整批不能发布（合格 {counts['valid']} / 隔离 {counts['quarantined']} / 共 {counts['total']}）")
 valid=[item for item in rows if item.status==BatchRowStatus.VALID]
 if not valid:raise HTTPException(409,'批次没有合格片段，不能发布')
 references=[item.reference for item in valid]
 if len(set(references))!=len(references):raise HTTPException(409,'编号冲突：合格行中存在重复编号，请先修正')
 if any(item.features is None for item in valid):raise HTTPException(409,'批次行内容不完整，请先修正')
 if db.scalar(select(CorpusSnapshot).where(CorpusSnapshot.name==batch.name)):raise HTTPException(409,'快照名称已存在，不能发布')
 snapshot=CorpusSnapshot(name=batch.name,kind=batch.kind,filename=batch.filename or f'{batch.name}.json',description=batch.description,import_batch_id=batch.id)
 snapshot_name=batch.name
 db.add(snapshot)
 try:
  db.flush()
  db.add_all([Utterance(snapshot_id=snapshot.id,reference=item.reference,features=item.features) for item in valid])
  batch.status=BatchStatus.PUBLISHED;batch.published_snapshot_id=snapshot.id;batch.published_at=datetime.now(timezone.utc);batch.publisher_id=user.id
  db.commit()
 except IntegrityError:
  db.rollback()
  fresh=db.scalar(select(ImportBatch).where(ImportBatch.id==id).with_for_update().execution_options(populate_existing=True))
  existing=_existing_publish(db,fresh,id)
  if existing:return existing
  if db.scalar(select(CorpusSnapshot).where(CorpusSnapshot.name==snapshot_name)):raise HTTPException(409,'快照名称已存在，不能发布')
  raise HTTPException(409,'发布冲突：快照名称或片段编号触发了数据库唯一约束，请检查后重试')
 record(db,user.email,'import_batch.published',{'batch_id':id,'snapshot_id':snapshot.id,'rows':counts['valid']})
 return _publish_result(db,batch,snapshot,True)
