/** Require public evidence for research, while ordinary conversation stays conversational. */
import {readFileSync} from 'node:fs';
const temporalPublic=new RegExp(JSON.parse(readFileSync(new URL('./conversation-patterns.json',import.meta.url),'utf8')).standalone_temporal_public,'iu');
import {simpleChatKind} from './simple-chat.mjs';
import {profileOnlyQuestion} from './personal-profile.mjs';
import {browserFallbackBlocked,publicReadFailure} from './public-read-status.mjs';
const offline=/不(?:要|用)?(?:再)?(?:联网|上网|搜索)|离线|仅(?:用|查|根据)本地|只(?:用|查|根据)(?:本地|知识库)|\b(?:offline|no\s+(?:internet|network|search)|don['’]t\s+(?:search|browse))\b/iu;
const localOnly=/^(?:你叫什么|你是谁)|(?:这份|这个|附件|文件|图片|视频|音频).*(?:总结|翻译|转写)|(?:我的|我家|我公司).*(?:密码|密钥|账号|订单|病历)/u;
const sensitive=/(?:bearer\s+\S+|(?:api[_-]?key|token|password|secret|authorization|密码|密钥)\s*[:=：]\s*\S+)|\b(?:sk-[A-Za-z0-9_-]{12,}|[\w.+-]+@[\w.-]+\.[a-z]{2,})\b/iu;
const validUrl=value=>{try{const u=new URL(value);return /^https?:$/.test(u.protocol)&&!u.username&&!u.password?u:null;}catch{return null;}};
const sourceHost=value=>{
 const parts=validUrl(value)?.hostname.toLowerCase().split('.') || [];
 // Treat mobile/www/subdomain pages of the same site as one source.
 return parts.slice(-(/^(?:com|org|net|co|ac|gov)\.[a-z]{2}$/.test(parts.slice(-2).join('.'))?3:2)).join('.');
};
export function hasPublicBody(source) {
 const text=source?.excerpt?.trim();
 if(!text || source.read_method==='search_result_snippet')return false;
 // Some static extractors return only a short footer from a dynamic page.
 return !(text.length<600 && /^(?:免责声明|风险声明|隐私政策|Cookie policy|Privacy policy|Disclaimer|Please enable JavaScript)/iu.test(text));
}
export function hasProductBody(source) {
 if(!hasPublicBody(source))return false;
 const prose=source.excerpt.replace(/\[[^\]]*\]\(https?:\/\/[^\s)]+\)/gu,'');
 return /功能|服务|支持|提供|匹配|沟通|简历|投递|招聘管理|features?|provides?|supports?/iu.test(prose);
}
const profileScore=s=>Number(/产品介绍|关于我们|功能|软件介绍|核心能力|features?|about us/iu.test(s.title || ''))*3
 +Number(/\/(?:about|products?|features|solutions)(?:[./-]|$)/iu.test(s.url || ''))*2;
