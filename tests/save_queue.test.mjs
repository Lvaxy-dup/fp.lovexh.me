import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const source=fs.readFileSync(new URL('../static/save-queue.js',import.meta.url),'utf8');
const {SaveQueue}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
function setup(){
 const data=new Map(),requests=[],states=[];
 const storage={getItem:k=>data.get(k),setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)};
 const options={storage,key:'draft',send:values=>new Promise((resolve,reject)=>requests.push({values,resolve,reject})),onState:s=>states.push(s)};
 return {data,requests,states,options,queue:new SaveQueue(options)};
}
const tick=()=>new Promise(setImmediate);
test('later edit remains unsaved until its own request finishes',async()=>{
 const {queue,requests,states,data}=setup();
 queue.edit('name','first');const done=queue.flush();await tick();
 queue.edit('name','second');assert.equal(queue.flush(),done);
 requests[0].resolve({});await tick();
 assert.equal(queue.pending,true);assert.equal(queue.values.get('name'),'second');assert.notEqual(states.at(-1),'saved');
 assert.equal(JSON.parse(data.get('draft')).name,'second');
 requests[1].resolve({});await done;assert.equal(queue.pending,false);assert.equal(states.at(-1),'saved');assert.equal(data.size,0);
});
test('failed request preserves the newest edit and survives reload',async()=>{
 const {queue,requests,options}=setup();
 queue.edit('name','old');const failed=queue.flush();await tick();queue.edit('name','new');
 requests[0].reject(Error('offline'));await assert.rejects(failed,/offline/);
 assert.equal(queue.pending,true);
 const restored=new SaveQueue(options);assert.equal(restored.values.get('name'),'new');
 const done=restored.flush();await tick();assert.equal(requests[1].values.name,'new');requests[1].resolve({});await done;
});
test('separate record and form draft keys never mix',()=>{
 const {queue,options}=setup();queue.edit('name','A');
 assert.equal(new SaveQueue({...options,key:'another-record'}).values.size,0);
 assert.equal(new SaveQueue({...options,key:'another-form'}).values.size,0);
});
