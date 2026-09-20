import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../static/browser-session.js',import.meta.url),'utf8');
const {BrowserSession}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const key='travel-session-v1',token='b'.repeat(64);
test('imported recovery file must be validated before replacing identity',async()=>{
 const local=storage();local.setItem(key,token);
 const denied=new BrowserSession({storage:local,locks:null,fetch:async()=>({ok:false,json:async()=>({detail:'not found'})})});
 await assert.rejects(denied.restoreToken('c'.repeat(64)),/not found/);assert.equal(local.getItem(key),token);
 const approved=new BrowserSession({storage:local,locks:null,fetch:async(url,options)=>({ok:true,json:async()=>({token:options.headers['X-Travel-Session']})})});
 await approved.restoreToken('c'.repeat(64));assert.equal(local.getItem(key),'c'.repeat(64));
});
function storage(){const data=new Map();return {getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v)}}

test('native fetch keeps its browser receiver',async()=>{
 const fetch=async function(){assert.equal(this,globalThis);return {ok:true,json:async()=>({token})}};
 await new BrowserSession({fetch,storage:storage(),locks:null}).initialize();
});

test('fresh bootstrap persists token and refresh reuses it',async()=>{
 const local=storage();let calls=0;
 const fetch=async(url,options)=>{
  assert.equal(url,'/api/session');assert.equal(options.credentials,'same-origin');
  assert.equal(options.headers['X-Travel-Session'],calls++?token:undefined);
  return {ok:true,json:async()=>({token})};
 };
 const first=new BrowserSession({fetch,storage:local,locks:null});await first.initialize();
 assert.equal(local.getItem(key),token);
 const refreshed=new BrowserSession({fetch,storage:local,locks:null});await refreshed.initialize();
 assert.equal(refreshed.headers()['X-Travel-Session'],token);
});

test('recovery failure preserves saved identity',async()=>{
 const local=storage();local.setItem(key,token);
 const session=new BrowserSession({storage:local,locks:null,fetch:async()=>({ok:false,json:async()=>({detail:'无法恢复'})})});
 await assert.rejects(session.initialize(),/无法恢复/);
 assert.equal(local.getItem(key),token);assert.deepEqual(session.headers(),{});
});

test('two new tabs serialize initialization and reuse one identity',async()=>{
 const local=storage();let tail=Promise.resolve(),created=0;
 const locks={request:(_,fn)=>{const current=tail.then(fn);tail=current.catch(()=>{});return current}};
 const fetch=async(_,options)=>{
  if(!options.headers['X-Travel-Session'])created++;
  return {ok:true,json:async()=>({token})};
 };
 const a=new BrowserSession({fetch,storage:local,locks}),b=new BrowserSession({fetch,storage:local,locks});
 await Promise.all([a.initialize(),b.initialize()]);assert.equal(created,1);assert.deepEqual(a.headers(),b.headers());
});