const primarySourceQuestion=question=>/官方(?:文档|说明|公告|资料|规范)|一手(?:来源|资料|原文)|原始(?:文档|公告|论文|来源)/u.test(question);
const newsTopic=/新闻|热点|热搜|时事|资讯|要闻|新鲜事|(?:今天|今日|最新|最近|近期).{0,16}(?:动态|消息|发生|大事)|\b(?:news|headlines|current events|latest developments)\b/iu;
export function publicResearchScope(question) {
 const onlyTool=question.match(/(?:只|仅)(?:能|可)?(?:用|使用|调用)\s*(web_search|web_read|visual_browser)\b/iu)?.[1]?.toLowerCase();
 const single=/只(?:查|看|读|找|要|用)(?:一(?:个|家|条)|这个|这家)|仅(?:查|看|读|找)(?:一|这)|\bsite:|https?:\/\//iu.test(question);
 const news=newsTopic.test(question);
 const broad=news || /有哪些|有什么(?:信息|内容)|推荐|盘点|综述|行业.*(?:动态|招聘|新闻)|招聘(?:平台|软件).*信息|\b(?:alternatives|overview)\b/iu.test(question)
  || /平台|软件|产品|工具|服务|品牌|网站|\b(?:platforms?|products?|tools?|services?)\b/iu.test(question)&&/对比|比较|区别|适用人群|优缺点|\b(?:compare|comparison)\b/iu.test(question);
 // A definition or one official document need not visit three unrelated
 // websites. Product/platform overviews still require independent sources.
 const verify=/核实|核对|查证|真假|传言|是否属实|交叉|\b(?:verify|fact.check|cross.check)\b/iu.test(question);
 const narrow=primarySourceQuestion(question)||/用法|定义|是什么|怎么用|如何使用|使用说明|定位时机|\b(?:definition|syntax|usage)\b/iu.test(question)||temporalPublic.test(question);
 return {target:!single && !onlyTool?(broad?3:verify||!narrow?2:1):1,onlyTool,news,verify};
}
export function publicSearchQuery(question,now=new Date()) {
 const date=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
 return question.replace(/^(?:请|帮我|请帮我)?(?:联网|上网)(?:搜索|搜一下|查询|查找)\s*/u,'').replace(/[。；;\n]\s*(?:请)?(?:简要|简短|用表格|分点|控制在|不超过|不要超过|只要结论)[\s\S]*$/u,'').replace(/@[\p{L}\p{N}_/-]+\s*/gu,'').replace(/(?:\/Users\/|[A-Z]:\\)\S+/g,'')
  .replace(/今天|当日|今日(?!招聘)/gu,date).replace(/这个月|本月|当月/gu,date.slice(0,7)).replace(/今年|本年/gu,date.slice(0,4)).replace(/^(?:那|请|帮我|请帮我|麻烦)?(?:关于|查找|找|搜索|介绍|了解|比较)?\s*/u,'')
  .replace(/[，,。？?！!／/]/gu,' ').replace(/\s+/g,' ').trim().slice(0,180);
}
export function needsPublicEvidence(question, intent={}) {
 if(intent.rephrase)return false;
 const explicit=/https?:\/\/|web_search|web_read|visual_browser|搜索|查找|查阅|查证|核实|核对|查一下|搜一下|找一找|再找|再查|再搜|官方(?:文档|资料|公告|说明)|一手(?:来源|资料)|原始(?:论文|出处)|\b(?:search|look\s*up|verify|fact.check|official\s+docs?|sources?)\b/iu;
 if(explicit.test(question) || temporalPublic.test(question))return true;
 // Ordinary follow-ups explain existing material; only a fresh public topic
 // or a comparison that still needs evidence inherits research requirements.
 if(intent.followup && !/区别|比较|对比|有哪些|还有(?:什么|哪些)|\b(?:compare|differences?|alternatives?)\b/iu.test(question))return false;
 const topic=intent.question || question;
 const liveTopic=/新闻|热点|热搜|天气|股价|汇率|赛程|比分|行情|政策|法规|票价|营业时间|价格|报价|收费|招聘|岗位|\b(?:news|weather|prices?|pricing|release|latest|current\s+version|job\s+(?:openings|listings))\b/iu;
 const datedPublic=/(?:最新|最近|近期|今天|今日|当前|现在).{0,16}(?:动态|消息|发布|版本|产品|软件|平台|工具|模型|更新|信息)|(?:产品|软件|平台|工具|模型).{0,12}(?:最新|更新|版本)/iu;
 const product=/平台|软件|产品|工具|服务|品牌|网站|\b(?:platforms?|products?|tools?|services?)\b/iu.test(topic)
   && /找|介绍|了解|信息|功能|比较|对比|区别|适用|怎么选|推荐|\b(?:compare|comparison|overview|recommend|features?|alternatives?)\b/iu.test(topic);
 const publicQuestion=/多少|怎么样|是什么|有哪些|有什么|哪(?:里|家|个)|何时|吗|[?？]|帮我|请|推荐|介绍|了解|查询|\b(?:what|which|where|when|how|find|recommend|show|tell)\b/iu.test(topic)
   || /^(?:(?:今天|今日|最新|最近|当前)\s*)?(?:新闻|天气|热点|汇率|股价|赛程|比分)|(?:当前|最新).{0,12}(?:价格|报价|收费|版本)$|^(?:latest|current)\s+(?:news|prices?|weather|version)\b/iu.test(topic);
 return (liveTopic.test(topic) || datedPublic.test(topic)) && publicQuestion || product
  || newsTopic.test(topic)&&(/什么|啥|哪些|咋样|给我|说说|说一说|看看|来点|来些|聊聊|盘点|综述|[?？]|\b(?:what|show|tell)\b/iu.test(topic)
   || /^(?:(?:今天|今日|最新|最近|近期)\s*)?(?:新闻|要闻|资讯|热点|热搜)[。！!\s]*$/u.test(topic));
}
export function defaultOnlineLookup(question,policy={},local={},intent={}) {
 if(!policy.default_online || !policy.network_allowed || policy.services?.search?.enabled===false || typeof question!=='string'
    || !question.trim() || offline.test(question) || simpleChatKind(question) || profileOnlyQuestion(question) || policy.has_attachments || localOnly.test(question) || sensitive.test(question))return null;
 // Only the current public question supplies search terms, never private context.
 if(!needsPublicEvidence(question,intent))return null;
 if(temporalPublic.test(question))intent={...intent,followup:false,question};
 let query=publicSearchQuery(question);
 // A named Chinese public-statistics topic has an authoritative public source.
 // Keep pronoun resolution with the model, and never infer a country from private history.
 if(temporalPublic.test(question) && !/https?:\/\/|\bsite:/iu.test(question))
  query += /中国|全国|国内/u.test(question) ? ' site:stats.gov.cn' : ' 官方统计';
 if(query.length<3)return null;
 const topic=intent.question || question;
 const scope=publicResearchScope(question),topicScope=publicResearchScope(topic),onlyTool=scope.onlyTool;
 const overview=/平台|软件|产品/u.test(topic)&&/找|介绍|了解|信息|功能|比较|对比|区别|适用|怎么选/u.test(topic);
 const primarySource=primarySourceQuestion(question);
 const target=!primarySource && !onlyTool && !/只(?:查|看|读|找|要|用)|仅(?:查|看|读|找)|\bsite:|https?:\/\//iu.test(question)
  ?Math.max(scope.target,overview?3:topicScope.target):scope.target;
 const profile=overview;
 const usable=profile?hasProductBody:hasPublicBody;
 const knownHosts=new Set((local.reads||[]).flatMap(r=>(r.sources||[]).map(s=>sourceHost(s.url)).filter(Boolean)));
 const instruction='本轮问题需要公开资料查证，继续联网获取相关原文，无需用户重复说联网。把本地内容作为待验证资料；比较网络原文与相关本地结论，核对一手出处、发布日期、产品版本、适用地区及条件。网页更新更晚或检索排名更高不等于更正确。冲突时继续搜索和读取原始规范、发布记录或独立来源；区分本地过时、网页过时、适用范围不同和仍无法证实。私有附件、账号、密钥及个人内容不进入搜索词；只搜索相关公开概念。'
  +(target>1?`本轮需要多个来源，至少尝试读取 ${target} 个不同网站的相关正文。同站不同链接、转载同一稿件不算独立印证。先读取候选资料，再调用 research_review 逐项核对问题覆盖、原始出处、日期与冲突；有缺口继续补查。平台比较要说明各平台的功能、差异和适用人群，适用建议标明是基于功能的判断。不得只给网址或读到首个搜索结果就结束。`:'');
 const reviewInstruction='对照用户问题调用 research_review，列出主要结论、已读正文的逐字引用、来源是否独立、日期是否匹配、存在的分歧和待补查问题。不能把搜索摘要、网页抓取时间或重复转载当成多方核实。';
 return {key:'default-online-v3:'+target+':'+query,instruction,onlyTool,coverageTarget:target,reviewRequired:target>1&&!onlyTool,
  requireIndependentSupport:scope.news||scope.verify||topicScope.news||topicScope.verify,
  finalAnswerInstruction:(temporalPublic.test(question)?'本轮查询有明确统计时间。检索到的旧月份不能当作本月数据；先判断日期与口径是否回答了问题，必要时继续检索官方对应期次。资料中只有比率时不能虚构人数。没有取得对应月份的可靠人数就简短说明本轮尚未查到，不据此断言官方尚未发布或不存在该数据，不重复无关年份的数字。用户要求简短时一句说明缺口并附最相关来源即可。\n':'')+'按当前问题直接回答，以实际读取的本地材料和联网原文为依据，附关键来源。必须有回答正文，来源链接不能代替解释；平台比较应按功能、区别和适用人群整理，只比较实际来源能支持的平台与功能，不能凭常识补入未查到的品牌或承诺反馈速度。历史答复中的产品事实不作为证据，上轮列过但本轮没有依据的平台不要沿用。适用人群作为基于功能的建议单独说明；未取得的细节明确说明。来源不足时说明实际范围，不能声称完成多方核实。发现差异时解释原始出处、版本与适用范围，无法证实时保留分歧。查询今天或最新动态时，必须核对账号身份、原帖的绝对发布时间及用户时区；搜索摘要或旧文章里的“今天”不证明今天发布，抓取时间也不是发布时间，同名网站也不证明今日动态。无法核对原帖与日期就明确无法确认。没有正式入库回执不要声称已经更新了知识库。',
  next({receipts,observations=[],allowed}) {
   const searched=receipts.filter(r=>r.tool==='web_search');
   if(!searched.length)return allowed.includes('web_search')&&(!onlyTool || onlyTool==='web_search')?{tool:'web_search',args:{query},allowSearchQueryRewrite:true,requireModelQuery:Boolean(intent.followup),
    hostQueryReady:!primarySource && !intent.followup && !/(?:它|他们|她们|这些|这几|上述|前面|刚才|这个|那个|继续|再找|再查|再搜|\b(?:it|they|them|those|these|above)\b)/iu.test(query),
    instruction:'先结合当前话题、用户最近的补充和纠正理解本轮问题，再提炼公开主题搜索词调用 web_search。短追问的代词需要还原成所指的主题，不直接搜索“它们”“再找找”。软件或平台概览默认了解用途、主要功能、差异和适用场景；没有求职意图时不要改查职位。不得把本地正文、私有信息或整段聊天放进查询词。'}:null;
   if(onlyTool==='web_search')return null;
   const reviews=observations.filter(o=>o.tool==='research_review'&&o.result?.status==='completed');
   const lastReview=reviews.at(-1)?.result;
   const reviewIndex=observations.findLastIndex(o=>o.tool==='research_review');
   const afterReview=receipts.slice(reviewIndex+1);
   const review=()=>allowed.includes('research_review')&&target>1?{tool:'research_review',args:{},instruction:reviewInstruction}:null;
   const readHosts=new Set();
   for(let i=0;i<receipts.length;i++){
    const r=receipts[i],result=observations[i]?.result;
    if(['web_read','visual_browser'].includes(r.tool)&&['completed','partial'].includes(result?.status)&&result.sources?.some(usable)){
     // A successful narrow lookup may omit its URL in a test/provider receipt.
     readHosts.add(sourceHost(result.sources.find(usable)?.url || r.args?.url) || 'unknown');
    }
   }
   if(readHosts.size>=target && !lastReview)return review();
   if(lastReview?.coverage_complete || reviews.length>=2)return null;
   if(lastReview && !afterReview.some(r=>r.tool==='web_search')&&allowed.includes('web_search')){
    const proposed=lastReview.follow_up_queries.find(q=>!searched.some(r=>r.args.query===q));
    return {tool:'web_search',args:{query:proposed || ((searched[0]?.args?.query || query)+' 原始来源 发布日期 核实').slice(0,180)},allowSearchQueryRewrite:true,
     instruction:'根据证据核对的缺口补查公开原始来源；只保留公开主题，不包含聊天私有信息。'};
   }
   const seen=new Set();
   const candidates=observations.slice(lastReview?reviewIndex+1:0).filter(o=>o.tool==='web_search').flatMap(o=>o.result?.sources||[])
    .filter(s=>validUrl(s.url)&&!seen.has(s.url)&&seen.add(s.url));
   const attemptedHosts=new Set(receipts.map(r=>sourceHost(r.args?.url)).filter(Boolean));
   // A dynamic page gets one rendered attempt before fresh static candidates
   // consume a narrow lookup's action budget. Broad comparisons still diversify.
   const pendingDynamic=new Set(target===1 && allowed.includes('visual_browser') && (!onlyTool||onlyTool==='visual_browser') && policy.services?.browser?.configured!==false
    ? receipts.filter((r,i)=>r.tool==='web_read' && publicReadFailure(observations[i]?.result)==='no_readable_body'
      && !receipts.some(other=>other.tool==='visual_browser'&&other.args?.url===r.args?.url)).map(r=>r.args?.url):[]);
   candidates.sort((a,b)=>Number(pendingDynamic.has(b.url))-Number(pendingDynamic.has(a.url))||(profile?profileScore(b)-profileScore(a):0)||Number(attemptedHosts.has(sourceHost(a.url)))-Number(attemptedHosts.has(sourceHost(b.url)))||Number(knownHosts.has(sourceHost(b.url)))-Number(knownHosts.has(sourceHost(a.url))));
   const refine=()=>({tool:'web_search',args:{query:((searched[0]?.args?.query || query)+' '+(profile?'官方 功能 介绍':scope.news?'重要新闻 原始报道 发布日期':'来源 详情')).slice(0,180)},instruction:'已有结果不足以覆盖本轮问题，补查原始报道、官方发布或独立资料，并核对日期。'});
   if(lastReview&&afterReview.filter(r=>['web_read','visual_browser'].includes(r.tool)).length>=3)return review();
   if(profile && !readHosts.size && receipts.filter(r=>r.tool==='web_read').length>=2 && searched.length<2 && allowed.includes('web_search'))return refine();
   for(const s of candidates.slice(0,target>1?12:2)){
    if(!lastReview&&readHosts.has(sourceHost(s.url)))continue;
    if(lastReview&&receipts.some((r,i)=>r.args?.url===s.url&&['web_read','visual_browser'].includes(r.tool)&&observations[i]?.result?.sources?.some(usable)))continue;
    const attempted=tool=>receipts.some(r=>r.tool===tool&&r.args?.url===s.url);
    const denied=receipts.some((r,i)=>r.args?.url===s.url && browserFallbackBlocked(observations[i]?.result));
    if(denied)continue; // A browser cannot override an explicit access restriction.
    if(!attempted('web_read')&&allowed.includes('web_read')&&(!onlyTool||onlyTool==='web_read'))return {tool:'web_read',args:{url:s.url},instruction:'读取实际搜索结果原文 '+s.url+'，核对与当前问题有关的内容；同名网站、导航分类不证明今日招聘情况。'};
    const navigationOnly=profile && receipts.some((r,i)=>r.tool==='web_read'&&r.args?.url===s.url&&observations[i]?.result?.sources?.some(hasPublicBody));
    if(!navigationOnly&&!attempted('visual_browser')&&allowed.includes('visual_browser')&&(!onlyTool||onlyTool==='visual_browser')&&policy.services?.browser?.configured!==false)return {tool:'visual_browser',args:{url:s.url,actions:'read',viewport:'desktop'},instruction:'静态读取未取得正文，继续只读浏览实际来源 '+s.url+'；取得原文后核对功能、版本和适用范围。'};
   }
   // Bounded second search when results were sparse/blocked or all one site.
   if(!lastReview&&target>1 && searched.length<2 && allowed.includes('web_search'))return refine();
   if(lastReview&&allowed.includes('web_search')&&afterReview.filter(r=>r.tool==='web_search').length<3){
    const pending=lastReview.follow_up_queries.find(q=>!searched.some(r=>r.args.query===q));
    if(pending)return {tool:'web_search',args:{query:pending},allowSearchQueryRewrite:true,instruction:'继续补查证据核对中尚未解决的公开问题，优先原始来源。'};
   }
   return review();
  },
  batch(state,first){
   if(first.tool!=='web_read'||target===1)return [first];
   const shadow={...state,receipts:[...state.receipts],observations:[...state.observations]},batch=[],hosts=new Set();
   let next=first;
   for(let tries=0;tries<12&&next?.tool==='web_read'&&batch.length<3;tries++){
    const host=sourceHost(next.args.url);
    shadow.receipts.push({tool:'web_read',args:next.args});
    // Reserve a domain without pretending the real execution has succeeded.
    shadow.observations.push({tool:'web_read',result:{status:'completed',sources:[{url:next.args.url,excerpt:'预留并发读取位置，提供功能说明',read_method:'host_reservation'}]}});
    if(!hosts.has(host)){batch.push(next);hosts.add(host);}
    next=this.next(shadow);
   }
   return batch;
  }};
}
