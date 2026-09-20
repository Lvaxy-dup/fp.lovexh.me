"""Field whitelist and deterministic, decimal-based school form calculations."""
from datetime import date, time, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

REASONS=['业务工作','会议培训','实习实训','竞赛','招生就业','科研','其他']
CATEGORIES={'hotel':'住宿费','meeting':'会务费','training':'培训费','insurance':'保险费','change':'退票/改签费','local':'市内短途车费','other':'其他费用'}
COMMON={'name':'姓名','department':'所属部门','fund_no':'经费编号','fund_name':'经费名称','destination':'出差地点'}
APP={**COMMON,'companions':'同行人员','reasons':'出差事由','start':'出差开始日期','end':'出差结束日期','plane':'是否乘坐飞机','purpose':'简述出差内容',
     'budget_transport':'城际交通费','budget_hotel':'住宿费','budget_allowance':'伙食补助和市内交通费','budget_meeting':'会务费','budget_other':'其他费用'}
REIM={**COMMON,'job_title':'职务/职称','start':'实际出差开始日期','end':'实际出差结束日期','has_fee':'是否有会务费或培训费'}
for i in range(7):
    for k,v in {'start':'出发日期','start_time':'出发时间','end':'到达日期','end_time':'到达时间','origin':'起点','destination':'终点','mode':'交通工具','fare':'票面金额','invoice':'票据号码'}.items():
        REIM[f'trip.{i}.{k}']=f'第{i+1}段{v}'
REIM.update({f'expense_{k}':v for k,v in CATEGORIES.items()})
FIELDS={'application':APP,'reimbursement':REIM}
REQUIRED={'application':['name','department','reasons','start','end','destination','plane','purpose'],
          'reimbursement':['name','department','job_title','start','end']}


def money(value):
    if isinstance(value,bool): raise ValueError('金额必须是数字')
    try: n=Decimal(str(value))
    except InvalidOperation: raise ValueError('金额格式错误')
    if not n.is_finite() or n<0 or n>Decimal('100000000'): raise ValueError('金额超出允许范围')
    return n.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)


def normalized(form,key,value):
    if key not in FIELDS[form]: raise ValueError('该位置不在允许填写范围：'+key)
    if value is None or value=='': return ''
    if key=='reasons':
        if not isinstance(value,list) or any(v not in REASONS for v in value): raise ValueError('出差事由必须来自表内选项')
        return list(dict.fromkeys(value))
    if key in ('plane','has_fee'):
        if value not in ('是','否'): raise ValueError('请选择是或否')
    if key in ('start','end') or re.match(r'trip\.\d+\.(start|end)$',key):
        if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value): raise ValueError('日期格式应为 YYYY-MM-DD')
        date.fromisoformat(value)
    if key.endswith('_time'): time.fromisoformat(str(value))
    if key.startswith(('budget_','expense_')) or key.endswith('.fare'): return str(money(value))
    if not isinstance(value,str) or len(value)>2000: raise ValueError('字段内容过长或格式错误')
    return value.strip()


def rmb(value):
    n=money(value); integer=int(n); cents=int((n-integer)*100)
    digits='零壹贰叁肆伍陆柒捌玖'; small=['','拾','佰','仟']
    def group(x):
        text=''; zero=False
        for i in range(3,-1,-1):
            d=x//(10**i)%10
            if d:
                if zero and text: text+='零'
                text+=digits[d]+small[i]; zero=False
            elif text: zero=True
        return text
    chunks=[]; x=integer
    while x: chunks.append(x%10000); x//=10000
    text=''; zero=False
    for i in range(len(chunks)-1,-1,-1):
        g=chunks[i]
        if not g: zero=bool(text); continue
        if text and (zero or g<1000): text+='零'
        text+=group(g)+['','万','亿'][i]; zero=False
    text=(text or '零')+'圆'
    j,f=divmod(cents,10)
    if not cents: return text+'整'
    if j: text+=digits[j]+'角'
    elif integer and f: text+='零'
    if f: text+=digits[f]+'分'
    return text


