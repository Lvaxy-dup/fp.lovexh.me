from decimal import Decimal
import pytest
from server.store import Store
from server.forms import patch,validate,rmb,money
from server.agent import Agent

@pytest.fixture
def record(tmp_path):
    store=Store(tmp_path/'test.db'); data=store.create('teacher')
    return store,data['id']

def update(store,rid,kind,values,**kwargs):
    return store.change('teacher',rid,lambda d:patch(d,kind,values,**kwargs))[0]

def test_application_dates_calculate_allowance_without_inventing_fares(record):
    s,r=record;d=update(s,r,'application',{'start':'2026-09-10','end':'2026-09-13'})
    assert d['forms']['application']['values']['days']==4
    assert d['forms']['application']['values']['budget_allowance']=='720.00'
    assert not d['forms']['application']['values'].get('budget_transport')
    assert not d['forms']['application']['values'].get('budget_hotel')

def test_subsidy_and_decimal_totals(record):
    s,r=record;d=update(s,r,'reimbursement',{'start':'2026-09-10','end':'2026-09-13','trip.0.fare':'172','expense_hotel':'1212.10'})
    v=d['forms']['reimbursement']['values'];assert v['allowance_total']=='720'
    assert Decimal(v['grand_total'])==Decimal('2104.10')
    d=update(s,r,'reimbursement',{'expense_training':'1000'})
    v=d['forms']['reimbursement']['values'];assert v['allowance_total']=='360'
    assert Decimal(v['grand_total'])==Decimal('2744.10')

def test_same_day_not_double_counted(record):
    s,r=record;d=update(s,r,'reimbursement',{'start':'2026-09-10','end':'2026-09-10','has_fee':'是'})
    assert d['forms']['reimbursement']['values']['allowance_total']=='180'

def test_manual_edit_and_delete_protected(record):
    s,r=record;d=update(s,r,'application',{'name':'老师手填'})
    d=update(s,r,'application',{'name':'Agent覆盖'},owner='agent',base_revision=0)
    assert d['forms']['application']['values']['name']=='老师手填'
    update(s,r,'application',{'name':''})
    d=update(s,r,'application',{'name':'Agent回填'},owner='agent')
    assert d['forms']['application']['values']['name']==''

def test_skip_does_not_repeat_question(record):
    s,r=record;d=update(s,r,'application',{'department':''},skip=True)
    result=validate(d,'application')
    assert 'department' not in [x['field'] for x in result['missing']]

def test_duplicate_transport_invoice(record):
    s,r=record;d=update(s,r,'reimbursement',{'trip.0.invoice':'ABC','trip.0.fare':'100','trip.1.invoice':'ABC','trip.1.fare':'100'})
    assert Decimal(d['forms']['reimbursement']['values']['transport_total'])==100
    assert any('重复' in x for x in validate(d,'reimbursement')['warnings'])

def test_expense_idempotent_and_unread_source_rejected(record):
    s,r=record;a=Agent(s);args={'invoice_no':'INV','category':'hotel','amount':'123.45','source':{'material_id':'doc','page':1}}
    with pytest.raises(ValueError): a.execute('teacher',r,'reimbursement','record_expense',args,set(),0,'')
    for _ in range(2):a.execute('teacher',r,'reimbursement','record_expense',args,{('doc',1)},0,'')
    d=s.get('teacher',r);assert len(d['forms']['reimbursement']['expenses'])==1
    assert d['forms']['reimbursement']['values']['expense_hotel']=='123.45'

@pytest.mark.parametrize('value',['NaN','Infinity','-1','100000001',True])
def test_invalid_money(value):
    with pytest.raises(ValueError):money(value)

@pytest.mark.parametrize('amount,expected',[('2060','贰仟零陆拾圆整'),('1212.10','壹仟贰佰壹拾贰圆壹角'),('10001.01','壹万零壹圆零壹分'),('0','零圆整'),('100000001','invalid')])
def test_uppercase(amount,expected):
    if expected=='invalid':
        with pytest.raises(ValueError):rmb(amount)
    else:assert rmb(amount)==expected

def test_whitelist_and_transaction_rollback(record):
    s,r=record
    with pytest.raises(ValueError):update(s,r,'application',{'name':'bad','approval':'伪造签字'})
    assert s.get('teacher',r)['forms']['application']['values']=={}

def test_session_isolation(record):
    s,r=record
    with pytest.raises(KeyError):s.get('another-teacher',r)

