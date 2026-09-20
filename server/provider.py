"""OpenAI-compatible provider. Reasoning/tool messages are preserved across rounds."""
import httpx
import ssl
from . import config


async def completion(messages, tools=None, max_tokens=5000):
    if not config.API_KEY:
        raise ValueError('尚未配置 DeepSeek API Key，请在后端 .env 中设置。')
    payload = {'model':config.MODEL,'messages':messages,'stream':False,'max_tokens':max_tokens,
               'temperature':0.1, 'thinking':{'type':'disabled'}}
    if tools:
        payload.update(tools=tools,tool_choice='auto')
    async with httpx.AsyncClient(timeout=httpx.Timeout(180,connect=20), trust_env=False, verify=ssl.create_default_context()) as client:
        response=await client.post(config.API_BASE+'/chat/completions',headers={'Authorization':'Bearer '+config.API_KEY},json=payload)
    if response.status_code != 200:
        raise ValueError(f'DeepSeek 请求失败（HTTP {response.status_code}），请检查模型配置或稍后重试。')
    body=response.json()
    choice=body['choices'][0]
    if choice.get('finish_reason')=='length':
        raise ValueError('模型输出超出长度限制，请减少本次材料或拆分操作。')
    msg=choice['message']
    return {k:v for k,v in msg.items() if k in ('role','content','tool_calls','reasoning_content')}

