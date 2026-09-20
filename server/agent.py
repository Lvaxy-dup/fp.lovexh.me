"""Bounded tool-use loop inspired by student-handbook/server/agent.py."""
import asyncio
import copy
from datetime import datetime, timezone, timedelta
import hashlib
import json
from jsonschema import validate as schema_validate, ValidationError
from .config import ROOT
from .provider import completion
from .forms import FIELDS,CATEGORIES,REASONS,patch,validate,money,recalculate,reimbursement_receipt
from .transport import record_transport_invoice, estimate_flight_times
from .invoice_amounts import verify_invoice_amount

S={'type':'string'}
SOURCE={'type':'object','properties':{'material_id':S,'page':{'type':'integer','minimum':1},'user':{'type':'boolean'}},'additionalProperties':False}

def spec(name,description,properties,required=()):
    return {'type':'function','function':{'name':name,'description':description,'parameters':{'type':'object','properties':properties,'required':list(required),'additionalProperties':False}}}

TOOLS=[
 spec('get_form_state','读取当前表单、字段白名单、来源和人工修改状态。',{}),
 spec('read_material','读取材料某一页；材料清单中的 page_count 表示总页数。',{'material_id':S,'page':{'type':'integer','minimum':1}},['material_id','page']),
 spec('fill_fields','批量填写当前表单的允许字段，每批填写共享同一来源。金额合计由程序计算。',{'values':{'type':'object'},'source':SOURCE},['values','source']),
 spec('record_expense','记录一张非交通费用票据，多次调用相同票据只更新一次。',{'invoice_no':S,'category':{'enum':list(CATEGORIES)},'amount':{'type':['string','number']},'source':SOURCE},['invoice_no','category','amount','source']),
 spec('record_transport_invoice','先填写行程，再一次登记一张交通票据覆盖的全部 rows 和含税总额 total。只有往返总额时程序将总额除以2，分别填入去程和返程；多段按段数均分，分币尾差由程序处理，分配合计始终等于票面总额。不可编造分段票号。同票再次调用更新原行程。所有交通票号和金额必须使用本工具。',{'rows':{'type':'array','items':{'type':'integer','minimum':0,'maximum':6},'minItems':1,'maxItems':7,'uniqueItems':True},'invoice_no':S,'total':{'type':['string','number']},'source':SOURCE},['rows','invoice_no','total','source']),
 spec('estimate_flight_times','飞机票缺少起止时刻时，根据航班、线路推测 duration_minutes；出发时刻也缺失时提供 departure_time 暂定时刻。日期沿用票面，跨日由程序计算，全部推测保留依据，不覆盖事实或人工值。',{'row':{'type':'integer','minimum':0,'maximum':6},'duration_minutes':{'type':'integer','minimum':5,'maximum':1440},'departure_time':{'type':'string','pattern':'^[0-2][0-9]:[0-5][0-9]$'},'reason':{'type':'string','minLength':8,'maxLength':1000},'source':SOURCE},['row','duration_minutes','reason','source']),
 spec('estimate_train_arrival','火车票缺少到达时间时，根据已读取的车次、起止站和出发时间推算行车分钟数；程序计算跨日到达时间，保存为估算。',{'row':{'type':'integer','minimum':0,'maximum':6},'duration_minutes':{'type':'integer','minimum':5,'maximum':4320},'reason':{'type':'string','minLength':8,'maxLength':1000}},['row','duration_minutes','reason']),
 spec('validate_form','重算并检查当前表单，返回未填必需字段与警告。',{}),
 spec('infer_fields','根据已读材料推测非身份、非票据金额字段；所有推测保存为估算，不能填造姓名、费用、票号或经费编号。',{'values':{'type':'object'},'reason':{'type':'string','minLength':8},'source':SOURCE},['values','reason','source']),
 spec('ask_user','就必须填写但无法确定的字段向用户提问，已填或跳过字段会过滤。',{'questions':{'type':'array','maxItems':8,'items':{'type':'object','properties':{'field':S,'question':S},'required':['field','question'],'additionalProperties':False}}},['questions']),
 spec('skip_fields','仅在用户明确表示不知道或不用填时，将指定字段留空且不再追问。',{'fields':{'type':'array','items':S}},['fields']),
]
for tool in TOOLS:
    if tool['function']['name']=='record_transport_invoice':
        tool['function']['parameters']['properties']['amounts']={'type':'object','patternProperties':{'^[0-6]$':{'type':['string','number']}},'additionalProperties':False,'minProperties':1}
        tool['function']['description']+=' 若票面明确列出不同分段价格，用 amounts（行号字符串到金额）提供全部明细且合计必须等于 total；只有总额时省略 amounts。程序核对材料中的合计，找不到或冲突时保留空白，不得换成其他金额绕过。'