def test_invalid_date_no_partial_write(record):
    s,r=record
    with pytest.raises(ValueError):update(s,r,'application',{'name':'bad','start':'2026-02-30'})
    assert s.get('teacher',r)['forms']['application']['values']=={}

def test_cross_category_invoice_not_counted_twice(record):
    s,r=record; a=Agent(s)
    update(s,r,'reimbursement',{'trip.0.invoice':'INV','trip.0.fare':'100'})
    args={'invoice_no':'INV','category':'hotel','amount':'100','source':{'user':True}}
    with pytest.raises(ValueError):a.execute('teacher',r,'reimbursement','record_expense',args,set(),0,'票据INV金额100')

def test_blank_user_field_not_overwritten_after_agent_running(record):
    s,r=record;revision=s.get('teacher',r)['revision']
    update(s,r,'application',{'department':''},skip=True)
    d=update(s,r,'application',{'department':'新识别的部门'},owner='agent',base_revision=revision)
    assert d['forms']['application']['meta']['department']['skipped']
    assert d['forms']['application']['values']['department']==''

def test_financial_receipt_uses_saved_values(record):
    from server.forms import reimbursement_receipt
    s,r=record
    d=update(s,r,'reimbursement',{'start':'2026-02-10','end':'2026-02-12','trip.0.fare':'172','expense_hotel':'1212.10'})
    text=reimbursement_receipt(d)
    assert '3 天，540.00 元' in text
    assert '报销总计：1924.10 元' in text
    assert '票面金额合计：1384.10 元' in text

def test_return_itinerary_automatically_sets_period_and_allocates(record):
    s,r=record
    d=update(s,r,'reimbursement',{'trip.0.start':'2026-09-10','trip.0.end':'2026-09-10','trip.0.origin':'徐州东站','trip.0.destination':'南京南站','trip.1.start':'2026-09-13','trip.1.end':'2026-09-13','trip.1.origin':'南京南站','trip.1.destination':'徐州东站'})
    v=d['forms']['reimbursement']['values']
    assert v['allowance_days']==4 and v['allowance_total']=='720'
    assert v['trip.0.allowance_days']==3 and v['trip.1.allowance_days']==1
    d=update(s,r,'reimbursement',{'expense_meeting':'100'})
    v=d['forms']['reimbursement']['values']
    assert v['allowance_days']==2 and v['allowance_total']=='360'
    assert v['trip.0.allowance_total']=='180' and v['trip.1.allowance_total']=='180'
    d=update(s,r,'reimbursement',{'expense_meeting':'','expense_training':'200'})
    assert d['forms']['reimbursement']['values']['allowance_total']=='360'
    d=update(s,r,'reimbursement',{'expense_training':''})
    assert d['forms']['reimbursement']['values']['allowance_total']=='720'

def test_train_estimate_rolls_date_and_keeps_evidence(record):
    s,r=record;a=Agent(s)
    update(s,r,'reimbursement',{'trip.0.start':'2026-09-10','trip.0.start_time':'23:30','trip.0.origin':'徐州东','trip.0.destination':'南京南','trip.0.mode':'高铁'},owner='agent',source={'material_id':'ticket','page':1})
    a.execute('teacher',r,'reimbursement','estimate_train_arrival',{'row':0,'duration_minutes':100,'reason':'根据高铁起止站间距离推算约100分钟，未查实时列车时刻表。'},{('ticket',1)},0,'')
    d=s.get('teacher',r);f=d['forms']['reimbursement']
    assert f['values']['trip.0.end']=='2026-09-11'
    assert f['values']['trip.0.end_time']=='01:10'
    assert f['meta']['trip.0.end_time']['source']['estimated']
    assert f['values']['allowance_total']==''  # one outbound trip is not a return
    assert any('估算' in x for x in validate(d,'reimbursement')['warnings'])

def test_estimate_does_not_overwrite_manual_arrival(record):
    s,r=record;a=Agent(s)
    update(s,r,'reimbursement',{'trip.0.start':'2026-09-10','trip.0.start_time':'10:00','trip.0.origin':'徐州东','trip.0.destination':'南京南','trip.0.mode':'高铁','trip.0.end_time':'12:30'})
    a.execute('teacher',r,'reimbursement','estimate_train_arrival',{'row':0,'duration_minutes':100,'reason':'根据起止站之间高铁行车距离估算。'},set(),0,'')
    assert s.get('teacher',r)['forms']['reimbursement']['values']['trip.0.end_time']=='12:30'

