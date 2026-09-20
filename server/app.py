from contextlib import asynccontextmanager
import asyncio
import hashlib
import secrets
import uuid
from pathlib import Path
from urllib.parse import urlparse
import fitz
from fastapi import FastAPI,Request,UploadFile,File,Form,HTTPException
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field,ConfigDict
from . import config
from .store import Store
from .forms import patch,validate,FIELDS
from .agent import Agent
from .extraction import extract
from .workflow import busy,generate
from .materials import remove_material
from .profile import apply_profile
from .storage_paths import material_path
from .runtime_lock import runtime_lock
from .upload_validation import validate_upload
from .backups import backup_loop
from .request_limit import RequestLimit

store=Store(); agent=Agent(store); tasks=set(); material_tasks={}; material_limit=asyncio.Semaphore(3)

def spawn(coro):
    task=asyncio.create_task(coro); tasks.add(task); task.add_done_callback(tasks.discard)
    return task

def start_material(owner,rid,mid):
    key=(owner,rid,mid)
    task=spawn(process(owner,rid,mid));material_tasks[key]=task
    def cleanup(done):
        if material_tasks.get(key) is done:material_tasks.pop(key,None)
    task.add_done_callback(cleanup)

@asynccontextmanager
async def lifespan(app):
    with runtime_lock(config.RUNTIME):
        store.recover()
        if config.AUTO_BACKUP:spawn(backup_loop(store,config.RUNTIME))
        try:yield
        finally:
            for task in list(tasks): task.cancel()
            await asyncio.gather(*list(tasks),return_exceptions=True)

app=FastAPI(title='徐海差旅助手',lifespan=lifespan)
app.add_middleware(RequestLimit,max_bytes=config.MAX_BYTES+1024*1024)

@app.middleware('http')
async def session(request,call_next):
    origin=request.headers.get('origin')
    if request.method not in ('GET','HEAD','OPTIONS') and origin and urlparse(origin).netloc!=request.headers.get('host'):
        return JSONResponse({'detail':'请求来源不匹配'},status_code=403)
    is_api=request.url.path.startswith('/api/')
    raw=request.cookies.get('travel_session','')
    owner=None
    if is_api:
        recovery=request.headers.get('X-Travel-Session')
        if recovery is not None:
            if len(recovery)!=64 or any(c not in '0123456789abcdef' for c in recovery):
                return JSONResponse({'detail':'本地会话标识无效，已停止加载以保护原有记录。'},status_code=401)
            owner=store.browser_session_owner(recovery)
            if owner is None:
                return JSONResponse({'detail':'无法恢复本地会话，请确认连接的是原来的项目服务。原有本地标识已保留。'},status_code=401)
        else:
            owner=raw if len(raw)==64 and all(c in '0123456789abcdef' for c in raw) else secrets.token_hex(32)
        request.state.owner=owner
        request.state.session_token=recovery
    response=await call_next(request)
    if is_api and owner!=raw: response.set_cookie('travel_session',owner,httponly=True,samesite='strict',secure=config.COOKIE_SECURE,max_age=60*60*24*90)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    if request.url.path.startswith('/api'): response.headers['Cache-Control']='no-store'
    else:response.headers['Cache-Control']='no-cache'
    return response

@app.exception_handler(KeyError)
async def missing(request,exc): return JSONResponse({'detail':'未找到记录或文件'},status_code=404)
@app.exception_handler(ValueError)
async def bad(request,exc): return JSONResponse({'detail':str(exc)},status_code=400)


def public(d):
    d.setdefault('pipeline', {'status':'idle','message':'导入材料后，点击填写当前表单。','completed':[],'forms':[]})
    d.setdefault('generation_requests', [])
    d={**d,'materials':[{k:v for k,v in m.items() if k not in ('path','job_id')} for m in d['materials']]}
    d['checks']={kind:validate(d,kind) for kind in FIELDS}
    return d

@app.post('/api/session')
async def browser_session(request:Request):
    token=request.state.session_token or store.create_browser_session(request.state.owner)
    return {'token':token}

@app.get('/healthz',include_in_schema=False)
async def health():
    with store.connect() as db:db.execute('SELECT 1')
    return {'status':'ok'}

@app.get('/api/config')
async def settings(): return {'deepseek_ready':bool(config.API_KEY),'paddle_ready':bool(config.OCR_TOKEN),'model':config.MODEL,'max_pages':config.MAX_PAGES,'fields':FIELDS}
@app.get('/api/records')
async def records(request:Request): return store.list(request.state.owner)

