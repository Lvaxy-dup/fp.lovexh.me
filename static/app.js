import {templateLayout} from '/static/template-layout.js';
import {BrowserSession} from '/static/browser-session.js?v=20260920';
import {SaveQueue} from '/static/save-queue.js?v=20260920';
const browserSession=new BrowserSession();
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
let record=null,kind='application',records=[],config={},dirty=new Map(),saveQueue=null,saveTimer,pollBusy=false,currentZoom=1,manualZoom=null,materialSignature='',uploading=false;
let profile={name:'',job_title:'',department:'',fund_no:'',fund_name:''};
let deleteRecordId=null;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const prose=s=>esc(s).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/^[-*] /gm,'• ');
function toast(text){$('#toast').textContent=text;$('#toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').hidden=true,6000)}
async function api(path,options={}){const r=await fetch('/api'+path,{credentials:'same-origin',...options,headers:{...(options.body instanceof FormData?{}:{'Content-Type':'application/json'}),...options.headers,...browserSession.headers()}});let d;try{d=await r.json()}catch{throw Error('服务器没有返回有效响应')}if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'请求失败，请检查输入');return d}
const endpoint=s=>`/records/${record.id}${s}`;
const field=(key,label='',type='text')=>`<div class="field-wrap ${type==='number'?'number':''}" data-wrap="${key}"><input data-field="${key}" type="${type}" aria-label="${esc(label||config.fields?.[kind]?.[key]||key)}" ${type==='number'?'min="0" step="0.01"':''} placeholder="${type==='text'?'点击填写':''}"><button type="button" class="evidence" data-source="${key}" title="查看填写依据" aria-label="查看${esc(label||key)}填写依据" hidden>来源</button></div>`;
const derived=key=>`<div class="derived" data-derived="${key}"></div>`;
const reasons=['业务工作','会议培训','实习实训','竞赛','招生就业','科研','其他'];
const cats={hotel:'住宿费',meeting:'会务费',training:'培训费',insurance:'保险费',change:'退票/改签费',local:'市内短途车费',other:'其他费用'};
function templateTable(type,content){const layout=templateLayout[type],total=layout.columns.reduce((a,b)=>a+b,0);return `<table class="form-table ${type==='reimbursement'?'report-table':''}"><colgroup>${layout.columns.map(w=>`<col style="width:${w/total*100}%">`).join('')}</colgroup><tbody>${layout.rows.map((row,r)=>`<tr class="template-row row-${r}">${row.cells.map(c=>`<td colspan="${c.colspan}" rowspan="${c.rowspan}" class="cell-${c.index}">${content(r,c.index,c.text)}</td>`).join('')}</tr>`).join('')}</tbody></table>`}
function application(){return `<h2>教职工出差申请表</h2>`+templateTable('application',(r,c,text)=>{
 const slots={'0.1':'name','0.3':'department','0.5':'companions'};
 if(slots[`${r}.${c}`])return field(slots[`${r}.${c}`]);
 if(r===1&&c>0)return `<div class="inline"><span>${c===1?'经费编号：':'经费名称：'}</span>${field(c===1?'fund_no':'fund_name')}</div>`;
 if(r===2&&c===1)return `<div class="checks-inline">${reasons.map(v=>`<label><input type="checkbox" data-reason="${v}">${v}</label>`).join('')}</div>`;
 if(r===3&&c===1)return `<div class="inline date-row">${field('start','','date')}<span>至</span>${field('end','','date')}<span>，共计：</span><span data-derived="days"></span><span>天</span></div>`;
 if(r===3&&c===2)return `<div class="inline"><span>出差地点：</span>${field('destination')}</div>`;
 if(r===4&&c===1)return `<div class="checks-inline plane-options"><label><input type="radio" name="plane" value="是" data-plane>是</label><label><input type="radio" name="plane" value="否" data-plane>否</label></div>`;
 if(r===5&&c===1)return `<div class="field-wrap" data-wrap="purpose"><textarea data-field="purpose" aria-label="简述出差内容" rows="1"></textarea><button class="evidence" data-source="purpose" hidden>来源</button></div>`;
 if(r===6&&c===0)return '费用预算<br><br>（单位：元）';
 if(r>=6&&r<=11&&c===2){const key=['budget_transport','budget_hotel','budget_allowance','budget_meeting','budget_other','budget_total'][r-6];return r===11?derived(key):field(key,'','number')}
 if(r>=12&&c===1)return '<div class="signature-original"><span>签字：</span><span>年　　月　　日</span></div>';
 return esc(text);
 })}