LABELS={'infer_fields':'补全可推测信息','estimate_train_arrival':'推算火车到达时间','get_form_state':'查看表单','read_material':'阅读材料','fill_fields':'填写表单','record_expense':'整理费用','validate_form':'核对与计算','ask_user':'确认缺失信息','skip_fields':'保留空白'}
LABELS.update(record_transport_invoice='登记交通票据总额', estimate_flight_times='推算飞机起止时间')


class Agent:
    def __init__(self,store): self.store=store

    async def run(self,owner,rid,kind,question,automatic=False):
        read=set(); base=self.store.get(owner,rid)['revision']; count=0; mutated=False
        data=self.store.get(owner,rid)
        materials=[{'id':m['id'],'name':m['name'],'status':m['status'],'page_count':len(m.get('pages',[]))} for m in data['materials'] if m['form']==kind]
        system=(ROOT/'skills/travel-agent.md').read_text(encoding='utf-8')+'\n当前表单：'+kind+'\n字段字典：'+json.dumps(FIELDS[kind],ensure_ascii=False)+'\n材料清单：'+json.dumps(materials,ensure_ascii=False)
        system += '\n当前日期（中国标准时间）：'+datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        system += '\n出差事由 reasons 必须为数组，可用值：'+json.dumps(REASONS,ensure_ascii=False)+'；培训或会议材料应直接选择会议培训，不必再问用户。'
        tools=copy.deepcopy([t for t in TOOLS if not automatic or t['function']['name'] not in ('ask_user','skip_fields')])
        if automatic:
            system += '\n'+(ROOT/'skills/automatic-fill.md').read_text(encoding='utf-8')
        field_properties={k:({'type':'array','items':{'enum':REASONS}} if k=='reasons' else {'type':['string','number','null']} if k.startswith(('budget_','expense_')) or k.endswith('.fare') else {'type':'string'}) for k in FIELDS[kind]}
        if kind=='reimbursement':
            field_properties={k:v for k,v in field_properties.items() if not k.endswith(('.fare','.invoice'))}
        next(t for t in tools if t['function']['name']=='fill_fields')['function']['parameters']['properties']['values']={'type':'object','properties':field_properties,'additionalProperties':False}
        messages=[{'role':'system','content':system}]
        history=[m for m in data['messages'] if not automatic and m['form']==kind and m['role'] in ('user','assistant')][-16:]
        messages.extend({'role':m['role'],'content':m['content']} for m in history)
        if not history or history[-1]['content']!=question: messages.append({'role':'user','content':question})
        try:
            async with asyncio.timeout(480):
                for round_no in range(10):
                    self.store.event(owner,rid,{'type':'status','message':'正在分析材料与表单' if not round_no else '正在继续填写'})
                    msg=await completion(messages,tools)
                    messages.append(msg)
                    calls=msg.get('tool_calls') or []
                    if not calls:
                        answer=msg.get('content') or '已核对当前表单，请检查标记的待填写内容。'
                        self.finish(owner,rid,kind,answer,summarize=mutated)
                        return
                    if len(calls)>12: raise ValueError('本轮工具请求过多，请缩小本次材料范围。')
                    for call in calls:
                        count+=1
                        if count>40: raise ValueError('本轮处理已达到上限，已保存填写内容，可以继续对话。')
                        name=call['function']['name']
                        self.store.event(owner,rid,{'type':'tool','name':name,'message':LABELS.get(name,'检查请求')})
                        try:
                            args=json.loads(call['function'].get('arguments') or '{}')
                            definition=next(t for t in tools if t['function']['name']==name)
                            schema_validate(args,definition['function']['parameters'])
                            result=self.execute(owner,rid,kind,name,args,read,base,question,automatic=automatic)
                            if name in ('fill_fields','record_expense','record_transport_invoice','estimate_flight_times','skip_fields','estimate_train_arrival','infer_fields') and 'error' not in result: mutated=True
                        except (ValueError,TypeError,KeyError,StopIteration,ValidationError) as e:
                            result={'error':str(e)[:250]}
                        messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps(result,ensure_ascii=False)})
                        self.store.event(owner,rid,{'type':'tool_result','message':LABELS.get(name,'检查请求')+('未完成' if 'error' in result else '完成'),'ok':'error' not in result,'detail':result.get('error')})
                        if sum(len(str(m.get('content',''))) for m in messages)>180000: raise ValueError('材料超过本次阅读范围，请分批处理。')
                self.finish(owner,rid,kind,'本轮填写已保存。还有需要确认的内容时，可以继续在下方告诉我。')
        except asyncio.CancelledError:
            self.finish(owner,rid,kind,'服务中断，已填写内容保留，请继续对话。','error'); raise
        except Exception as e:
            text=str(e) if isinstance(e,(ValueError,TimeoutError)) else '处理连接中断，请稍后重试，已填写内容已保存。'
            self.finish(owner,rid,kind,text or '本轮处理超时，已填写内容保留，可继续。','error')

    def finish(self,owner,rid,kind,text,status='idle',summarize=False):
        def done(d):
            nonlocal text
            d['agent']={'status':status,'form':kind}
            if summarize and kind=='reimbursement' and status=='idle': text=reimbursement_receipt(d)
            d['messages'].append({'role':'assistant','content':text,'form':kind})
            d['agent']={'status':status,'form':kind,'message':text}
            validate(d,kind)
        self.store.change(owner,rid,done)
        self.store.event(owner,rid,{'type':'done','message':text})

    def execute(self,owner,rid,kind,name,args,read,base,question,automatic=False):
        data=self.store.get(owner,rid)
        if name=='get_form_state': return {'form':data['forms'][kind],'fields':FIELDS[kind]}
        if name=='read_material':
            m=next(m for m in data['materials'] if m['id']==args['material_id'] and m['form']==kind and m['status']=='done')
            page=next(p for p in m['pages'] if p['page']==args['page'])
            read.add((m['id'],args['page']))
            return {'material_id':m['id'],'name':m['name'],**page}
        if name in ('fill_fields','record_expense','infer_fields','record_transport_invoice','estimate_flight_times'):
            source=args['source']
            if source.get('user'):
                if automatic: raise ValueError('自动填写只能引用实际材料，不能将系统任务当作用户提供的事实')
                source={'user':True,'quote':question[:2000]}
            elif (source.get('material_id'),source.get('page')) not in read:
                raise ValueError('必须先读取来源材料的对应页')
            if name in ('record_transport_invoice','estimate_flight_times'):
                if kind!='reimbursement': raise ValueError('此工具只用于报销行程')
                if name=='record_transport_invoice':
                    manual=data['forms'][kind]['meta']
                    if any(manual.get(f'trip.{row}.{key}',{}).get('owner')=='user' for row in args['rows'] for key in ('fare','invoice')):
                        return self.store.change(owner,rid,lambda d:record_transport_invoice(d,args['rows'],args['invoice_no'],args['total'],source,args.get('amounts')))[1]
                    if not source.get('user'):
                        material=next(m for m in data['materials'] if m['id']==source['material_id'] and m['form']==kind)
                        page=next(p for p in material['pages'] if p['page']==source['page'])
                        if ''.join(args['invoice_no'].split()) not in ''.join(page['text'].split()):
                            raise ValueError('票号必须来自原始材料，不能添加去程、返程后缀；整张往返票一次登记所有 rows')
                        source={**source,'amount_verification':verify_invoice_amount(page['text'],args['total'],args.get('amounts'))}
                    return self.store.change(owner,rid,lambda d:record_transport_invoice(d,args['rows'],args['invoice_no'],args['total'],source,args.get('amounts')))[1]
                return self.store.change(owner,rid,lambda d:estimate_flight_times(d,args['row'],args['duration_minutes'],args['reason'],source,args.get('departure_time')))[1]
            if name=='infer_fields':
                allowed={'start','end','destination'}
                if kind=='application': allowed|={'purpose','reasons','plane'}
                if not set(args['values'])<=allowed: raise ValueError('这些字段不允许推测：'+','.join(set(args['values'])-allowed))
                estimate={**source,'estimated':True,'reason':args['reason']}
                def infer(d):
                    f=d['forms'][kind]
                    # Inference only fills blanks or previous estimates, never evidence-backed facts.
                    changes={k:v for k,v in args['values'].items() if not f['values'].get(k) or f['meta'].get(k,{}).get('source',{}).get('estimated')}
                    return patch(d,kind,changes,'agent',estimate)
                return self.store.change(owner,rid,infer)[1]
            if name=='fill_fields':
                if kind=='reimbursement' and any(k.startswith('expense_') for k in args['values']): raise ValueError('其他费用请通过 record_expense 逐票据录入')
                if kind=='reimbursement' and any(k.endswith(('.fare','.invoice')) for k in args['values']):
                    raise ValueError('交通票号和金额必须通过 record_transport_invoice 登记整张票据，往返总额只能计一次；请先单独填写行程信息')
                return self.store.change(owner,rid,lambda d:patch(d,kind,args['values'],'agent',source))[1]
            if kind!='reimbursement': raise ValueError('申请表预算请使用 fill_fields')
            if not args['invoice_no'].strip(): raise ValueError('缺少票号，无法去重，请先询问核对')
            amount=str(money(args['amount'])); category=args['category']
            key=hashlib.sha256(args['invoice_no'].strip().encode()).hexdigest()[:24]
            def expense(d):
                f=d['forms'][kind]
                if any(f['values'].get(f'trip.{i}.invoice')==args['invoice_no'].strip() for i in range(7)):
                    raise ValueError('该票据已作为交通费录入，不能重复计入其他费用')
                if f['meta'].get('expense_'+category,{}).get('owner')=='user': return {'error':'该费用已由老师修改，保留人工金额'}
                f['expenses'][key]={'invoice_no':args['invoice_no'].strip(),'category':category,'amount':amount,'source':source}
                f['meta']['expense_'+category]={'owner':'agent','source':source,'revision':d['revision']+1}
                return validate(d,kind)
            return self.store.change(owner,rid,expense)[1]
        if name=='estimate_train_arrival':
            if kind!='reimbursement': raise ValueError('到达时间推算仅用于报销行程')
            row=args['row'];pre=f'trip.{row}.'; f=data['forms'][kind];v=f['values']
            if not any(k in (v.get(pre+'mode') or '') for k in ('高铁','动车','火车','铁路','列车')): raise ValueError('只能推算火车行程')
            if not all(v.get(pre+k) for k in ('start','start_time','origin','destination')): raise ValueError('先填写出发日期、时间和起止站')
            if v.get(pre+'end_time'): return {'skipped':'已有到达时间，保留现值'}
            source=f['meta'].get(pre+'start',{}).get('source',{})
            if not source.get('user') and (source.get('material_id'),source.get('page')) not in read: raise ValueError('先读取该行程的票据页')
            start=datetime.fromisoformat(v[pre+'start']+'T'+v[pre+'start_time'])
            arrival=start+timedelta(minutes=args['duration_minutes'])
            estimate={**source,'estimated':True,'reason':args['reason'],'duration_minutes':args['duration_minutes']}
            def apply(d):
                current=d['forms'][kind]
                for key in (pre+'start',pre+'start_time',pre+'origin',pre+'destination',pre+'end',pre+'end_time'):
                    if current['values'].get(key)!=v.get(key): raise ValueError('行程已修改，请重新读取后推算')
                if current['meta'].get(pre+'end_time',{}).get('owner')=='user': return {'conflicts':[pre+'end_time']}
                actual_date=current['values'].get(pre+'end')
                if actual_date and actual_date!=arrival.date().isoformat() and current['meta'].get(pre+'end',{}).get('owner')=='user': raise ValueError('推算日期与老师指定到达日期冲突，请重新推算')
                changes={pre+'end_time':arrival.strftime('%H:%M')}
                if not actual_date or current['meta'].get(pre+'end',{}).get('owner')!='user': changes[pre+'end']=arrival.date().isoformat()
                return patch(d,kind,changes,'agent',estimate)
            return self.store.change(owner,rid,apply)[1]
        if name=='validate_form': return self.store.change(owner,rid,lambda d:validate(d,kind))[1]
        if name=='ask_user':
            if automatic: raise ValueError('一键填写不允许提问，请填完可确定部分后结束')
            def ask(d):
                f=d['forms'][kind]; qs=[]
                for q in args['questions']:
                    if q['field'] not in FIELDS[kind]: continue
                    if not f['values'].get(q['field']) and not f['meta'].get(q['field'],{}).get('skipped'):
                        qs.append(q)
                f['questions']=qs
                return {'questions':qs,'message':'等待用户回答；能确定的字段请先填写。'}
            return self.store.change(owner,rid,ask)[1]
        if name=='skip_fields':
            if not any(w in question for w in ('不知道','不用','不填','留空','跳过','不清楚')): raise ValueError('用户尚未明确要求跳过')
            return self.store.change(owner,rid,lambda d:patch(d,kind,{k:'' for k in args['fields']},'user',{'user':True},skip=True))[1]
        raise ValueError('工具不在白名单中')
