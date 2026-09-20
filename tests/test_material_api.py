import asyncio
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from server import app as api
from server.store import Store

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(api.config,'AUTO_BACKUP',False)
    monkeypatch.setattr(api,'store',Store(tmp_path/'api.db'))
    monkeypatch.setattr(api.config,'RUNTIME',tmp_path)
    calls=[]
    class FakeAgent:
        async def run(self,owner,rid,kind,question,automatic=False):
            calls.append(kind)
            api.store.change(owner,rid,lambda d:d['agent'].update(status='idle'))
    async def extract(path,engine,progress,job=None):
        await asyncio.sleep(.15)
        return [{'page':1,'text':'测试材料'}]
    monkeypatch.setattr(api,'agent',FakeAgent())
    monkeypatch.setattr(api,'extract',extract)
    with TestClient(api.app) as c:
        yield c,calls,tmp_path


def wait_record(c,rid,predicate):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        d=c.get('/api/records/'+rid).json()
        if predicate(d):return d
        time.sleep(.03)
    raise AssertionError(d)


def test_upload_and_retry_do_not_fill_and_generate_is_scoped(client):
    c,calls,_=client
    rid=c.post('/api/records',json={}).json()['id']
    path='/api/records/'+rid
    upload=c.post(path+'/materials',files={'file':('a.txt',b'notice')},data={'engine':'deepseek','form':'application'})
    assert upload.status_code==200
    mid=upload.json()['material']['id']
    wait_record(c,rid,lambda d:d['materials'][0]['status']=='done')
    assert calls==[]
    assert c.post(path+'/materials/'+mid+'/retry',json={'engine':'deepseek'}).status_code==200
    wait_record(c,rid,lambda d:d['materials'][0]['status']=='done')
    assert calls==[]
    assert c.post(path+'/generate',json={'form':'reimbursement','request_id':'wrong-form-1'}).status_code==400
    assert c.post(path+'/generate',json={'form':'application','both':True,'request_id':'legacy-both-1'}).status_code==422
    assert c.post(path+'/generate',json={'form':'application','request_id':'single-form-1'}).status_code==200
    d=wait_record(c,rid,lambda d:d['pipeline']['status']=='done')
    assert calls==['application'] and d['pipeline']['completed']==['application']
    assert not d['forms']['reimbursement']['values'].get('name')


def test_removal_cancels_ocr_and_removes_original(client):
    c,calls,root=client
    rid=c.post('/api/records',json={}).json()['id'];path='/api/records/'+rid
    result=c.post(path+'/materials',files={'file':('a.txt',b'notice')},data={'engine':'deepseek','form':'application'}).json()
    mid=result['material']['id']
    assert c.delete(path+'/materials/'+mid).status_code==200
    time.sleep(.2)
    assert c.get(path).json()['materials']==[] and calls==[]
    assert not list((root/'uploads'/rid).glob(mid+'*'))
    assert c.get(path+'/materials/'+mid+'/original').status_code==404
    assert c.delete(path+'/materials/'+mid).status_code==404
    assert c.post(path+'/generate',json={'form':'application','request_id':'empty-files-1'}).status_code==400


def test_profile_validation_persistence_and_session_isolation(client):
    c,_,_=client
    assert c.get('/api/profile').json()=={'name':'','job_title':'','department':'','fund_no':'','fund_name':''}
    values={'name':' 张老师 ','job_title':'讲师','department':'计算机系','fund_no':'00123'}
    response=c.put('/api/profile',json=values)
    assert response.status_code==200 and response.json()['name']=='张老师'
    assert response.json()['fund_no']=='00123' and response.json()['fund_name']=='计算机系经费'
    assert c.put('/api/profile',json={**values,'fund_no':'  '}).status_code==422
    assert c.put('/api/profile',json={k:v for k,v in values.items() if k!='fund_no'}).status_code==422
    assert c.put('/api/profile',json={**values,'name':'  '}).status_code==422
    assert c.put('/api/profile',json={**values,'owner':'another'}).status_code==422
    owner=c.cookies.get('travel_session')
    assert Store(api.store.path).get_profile(owner)['department']=='计算机系'
    c.cookies.clear()
    assert c.get('/api/profile').json()['name']==''
    assert api.store.get_profile(owner)['name']=='张老师'


