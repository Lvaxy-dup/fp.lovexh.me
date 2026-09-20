"""Application forecasts: model estimates a rail fare; code applies school rules."""
from datetime import date
from decimal import Decimal
from pathlib import Path
import re
from .allowance import allowance_dates

STANDARD=Path(__file__).parent/'data'/'住宿费标准.md'
TIERS=('其他人员','教授及院领导、院长助理')

def lodging_rows():
    rows=[]
    for line_no,line in enumerate(STANDARD.read_text(encoding='utf-8-sig').splitlines(),1):
        cells=[c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells)==5 and cells[0].isdigit():
            rows.append({'line':line_no,'region':cells[1],'scope':cells[2],'senior':int(cells[3]),'other':int(cells[4])})
    if not rows:raise ValueError('住宿标准表为空，不能估算住宿费')
    return rows

def place(value):
    return re.sub(r'(壮族自治区|回族自治区|维吾尔自治区|自治区|省|市)$','',value.strip())

def lodging_standard(city,province=''):
    city=place(city);province=place(province)
    if not city:raise ValueError('先确定住宿城市')
    rows=lodging_rows()
    exact=[r for r in rows if city in [place(s.strip()) for s in re.split('[、，,]',r['scope'])]]
    if exact:return exact[0]
    direct=[r for r in rows if place(r['region'])==city]
    if direct:
        # City-wide entries and the default central-city group of municipalities.
        return next((r for r in direct if r['scope'] in ('全市','全省') or '中心城区' in r['scope']),direct[0])
    fallback=[r for r in rows if place(r['region'])==province and r['scope'] in ('其他地区','全省')]
    if fallback:return fallback[0]
    raise ValueError('住宿城市未匹配到标准，请提供正确省份简称和城市，不能自行编造住宿单价')

def lodging_tier(values):
    if values.get('lodging_tier') in TIERS:return values['lodging_tier']
    title=values.get('job_title','')
    return TIERS[1] if re.search(r'(?<!副)教授|院长|院长助理|党委书记|党委副书记',title) else TIERS[0]

def recalculate_application_budget(form):
    from .forms import money
    v,meta=form['values'],form['meta'];warnings=[]
    def assign(key,value,reason,source=None):
        if meta.get(key,{}).get('owner')=='user':return
        v[key]=str(money(value)) if value is not None else ''
        meta[key]={'owner':'agent','source':{**(source or {}),'estimated':True,'budget_estimate':True,'reason':reason}}
    has_fee=v.get('has_fee')=='是' or money(v.get('budget_meeting') or 0)>0
    dates=allowance_dates(v.get('start'),v.get('end'),has_fee)
    basis='有会务费或培训费，只计首尾日期' if has_fee else '无会务费或培训费，计完整出差日期'
    assign('budget_allowance',len(dates)*180 if dates is not None else None,
           f'{basis}；{len(dates)}天×180元/天。' if dates is not None else '待确定有效出差日期。',meta.get('start',{}).get('source'))
    if v.get('has_fee')=='否' and money(v.get('budget_meeting') or 0)>0:warnings.append('选择未收费但会务费预算仍有金额，暂按首尾补助计算；如属误填请清零会务费')
    plan=form.get('budget_plan')
    if plan:
        if plan['destination']!=v.get('destination'):
            for key in ('budget_transport','budget_hotel'):assign(key,None,'目的地已变化，请重新填写预算。')
            warnings.append('目的地已变化，请点击填写当前表单重新估算交通和住宿预算')
        else:
            fare=money(plan['one_way_fare'])
            total=fare*2
            assign('budget_transport',total,f"徐州→{plan['city']}→徐州，高铁二等座；单程估算{fare}元×2，预算{total}元。{plan['reason']} 未查询实时售票价格。",plan['source'])
            standard=lodging_standard(plan['city'],plan['province']);tier=lodging_tier(v)
            rate=standard['senior' if tier==TIERS[1] else 'other']
            nights=(date.fromisoformat(v['end'])-date.fromisoformat(v['start'])).days if dates is not None else None
            assign('budget_hotel',rate*nights if nights is not None else None,
                   f"按《住宿费标准.md》第{standard['line']}行：{standard['region']}／{standard['scope']}，{tier}，{rate}元/晚；按出发至返回相差{nights}晚预算，共{rate*nights}元。" if nights is not None else '住宿晚数待确定有效出差日期。',plan['source'])
    amounts=[money(v[k]) for k in ('budget_transport','budget_hotel','budget_allowance','budget_meeting','budget_other') if v.get(k) not in (None,'')]
    v['budget_total']=str(sum(amounts,Decimal(0))) if amounts else ''
    return warnings

def estimate_application_budget(data,city,province,one_way_fare,reason,source):
    from .forms import money,validate
    form=data['forms']['application'];v=form['values'];city=place(city)
    if not v.get('destination') or city not in v['destination']:raise ValueError('预算城市必须与当前出差地点一致，请先填写城市及出差日期')
    if not allowance_dates(v.get('start'),v.get('end')):raise ValueError('请先填写有效出差日期（不超过366天）')
    fare=money(one_way_fare)
    if fare>5000 or (city!='徐州' and fare<=0):raise ValueError('请提供合理的高铁二等座单程基础估价，非本地行程不能为零')
    if city=='徐州':fare=Decimal(0)
    standard=lodging_standard(city,province)
    form['budget_plan']={'destination':v['destination'],'city':city,'province':province,'one_way_fare':str(fare),'reason':reason,'source':source}
    check=validate(data,'application')
    return {'validation':check,'lodging_standard':standard,'tier':lodging_tier(v),'budget':{k:v.get(k) for k in ('budget_transport','budget_hotel','budget_allowance','budget_meeting','budget_total')}}
