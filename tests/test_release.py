import asyncio
from io import BytesIO
from pathlib import Path
import shutil
from types import SimpleNamespace
from zipfile import ZipFile,ZIP_DEFLATED
import pytest
from server import app as api
from server.forms import patch,validate
from server.invoice_amounts import verify_invoice_amount
from server.runtime_lock import runtime_lock
from server.storage_paths import material_path
from server.backups import create_backup
from server.maintenance import restore_backup
from server.store import Store
from server.upload_validation import validate_upload
from test_material_api import client,wait_record

def test_fee_flag_can_be_corrected_without_agent_overwriting(tmp_path):
    d=Store(tmp_path/'a.db').create('teacher')
    patch(d,'reimbursement',{'start':'2026-09-11','end':'2026-09-13','has_fee':'是'},'agent')
    assert d['forms']['reimbursement']['values']['allowance_total']=='360'
    patch(d,'reimbursement',{'has_fee':'否','expense_meeting':'0','expense_training':'0'})
    patch(d,'reimbursement',{'has_fee':'是'},'agent')
    assert d['forms']['reimbursement']['values']['allowance_total']=='540'

def test_missing_retry_is_404_and_body_limit_413(client):
    c,_,_=client;rid=c.post('/api/records',json={}).json()['id']
    assert c.post(f'/api/records/{rid}/materials/no-such-file/retry',json={'engine':'deepseek'}).status_code==404
    assert c.post('/api/records',content=b'{}',headers={'Content-Length':str(22*1024*1024)}).status_code==413

def test_new_and_legacy_paths_work_after_relocation(client,monkeypatch):
    c,_,root=client;rid=c.post('/api/records',json={}).json()['id'];url=f'/api/records/{rid}'
    mid=c.post(url+'/materials',files={'file':('sample.txt',b'synthetic')},data={'engine':'deepseek','form':'application'}).json()['material']['id']
    wait_record(c,rid,lambda d:d['materials'][0]['status']=='done')
    owner=c.cookies.get('travel_session');m=api.store.get(owner,rid)['materials'][0]
    assert m['path']==f'uploads/{rid}/{mid}.txt'
    moved=root/'moved';shutil.move(root/'uploads',moved/'uploads')
    monkeypatch.setattr(api.config,'RUNTIME',moved)
    assert c.get(url+f'/materials/{mid}/original').content==b'synthetic'
    api.store.change(owner,rid,lambda d:d['materials'][0].update(path=f'E:\\old\\.runtime\\uploads\\{rid}\\{mid}.txt'))
    assert c.get(url+f'/materials/{mid}/original').content==b'synthetic'
    assert c.delete(url).status_code==200
    assert not (moved/'uploads'/rid/f'{mid}.txt').exists()

def test_concurrent_uploads_recheck_limit_and_dedup(tmp_path,monkeypatch):
    store=Store(tmp_path/'a.db');rid=store.create('teacher')['id']
    monkeypatch.setattr(api,'store',store);monkeypatch.setattr(api.config,'RUNTIME',tmp_path);monkeypatch.setattr(api,'start_material',lambda *args:None)
    store.change('teacher',rid,lambda d:d['materials'].extend({'id':str(i),'sha256':str(i),'form':'application','status':'done'} for i in range(29)))
    async def concurrent(contents):
        arrived=0;barrier=asyncio.Event()
        class Upload:
            filename='sample.txt'
            def __init__(self,content):self.content=content
            async def read(self,limit):
                nonlocal arrived
                arrived+=1
                if arrived==len(contents):barrier.set()
                await barrier.wait();return self.content
        request=SimpleNamespace(state=SimpleNamespace(owner='teacher'))
        return await asyncio.gather(*(api.upload(rid,request,Upload(c),'deepseek','application') for c in contents),return_exceptions=True)
    results=asyncio.run(concurrent([b'identical',b'identical']))
    assert sorted(r['duplicate'] for r in results)==[False,True]
    assert len(store.get('teacher',rid)['materials'])==30
    results=asyncio.run(concurrent([b'different-a',b'different-b']))
    assert all(isinstance(r,ValueError) for r in results)
    assert len(list((tmp_path/'uploads'/rid).iterdir()))==1

def test_second_worker_refused_without_mutating_running_job(tmp_path):
    store=Store(tmp_path/'a.db');rid=store.create('teacher')['id']
    store.change('teacher',rid,lambda d:d['agent'].update(status='running'))
    with runtime_lock(tmp_path):
        with pytest.raises(RuntimeError):
            with runtime_lock(tmp_path):store.recover()
        assert store.get('teacher',rid)['agent']['status']=='running'
    with runtime_lock(tmp_path):pass

def test_backup_restore_preserves_session_records_and_originals(tmp_path):
    root=tmp_path/'data';root.mkdir();store=Store(root/'travel.db');rid=store.create('teacher')['id'];token=store.create_browser_session('teacher')
    material={'id':'sample','path':f'uploads/{rid}/sample.txt','status':'done','form':'application'}
    original=material_path(rid,material,root);original.parent.mkdir(parents=True);original.write_text('synthetic')
    store.change('teacher',rid,lambda d:d['materials'].append(material))
    archive=create_backup(store,root,tmp_path/'snapshot.zip')
    restored=restore_backup(archive,tmp_path/'restored');new_store=Store(restored/'travel.db')
    assert new_store.browser_session_owner(token)=='teacher'
    assert material_path(rid,new_store.get('teacher',rid)['materials'][0],restored).read_text()=='synthetic'
    with pytest.raises(ValueError):restore_backup(archive,restored)

def test_restore_rejects_traversal_before_writing_outside(tmp_path):
    archive=tmp_path/'bad.zip'
    with ZipFile(archive,'w') as z:z.writestr('travel.db',b'bad');z.writestr('../outside.txt','bad')
    with pytest.raises(ValueError):restore_backup(archive,tmp_path/'restore')
    assert not (tmp_path/'outside.txt').exists() and not (tmp_path/'restore').exists()

@pytest.mark.parametrize('text', ['价税合计 ￥2,160.00','价税合计（大写）贰仟壹佰陆拾圆整 （小写）￥2160.00','<td>价税合计</td><td>2160.00</td>'])
def test_supported_total_formats(text):assert verify_invoice_amount(text,'2160')['total']=='2160.00'

def test_tax_subtotal_does_not_replace_grand_total():
    text='合计 2000.00 税额160.00\n价税合计（小写）￥2160.00'
    assert verify_invoice_amount(text,'2160')['total']=='2160.00'
    with pytest.raises(ValueError):verify_invoice_amount(text,'2000')

@pytest.mark.parametrize('text',['没有合计金额','价税合计2160.00\n另一张票价税合计4320.00'])
def test_ambiguous_total_is_not_guessed(text):
    with pytest.raises(ValueError):verify_invoice_amount(text,'2160')

def test_docx_bomb_and_invalid_utf8_rejected():
    content=BytesIO()
    with ZipFile(content,'w',ZIP_DEFLATED) as z:z.writestr('word/document.xml',b'0'*(2*1024*1024))
    with pytest.raises(ValueError):validate_upload(content.getvalue(),'.docx')
    with pytest.raises(ValueError):validate_upload(b'\xff','.txt')
