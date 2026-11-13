<script setup lang="ts">
import {ref,reactive,computed} from 'vue'
import type {Snapshot,Utterance,User,ImportBatch,BatchRow} from '../types/domain'
import {snapshotApi} from '../api/snapshots'
import {useAsync} from '../hooks/useAsync'
import PageTitle from '../components/common/PageTitle.vue'
import Table from '../components/common/Table.vue'
import Badge from '../components/common/Badge.vue'
import Notice from '../components/common/Notice.vue'
import {date} from '../utils/format'
const props=defineProps<{snapshots:Snapshot[];batches:ImportBatch[];features:Record<string,string>;user:User;reload:()=>Promise<any>}>()
const utterances=ref<Utterance[]>([]),showImport=ref(false),mode=ref<'batch'|'legacy'>('batch')
const name=ref(''),kind=ref('candidate'),filename=ref(''),description=ref(''),raw=ref(''),legacyJson=ref('')
const detail=ref<ImportBatch|null>(null),detailLoading=ref(false),openId=ref(0)
const drafts=reactive<Record<number,string>>({}),editing=ref(0)
const {task,act}=useAsync()
const publishResult=ref<any>(null)
const pendingCount=computed(()=>detail.value?.counts.quarantined??0)
const canWrite=computed(()=>props.user.role!=='viewer')
const isPending=computed(()=>detail.value?.status==='pending')
async function loadBatches(){await props.reload()}
async function openBatch(id:number){
 detailLoading.value=true
 try{
  if(id!==openId.value)publishResult.value=null
  detail.value=await snapshotApi.batch(id);openId.value=id;editing.value=0
 }catch(e){task.error=e.message}
 finally{detailLoading.value=false}
}
async function createBatch(){
 await act(async()=>{
  const created=await snapshotApi.createBatch({name:name.value,kind:kind.value,filename:filename.value,description:description.value,content:raw.value})
  await loadBatches();await openBatch(created.id);showImport.value=false
 },'批次已建立，逐行结果已保留')
}
async function createLegacy(){
 await act(async()=>{
  await snapshotApi.create({name:name.value,kind:kind.value,filename:filename.value||name.value+'.json',description:description.value||'研究员导入的匿名元特征',utterances:JSON.parse(legacyJson.value)})
  await loadBatches();showImport.value=false
 },'快照已导入')
}
function startEdit(row:BatchRow){editing.value=row.id;drafts[row.id]=row.raw_text}
function cancelEdit(){editing.value=0}
async function saveEdit(row:BatchRow){
 await act(async()=>{
  const result=await snapshotApi.correctRow(row.batch_id,row.id,drafts[row.id])
  await openBatch(row.batch_id);await loadBatches()
  editing.value=0
  return result
 },`第 ${row.line_no} 行已只重验本行，结果见行状态与修正记录`)
}
async function publish(){
 await act(async()=>{
  publishResult.value=await snapshotApi.publish(detail.value!.id)
  await openBatch(detail.value!.id);await loadBatches()
 },'批次已发布；快照内容冻结')
}
function draftFor(row:BatchRow){return drafts[row.id]??row.raw_text}
</script>
<template>
<PageTitle index="02 / SOURCE MATERIAL" title="同一把标尺，始于两份来源。" description="匿名片段只保留时长、噪声、语速、语言与设备类别。缺失值进入独立桶，新类别与参考缺失分开计数。导入先进入待校验批次，逐行保留原文、错误与处置状态。">
 <button v-if="canWrite" @click="showImport=!showImport">建立待校验批次 ↗</button>
