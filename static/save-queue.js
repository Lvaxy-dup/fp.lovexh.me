// Keep edits until their exact version is acknowledged by the server.
export class SaveQueue {
 constructor({send,storage,key,onState=()=>{},onSaved=()=>{}}){
  Object.assign(this,{send,storage,key,onState,onSaved});
  this.values=new Map();this.versions=new Map();this.running=null;this.version=0;
  const saved=JSON.parse(storage.getItem(key)||'{}');
  for(const [field,value] of Object.entries(saved)){this.values.set(field,value);this.versions.set(field,++this.version)}
 }
 get pending(){return this.values.size>0||this.running!==null}
 persist(){
  if(this.values.size)this.storage.setItem(this.key,JSON.stringify(Object.fromEntries(this.values)));
  else this.storage.removeItem(this.key);
 }
 edit(field,value){
  this.values.set(field,value);this.versions.set(field,++this.version);
  this.onState('saving');
  try{this.persist()}catch(e){this.onState('error');throw Error('本地草稿无法保存，请勿关闭页面：'+e.message)}
 }
 flush(){
  if(this.running)return this.running;
  if(!this.values.size)return Promise.resolve();
  this.onState('saving');
  // Defer the loop until running is assigned, including synchronously failed sends.
  this.running=Promise.resolve().then(async()=>{
   while(this.values.size){
    const values=Object.fromEntries(this.values),versions=new Map(this.versions);
    const result=await this.send(values);
    for(const field of Object.keys(values))if(this.versions.get(field)===versions.get(field)){this.values.delete(field);this.versions.delete(field)}
    this.persist();this.onSaved(result);
   }
  }).then(()=>{this.running=null;this.onState('saved')},error=>{this.running=null;this.onState('error');throw error});
  return this.running;
 }
}
