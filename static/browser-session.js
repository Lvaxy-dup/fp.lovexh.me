const SESSION_KEY='travel-session-v1';

export class BrowserSession {
 constructor({fetch=globalThis.fetch,storage=globalThis.localStorage,locks=globalThis.navigator?.locks}={}){
  this.fetch=fetch.bind(globalThis);this.storage=storage;this.locks=locks;this.token=null;
 }
 headers(){return this.token?{'X-Travel-Session':this.token}:{}}
 async restoreToken(token){
  if(!/^[0-9a-f]{64}$/.test(token))throw Error('找回文件格式不正确');
  const response=await this.fetch('/api/session',{method:'POST',credentials:'same-origin',headers:{'X-Travel-Session':token}});
  const data=await response.json();
  if(!response.ok||data.token!==token)throw Error(data.detail||'找回文件与当前服务不匹配');
  this.storage.setItem(SESSION_KEY,token);this.token=token;
 }
 async initialize(){
  const restore=async()=>{
   const saved=this.storage.getItem(SESSION_KEY);
   const response=await this.fetch('/api/session',{method:'POST',credentials:'same-origin',headers:saved?{'X-Travel-Session':saved}:{}});
   const data=await response.json();
   if(!response.ok)throw Error(data.detail||'无法恢复出差记录会话，请稍后重试。');
   if(!/^[0-9a-f]{64}$/.test(data.token))throw Error('服务器返回的会话标识无效。');
   // Persist before any record is created. Failed recovery never overwrites the old token.
   this.storage.setItem(SESSION_KEY,data.token);
   this.token=data.token;
  };
  // Two freshly opened tabs must not create competing browser identities.
  if(this.locks)await this.locks.request('travel-session-init',restore);
  else await restore();
 }
}