def trip_period(form):
    v=form['values']; meta=form['meta']
    rows=[i for i in range(7) if v.get(f'trip.{i}.start')]
    rows.sort(key=lambda i:(v[f'trip.{i}.start'],v.get(f'trip.{i}.start_time') or '00:00'))
    start,end=v.get('start'),v.get('end')
    # Infer the whole trip only from a complete return itinerary, not a single outbound ticket.
    if len(rows)>=2:
        first,last=rows[0],rows[-1]
        normalize=lambda x:re.sub(r'[站\s]','',x or '')
        home=normalize(v.get(f'trip.{first}.origin'))
        returned=normalize(v.get(f'trip.{last}.destination'))
        if home and returned and home==returned and v.get(f'trip.{last}.end'):
            if meta.get('start',{}).get('owner')!='user' and not meta.get('start',{}).get('skipped'):
                start=v[f'trip.{first}.start']
            if meta.get('end',{}).get('owner')!='user' and not meta.get('end',{}).get('skipped'):
                end=v[f'trip.{last}.end']
    return start,end,rows


def allocate_allowance(v,rows,start,end,has_fee=False):
    for i in range(7):
        v[f'trip.{i}.allowance_days']=''
        v[f'trip.{i}.allowance_total']=''
    if not start or not end or end<start:return None
    a,b=date.fromisoformat(start),date.fromisoformat(end)
    days=(b-a).days+1
    if days>366: return None
    # A same-day trip has one unique boundary date, never two allowances.
    dates=sorted({a,b}) if has_fee else [a+timedelta(days=i) for i in range(days)]
    counts={}
    for day in dates:
        earlier=[i for i in rows if v[f'trip.{i}.start']<=day.isoformat()]
        row=earlier[-1] if earlier else rows[0] if rows else 0
        counts[row]=counts.get(row,0)+1
    for row,count in counts.items():
        v[f'trip.{row}.allowance_days']=count
        v[f'trip.{row}.allowance_total']=str(count*180)
    if not dates:
        row=rows[0] if rows else 0
        v[f'trip.{row}.allowance_days']=0
        v[f'trip.{row}.allowance_total']='0'
    return len(dates)


