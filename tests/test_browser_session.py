from fastapi.testclient import TestClient

from server import app as api
from server.store import Store
from test_material_api import client


def bootstrap(c,token=None):
    return c.post('/api/session',headers={'X-Travel-Session':token} if token else {})


def test_legacy_cookie_session_is_preserved(client):
    c,_,_=client
    rid=c.post('/api/records',json={'title':'已有出差'}).json()['id']
    c.put('/api/profile',json={'name':'测试老师','job_title':'讲师','department':'计算机系','fund_no':'001'})
    token=bootstrap(c).json()['token']
    old_owner=c.cookies.get('travel_session')
    assert token!=old_owner
    c.cookies.clear()
    response=bootstrap(c,token)
    assert response.status_code==200 and response.json()['token']==token
    assert c.cookies.get('travel_session')==old_owner
    assert c.get('/api/records').json()[0]['id']==rid
    assert c.get('/api/profile').json()['name']=='测试老师'


def test_recovery_header_survives_missing_cookies_on_every_request(client):
    c,_,_=client
    token=bootstrap(c).json()['token'];headers={'X-Travel-Session':token}
    rid=c.post('/api/records',json={'title':'刷新保留测试'},headers=headers).json()['id']
    c.patch('/api/records/'+rid+'/fields',json={'form':'reimbursement','values':{'trip.0.fare':'1080'}},headers=headers)
    for _ in range(3):
        c.cookies.clear()
        assert c.get('/api/records',headers=headers).json()[0]['id']==rid
        c.cookies.clear()
        assert c.get('/api/records/'+rid,headers=headers).json()['forms']['reimbursement']['values']['trip.0.fare']=='1080.00'


def test_static_requests_do_not_create_or_replace_identity(client):
    c,_,_=client
    for path in ('/','/favicon.ico','/static/app.js','/static/browser-session.js','/static/styles.css'):
        response=c.get(path)
        assert response.status_code==200
        assert 'set-cookie' not in response.headers
    assert not c.cookies.get('travel_session')


def test_header_restores_identity_even_with_different_cookie(client):
    c,_,_=client
    first=bootstrap(c).json()['token']
    rid=c.post('/api/records',json={}).json()['id']
    c.cookies.clear()
    second=bootstrap(c).json()['token']
    assert second!=first and c.get('/api/records').json()==[]
    assert c.get('/api/records',headers={'X-Travel-Session':first}).json()[0]['id']==rid
    assert c.get('/api/records/'+rid,headers={'X-Travel-Session':second}).status_code==404


def test_invalid_recovery_never_silently_creates_a_new_identity(client):
    c,_,_=client
    rid=c.post('/api/records',json={}).json()['id']
    for token in ('invalid','a'*64):
        response=bootstrap(c,token)
        assert response.status_code==401 and 'set-cookie' not in response.headers
        assert c.post('/api/records',json={},headers={'X-Travel-Session':token}).status_code==401
    assert len(c.get('/api/records').json())==1
    assert c.get('/api/records').json()[0]['id']==rid


def test_recovery_survives_database_reopen_and_record_id_is_not_a_credential(client,monkeypatch):
    c,_,_=client
    token=bootstrap(c).json()['token']
    rid=c.post('/api/records',json={}).json()['id']
    monkeypatch.setattr(api,'store',Store(api.store.path))
    c.cookies.clear()
    assert bootstrap(c,token).status_code==200
    assert c.get('/api/records').json()[0]['id']==rid
    assert bootstrap(c,rid).status_code==401
