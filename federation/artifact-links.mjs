/** Only host-returned attachments can resolve provider-invented sandbox URLs. */
export function artifactLinks(text,artifacts=[]) {
 const valid=artifacts.filter(a=>a && /^[a-f0-9]{32}$/.test(a.id || '') && /^[a-f0-9]{32}$/.test(a.room_id || '')
  && /^[a-f0-9]{64}$/.test(a.sha256 || '') && typeof a.name==='string'
  && a.url===`/api/chat/rooms/${a.room_id}/files/${a.id}`);
 return text.replace(/\[([^\]\n]+)\]\((sandbox:[^\s)]+|\/mnt\/data\/[^\s)]+)\)/g,(_match,label,url)=>{
  let name;try{name=decodeURIComponent(url.split('/').at(-1));}catch{return label;}
  const matches=[...new Map(valid.filter(a=>a.name===name).map(a=>[a.id,a])).values()];
  return matches.length===1?`[${label}](${matches[0].url})`:label;
 });
}