def recalculate(form):
    v=form['values']; warnings=[]
    if 'budget_transport' in v or any(k.startswith('budget_') for k in v):
        vals=[money(v[k]) for k in APP if k.startswith('budget_') and v.get(k) not in (None,'')]
        v['budget_total']=str(sum(vals,Decimal(0))) if vals else ''
    rows=[]
    if form.get('kind')=='reimbursement':
        a,b,rows=trip_period(form)
        v['start'],v['end']=a or '',b or ''
    days=None
    if v.get('start') and v.get('end'):
        days=(date.fromisoformat(v['end'])-date.fromisoformat(v['start'])).days+1
        if days<=0: warnings.append('结束日期早于开始日期'); days=None
    v['days']=days if days else ''
    if form.get('kind')=='application': return warnings
    entries=form.get('expenses',{})
    for cat in CATEGORIES:
        key='expense_'+cat
        if form['meta'].get(key,{}).get('owner')=='user': continue
        items=[money(x['amount']) for x in entries.values() if x['category']==cat]
        v[key]=str(sum(items,Decimal(0))) if items else ''
    seen={}; fares=[]
    for i in range(7):
        pre=f'trip.{i}.'; fare=v.get(pre+'fare'); inv=v.get(pre+'invoice')
        duplicate=False
        if inv:
            if inv in seen:
                group=form['meta'].get(pre+'invoice',{}).get('source',{}).get('transport_invoice',{})
                first_group=form['meta'].get(f'trip.{seen[inv]}.invoice',{}).get('source',{}).get('transport_invoice',{})
                allocated=(group.get('allocation') in ('equal','explicit') and group==first_group and group.get('invoice_no')==inv
                           and i in group.get('rows',[]) and seen[inv] in group.get('rows',[]))
                duplicate=not allocated
                if duplicate and not (group.get('invoice_no')==inv and group.get('charged_row')==seen[inv] and fare not in (None,'') and money(fare)==0):
                    warnings.append(f'第{i+1}段与第{seen[inv]+1}段票据号码重复，未重复计入金额')
            else: seen[inv]=i
        if not duplicate and fare not in (None,''): fares.append(money(fare))
        a,b=v.get(pre+'start'),v.get(pre+'end')
        if a and b and a>b: warnings.append(f'第{i+1}段到达日期早于出发日期')
        if form['meta'].get(pre+'end_time',{}).get('source',{}).get('estimated'):
            warnings.append(f"第{i+1}段到达时间 {v.get(pre+'end','')} {v.get(pre+'end_time','')} 为模型估算，请核对")
    other=[money(v['expense_'+c]) for c in CATEGORIES if v.get('expense_'+c) not in (None,'')]
    has_fee=v.get('has_fee')=='是' or any(money(v.get('expense_'+c) or 0)>0 for c in ('meeting','training'))
    if form['meta'].get('has_fee',{}).get('owner')=='user' and v.get('has_fee') in ('是','否'):
        has_fee=v['has_fee']=='是' or any(money(v.get('expense_'+c) or 0)>0 for c in ('meeting','training'))
        if v['has_fee']=='否' and has_fee:
            warnings.append('选择了“未收费”，但会务费或培训费仍有金额，暂按有费用计算；如属误填请将费用清零')
    for inv,row in seen.items():
        group=form['meta'].get(f'trip.{row}.invoice',{}).get('source',{}).get('transport_invoice',{})
        if group.get('allocation') in ('equal','explicit'):
            actual=sum((money(v.get(f'trip.{i}.fare') or 0) for i in group['rows'] if v.get(f'trip.{i}.invoice')==inv),Decimal(0))
            if actual!=money(group['total']):warnings.append(f'票据 {inv} 的行程金额合计与原票总额不一致，请核对人工修改')
    allowed_days=allocate_allowance(v,rows,v.get('start'),v.get('end'),has_fee) if days else allocate_allowance(v,rows,None,None)
    v['allowance_basis']=('有会务费或培训费，仅计出发日和返回日，每天180元；同日往返只计1天' if has_fee else '无会务费或培训费，按完整出差日期每天180元，包含出发日和返回日')
    if days and days>366: warnings.append('出差期间超过366天，请核对日期后计算补助')
    v['allowance_days']=allowed_days if allowed_days is not None else ''
    v['allowance_total']=str(Decimal(allowed_days)*180) if allowed_days is not None else ''
    v['transport_total']=str(sum(fares,Decimal(0))) if fares else ''
    v['other_total']=str(sum(other,Decimal(0))) if other else ''
    ticket=sum(fares+other,Decimal(0))
    v['ticket_total']=str(ticket) if fares or other else ''
    v['ticket_upper']=rmb(ticket) if fares or other else ''
    total=ticket+money(v.get('allowance_total') or 0)
    v['grand_total']=str(total) if fares or other or allowed_days is not None else ''
    v['grand_upper']=rmb(total) if v['grand_total']!='' else ''
    return warnings