def test_positive_training_fee_wins_over_negative_flag(record):
    s,r=record;d=update(s,r,'reimbursement',{'start':'2026-09-10','end':'2026-09-18','has_fee':'否','expense_training':'10'})
    assert d['forms']['reimbursement']['values']['allowance_total']=='360'


def test_fee_added_cleared_and_date_changed_recalculates(record):
    s,r=record
    def change(values):return update(s,r,'reimbursement',values)['forms']['reimbursement']['values']
    assert change({'start':'2026-09-10','end':'2026-09-16'})['allowance_total']=='1260'
    assert change({'expense_meeting':'100'})['allowance_total']=='360'
    assert change({'expense_training':'200'})['allowance_total']=='360'
    assert change({'expense_meeting':''})['allowance_total']=='360'
    assert change({'expense_training':'0'})['allowance_total']=='1260'
    assert change({'has_fee':'是'})['allowance_total']=='360'
    assert change({'end':'2026-09-10'})['allowance_total']=='180'
    assert change({'has_fee':'否'})['allowance_total']=='180'
    assert change({'end':'2026-09-09'})['allowance_total']==''


def test_agent_expense_classification_changes_allowance(record):
    s,r=record;a=Agent(s)
    update(s,r,'reimbursement',{'start':'2026-09-10','end':'2026-09-16'})
    args={'invoice_no':'FEE','category':'training','amount':'100','source':{'material_id':'doc','page':1}}
    a.execute('teacher',r,'reimbursement','record_expense',args,{('doc',1)},0,'')
    assert s.get('teacher',r)['forms']['reimbursement']['values']['allowance_total']=='360'
    a.execute('teacher',r,'reimbursement','record_expense',{**args,'category':'hotel'},{('doc',1)},0,'')
    assert s.get('teacher',r)['forms']['reimbursement']['values']['allowance_total']=='1260'

def test_automatic_inference_is_restricted_and_marked(record):
    s,r=record;a=Agent(s)
    args={'values':{'start':'2026-09-10','end':'2026-09-10'},'reason':'仅有一张去程票，将已知行程暂作为出差期间。','source':{'material_id':'ticket','page':1}}
    a.execute('teacher',r,'reimbursement','infer_fields',args,{('ticket',1)},0,'',automatic=True)
    f=s.get('teacher',r)['forms']['reimbursement']
    assert f['meta']['start']['source']['estimated']
    assert f['values']['allowance_total']=='180'
    for key,value in [('name','张三'),('department','计算机系'),('expense_hotel','100'),('trip.0.fare','100'),('trip.0.invoice','fake')]:
        with pytest.raises(ValueError):
            a.execute('teacher',r,'reimbursement','infer_fields',{**args,'values':{key:value}},{('ticket',1)},0,'',automatic=True)


def test_automatic_mode_cannot_ask_or_claim_user_evidence(record):
    s,r=record;a=Agent(s)
    with pytest.raises(ValueError):
        a.execute('teacher',r,'application','ask_user',{'questions':[{'field':'name','question':'姓名？'}]},set(),0,'',automatic=True)
    with pytest.raises(ValueError):
        a.execute('teacher',r,'application','fill_fields',{'values':{'name':'张三'},'source':{'user':True}},set(),0,'自动填写',automatic=True)


def test_inference_never_replaces_facts_or_manual_values(record):
    s,r=record;a=Agent(s)
    update(s,r,'application',{'destination':'北京'},owner='agent',source={'material_id':'doc','page':1})
    update(s,r,'application',{'start':'2026-09-01'})
    a.execute('teacher',r,'application','infer_fields',{'values':{'destination':'南京','start':'2026-09-10','end':'2026-09-12'},'reason':'根据通知活动安排推测结束日期。','source':{'material_id':'doc','page':1}},{('doc',1)},0,'',automatic=True)
    v=s.get('teacher',r)['forms']['application']['values']
    assert v['destination']=='北京' and v['start']=='2026-09-01' and v['end']=='2026-09-12'