</PageTitle>
<Notice :error="task.error" :message="task.message"/>
<form class="editor" v-if="showImport" @submit.prevent="mode==='batch'?createBatch():createLegacy()">
 <h2>导入匿名片段</h2>
 <div class="mode-switch"><label><input type="radio" value="batch" v-model="mode"/>待校验批次（逐行隔离，推荐）</label><label><input type="radio" value="legacy" v-model="mode"/>原有JSON数组导入（直接生成快照）</label></div>
 <div class="form-grid"><label>名称<input v-model="name" maxlength="100" required/></label><label>快照用途<select v-model="kind"><option value="candidate">候选新增</option><option value="reference">参考冻结</option></select></label><label>源文件名<input v-model="filename" maxlength="160" :placeholder="name+'.json'"/></label><label>说明<input v-model="description" maxlength="500" placeholder="匿名元特征；按行导入"/></label></div>
 <template v-if="mode==='batch'">
  <label>片段原文 / 每行一个 JSON 对象<textarea v-model="raw" rows="7" required placeholder='{"reference":"NEW-001","features":{"duration":3.1,"noise":10,"token_rate":4.8,"language":"zh","device":"mobile"}}&#10;{"reference":"NEW-002","features":{...}}'/></label>
  <p>一行只放一个片段。解析失败、字段非法或编号冲突的行进入隔离区并保留原文；修正隔离行时只重验该行。存在隔离行时整批不能发布。</p>
  <button class="primary" :disabled="task.busy">逐行校验并建立批次</button>
 </template>
 <template v-else>
  <label>片段JSON数组<textarea v-model="legacyJson" rows="6" required placeholder='[{"reference":"NEW-001","features":{...}},…]'/></label>
  <p>原有导入保持可用：20–5000条、reference唯一、五特征完整，整批校验失败则不落库。需要逐行修正请使用待校验批次。</p>
  <button class="primary" :disabled="task.busy">校验并导入快照</button>
 </template>
</form>

<div class="section-title"><h2>待校验批次</h2><small>合格 + 隔离 = 批次总行数；发布前不参与比较</small></div>
<Table :headers="['批次 / 源文件','用途','行数核对','状态 / 发布结果','']">
 <tr v-for="b in batches" :key="b.id">
  <td><strong>{{b.name}}</strong><small>{{b.filename}} · 建立 {{date(b.created_at)}}</small></td>
  <td>{{b.kind==='reference'?'参考冻结':'候选新增'}}</td>
  <td class="number-cell"><b>{{b.counts.total}}</b> 行<small>合格 {{b.counts.valid}} / 隔离 {{b.counts.quarantined}}</small></td>
  <td><Badge :status="b.status"/><small v-if="b.snapshot">快照 #{{b.snapshot.id}} · {{b.snapshot.count}} 片段 · {{b.published_at?date(b.published_at):''}}</small><small v-else>隔离清零后方可发布</small></td>
  <td><button class="text-button" @click="openBatch(b.id)">查看逐行结果 ↗</button></td>
 </tr>
</Table>
<p v-if="!batches.length" class="fine">尚无批次。导入时选择“待校验批次”，逐行结果会保留在这里。</p>
<p v-if="detailLoading" class="fine">正在读取逐行结果…</p>