class Profile(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    name:str=Field(min_length=1,max_length=80)
    job_title:str=Field(min_length=1,max_length=80)
    department:str=Field(min_length=1,max_length=100)
    fund_no:str=Field(min_length=1,max_length=100)

@app.get('/api/profile')
async def get_profile(request:Request):
    return store.get_profile(request.state.owner)

@app.put('/api/profile')
async def save_profile(request:Request,body:Profile):
    return store.save_profile(request.state.owner,body.model_dump())

class ProfileForm(BaseModel):
    model_config=ConfigDict(extra='forbid')
    form:str

@app.post('/api/records/{rid}/profile')
async def fill_profile(rid:str,request:Request,body:ProfileForm):
    if body.form not in FIELDS:raise ValueError('未知表单')
    profile=store.get_profile(request.state.owner)
    def edit(d):
        if busy(d):raise HTTPException(409,'正在填写，个人信息将在下次填写时带入')
        return apply_profile(d,body.form,profile)
    return public(store.change(request.state.owner,rid,edit)[0])

class Create(BaseModel): title:str=Field(default='新的出差',min_length=1,max_length=80)
@app.post('/api/records')
async def create(request:Request,body:Create): return public(store.create(request.state.owner,body.title))
@app.get('/api/records/{rid}')
async def record(rid:str,request:Request): return public(store.get(request.state.owner,rid))
@app.delete('/api/records/{rid}')
async def delete_record(rid:str,request:Request):
    def remove(d):
        if busy(d) or any(m['status'] in ('queued','running') for m in d['materials']):
            raise HTTPException(409,'该记录正在识别或填写，请等待完成后再删除')
        # Delete only verified attachment files belonging to this authorized record.
        root=(config.RUNTIME/'uploads').resolve()
        folder=(root/d['id']).resolve()
        if folder.parent!=root:raise ValueError('记录文件路径异常')
        paths=[]
        for material in d['materials']:
            path=material_path(rid,material)
            if path.parent!=folder or path.stem!=material['id']:raise ValueError('材料文件路径异常')
            paths.append(path)
        for path in paths:path.unlink(missing_ok=True)
    store.delete(request.state.owner,rid,remove)
    return {'ok':True}
@app.patch('/api/records/{rid}/title')
async def title(rid:str,request:Request,body:Create): return public(store.change(request.state.owner,rid,lambda d:d.update(title=body.title))[0])

class Edit(BaseModel):
    form:str
    values:dict
    skip:bool=False
@app.patch('/api/records/{rid}/fields')
async def fields(rid:str,request:Request,body:Edit):
    if body.form not in FIELDS: raise ValueError('未知表单')
    return public(store.change(request.state.owner,rid,lambda d:patch(d,body.form,body.values,skip=body.skip))[0])

class Chat(BaseModel):
    form:str
    message:str=Field(min_length=1,max_length=10000)
    request_id:str=Field(min_length=8,max_length=100)
@app.post('/api/records/{rid}/chat')
async def chat(rid:str,request:Request,body:Chat):
    if body.form not in FIELDS: raise ValueError('未知表单')
    def start(d):
        if any(m.get('request_id')==body.request_id for m in d['messages']): return False
        if busy(d): raise HTTPException(409,'助手正在处理，请等待本轮完成；表格仍可编辑。')
        pending=[m for m in d['materials'] if m['form']==body.form and m['status'] in ('queued','running')]
        if pending: raise HTTPException(409,'材料仍在识别，请完成后再开始填写。')
        d['messages'].append({'role':'user','content':body.message,'form':body.form,'request_id':body.request_id})
        d['agent']={'status':'running','form':body.form}
        return True
    data,started=store.change(request.state.owner,rid,start)
    if started: spawn(agent.run(request.state.owner,rid,body.form,body.message))
    return public(data)

class Generate(BaseModel):
    model_config=ConfigDict(extra="forbid")
    form:str
    request_id:str=Field(min_length=8,max_length=100)

@app.post('/api/records/{rid}/generate')
async def generate_forms(rid:str,request:Request,body:Generate):
    if body.form not in FIELDS: raise ValueError('未知表单')
    forms=[body.form]
    profile=store.get_profile(request.state.owner)
    def begin(d):
        if body.request_id in d.get('generation_requests',[]): return False
        if busy(d): raise HTTPException(409,'当前任务正在自动处理，完成后可再次填写')
        if not any(m['form']==body.form for m in d['materials']): raise ValueError('请先为当前表单导入材料')
        apply_profile(d,body.form,profile,refresh=True)
        d['generation_requests']=(d.get('generation_requests',[])+[body.request_id])[-100:]
        d['pipeline']={'status':'running','message':'准备识别与填写','completed':[],'forms':forms,'request_id':body.request_id}
        for k in forms:d['forms'][k]['questions']=[]
        return True
    data,started=store.change(request.state.owner,rid,begin)
    if started:spawn(generate(store,agent,request.state.owner,rid,forms,[m['id'] for m in data['materials'] if m['form']==body.form]))
    return public(data)

async def process(owner,rid,mid):
    async with material_limit:
        d=store.get(owner,rid); m=next((m for m in d['materials'] if m['id']==mid),None)
        if m is None:return
        def progress(text,current=0,total=None,job_id=None):
            def write(d):
                target=next((m for m in d['materials'] if m['id']==mid),None)
                if target is None:return
                target.update(status='running',progress=text,current=current,total=total)
                if job_id: target['job_id']=job_id
            store.change(owner,rid,write)
        try:
            progress('正在准备材料')
            pages=await extract(material_path(rid,m),m['engine'],progress,m.get('job_id'))
            def done(d):
                target=next((m for m in d['materials'] if m['id']==mid),None)
                if target is None:return
                target.update(status='done',pages=pages,progress=f'已识别 {len(pages)} 页',error=None)
            store.change(owner,rid,done)
        except asyncio.CancelledError: raise
        except Exception as e:
            message=str(e) if isinstance(e,ValueError) else '识别连接失败，请重试或切换识别方式。'
            def fail(d):
                target=next((m for m in d['materials'] if m['id']==mid),None)
                if target is None:return
                target.update(status='error',error=message)
                if '查询失败' not in message and '超时' not in message:
                    target.pop('job_id',None)
            store.change(owner,rid,fail)

@app.post('/api/records/{rid}/materials')
async def upload(rid:str,request:Request,file:UploadFile=File(...),engine:str=Form(...),form:str=Form(...)):
    if form not in FIELDS or engine not in ('deepseek','paddle'): raise ValueError('请选择表单和识别方式')
    data=store.get(request.state.owner,rid)
    if busy(data): raise HTTPException(409,'请等待当前填写完成后再添加材料')
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in ('.pdf','.png','.jpg','.jpeg','.webp','.docx','.txt','.md'): raise ValueError('请上传 PDF、图片、DOCX 或文字文件；旧版 DOC 请先另存为 DOCX/PDF。')
    content=await file.read(config.MAX_BYTES+1)
    if len(content)>config.MAX_BYTES: raise ValueError('单个文件不能超过20MB')
    if not content: raise ValueError('文件为空')
    digest=hashlib.sha256(content).hexdigest()
    await asyncio.to_thread(validate_upload,content,suffix)
    mid=uuid.uuid4().hex
    material={'id':mid,'name':Path(file.filename).name,'sha256':digest,'path':f'uploads/{rid}/{mid}{suffix}','engine':engine,'form':form,'status':'queued','pages':[],'progress':'等待识别'}
    path=material_path(rid,material)
    def append(d):
        if busy(d):raise HTTPException(409,'请等待当前填写完成后再添加材料')
        duplicate=next((m for m in d['materials'] if m.get('sha256')==digest and m['form']==form),None)
        if duplicate:return duplicate
        if len(d['materials'])>=30:raise ValueError('每条出差记录最多上传30份材料')
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(content)
        d['materials'].append(material)
    try:
        _,duplicate=store.change(request.state.owner,rid,append)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    if duplicate:return {'duplicate':True,'material':{k:v for k,v in duplicate.items() if k not in ('path','job_id')}}
    start_material(request.state.owner,rid,mid)
    return {'duplicate':False,'material':{k:v for k,v in material.items() if k!='path'}}

class Retry(BaseModel): engine:str
@app.post('/api/records/{rid}/materials/{mid}/retry')
async def retry(rid:str,mid:str,request:Request,body:Retry):
    if body.engine not in ('deepseek','paddle'): raise ValueError('未知识别方式')
    def edit(d):
        if busy(d): raise HTTPException(409,'请等待当前填写完成')
        m=next((m for m in d['materials'] if m['id']==mid),None)
        if m is None:raise KeyError(mid)
        if m['status'] in ('queued','running'): raise HTTPException(409,'正在识别')
        if m['engine']!=body.engine or m['status']=='done': m.pop('job_id',None)
        m.update(engine=body.engine,status='queued',pages=[],error=None)
    store.change(request.state.owner,rid,edit)
    start_material(request.state.owner,rid,mid)
    return {'ok':True}

@app.delete('/api/records/{rid}/materials/{mid}')
async def delete_material(rid:str,mid:str,request:Request):
    owner=request.state.owner
    def remove(d):
        if busy(d):raise HTTPException(409,'正在填写，请等待本轮完成后移除材料')
        return remove_material(d,mid)
    data,result=store.change(owner,rid,remove)
    task=material_tasks.get((owner,rid,mid))
    if task:
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)
    # Only remove this verified attachment, never a recursive or client-supplied path.
    path=material_path(rid,result['material'])
    folder=(config.RUNTIME/'uploads'/rid).resolve()
    if path.parent==folder and path.stem==mid:
        path.unlink(missing_ok=True)
    return {'record':public(data),'cleared_fields':result['cleared']}

@app.get('/api/records/{rid}/materials/{mid}/original')
async def original(rid:str,mid:str,request:Request):
    d=store.get(request.state.owner,rid); m=next((m for m in d['materials'] if m['id']==mid),None)
    if m is None:raise KeyError(mid)
    path=material_path(rid,m)
    if not path.is_file():raise KeyError(mid)
    return FileResponse(path,filename=m['name'],content_disposition_type='inline')

@app.get('/favicon.ico', include_in_schema=False)
async def favicon():
    return FileResponse(config.ROOT/'static/images/college-emblem.ico', media_type='image/vnd.microsoft.icon')

@app.get('/')
async def index(): return FileResponse(config.ROOT/'static/index.html')
app.mount('/static',StaticFiles(directory=config.ROOT/'static'),name='static')