def test_profile_apply_is_scoped_and_protected(client):
    from server.forms import patch
    c,_,_=client
    c.put('/api/profile',json={'name':'张老师','job_title':'讲师','department':'计算机系','fund_no':'00123'})
    rid=c.post('/api/records',json={}).json()['id'];path='/api/records/'+rid
    assert c.post(path+'/profile',json={'form':'both'}).status_code==400
    d=c.post(path+'/profile',json={'form':'application'}).json()
    assert d['forms']['application']['values']['name']=='张老师'
    assert d['forms']['application']['values']['fund_no']=='00123'
    assert d['forms']['application']['values']['fund_name']=='计算机系经费'
    assert d['forms']['application']['values']['job_title']=='讲师'
    assert not d['forms']['reimbursement']['values'].get('name')
    owner=c.cookies.get('travel_session')
    d=api.store.change(owner,rid,lambda d:patch(d,'application',{'name':'模型乱填'},owner='agent'))[0]
    assert d['forms']['application']['values']['name']=='张老师'
    c.patch(path+'/fields',json={'form':'application','values':{'name':'代办老师','department':'','fund_no':'手工编号','fund_name':''}})
    d=c.post(path+'/profile',json={'form':'application'}).json()
    assert d['forms']['application']['values']['name']=='代办老师'
    assert d['forms']['application']['values']['department']==''
    assert d['forms']['application']['values']['fund_no']=='手工编号'
    assert d['forms']['application']['values']['fund_name']==''
    d=c.post(path+'/profile',json={'form':'reimbursement'}).json()
    assert d['forms']['reimbursement']['values']['job_title']=='讲师'
    assert d['forms']['reimbursement']['values']['fund_no']=='00123'
    assert d['forms']['reimbursement']['values']['fund_name']=='计算机系经费'


def test_generate_refreshes_profile_defaults_only_for_selected_form(client):
    c,calls,_=client
    c.put('/api/profile',json={'name':'张老师','job_title':'讲师','department':'计算机系','fund_no':'00123'})
    rid=c.post('/api/records',json={}).json()['id'];path='/api/records/'+rid
    c.post(path+'/profile',json={'form':'reimbursement'})
    c.patch(path+'/fields',json={'form':'reimbursement','values':{'name':'手动姓名'}})
    c.put('/api/profile',json={'name':'新姓名','job_title':'副教授','department':'教务处','fund_no':'00999'})
    before=c.get(path).json()
    assert before['forms']['reimbursement']['values']['job_title']=='讲师'
    c.post(path+'/materials',files={'file':('a.txt',b'ticket')},data={'engine':'deepseek','form':'reimbursement'})
    c.post(path+'/generate',json={'form':'reimbursement','request_id':'profile-fill-1'})
    d=wait_record(c,rid,lambda d:d['pipeline']['status']=='done')
    v=d['forms']['reimbursement']['values']
    assert v['name']=='手动姓名' and v['job_title']=='副教授' and v['department']=='教务处'
    assert v['fund_no']=='00999' and v['fund_name']=='教务处经费'
    assert d['forms']['application']==before['forms']['application']
    assert calls==['reimbursement']


def test_legacy_profile_without_funding_still_loads(client):
    import json
    c,_,_=client
    c.get('/api/profile')
    owner=c.cookies.get('travel_session')
    with api.store.connect() as db:
        db.execute('INSERT INTO profiles VALUES (?,?)',(owner,json.dumps({'name':'旧用户','job_title':'讲师','department':'财务处'})))
    profile=c.get('/api/profile').json()
    assert profile['name']=='旧用户' and profile['fund_no']==''
    assert profile['fund_name']=='财务处经费'


def test_delete_record_removes_owned_materials_but_keeps_profile_and_other_records(client):
    c,_,root=client
    c.put('/api/profile',json={'name':'老师','job_title':'讲师','department':'计算机系','fund_no':'01'})
    rid=c.post('/api/records',json={}).json()['id'];path='/api/records/'+rid
    other=c.post('/api/records',json={}).json()['id']
    c.post(path+'/materials',files={'file':('a.txt',b'notice')},data={'engine':'deepseek','form':'application'})
    wait_record(c,rid,lambda d:d['materials'][0]['status']=='done')
    assert list((root/'uploads'/rid).iterdir())
    assert c.delete(path).status_code==200
    assert c.get(path).status_code==404 and c.delete(path).status_code==404
    assert not list((root/'uploads'/rid).iterdir())
    assert [r['id'] for r in c.get('/api/records').json()]==[other]
    assert c.get('/api/profile').json()['fund_no']=='01'


def test_delete_record_rejects_other_owner_and_running_jobs(client):
    c,_,_=client
    rid=c.post('/api/records',json={}).json()['id'];path='/api/records/'+rid
    owner=c.cookies.get('travel_session')
    c.cookies.clear()
    assert c.delete(path).status_code==404
    c.cookies.set('travel_session',owner)
    for field in ('agent','pipeline'):
        api.store.change(owner,rid,lambda d:d[field].update(status='running'))
        assert c.delete(path).status_code==409
        api.store.change(owner,rid,lambda d:d[field].update(status='idle'))
    api.store.change(owner,rid,lambda d:d['materials'].append({'id':'pending','status':'running'}))
    assert c.delete(path).status_code==409
    assert api.store.get(owner,rid)


def test_delete_record_rejects_attachment_outside_record_folder(client):
    c,_,root=client
    rid=c.post('/api/records',json={}).json()['id']
    owner=c.cookies.get('travel_session');outside=root/'keep.txt';outside.write_text('keep')
    api.store.change(owner,rid,lambda d:d['materials'].append({'id':'keep','status':'done','path':str(outside)}))
    assert c.delete('/api/records/'+rid).status_code==400
    assert outside.read_text()=='keep' and api.store.get(owner,rid)
