"""Persistent one-click pipeline: await OCR, fill selected forms, publish a non-chat result."""
import asyncio
from .forms import FIELDS,validate


def busy(data):
    return data['agent']['status']=='running' or data.get('pipeline',{}).get('status')=='running'


async def generate(store,agent,owner,rid,forms,material_ids):
    def stage(text):
        store.change(owner,rid,lambda d:d['pipeline'].update(message=text))
    try:
        if len(forms)!=1 or forms[0] not in FIELDS: raise ValueError('一次只允许填写当前表单')
        async with asyncio.timeout(1700):
            stage('正在识别导入材料，完成后自动填表')
            async with asyncio.timeout(680):
                while True:
                    data=store.get(owner,rid)
                    materials=[m for m in data['materials'] if m['id'] in material_ids and m['form']==forms[0]]
                    if all(m['status'] not in ('queued','running') for m in materials): break
                    await asyncio.sleep(1)
            ready=[m for m in materials if m['status']=='done']
            failed=[m['name'] for m in materials if m['status']!='done']
            if not ready: raise ValueError('材料识别失败，请重试识别后再一键填写。')
            errors=[]
            for kind in forms:
                label='出差申请表' if kind=='application' else '差旅报销单'
                stage('正在填写'+label)
                def start(d):
                    d['forms'][kind]['questions']=[]
                    d['agent']={'status':'running','form':kind}
                store.change(owner,rid,start)
                await agent.run(owner,rid,kind,'只阅读当前表单已导入的材料，填写当前表单、补全允许推測的信息，计算并结束，不提问。',automatic=True)
                result=store.get(owner,rid)
                if result['agent']['status']=='error':errors.append(label+'：'+result['agent'].get('message','填写失败'))
                def done(d):
                    check=validate(d,kind)
                    d['forms'][kind]['questions']=[]
                    d['forms'][kind]['generation']={'status':'error' if result['agent']['status']=='error' else 'done','filled':sum(v not in ('',None,[]) for k,v in d['forms'][kind]['values'].items() if k in FIELDS[kind]),'estimated':len(check['estimated']),'missing':len(check['missing'])}
                    d['pipeline']['completed'].append(kind)
                store.change(owner,rid,done)
            def finish(d):
                d['pipeline'].update(status='partial' if failed or errors else 'done',message='已完成可填写内容，请直接核对表格' if not errors else '部分表单填写失败，已保存成功部分',failed_files=failed,errors=errors)
                if d['title']=='新的出差':
                    v=d['forms'][forms[0]]['values']; place=v.get('destination','');day=v.get('start','')
                    if place:d['title']=f'{place}出差'+(f' · {day}' if day else '')
            store.change(owner,rid,finish)
    except asyncio.CancelledError:
        store.change(owner,rid,lambda d:d['pipeline'].update(status='error',message='填写中断，已保存内容保留，可重新填写。'))
        raise
    except Exception as exc:
        text=str(exc) if isinstance(exc,ValueError) else '自动处理超时或中断，已保存内容保留，请重试。'
        store.change(owner,rid,lambda d:d['pipeline'].update(status='error',message=text))
