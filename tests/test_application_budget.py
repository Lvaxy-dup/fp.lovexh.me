import pytest
from server.store import Store
from server.forms import patch,validate
from server.agent import Agent
from server.application_budget import estimate_application_budget,lodging_standard,lodging_tier,lodging_rows
from server.materials import remove_material

@pytest.fixture
def budget(tmp_path):
    store=Store(tmp_path/'test.db');rid=store.create('teacher')['id']
    source={'material_id':'notice','page':2}
    def prepare(d):
        d['materials']=[{'id':'notice','form':'application','status':'done','pages':[{'page':1,'text':'2026年5月14日至16日南京研修班'},{'page':2,'text':'会务费1190元，食宿自理'}]}]
        patch(d,'application',{'start':'2026-05-14','end':'2026-05-16','destination':'南京理工大学（南京市）','has_fee':'是','budget_meeting':'1190'},'agent',source)
    store.change('teacher',rid,prepare)
    return store,rid,source

def estimate(budget,**changes):
    s,r,source=budget
    return s.change('teacher',r,lambda d:estimate_application_budget(d,**{'city':'南京','province':'江苏','one_way_fare':180,'reason':'按徐州东至南京南高铁二等座估算基础单程票价','source':source,**changes}))[0]

def test_notice_budget_and_exact_total(budget):
    d=estimate(budget);v=d['forms']['application']['values']
    assert [v[k] for k in ('budget_transport','budget_hotel','budget_allowance','budget_meeting','budget_total')]==['360.00','760.00','360.00','1190.00','2670.00']
    assert d['forms']['application']['meta']['budget_hotel']['source']['estimated']
    assert '380元/晚' in d['forms']['application']['meta']['budget_hotel']['source']['reason']
    assert not d['forms']['reimbursement']['values']

def test_dates_fee_tier_recalculate_and_manual_budget_stays(budget):
    d=estimate(budget)
    patch(d,'application',{'has_fee':'否','budget_meeting':'0','end':'2026-05-17'})
    v=d['forms']['application']['values'];assert v['budget_hotel']=='1140.00' and v['budget_allowance']=='720.00'
    patch(d,'application',{'lodging_tier':'教授及院领导、院长助理'})
    assert v['budget_hotel']=='1470.00'
    patch(d,'application',{'budget_hotel':'999','budget_transport':'','budget_allowance':'123'})
    patch(d,'application',{'end':'2026-05-18'})
    assert (v['budget_hotel'],v['budget_transport'],v['budget_allowance'])==('999.00','','123.00')

def test_transport_budget_has_no_markup_or_round_up(budget):
    d=estimate(budget,one_way_fare=153.25)
    assert d['forms']['application']['values']['budget_transport']=='306.50'
    check=validate(d,'application')
    assert not check['estimated']
    assert not any('推测' in warning for warning in check['warnings'])
    # Time inference still needs its usual notice; only budget presentation is hidden.
    d['forms']['application']['meta']['start']['source']={'estimated':True,'reason':'推测出发日期'}
    assert any(item['field']=='start' for item in validate(d,'application')['estimated'])

def test_invalid_dates_and_same_day(budget):
    d=estimate(budget);patch(d,'application',{'end':'2026-05-14'})
    v=d['forms']['application']['values'];assert v['budget_hotel']=='0.00' and v['budget_allowance']=='180.00'
    patch(d,'application',{'end':'2026-05-13'})
    assert v['budget_hotel']=='' and v['budget_allowance']==''

def test_destination_change_invalidates_estimates(budget):
    d=estimate(budget);patch(d,'application',{'destination':'上海市'})
    assert d['forms']['application']['values']['budget_transport']==''
    assert d['forms']['application']['values']['budget_hotel']==''
    assert any('目的地已变化' in w for w in validate(d,'application')['warnings'])

def test_removal_cannot_regenerate_budget_from_removed_plan(budget):
    d=estimate(budget);remove_material(d,'notice')
    assert 'budget_plan' not in d['forms']['application']
    assert not d['forms']['application']['values'].get('budget_hotel')
    assert not d['forms']['application']['values'].get('budget_transport')

def test_tool_requires_reading_all_notice_pages_and_stays_scoped(budget):
    s,r,source=budget;agent=Agent(s)
    args={'city':'南京','province':'江苏','one_way_fare':180,'reason':'徐州至南京的高铁二等座估价','source':source}
    with pytest.raises(ValueError,match='所有页面'):agent.execute('teacher',r,'application','estimate_application_budget',args,{('notice',2)},0,'',True)
    agent.execute('teacher',r,'application','estimate_application_budget',args,{('notice',1),('notice',2)},0,'',True)
    with pytest.raises(ValueError,match='只用于申请表'):agent.execute('teacher',r,'reimbursement','estimate_application_budget',args,{('notice',1),('notice',2)},0,'',True)
    with pytest.raises(ValueError,match='预算使用'):agent.execute('teacher',r,'application','fill_fields',{'values':{'budget_transport':'9999'},'source':source},{('notice',2)},0,'',True)

@pytest.mark.parametrize('city,province,rate',[('南京市','江苏省',380),('徐州','江苏',360),('北京','北京',500),('宁波','浙江',350),('成都','四川',370),('厦门','福建',400)])
def test_lodging_table(city,province,rate):assert lodging_standard(city,province)['other']==rate

@pytest.mark.parametrize('title,tier',[('教授','教授及院领导、院长助理'),('副教授','其他人员'),('讲师','其他人员'),('','其他人员'),('院长助理','教授及院领导、院长助理')])
def test_lodging_category(title,tier):assert lodging_tier({'job_title':title})==tier

def test_missing_standard_or_wrong_city_rejected(budget):
    with pytest.raises(ValueError):lodging_standard('巴黎','法国')
    with pytest.raises(ValueError):estimate(budget,city='上海',province='上海')
    assert len(lodging_rows())>50

def test_positive_fee_not_merely_activity_controls_allowance(budget):
    d=estimate(budget)
    patch(d,'application',{'reasons':['会议培训'],'has_fee':'否','budget_meeting':'0'})
    assert d['forms']['application']['values']['budget_allowance']=='540.00'
    patch(d,'application',{'budget_meeting':'100'})
    assert d['forms']['application']['values']['budget_allowance']=='360.00'
