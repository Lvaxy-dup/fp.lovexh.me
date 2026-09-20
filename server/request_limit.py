from fastapi import HTTPException
from starlette.responses import JSONResponse

class RequestLimit:
    def __init__(self,app,max_bytes):self.app=app;self.max_bytes=max_bytes
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        try:length=int(dict(scope['headers']).get(b'content-length',b'0'))
        except ValueError:length=-1
        if length<0 or length>self.max_bytes:
            return await JSONResponse({'detail':'请求体超过21MB或长度无效'},status_code=413)(scope,receive,send)
        size=0
        async def limited_receive():
            nonlocal size
            message=await receive()
            size+=len(message.get('body',b''))
            if size>self.max_bytes:raise HTTPException(413,'请求体超过21MB')
            return message
        await self.app(scope,limited_receive,send)
