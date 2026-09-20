from fastapi import FastAPI,Request
from fastapi.testclient import TestClient
from server.request_limit import RequestLimit

def test_stream_without_content_length_is_bounded():
    app=FastAPI();app.add_middleware(RequestLimit,max_bytes=10)
    @app.post('/body')
    async def body(request:Request):return {'size':len(await request.body())}
    with TestClient(app) as client:
        assert client.post('/body',content=iter([b'12345',b'678901'])).status_code==413
        assert client.post('/body',content=iter([b'123',b'45'])).json()=={'size':5}