<section v-if="detail" class="batch-detail">
 <div class="section-title"><h2>批次 #{{detail.id}} · {{detail.name}}</h2><small>{{detail.filename}} · {{detail.status==='pending'?'待校验，未参与比较':'已发布，内容冻结'}}</small></div>
 <div class="batch-meta">
  <span>用途 <b>{{detail.kind==='reference'?'参考冻结':'候选新增'}}</b></span>
  <span>总行数 <b>{{detail.counts.total}}</b></span>
  <span>合格 <b>{{detail.counts.valid}}</b></span>
  <span>隔离 <b>{{detail.counts.quarantined}}</b></span>
  <span v-if="detail.published_at">发布于 {{date(detail.published_at)}} · 操作者 #{{detail.publisher_id}}</span>
 </div>
 <Notice v-if="detail.counts.quarantined" :error="`仍有 ${detail.counts.quarantined} 条隔离行：整批不能发布，请逐行修正。`"/>
 <div v-if="publishResult" class="notice success">发布完成：快照 #{{publishResult.snapshot_id}} 共 {{publishResult.counts.valid}} 条合格片段；重复发布返回同一份快照，不再生成新副本。</div>
 <div class="batch-actions" v-if="canWrite&&isPending">
  <button class="primary" :disabled="task.busy||pendingCount>0" @click="publish">{{pendingCount?'隔离行未清零，暂不可发布':'发布为完整快照 →'}}</button>
  <small>发布时一次生成完整快照；重试或并发发布只保留一份。</small>
 </div>
 <div v-else-if="detail.status==='published'" class="batch-actions"><small>批次已发布，行原文与校验结果只读；发布结果：快照 #{{detail.published_snapshot_id}}，共 {{detail.counts.valid}} 条。</small></div>
 <div class="table-wrap batch-table"><table>
  <thead><tr><th>行号</th><th>状态</th><th>编号</th><th>原文 / 校验</th><th>修正记录</th><th></th></tr></thead>
  <tbody>
   <tr v-for="row in detail.rows" :key="row.id" :class="['batch-row',row.status]">
    <td class="mono">{{row.line_no}}</td>
    <td><Badge :status="row.status"/><small v-if="row.corrected_at">修正于 {{date(row.corrected_at)}}</small></td>
    <td class="mono">{{row.reference??'—'}}</td>
    <td>
     <template v-if="editing===row.id">
      <textarea v-model="drafts[row.id]" rows="4" class="row-editor" aria-label="修正原文"/>
     </template>
     <template v-else>
      <code class="raw-line">{{row.raw_text||'（空行）'}}</code>
      <small class="row-error" v-if="row.error">{{row.error}}</small>
      <small v-else-if="row.features">已通过：编号、五项特征与取值均可解析</small>
     </template>
    </td>
    <td class="revision-cell">
     <template v-if="row.revisions.length">
      <div v-for="rev in row.revisions" :key="rev.id" class="revision">
       <small>{{date(rev.created_at)}} · {{rev.actor}}</small>
       <small>前次 {{rev.previous_status==='valid'?'合格':'隔离'}}：{{rev.previous_error||'无错误'}}</small>
       <small>改为 {{rev.new_status==='valid'?'合格':'隔离'}}：{{rev.new_error||'无错误'}}</small>
      </div>
     </template>
     <small v-else>—</small>
    </td>
    <td>
     <template v-if="isPending&&canWrite&&row.status==='quarantined'">
      <template v-if="editing===row.id">
       <button class="primary small-button" :disabled="task.busy" @click="saveEdit(row)">只重验本行</button>
       <button class="text-button" @click="cancelEdit">取消</button>
      </template>
      <button v-else class="text-button" @click="startEdit(row)">修正本行 ↗</button>
     </template>
     <small v-else-if="!isPending">已冻结</small>
    </td>
   </tr>
  </tbody>
 </table></div>
 <p class="fine">修正只重新解析该行并检查同编号冲突；其他行原文不会重新解析，仅旧编号组的冲突标记会随之重算。同编号不同内容会明确隔离并标出冲突行号，即使内容完全相同也按重复编号隔离。</p>
</section>

<div class="section-title"><h2>已发布快照</h2><small>批次发布快照与原有导入快照均在此列出</small></div>
<Table :headers="['快照 / 源文件','用途','片段数','说明','']">
 <tr v-for="s in snapshots" :key="s.id"><td><strong>{{s.name}}</strong><small>{{s.filename}}<template v-if="s.import_batch_id"> · 批次 #{{s.import_batch_id}}</template></small></td><td>{{s.kind==='reference'?'参考冻结':'候选新增'}}</td><td class="number">{{s.count}}</td><td class="description-cell">{{s.description}}</td><td><button class="text-button" @click="act(async()=>utterances=await snapshotApi.utterances(s.id),'')">查看前100片段 ↗</button></td></tr>
</Table>
<div class="source-principle"><b>来源检查</b><p>参考箱只从参考样本拟合；候选的极端值进入冻结尾箱，不改变边界。类别参考未出现的值进入新类别桶，null进入缺失桶。KS仅比较连续特征非缺失值，缺失比例由箱计数另行呈现。待校验批次在发布前不进入比较；发布后快照内容冻结。</p></div>
<template v-if="utterances.length"><div class="section-title"><h2>匿名元特征样本</h2><small>展示前{{utterances.length}}条；计算使用全量切片</small></div><Table :headers="['片段',...Object.values(features)]"><tr v-for="u in utterances" :key="u.id"><td class="mono">{{u.reference}}</td><td v-for="key in Object.keys(features)" :key="key">{{u.features[key]??'缺失'}}</td></tr></Table></template>
</template>
