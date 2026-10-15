/** Service state and image checks: controlled API responses, no remote account or model calls. */
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.listeners={};this.style={};this.dataset={};this.value='';this._text='';this.open=false;}
  set textContent(v){this._text=String(v);this.children=[];}
  get textContent(){return this._text+this.children.map(n=>n.textContent).join('');}
  set innerHTML(v){throw Error('Unsafe HTML');}
  append(...n){this.children.push(...n);}
  prepend(...n){this.children.unshift(...n);}
  replaceChildren(...n){this._text='';this.children=n;}
  setAttribute(k,v){this[k]=v;}
  addEventListener(k,v){this.listeners[k]=v;}
  showModal(){this.open=true;}
  close(){this.open=false;this.listeners.close?.();}
  querySelector(q){if(q==='.ag-compose-actions')return actions;if(q==='[name=provider]')return walk(this).find(n=>n.name==='provider');return null;}
  querySelectorAll(){return [];}
  get elements(){return walk(this).filter(n=>['input','select','button'].includes(n.tagName));}
}
const walk=n=>[n,...n.children.flatMap(walk)];
const body=new Element('body'),form=new Element('form'),actions=new Element('div'),header=new Element('div');
const rid='a'.repeat(32),fid='b'.repeat(32),calls=[];
let services={image:{configured:true,verified:false,enabled:true,reuse_report:true,model:'gpt-image-1',response_model:'main-fixture',image_api:'responses'},connectors:{notion:{enabled:true,configured:true,identity_verified:false,verified:false}}};
const sandbox={window:{},document:{body,createElement:tag=>new Element(tag),getElementById:()=>form,querySelector:()=>header,querySelectorAll:()=>[]},Map,Set,Object,Array,String,JSON,Promise,Error,setTimeout,clearTimeout};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(new URL('../federation/web/agent-tools.js',import.meta.url),'utf8').replace('export function','function'),sandbox);
await sandbox.initializeTools({getRoom:()=>({id:rid,status:'idle',messages:[]}),notice(){},api:async(path,options)=>{
  calls.push({path,options});
  if(path==='/api/tool-services/status')return services;
  if(path==='/api/platform-mcp/status')return {platforms:[{id:'bilibili',name:'B站',installed:true,handshake_verified:true,credentials_saved:false,login:{}}]};
  if(path==='/api/tool-services/image' && options.method==='PUT'){services={...services,image:{...services.image,verified:false}};return services;}
  if(path==='/api/tool-services/connectors/notion/check'){
    services.connectors.notion.identity_verified=true;return {identity:'<img src=x onerror=bad()>',scope:'connection_identity',read_verified:false};
  }
  if(path==='/api/tool-services/image/check'){
    services.image.verified=true;return {status:'completed',artifacts:[{id:fid,room_id:rid,name:'test.png',kind:'image',url:`/api/chat/rooms/${rid}/files/${fid}`},{id:fid,room_id:'c'.repeat(32),name:'wrong-room',kind:'image',url:`/api/chat/rooms/${rid}/files/${fid}`},{id:fid,room_id:rid,name:'unsafe',kind:'image',url:'javascript:alert(1)'}]};
  }
  throw Error('Unexpected request: '+path);
}});
await walk(header).find(n=>n.tagName==='button' && n.textContent==='工具与连接').listeners.click();
await new Promise(resolve=>setImmediate(resolve));
const dialog=walk(body).find(n=>n.tagName==='dialog'),sections=dialog.children.filter(n=>n.tagName==='section');
const image=sections.find(n=>n.children[0].textContent==='生成图片'),notion=sections.find(n=>n.children[0].textContent==='Notion');
assert.equal(walk(image).find(n=>n.name==='image_api').value,'responses');
assert.equal(walk(image).find(n=>n.name==='response_model').value,'main-fixture');
assert.equal(calls.filter(c=>c.path.endsWith('/image/check')).length,0,'Opening settings must not generate an image');
await walk(notion).find(n=>n.textContent==='验证账号').listeners.click();
assert.match(notion.children[1].textContent,/账号已连接.*尚未验证/);
assert.match(notion.textContent,/<img src=x onerror=bad\(\)>/);
assert.equal(walk(notion).filter(n=>n.tagName==='img').length,0,'Identity is rendered as text');
await walk(image).find(n=>n.textContent==='生成测试图片').listeners.click();
assert.equal(calls.filter(c=>c.path.endsWith('/image/check')).length,1);
assert.equal(JSON.parse(calls.find(c=>c.path.endsWith('/image/check')).options.body).room_id,rid);
assert.equal(walk(image).filter(n=>n.tagName==='img').length,1,'Only host-scoped artifact may preview');
assert.equal(walk(image).filter(n=>n.tagName==='a').length,1);
assert.match(image.children[1].textContent,/实际调用验证/);
await walk(image).find(n=>n.tagName==='form').listeners.submit({preventDefault(){}});
assert.match(image.children[1].textContent,/尚未完成实际调用验证/,'A config save invalidates prior proof');
const saved=JSON.parse(calls.find(c=>c.path==='/api/tool-services/image').options.body);
assert.equal(saved.image_api,'responses');assert.equal(saved.response_model,'main-fixture');
console.log('Tool settings behavioral checks passed: explicit image call, identity scope, safe artifacts and changed-config status.');

const platforms=sections.find(n=>n['aria-label']==='平台 MCP');
assert.match(platforms.textContent,/部分公开信息可读/);
assert.equal(calls.filter(c=>c.path.endsWith('/login')).length,0,'Opening settings never starts login or writes to a platform');
