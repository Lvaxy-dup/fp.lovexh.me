from decimal import Decimal

import pytest

from server.agent import Agent
from server.forms import patch, validate
from server.materials import remove_material
from server.store import Store


@pytest.fixture
def flight(tmp_path):
    store=Store(tmp_path/'flight.db')
    rid=store.create('teacher')['id']
    source={'material_id':'flight','page':1}
    def prepare(d):
        d['materials']=[{'id':'flight','name':'飞机发票.pdf','form':'reimbursement','status':'done',
                         'pages':[{'page':1,'text':'发票号码 00000000000000000001 价税合计2160.00；3U8992 南京-成都 2026年07月11日；3U8991 成都-南京 2026年07月13日'}]}]
        patch(d,'reimbursement',{'trip.0.mode':'飞机 3U8992','trip.0.start':'2026-07-11','trip.0.origin':'南京','trip.0.destination':'成都',
                                 'trip.1.mode':'飞机 3U8991','trip.1.start':'2026-07-13','trip.1.origin':'成都','trip.1.destination':'南京'},'agent',source)
    store.change('teacher',rid,prepare)
    agent=Agent(store)
    def execute(name,**args):
        return agent.execute('teacher',rid,'reimbursement',name,{'source':source,**args},{('flight',1)},0,'',automatic=True)
    return store,rid,execute


def invoice(execute,**changes):
    return execute('record_transport_invoice',**{'rows':[0,1],'invoice_no':'00000000000000000001','total':'2160',**changes})


def estimate(execute,row=0,**changes):
    return execute('estimate_flight_times',**{'row':row,'duration_minutes':150,'departure_time':'10:00',
                   'reason':'票面只有日期，暂定10点起飞，按南京成都航线估算150分钟，未查实时航班时刻表。',**changes})


def form(store,rid):
    return store.get('teacher',rid)['forms']['reimbursement']


def test_round_trip_total_charged_once_and_repeat_is_idempotent(flight):
    s,r,run=flight
    for _ in range(2): invoice(run)
    f=form(s,r)
    assert [f['values'][f'trip.{i}.fare'] for i in range(2)]==['1080.00','1080.00']
    assert f['values']['transport_total']=='2160.00'
    assert sum(Decimal(f['values'][f'trip.{i}.fare']) for i in range(2))==Decimal('2160')
    assert not any('重复' in warning for warning in validate(s.get('teacher',r),'reimbursement')['warnings'])
    assert f['meta']['trip.1.fare']['source']['transport_invoice']['allocation']=='equal'


def test_corrects_old_agent_duplicate_amounts(flight):
    s,r,run=flight
    s.change('teacher',r,lambda d:patch(d,'reimbursement',{'trip.0.fare':'2160','trip.1.fare':'2160',
             'trip.0.invoice':'00000000000000000001-去程','trip.1.invoice':'00000000000000000001-返程'},'agent'))
    invoice(run)
    assert form(s,r)['values']['transport_total']=='2160.00'
    assert form(s,r)['values']['trip.1.fare']=='1080.00'


@pytest.mark.parametrize('total,expected',[('2160.01',['1080.01','1080.00']),('0.01',['0.01','0.00']),('0',['0.00','0.00'])])
def test_split_preserves_every_cent(flight,total,expected):
    s,r,run=flight
    s.change('teacher',r,lambda d:d['materials'][0]['pages'][0].update(text=f'发票号码 00000000000000000001 价税合计 {total}'))
    invoice(run,total=total)
    v=form(s,r)['values']
    assert [v[f'trip.{i}.fare'] for i in range(2)]==expected
    assert Decimal(v['transport_total'])==Decimal(total)


def test_manual_edit_of_allocated_fare_is_included_in_total(flight):
    s,r,run=flight
    invoice(run)
    s.change('teacher',r,lambda d:patch(d,'reimbursement',{'trip.1.fare':'1100'}))
    assert form(s,r)['values']['transport_total']=='2180.00'
    assert any('原票总额不一致' in w for w in validate(s.get('teacher',r),'reimbursement')['warnings'])

def test_wrong_model_total_is_rejected_before_write(flight):
    s,r,run=flight
    before=form(s,r)
    with pytest.raises(ValueError,match='票面合计不一致'):invoice(run,total='4320')
    assert form(s,r)==before

def test_explicit_segment_prices_preserve_invoice_breakdown(flight):
    s,r,run=flight
    s.change('teacher',r,lambda d:d['materials'][0]['pages'][0].update(text='发票号码 00000000000000000001 去程1000.00 返程1160.00 价税合计2160.00'))
    invoice(run,amounts={'0':'1000','1':'1160'})
    v=form(s,r)['values']
    assert [v['trip.0.fare'],v['trip.1.fare'],v['transport_total']]==['1000.00','1160.00','2160.00']
    with pytest.raises(ValueError):invoice(run,amounts={'0':'1000','1':'1000'})


