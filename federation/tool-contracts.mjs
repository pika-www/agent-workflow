/** One contract for provider schemas and both host execution boundaries. */
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
export const toolContracts=JSON.parse(readFileSync(new URL('./tool-contracts.json',import.meta.url),'utf8'));
export const MAX_ARGUMENT_BYTES=toolContracts.argument_bytes;
export const MAX_REQUEST_BYTES=toolContracts.request_bytes;
export class NativeArgumentsError extends Error {
 constructor(message,field='$',code='invalid_argument',expected='查看工具参数定义') {
  super(message);this.name='NativeArgumentsError';this.detail={code,field,expected,retryable:true};
 }
}
export function validateContract(name,args) {
 const contract=toolContracts.tools[name];
 const reject=(field,code,expected)=>{throw new NativeArgumentsError((field.includes('file_id')?'附件ID无效；':'')+'参数校验失败：'+field+' '+expected,field,code,expected);};
 if(!contract)reject('$tool','unknown_tool','使用当前允许的工具');
 if(!args||typeof args!=='object'||Array.isArray(args))reject('$','type','JSON 对象');
 const {properties,required}=contract.schema;
 for(const field of required)if(!Object.hasOwn(args,field))reject(field,'required','必填字段');
 for(const field of Object.keys(args))if(!Object.hasOwn(properties,field))reject(field,'additional_property','仅允许字段：'+required.join(', '));
 for(const [field,rule] of Object.entries(properties)){
  const value=args[field];
  if(typeof value!=='string')reject(field,'type','字符串；数字使用十进制字符串');
  const length=Array.from(value).length;
  if(value.includes('\0')||length<rule.minLength||length>rule.maxLength||rule.minLength&&!value.trim())reject(field,'length',`长度 ${rule.minLength} 至 ${rule.maxLength}，不含空字符`);
  if(rule.enum&&!rule.enum.includes(value))reject(field,'enum','允许值：'+rule.enum.join(', '));
  if(rule.pattern&&!new RegExp(rule.pattern,'u').test(value))reject(field,'format',rule.description || rule.pattern);
  const range=contract.numeric[field];
  if(range&&(!Number.isFinite(Number(value))||Number(value)<range.minimum||Number(value)>range.maximum))reject(field,'range',`范围 ${range.minimum} 至 ${range.maximum}`);
 }
 for(const field of contract.json_fields){
  let parsed;try{parsed=JSON.parse(args[field]);}catch{reject(field,'invalid_json','完整 JSON 对象字符串');}
  if(!parsed||typeof parsed!=='object'||Array.isArray(parsed))reject(field,'type','JSON 对象字符串');
  const nested=contract.variants?.[args.action];
  if(nested){
   for(const key of nested.required)if(!Object.hasOwn(parsed,key))reject(field+'.'+key,'required','必填字段');
   for(const [key,value] of Object.entries(parsed)){
    const rule=nested.properties[key],at=field+'.'+key;
    if(!rule)reject(at,'additional_property','仅允许字段：'+Object.keys(nested.properties).join(', '));
    if(rule.type==='integer'&&(!Number.isSafeInteger(value)||value<rule.minimum||value>rule.maximum))reject(at,'range',`整数 ${rule.minimum} 至 ${rule.maximum}`);
    if(rule.type==='string'&&(typeof value!=='string'||Array.from(value).length<(rule.minLength||0)||Array.from(value).length>(rule.maxLength||Infinity)||value.includes('\0')))reject(at,'type','符合长度约束的字符串');
    if(rule.maxBytes&&Buffer.byteLength(value)>rule.maxBytes)reject(at,'byte_length',`UTF-8 字节数不超过 ${rule.maxBytes}`);
    if(rule.enum&&!rule.enum.includes(value))reject(at,'enum','允许值：'+rule.enum.join(', '));
   }
  }
 }
 return args;
}
const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(k=>[k,canonical(value[k])])):value;
export function invocationKey(name,args,raw=''){
 let value=args;try{value=JSON.parse(raw||JSON.stringify(args));}catch{value=raw;}
 if(value&&typeof value==='object')for(const field of toolContracts.tools[name]?.json_fields || [])try{value[field]=JSON.parse(value[field]);}catch{}
 return createHash('sha256').update(JSON.stringify([name,canonical(value)])).digest('hex');
}
export function toolFailureSummary(receipts){
 const result={attempts:receipts.length,executed:0,failed:0,invalid_arguments:0,repeat_blocked:0,first_attempts:0,first_successes:0,correction_attempts:0,correction_successes:0,by_tool:{}};
 const last=new Map();
 for(const r of receipts){
  result.executed+=r.executed===true?1:0;result.failed+=r.status==='failed'?1:0;
  result.invalid_arguments+=r.failure_code==='invalid_arguments'?1:0;result.repeat_blocked+=r.failure_code==='repeated_failure'?1:0;
  const previous=last.get(r.tool);
  if(!previous){result.first_attempts++;result.first_successes+=r.status==='completed'?1:0;}
  else if(previous.status==='failed'&&r.argument_fingerprint!==previous.argument_fingerprint){result.correction_attempts++;result.correction_successes+=r.status==='completed'?1:0;}
  last.set(r.tool,r);
  const key=r.tool;const row=result.by_tool[key]??={attempts:0,failed:0,codes:{}};row.attempts++;row.failed+=r.status==='failed'?1:0;
  if(r.failure_code)row.codes[r.failure_code]=(row.codes[r.failure_code]||0)+1;
 }
 return result;
}