function dateCell(key,part){return part==='month'?`<div class="field-wrap date-part" data-wrap="${key}"><input type="date" data-field="${key}" aria-label="${esc(config.fields.reimbursement[key])}"><span data-date-display="${key}" data-part="month"></span><button class="evidence" data-source="${key}" hidden>来源</button></div>`:`<button class="date-day" data-date-picker="${key}" aria-label="选择${esc(config.fields.reimbursement[key])}"><span data-date-display="${key}" data-part="day"></span></button>`}
function reimbursement(){return `<div class="binding-line"><span>装</span><span>订</span><span>线</span></div><h2>中国矿业大学徐海学院差旅费报销单</h2>`+templateTable('reimbursement',(r,c,text)=>{
 if(r===0)return c===0?'年　月　日':'单位：元';
 const slots={'1.1':'name','1.3':'job_title','1.5':'department','2.1':'fund_no','2.3':'fund_name','2.5':'destination'};
 if(slots[`${r}.${c}`])return field(slots[`${r}.${c}`]);
 if(r>=6&&r<=12){const i=r-6,pre=`trip.${i}.`;
  if(c===0||c===3)return dateCell(pre+(c===0?'start':'end'),'month');
  if(c===1||c===4)return dateCell(pre+(c===1?'start':'end'),'day');
  if(c===2||c===5)return field(pre+(c===2?'start_time':'end_time'),'','time');
  if(c>=6&&c<=9)return field(pre+['origin','destination','mode','fare'][c-6],'',c===9?'number':'text');
  if(c===10||c===11)return derived(`trip.${i}.allowance_${c===10?'days':'total'}`);
  if(c===13)return field('expense_'+Object.keys(cats)[i],'','number');
 }
 if(r===13)return c===0?'小　计':c===4?'小　计':derived({1:'transport_total',2:'allowance_days',3:'allowance_total',5:'other_total'}[c]);
 if(r===14)return c===0?'票面金额合计（大写）：<span data-derived="ticket_upper"></span>':'补助合计：<span data-derived="allowance_total"></span>';
 if(r===15)return c===0?'总计（大写）：<span data-derived="grand_upper"></span>':'¥：<span data-derived="grand_total"></span>';
 return esc(text);
 })}