def test_workflow_waits_for_ocr_and_only_completes_selected_form(record):
    import asyncio
    from server.workflow import generate
    s,r=record
    def prepare(d):
        d['materials']=[{'id':'m','name':'notice.txt','form':'application','status':'queued','pages':[]}]
        d['pipeline']={'status':'running','completed':[],'forms':['application']}
    s.change('teacher',r,prepare)
    class FakeAgent:
        calls=[]
        async def run(self,owner,rid,kind,question,automatic=False):
            assert automatic and s.get(owner,rid)['materials'][0]['status']=='done'
            self.calls.append(kind)
            s.change(owner,rid,lambda d:d['agent'].update(status='idle'))
    a=FakeAgent()
    async def test():
        async def finish_ocr():
            await asyncio.sleep(.01)
            s.change('teacher',r,lambda d:d['materials'][0].update(status='done'))
        await asyncio.gather(generate(s,a,'teacher',r,['application'],['m']),finish_ocr())
    asyncio.run(test())
    d=s.get('teacher',r)
    assert d['pipeline']['status']=='done'
    assert a.calls==['application']
    assert d['forms']['reimbursement']['values']=={}
    assert all(not f['questions'] for f in d['forms'].values())


def test_workflow_continues_with_successful_materials(record):
    import asyncio
    from server.workflow import generate
    s,r=record
    def prepare(d):
        d['materials']=[{'id':'ok','name':'ok.pdf','form':'application','status':'done'},{'id':'bad','name':'bad.pdf','form':'application','status':'error'}]
        d['pipeline']={'status':'running','completed':[],'forms':['application']}
    s.change('teacher',r,prepare)
    class FakeAgent:
        async def run(self,owner,rid,kind,question,automatic=False):
            s.change(owner,rid,lambda d:d['agent'].update(status='idle'))
    asyncio.run(generate(s,FakeAgent(),'teacher',r,['application'],['ok','bad']))
    d=s.get('teacher',r)
    assert d['pipeline']['status']=='partial'
    assert d['pipeline']['failed_files']==['bad.pdf']

@pytest.mark.parametrize('start,end,expected',[('2026-09-11','2026-09-13',3),('2026-09-10','2026-09-13',4),('2026-09-10','2026-09-10',1),('2026-09-10','2026-09-11',2),('2026-09-30','2026-10-02',3),('2026-12-31','2027-01-02',3),('2028-02-28','2028-03-01',3)])
@pytest.mark.parametrize('expense',['','meeting','training'])
def test_allowance_conditional_dates(record,start,end,expected,expense):
    s,r=record
    changes={'start':start,'end':end}
    if expense:
        changes['expense_'+expense]='100'
        expected=1 if start==end else 2
    v=update(s,r,'reimbursement',changes)['forms']['reimbursement']['values']
    assert v['allowance_days']==expected
    assert Decimal(v['allowance_total'])==expected*180
    assert sum(v.get(f'trip.{i}.allowance_days') or 0 for i in range(7))==expected


def test_automatic_cannot_read_other_form_material(record):
    s,r=record
    s.change('teacher',r,lambda d:d['materials'].append({'id':'foreign','name':'invoice','form':'reimbursement','status':'done','pages':[{'page':1,'text':'secret'}]}))
    with pytest.raises(StopIteration):
        Agent(s).execute('teacher',r,'application','read_material',{'material_id':'foreign','page':1},set(),0,'',automatic=True)


def test_remove_material_clears_generated_but_retains_manual_and_other_form(record):
    from server.materials import remove_material
    s,r=record
    s.change('teacher',r,lambda d:d['materials'].append({'id':'doc','form':'application','name':'notice','status':'done'}))
    update(s,r,'application',{'destination':'南京','purpose':'参加培训'},owner='agent',source={'material_id':'doc','page':1})
    update(s,r,'application',{'destination':'老师修改'})
    update(s,r,'reimbursement',{'department':'另一张表'})
    d,result=s.change('teacher',r,lambda d:remove_material(d,'doc'))
    assert d['materials']==[]
    assert d['forms']['application']['values']['destination']=='老师修改'
    assert not d['forms']['application']['values'].get('purpose')
    assert d['forms']['reimbursement']['values']['department']=='另一张表'


def test_remove_invoice_recalculates_expenses(record):
    from server.materials import remove_material
    s,r=record
    def prepare(d):
        d['materials']=[{'id':'invoice','form':'reimbursement','name':'酒店','status':'done'}]
        d['forms']['reimbursement']['expenses']={'a':{'category':'hotel','amount':'200','invoice_no':'1','source':{'material_id':'invoice','page':1}}}
    s.change('teacher',r,prepare)
    d=update(s,r,'reimbursement',{'trip.0.fare':'100'})
    assert d['forms']['reimbursement']['values']['ticket_total']=='300.00'
    d,_=s.change('teacher',r,lambda d:remove_material(d,'invoice'))
    assert d['forms']['reimbursement']['values']['ticket_total']=='100.00'