def test_extra_duplicate_row_is_not_part_of_allocation(flight):
    s,r,run=flight
    invoice(run)
    s.change('teacher',r,lambda d:patch(d,'reimbursement',{'trip.2.invoice':'00000000000000000001','trip.2.fare':'2160'}))
    assert form(s,r)['values']['transport_total']=='2160.00'
    assert any('重复' in x for x in validate(s.get('teacher',r),'reimbursement')['warnings'])


def test_cannot_bypass_invoice_accounting_or_invent_suffix(flight):
    _,_,run=flight
    with pytest.raises(ValueError,match='record_transport_invoice'):
        run('fill_fields',values={'trip.0.fare':'2160','trip.1.fare':'2160'})
    with pytest.raises(ValueError,match='票号必须来自'):
        invoice(run,invoice_no='00000000000000000001-返程')


def test_invoice_cannot_move_to_duplicate_rows(flight):
    _,_,run=flight
    invoice(run)
    with pytest.raises(ValueError,match='复用'):
        invoice(run,rows=[2,3])


def test_manual_fare_protects_whole_invoice_update(flight):
    s,r,run=flight
    invoice(run)
    s.change('teacher',r,lambda d:patch(d,'reimbursement',{'trip.0.fare':'2000'}))
    before=form(s,r)
    assert invoice(run,total='2200')['conflicts']==['trip.0.fare']
    assert form(s,r)==before


def test_expense_and_transport_are_not_double_counted(flight):
    _,_,run=flight
    invoice(run)
    with pytest.raises(ValueError,match='不能重复'):
        run('record_expense',invoice_no='00000000000000000001',category='other',amount='100')


def test_flight_missing_times_are_filled_and_marked(flight):
    s,r,run=flight
    invoice(run)
    estimate(run,0);estimate(run,1)
    f=form(s,r)
    for row,day in [(0,'2026-07-11'),(1,'2026-07-13')]:
        assert f['values'][f'trip.{row}.start']==day
        assert f['values'][f'trip.{row}.end']==day
        assert f['values'][f'trip.{row}.start_time']=='10:00'
        assert f['values'][f'trip.{row}.end_time']=='12:30'
        for key in ('start_time','end','end_time'):
            assert f['meta'][f'trip.{row}.{key}']['source']['estimated']
        assert not f['meta'][f'trip.{row}.start']['source'].get('estimated')
    assert f['values']['start']=='2026-07-11' and f['values']['end']=='2026-07-13'
    assert f['values']['allowance_total']=='540'
    check=validate(s.get('teacher',r),'reimbursement')
    assert not any(x['field'].startswith('trip.') for x in check['missing'])
    assert len(check['estimated'])==6


def test_cross_midnight_uses_existing_departure(flight):
    s,r,run=flight
    s.change('teacher',r,lambda d:patch(d,'reimbursement',{'trip.0.start_time':'23:30'}))
    estimate(run)
    f=form(s,r)
    assert f['values']['trip.0.end']=='2026-07-12'
    assert f['values']['trip.0.end_time']=='02:00'
    assert f['meta']['trip.0.start_time']['owner']=='user'


@pytest.mark.parametrize('owner',['user','agent'])
def test_inference_does_not_change_known_arrival_date(flight,owner):
    s,r,run=flight
    s.change('teacher',r,lambda d:patch(d,'reimbursement',{'trip.0.end':'2026-07-11'},owner))
    with pytest.raises(ValueError,match='冲突'):
        estimate(run,departure_time='23:30')
    assert not form(s,r)['values'].get('trip.0.start_time')


def test_known_arrival_can_infer_missing_departure(flight):
    s,r,run=flight
    s.change('teacher',r,lambda d:patch(d,'reimbursement',{'trip.0.end':'2026-07-11','trip.0.end_time':'15:00'}))
    estimate(run)
    assert form(s,r)['values']['trip.0.start_time']=='12:30'
    assert form(s,r)['meta']['trip.0.end_time']['owner']=='user'


def test_manual_blank_time_stays_blank(flight):
    s,r,run=flight
    s.change('teacher',r,lambda d:patch(d,'reimbursement',{'trip.0.start_time':''}))
    estimate(run)
    assert form(s,r)['values']['trip.0.start_time']==''


def test_removed_invoice_clears_amounts_and_inferred_times(flight):
    s,r,run=flight
    invoice(run);estimate(run);estimate(run,1)
    s.change('teacher',r,lambda d:remove_material(d,'flight'))
    f=form(s,r)
    assert not f['values'].get('transport_total')
    assert not f['values'].get('trip.1.end_time')
    assert not any(m.get('source',{}).get('transport_invoice') for m in f['meta'].values())


def test_duplicate_invoice_does_not_skip_return_time_validation(flight):
    s,r,run=flight
    invoice(run)
    estimate(run,1)
    warnings=validate(s.get('teacher',r),'reimbursement')['warnings']
    assert any('第2段到达时间' in warning for warning in warnings)