function buildForm(){const p=$('#paper');p.className='paper '+kind;p.innerHTML=kind==='application'?application():reimbursement();$$('[data-field]').forEach(el=>el.addEventListener('input',()=>queueEdit(el.dataset.field,el.value)));$$('[data-reason]').forEach(el=>el.addEventListener('change',()=>queueEdit('reasons',$$('[data-reason]:checked').map(e=>e.dataset.reason))));$$('[data-plane]').forEach(el=>el.addEventListener('change',()=>queueEdit('plane',el.value)));$$('[data-source]').forEach(el=>el.addEventListener('click',()=>showSource(el.dataset.source)));$('#report-controls').hidden=kind!=='reimbursement';$('#paper-size').textContent=kind==='application'?'A4 纵向':'A4 横向';$('#upload-hint').textContent=kind==='application'?'会议通知、邀请函、活动或培训安排':'车票、酒店发票、会务费或培训费票据';$('#scope-note').textContent=kind==='application'?'仅用于出差申请表':'仅用于差旅报销单';$('#current-form-title').textContent=kind==='application'?'教职工出差申请表':'差旅费报销单';materialSignature='';$$('[data-date-picker]').forEach(b=>b.onclick=()=>{const input=$(`[data-field="${b.dataset.datePicker}"]`);input?.showPicker?.()});requestAnimationFrame(fitPaper)}
function fitPaper(){
 const viewport=$('#paper-viewport'),paper=$('#paper'),stage=$('#paper-stage');
 if(!paper.children.length||!viewport.clientHeight)return;
 const padding=getComputedStyle(stage),width=viewport.clientWidth-parseFloat(padding.paddingLeft)-parseFloat(padding.paddingRight)-2,height=viewport.clientHeight-parseFloat(padding.paddingTop)-parseFloat(padding.paddingBottom)-2;
 // Measure the actual document, including any taller rows after a teacher edits it.
 const fitted=Math.min(width/paper.offsetWidth,height/paper.offsetHeight,1.25);
 currentZoom=manualZoom??Math.max(.05,Math.floor(fitted*1000)/1000);
 const zoom=String(currentZoom);if(paper.style.zoom!==zoom)paper.style.zoom=zoom;
 $('#zoom-level').textContent=Math.round(currentZoom*100)+'%';
 $('#fit').setAttribute('aria-pressed',String(manualZoom===null));
 $('#zoom-out').disabled=currentZoom<=.2;$('#zoom-in').disabled=currentZoom>=1.6;
}
function zoomPaper(delta){manualZoom=Math.max(.2,Math.min(1.6,Math.round((currentZoom+delta)*100)/100));fitPaper()}
function setupSaveQueue(){
 const rid=record.id,form=kind;
 saveQueue=new SaveQueue({storage:localStorage,key:`travel-draft:${browserSession.token}:${rid}:${form}`,
  send:values=>api(`/records/${rid}/fields`,{method:'PATCH',body:JSON.stringify({form,values})}),
  onSaved:next=>{if(record?.id===rid)accept(next)},
  onState:state=>{$('#save-status').textContent={saving:'正在保存…',saved:'已保存',error:'保存失败，点击重试'}[state]}
 });
 dirty=saveQueue.values;
}
function queueEdit(key,value){try{saveQueue.edit(key,value)}catch(e){toast(e.message)}clearTimeout(saveTimer);saveTimer=setTimeout(()=>flush().catch(()=>{}),450)}
async function flush(){clearTimeout(saveTimer);try{await saveQueue?.flush()}catch(e){toast(e.message);throw e}}
function accept(next){if(!record||next.id!==record.id||next.revision>=record.revision){const renamed=record?.id===next.id&&record.title!==next.title;record=next;render();if(renamed)listRecords().catch(()=>{})}}
async function listRecords(){records=await api('/records');$('#records').innerHTML=records.map(r=>`<div class="record-row ${r.id===record?.id?'selected':''}"><button data-record="${r.id}" title="${esc(r.title)}">${esc(r.title)}</button><button class="delete-record" data-delete-record="${r.id}" aria-label="删除出差记录：${esc(r.title)}" title="删除记录"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/></svg></button></div>`).join('');$$('[data-record]').forEach(b=>b.onclick=async()=>{try{await openRecord(b.dataset.record);if(narrowSidebar.matches)setSidebar(true,false)}catch(e){toast(e.message)}});$$('[data-delete-record]').forEach(b=>b.onclick=()=>{deleteRecordId=b.dataset.deleteRecord;$('#delete-record-title').textContent=records.find(r=>r.id===deleteRecordId)?.title||'该记录';$('#delete-record-error').hidden=true;$('#delete-record-dialog').showModal()})}
async function openRecord(id){await flush();record=await api('/records/'+id);localStorage.setItem('travel-record',id);setupSaveQueue();await flush();await fillProfileDefaults();buildForm();render();await listRecords()}
$('#confirm-delete-record').onclick=async()=>{
 const rid=deleteRecordId,dialog=$('#delete-record-dialog');if(!rid)return;
 const buttons=[...dialog.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);$('#delete-record-error').hidden=true;
 try{
  await flush();await api(`/records/${rid}`,{method:'DELETE'});
  if(record?.id===rid){record=null;dirty.clear();localStorage.removeItem('travel-record')}
  await listRecords();
  if(!record){const next=records[0]?.id||(await api('/records',{method:'POST',body:'{}'})).id;await openRecord(next)}
  dialog.close();deleteRecordId=null;toast('出差记录已删除');
 }catch(e){$('#delete-record-error').textContent=e.message;$('#delete-record-error').hidden=false}
 finally{buttons.forEach(b=>b.disabled=false)}
};
$('#delete-record-dialog').addEventListener('cancel',e=>{if($('#confirm-delete-record').disabled)e.preventDefault()});
function render(){if(!record)return;$('#rename').textContent=record.title;const f=record.forms[kind],v=f.values;$$('[data-field]').forEach(el=>{const k=el.dataset.field;if(document.activeElement!==el&&!dirty.has(k))el.value=v[k]??'';if(el.tagName==='TEXTAREA'){el.style.height='auto';el.style.height=Math.max(45,el.scrollHeight)+'px'}const wrap=el.closest('[data-wrap]'),meta=f.meta[k];wrap?.classList.toggle('agent',meta?.owner==='agent');wrap?.classList.toggle('user',meta?.owner==='user');wrap?.classList.toggle('estimated',!!meta?.source?.estimated&&!meta?.source?.budget_estimate&&v[k]!==''&&v[k]!=null);const s=wrap?.querySelector('[data-source]');if(s)s.hidden=!!meta?.source?.budget_estimate||!meta?.source||!Object.keys(meta.source).length});$$('[data-date-display]').forEach(el=>{const parts=(v[el.dataset.dateDisplay]||'').split('-');el.textContent=parts.length===3?String(+parts[el.dataset.part==='month'?1:2]):''});$$('[data-derived]').forEach(el=>el.textContent=v[el.dataset.derived]??'');if(!dirty.has('reasons'))$$('[data-reason]').forEach(el=>el.checked=(v.reasons||[]).includes(el.dataset.reason));if(!dirty.has('plane'))$$('[data-plane]').forEach(el=>el.checked=v.plane===el.value);for(const k of ['start','end'])if(document.activeElement!==$('#report-'+k)&&!dirty.has(k))$('#report-'+k).value=v[k]||'';
 const check=record.checks?.[kind]||{missing:[],warnings:[],estimated:[]};
 const currentMaterials=record.materials.filter(m=>m.form===kind);const globalBusy=record.agent.status==='running'||record.pipeline?.status==='running';const pipeline=record.pipeline?.forms?.includes(kind)?record.pipeline:{};const pending=currentMaterials.some(m=>['queued','running'].includes(m.status));
 $('#agent-dot').classList.toggle('busy',pipeline.status==='running'||pending||uploading);$('#autofill').disabled=globalBusy||uploading||!currentMaterials.length;$('#upload').disabled=globalBusy||uploading;
 $('#activity').textContent=uploading?'正在导入文件…':pipeline.status==='running'?pipeline.message:pending?'正在识别当前表单材料；可继续添加或移除文件。':pipeline.message|| (currentMaterials.length?'材料已就绪，请点击「填写当前表单」。':'先添加材料，再点击填写当前表单。');
 const generated=record.forms[kind].generation;$('#result-stats').textContent=generated?`已填 ${Object.keys(v).filter(k=>config.fields[kind][k]&&v[k]!==''&&v[k]!=null).length} 项 · 推测 ${check.estimated?.length||0} 项 · 留空 ${check.missing.length} 项`:'';
 $('#checks').innerHTML=(pipeline.failed_files?.length?`<div class="warn">未识别成功：${pipeline.failed_files.map(esc).join('、')}。成功材料已继续填写。</div>`:'')+[...(pipeline.errors||[]),...check.warnings].map(w=>`<div class="warn">${esc(w)}</div>`).join('')+(check.missing.length&&generated?`<span>无依据的空白项：${check.missing.slice(0,6).map(x=>esc(x.label)).join('、')}。可直接在表格中补充。</span>`:'');
  $('#application-budget-controls').hidden=kind!=='application';
  if(!dirty.has('has_fee')){$('#has-fee').value=v.has_fee||'';$('#application-has-fee').value=v.has_fee||''}
  if(!dirty.has('lodging_tier'))$('#lodging-tier').value=v.lodging_tier||'';
  $('#allowance-hint').textContent=v.allowance_basis||'每天180元；有会务费或培训费只计首尾，无这两项费用按完整出差日期计算，包含出发日和返回日。';
  renderMaterials(globalBusy);requestAnimationFrame(fitPaper);

}
function renderMaterials(busy=false){const list=record.materials.filter(m=>m.form===kind);$('#material-count').textContent=list.length+' 份';const sig=JSON.stringify([kind,busy,...list.map(m=>[m.id,m.status,m.progress,m.error,m.engine])]);if(sig===materialSignature)return;materialSignature=sig;
 $('#materials').innerHTML=list.length?list.map(m=>`<div class="material"><div class="material-top"><span class="file-icon">${esc(m.name.split('.').pop().toUpperCase().slice(0,4))}</span><button class="material-name" data-material="${m.id}" title="${esc(m.name)}">${esc(m.name)}</button><div class="material-actions">${['error','done'].includes(m.status)?`<button class="retry" data-retry="${m.id}" ${busy?'disabled':''}>重新识别</button>`:''}<button class="remove-material" data-remove="${m.id}" aria-label="移除 ${esc(m.name)}" ${busy?'disabled':''}>移除</button></div></div><div class="material-status ${m.status==='error'?'error':''}">${esc(m.status==='error'?m.error:m.progress||'等待识别')} · ${m.engine==='paddle'?'PaddleOCR':'DeepSeek'}</div></div>`).join(''):'<p class="materials-empty">尚未添加材料。此处仅显示当前表单的文件。</p>';
 $$('[data-material]').forEach(el=>el.onclick=()=>showMaterial(el.dataset.material));
 $$('[data-retry]').forEach(el=>el.onclick=async()=>{try{await api(endpoint(`/materials/${el.dataset.retry}/retry`),{method:'POST',body:JSON.stringify({engine:engine()})});toast('已重新识别，完成后点击填写当前表单');await refresh()}catch(e){toast(e.message)}});
 $$('[data-remove]').forEach(el=>el.onclick=async()=>{const rid=record.id;el.disabled=true;try{await flush();const result=await api(`/records/${rid}/materials/${el.dataset.remove}`,{method:'DELETE'});if(record?.id===rid)accept(result.record);toast(result.cleared_fields.length?'已移除文件及其自动填写内容，手工修改已保留':'文件已移除')}catch(e){toast(e.message);el.disabled=false}});
}
function engine(){return $('input[name=engine]:checked').value}
async function uploadFiles(files){if(!record||uploading||record.pipeline?.status==='running')return;await flush();const rid=record.id,form=kind;uploading=true;render();let accepted=0;try{for(const file of files){const body=new FormData();body.append('file',file);body.append('engine',engine());body.append('form',form);try{const r=await api(`/records/${rid}/materials`,{method:'POST',body});accepted++;if(r.duplicate)toast(file.name+' 已导入，将复用识别结果')}catch(e){toast(file.name+'：'+e.message)}}$('#files').value='';if(record.id===rid)await refresh();if(accepted)toast('材料已添加，检查后点击「填写当前表单」')}finally{uploading=false;render()}}
async function generateForms(form=kind,rid=record?.id){if(!rid)return;await flush();const next=await api(`/records/${rid}/generate`,{method:'POST',body:JSON.stringify({form,request_id:crypto.randomUUID()})});if(record?.id===rid)accept(next);}
async function refresh(){if(!record||pollBusy)return;const rid=record.id;pollBusy=true;try{const d=await api('/records/'+rid);if(record?.id===rid)accept(d)}finally{pollBusy=false}}
function showMaterial(id,page=null){const m=record.materials.find(m=>m.id===id);if(!m)return;$('#source-title').textContent=m.name;$('#source-body').innerHTML=`<p><a href="/api/records/${record.id}/materials/${m.id}/original" target="_blank" rel="noopener">打开原始文件</a></p>`+(m.pages.length?m.pages.filter(p=>!page||p.page===page).map(p=>`<h3>${p.page_label?esc(p.page_label):'第 '+p.page+' 页'}</h3><pre>${esc(p.text)}</pre>`).join(''):`<p>${esc(m.error||m.progress||'尚未完成识别')}</p>`);$('#source-dialog').showModal()}
function showSource(key){const m=record.forms[kind].meta[key],s=m?.source;if(s?.budget_estimate)return;if(s?.profile){$('#source-title').textContent='来自个人信息';$('#source-body').textContent='此项来自你保存的个人信息。点击左下角头像可以查看或修改；也可以直接修改当前表格。';$('#source-dialog').showModal();return}if(s?.estimated){$('#source-title').textContent=(config.fields[kind][key]||'字段')+' · 推测依据';$('#source-body').innerHTML=`<p>此内容由模型推测，尚未核实。可直接修改表格。</p><pre>${esc(s.reason||'')}</pre>${s.duration_minutes?`<p>推算时长：${esc(s.duration_minutes)} 分钟</p>`:''}`;$('#source-dialog').showModal();return}if(s?.other_form){$('#source-title').textContent='来自同次出差的另一张表';$('#source-body').innerHTML=`<p>沿用了另一张表已填写的${esc(config.fields[kind][key]||key)}。</p>`;$('#source-dialog').showModal();return}if(s?.material_id){showMaterial(s.material_id,s.page);return}$('#source-title').textContent=config.fields[kind][key]||'填写依据';$('#source-body').innerHTML=`<p>${m?.owner==='user'?'由你直接填写或选择留空。':'依据对话中的补充信息填写。'}</p>${s?.quote?`<pre>${esc(s.quote)}</pre>`:''}`;$('#source-dialog').showModal()}
async function preparePrint(){await flush();await refresh();const c=record.checks[kind];$('#print-description').textContent=(kind==='application'?'教职工出差申请表 · A4 纵向':'差旅费报销单 · A4 横向')+'。打印内容与当前表格一致。';$('#print-checks').innerHTML=[...c.warnings,...c.missing.map(x=>x.label+' 尚未填写')].map(x=>`<li>${esc(x)}</li>`).join('')||'<li>必需信息已填写或已选择留空。</li>';$('#print-dialog').showModal()}
function printNow(){if(dirty.size){toast('仍有未保存修改，请关闭预览并重试');return}$('#print-dialog').close();$$('.print-value').forEach(e=>e.remove());$$('#paper input:not([type=checkbox]):not([type=radio]),#paper textarea').forEach(el=>{const span=document.createElement('span');span.className='print-value';let value=el.value;if(el.closest('.date-part'))return;if(el.type==='date'&&value){const[y,m,d]=value.split('-');value=kind==='application'?`${y}年${+m}月${+d}日`:`${+m}月${+d}日`}span.textContent=value;el.after(span)});$$('.inference-print-note').forEach(e=>e.remove());const estimates=record.checks[kind].estimated||[];if(estimates.length){const note=document.createElement('div');note.className='inference-print-note';note.textContent='推测草稿：'+estimates.map(e=>`${e.label} ${Array.isArray(e.value)?e.value.join('、'):e.value}`).join('；')+'。相应期间补助为暂估，待核对。';$('#paper').append(note)}let style=$('#print-page-style');if(!style){style=document.createElement('style');style.id='print-page-style';document.head.append(style)}style.textContent=`@media print{@page{size:A4 ${kind==='application'?'portrait':'landscape'};margin:0}`;const prior=document.title;document.title=record.title+'-'+(kind==='application'?'出差申请表':'差旅报销单');window.print();document.title=prior}
$('#new-record').onclick=async()=>{try{await flush();const d=await api('/records',{method:'POST',body:'{}'});await openRecord(d.id);if(narrowSidebar.matches)setSidebar(true,false)}catch(e){toast(e.message)}};
function syncFormSelection(){
 $$('[data-form]').forEach(b=>{const selected=b.dataset.form===kind;b.classList.toggle('active',selected);b.setAttribute('aria-selected',String(selected));b.querySelector('.choice-state').textContent=selected?'已选择':'选择'});
}
$$('[data-form]').forEach(el=>el.onclick=async()=>{try{await flush();kind=el.dataset.form;setupSaveQueue();await flush();localStorage.setItem('travel-form',kind);manualZoom=null;syncFormSelection();buildForm();render();await fillProfileDefaults();render();$('#paper-viewport').scrollTo(0,0)}catch(e){toast(e.message)}});
for(const k of ['start','end'])$('#report-'+k).addEventListener('input',e=>queueEdit(k,e.target.value));
$('#has-fee').onchange=e=>queueEdit('has_fee',e.target.value);
$('#application-has-fee').onchange=e=>queueEdit('has_fee',e.target.value);
$('#lodging-tier').onchange=e=>queueEdit('lodging_tier',e.target.value);
$('#files').onchange=e=>uploadFiles(e.target.files).catch(e=>toast(e.message));$('#upload').onclick=()=>$('#files').click();
for(const ev of ['dragenter','dragover'])$('#upload').addEventListener(ev,e=>{e.preventDefault();$('#upload').classList.add('drag')});for(const ev of ['dragleave','drop'])$('#upload').addEventListener(ev,e=>{e.preventDefault();$('#upload').classList.remove('drag')});$('#upload').addEventListener('drop',e=>uploadFiles(e.dataTransfer.files).catch(e=>toast(e.message)));
$('#autofill').onclick=()=>generateForms().catch(e=>toast(e.message));
$('#rename').onclick=()=>{$('#record-title').value=record.title;$('#rename-dialog').showModal()};$('#rename-form').onsubmit=async e=>{e.preventDefault();try{accept(await api(endpoint('/title'),{method:'PATCH',body:JSON.stringify({title:$('#record-title').value.trim()})}));$('#rename-dialog').close();await listRecords()}catch(e){toast(e.message)}};$$('.close-dialog').forEach(b=>b.onclick=()=>b.closest('dialog').close());
$('#fit').onclick=()=>{manualZoom=null;fitPaper();$('#paper-viewport').scrollTo(0,0)};
$('#zoom-in').onclick=()=>zoomPaper(.1);$('#zoom-out').onclick=()=>zoomPaper(-.1);
// Only intercept Ctrl+wheel inside the preview, including focused form inputs.
$('#paper-viewport').addEventListener('wheel',e=>{
 if(!e.ctrlKey)return;
 e.preventDefault();
 e.stopPropagation();
 if(e.deltaY)zoomPaper(e.deltaY<0?.05:-.05);
},{passive:false,capture:true});
$('#print').onclick=()=>preparePrint().catch(e=>toast(e.message));$('#confirm-print').onclick=printNow;
const paperObserver=new ResizeObserver(()=>requestAnimationFrame(fitPaper));paperObserver.observe($('#paper-viewport'));paperObserver.observe($('#paper'));
document.fonts.ready.then(fitPaper);
window.addEventListener('beforeunload',e=>{if(saveQueue?.pending){e.preventDefault();e.returnValue=''}});
window.addEventListener('online',()=>flush().catch(()=>{}));
$('#save-status').onclick=()=>flush().catch(()=>{});
const narrowSidebar=matchMedia('(max-width:1150px)'),narrowMaterials=matchMedia('(max-width:900px)');
function syncPanels(){
 const focused=document.body.classList.contains('focus-mode'),materialsOpen=!document.body.classList.contains('materials-collapsed')&&!focused,sidebarOpen=!document.body.classList.contains('sidebar-collapsed')&&!focused;
 $('#materials-toggle').setAttribute('aria-expanded',String(materialsOpen));
 const overlay=(narrowMaterials.matches&&materialsOpen)||(narrowSidebar.matches&&sidebarOpen);
 $('#panel-backdrop').hidden=!overlay;
 $('#document-editor').inert=overlay;$('.form-selector').inert=overlay;$('.topbar').inert=overlay;
 $('#sidebar').inert=narrowMaterials.matches&&materialsOpen;$('#materials-panel').inert=narrowSidebar.matches&&sidebarOpen;
 requestAnimationFrame(fitPaper);
}
function setSidebar(collapsed,persist=true){document.body.classList.toggle('sidebar-collapsed',collapsed);$('#sidebar-toggle').setAttribute('aria-expanded',String(!collapsed));$('#sidebar-toggle').setAttribute('aria-label',collapsed?'展开侧栏':'收起侧栏');$('#sidebar-toggle').title=collapsed?'展开侧栏':'收起侧栏';$('#sidebar-content').inert=collapsed;if(persist)localStorage.setItem('travel-sidebar-collapsed',String(collapsed));if(!collapsed&&narrowSidebar.matches){document.body.classList.add('materials-collapsed')}syncPanels()}
function setMaterials(collapsed){document.body.classList.toggle('materials-collapsed',collapsed);if(!collapsed&&narrowMaterials.matches)setSidebar(true,false);syncPanels()}
function setFocus(focused){document.body.classList.toggle('focus-mode',focused);$('#focus-toggle').setAttribute('aria-pressed',String(focused));$('#focus-toggle').setAttribute('aria-label',focused?'退出专注模式':'进入专注模式');$('#focus-toggle').title=focused?'退出专注模式':'专注模式 · 收起两侧面板';manualZoom=null;syncPanels()}
$('#sidebar-toggle').onclick=()=>setSidebar(!document.body.classList.contains('sidebar-collapsed'));
setSidebar(narrowSidebar.matches||localStorage.getItem('travel-sidebar-collapsed')==='true',false);
setMaterials(narrowMaterials.matches);
$('#materials-toggle').onclick=()=>{const opening=document.body.classList.contains('materials-collapsed')||document.body.classList.contains('focus-mode');if(document.body.classList.contains('focus-mode'))setFocus(false);setMaterials(!opening);if(opening&&narrowMaterials.matches)$('#materials-close').focus()};
$('#materials-close').onclick=()=>{setMaterials(true);$('#materials-toggle').focus()};
$('#focus-toggle').onclick=()=>setFocus(!document.body.classList.contains('focus-mode'));
function closeOverlays(){if(narrowSidebar.matches)setSidebar(true,false);if(narrowMaterials.matches)setMaterials(true)}
$('#panel-backdrop').onclick=closeOverlays;
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('dialog[open]')){closeOverlays();if(document.body.classList.contains('focus-mode'))setFocus(false)}});
narrowSidebar.addEventListener('change',e=>{setSidebar(e.matches||localStorage.getItem('travel-sidebar-collapsed')==='true',false)});
narrowMaterials.addEventListener('change',e=>setMaterials(e.matches));
$$('[data-form]').forEach((button,index)=>button.addEventListener('keydown',e=>{if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();const other=$$('[data-form]')[1-index];other.focus();other.click()}}));
function renderProfile(){
 $$('[data-profile-avatar]').forEach(e=>e.textContent=profile.name?.slice(0,1)||'徐');
 $$('[data-profile-name]').forEach(e=>e.textContent=profile.name||'个人信息');
 $$('[data-profile-department]').forEach(e=>{e.textContent=profile.department||'设置姓名、职务和部门';e.title=e.textContent});
}
async function fillProfileDefaults(){
 if(!record||!profile.name||record.agent.status==='running'||record.pipeline?.status==='running')return;
 const rid=record.id,selected=kind,f=record.forms[selected];
 if(!['name','department','job_title','fund_no','fund_name'].some(k=>config.fields[selected][k]&&profile[k]&&!f.values[k]&&f.meta[k]?.owner!=='user'))return;
 const next=await api(`/records/${rid}/profile`,{method:'POST',body:JSON.stringify({form:selected})});
 if(record?.id===rid&&next.revision>=record.revision)record=next;
}
function openProfile(first=false){
 $('#profile-heading').textContent=first?'先完善你的基本信息':'个人信息设置';
 $('#profile-description').textContent=first?'完善基本信息和经费编号，以后自动带入表单。':'在这里查看或修改，下次填写时会使用最新信息。';
 $('#profile-later').textContent=first?'稍后填写':'取消';
 $('#profile-name').value=profile.name||'';$('#profile-job-title').value=profile.job_title||'';$('#profile-department').value=profile.department||'';
 $('#profile-fund-no').value=profile.fund_no||'';previewFundName();
 $('#profile-preview-avatar').textContent=profile.name?.slice(0,1)||'徐';$('#profile-error').hidden=true;$('#profile-dialog').showModal();
}
$('#export-session').onclick=async()=>{
 try{await flush();const blob=new Blob([JSON.stringify({version:1,token:browserSession.token})],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='差旅记录找回文件.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(e){toast(e.message)}
};
$('#restore-session').onclick=()=>$('#session-file').click();
$('#session-file').onchange=async e=>{
 try{const file=e.target.files[0];if(!file)return;if(file.size>4096)throw Error('找回文件格式不正确');await flush();const data=JSON.parse(await file.text());if(data.version!==1)throw Error('找回文件版本不支持');await browserSession.restoreToken(data.token);localStorage.removeItem('travel-record');location.reload()}catch(e){toast(e.message)}finally{e.target.value=''}
};
$$('[data-profile-open]').forEach(b=>b.onclick=()=>openProfile());
$('#profile-name').oninput=e=>$('#profile-preview-avatar').textContent=e.target.value.trim().slice(0,1)||'徐';
function previewFundName(){const department=$('#profile-department').value.trim();$('#profile-fund-name').value=department?department+'经费':''}
$('#profile-department').oninput=previewFundName;
$('#profile-later').onclick=()=>$('#profile-dialog').close();
$('#profile-dialog').addEventListener('close',()=>localStorage.setItem('travel-profile-dismissed','true'));
$('#profile-form').onsubmit=async e=>{
 e.preventDefault();const button=$('#profile-save');button.disabled=true;$('#profile-error').hidden=true;
 try{
  const values={name:$('#profile-name').value.trim(),job_title:$('#profile-job-title').value.trim(),department:$('#profile-department').value.trim(),fund_no:$('#profile-fund-no').value.trim()};
  if(Object.values(values).some(v=>!v))throw Error('请填写姓名、职务、所属部门和经费编号，不能只输入空格。');
  await flush();profile=await api('/profile',{method:'PUT',body:JSON.stringify(values)});renderProfile();
  $('#profile-dialog').close();toast('个人信息已保存，下次填写将自动带入');
  try{await fillProfileDefaults();render()}catch(err){toast('个人信息已保存。'+err.message)}
 }catch(err){$('#profile-error').textContent=err.message;$('#profile-error').hidden=false}finally{button.disabled=false}
};
async function init(){await browserSession.initialize();config=await api('/config');if(!config.deepseek_ready)toast('请在后端配置 DeepSeek API Key');profile=await api('/profile');renderProfile();records=await api('/records');let id=localStorage.getItem('travel-record');if(!records.some(r=>r.id===id))id=records[0]?.id;if(!id)id=(await api('/records',{method:'POST',body:'{}'})).id;const savedForm=localStorage.getItem('travel-form');kind=savedForm==='reimbursement'?'reimbursement':'application';syncFormSelection();await openRecord(id);if((!profile.name&&localStorage.getItem('travel-profile-dismissed')!=='true')||(profile.name&&!profile.fund_no))openProfile(true);setInterval(()=>{if(!document.hidden&&record&&(record.agent.status==='running'||record.pipeline?.status==='running'||record.materials.some(m=>['queued','running'].includes(m.status))))refresh().catch(()=>{})},1800);setInterval(()=>{if(!document.hidden)refresh().catch(()=>{})},15000)}
init().catch(e=>toast(e.message));