def validate(data,kind):
    form=data['forms'][kind]; form['kind']=kind
    warnings=recalculate(form)
    missing=[{'field':k,'label':FIELDS[kind][k]} for k in REQUIRED[kind] if not form['values'].get(k) and not form['meta'].get(k,{}).get('skipped')]
    if kind=='reimbursement':
        for i in range(7):
            if form['values'].get(f'trip.{i}.mode'):
                required=('start','origin','destination','fare')
                if any(word in form['values'][f'trip.{i}.mode'] for word in ('飞机','航空','航班')):
                    required+=('start_time','end','end_time')
                for name in required:
                    k=f'trip.{i}.{name}'
                    if not form['values'].get(k) and not form['meta'].get(k,{}).get('skipped'):
                        missing.append({'field':k,'label':FIELDS[kind][k]})
    if data['agent']['status']=='running' and data['agent'].get('form')==kind: warnings.append('助手仍在填写，当前内容可能尚未完成')
    if any(m['status']!='done' for m in data['materials'] if m['form']==kind): warnings.append('仍有材料未完成识别，请核对后再打印')
    estimated=[{'field':k,'label':FIELDS[kind].get(k,k),'reason':m['source'].get('reason',''),'value':form['values'].get(k,'')} for k,m in form['meta'].items() if m.get('source',{}).get('estimated') and form['values'].get(k) not in (None,'')]
    if estimated: warnings.append('含模型推测内容，请核对；推测期间对应补助为暂估')
    computed={k:form['values'].get(k,'') for k in ('days','budget_total','transport_total','other_total','ticket_total','allowance_days','allowance_total','grand_total','grand_upper','allowance_basis')}
    return {'missing':missing,'warnings':warnings,'estimated':estimated,'computed':computed,'allowance_rule':'每天180元；有会务费或培训费只计出发日和返回日，同日往返计1天；无这两项费用按完整出差日期计算，包含出发日和返回日。'}


def patch(data,kind,changes,owner='user',source=None,base_revision=None,skip=False):
    form=data['forms'][kind]; form['kind']=kind
    checked={k:normalized(kind,k,v) for k,v in changes.items()}
    if kind=='reimbursement':
        expense_invoices={e['invoice_no'] for e in form['expenses'].values()}
        if any(k.endswith('.invoice') and value and value in expense_invoices for k,value in checked.items()):
            raise ValueError('该票据已作为其他费用录入，不能重复计入交通费')
    conflicts=[]; applied=[]
    for k,value in checked.items():
        meta=form['meta'].get(k,{})
        if owner=='agent' and (meta.get('owner')=='user' or (base_revision is not None and meta.get('revision',0)>base_revision)):
            conflicts.append(k); continue
        old=form['values'].get(k)
        form['values'][k]=value
        form['meta'][k]={'owner':owner,'revision':data['revision']+1,'source':source or {},'skipped':skip and value==''}
        data['audit'].append({'field':k,'form':kind,'before':old,'after':value,'owner':owner,'revision':data['revision']+1})
        applied.append(k)
    data['audit']=data['audit'][-500:]
    form['questions']=[q for q in form['questions'] if not form['values'].get(q['field']) and not form['meta'].get(q['field'],{}).get('skipped')]
    return {'applied':applied,'conflicts':conflicts,'validation':validate(data,kind)}


def reimbursement_receipt(data):
    """Financial status is rendered from committed values, never free-form model prose."""
    result=validate(data,'reimbursement'); f=data['forms']['reimbursement']; v=f['values']
    lines=['当前报销单已保存。']
    for key,label in [('transport_total','交通费'),('other_total','其他费用'),('ticket_total','票面金额合计')]:
        if v.get(key) not in (None,''): lines.append(f"{label}：{money(v[key]):.2f} 元")
    if v.get('allowance_total') not in (None,''):
        lines.append(f"伙食交通补助：{v['allowance_days']} 天，{money(v['allowance_total']):.2f} 元")
        lines.append(v['allowance_basis']+'。')
    else: lines.append('伙食交通补助：等待确认实际出差起止日期。')
    if v.get('grand_total') not in (None,''):
        label='当前合计（补助待确认）' if v.get('allowance_total') in (None,'') else '报销总计'
        lines.append(f"{label}：{money(v['grand_total']):.2f} 元")
    if result['missing']:
        lines.append('\n还需补充：'+'、'.join(x['label'] for x in result['missing'])+'。')
    if f['questions']:
        lines.append('\n'+'\n'.join(q['question'] for q in f['questions']))
    skipped=[FIELDS['reimbursement'][k] for k,m in f['meta'].items() if m.get('skipped') and k in FIELDS['reimbursement']]
    if skipped: lines.append('\n已按您的选择留空：'+'、'.join(skipped)+'。')
    if result['warnings']: lines.append('\n请核对：'+'；'.join(result['warnings'])+'。')
    return '\n'.join(lines)
