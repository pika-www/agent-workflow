/** Explicit platform research uses installed tools before generic web search. */
export function platformLookup(question,policy={}){
 if(!policy.tools_enabled||!policy.network_allowed||typeof question!=='string')return null;
 if(/不(?:要|用)?(?:联网|上网|搜索)|离线|只用本地/.test(question))return null;
 if(!/(?:搜|查|找|读取|看看|看一下|分析|总结|评论|楼中楼|弹幕)/u.test(question))return null;
 const matches=[[/B站|哔哩哔哩|bilibili(?:\.com)?/iu,'bilibili'],[/抖音|douyin(?:\.com)?/iu,'douyin'],[/贴吧|tieba\.baidu\.com/iu,'tieba']].filter(([pattern])=>pattern.test(question));
 if(matches.length!==1)return null;
 const platform=matches[0][1];
 return {key:'platform-read:'+platform,instruction:'本轮要求读取平台内容。先检查实际平台工具和登录状态，再调用只读工具取得内容或评论；不要用热榜代替评论。',
  next({receipts,allowed}){return !receipts.some(r=>r.tool==='platform_tools'||r.tool==='platform_read')&&allowed.includes('platform_tools')?{tool:'platform_tools',args:{platform},instruction:'查看此平台已安装的 MCP 工具及登录状态，继续完成原问题。'}:null;}};
}
