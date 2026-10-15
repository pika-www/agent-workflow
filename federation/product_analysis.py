"""Human analysis requests are read-only, even when they discuss implementation."""
import re
from .conversation_intent import latest_dialogue


def analysis_only(question):
    text = re.sub(r'\s+', '', str(question)).lower()
    if re.search(r'(?:不要|不用|别).{0,8}(?:待确认|确认方案|确认按钮)', text) and re.search(r'分析|研究|拆解', text):
        return True
    if re.search(r'(?:不是|并非)(?:只|仅|先)?(?:分析|研究|讨论)|待确认.{0,12}(?:方案|计划)|(?:方案|计划).{0,8}(?:供|等|待)确认', text):
        return False
    activity = r'分析|研究|调研|拆解|拆一下|讨论|评估'
    if re.search(r'讨论方案|只做方案', text) and not re.search(r'只分析|仅分析|先分析|先不做|不开发|不要开发', text):
        return False
    return bool(re.search(r'(?:只|仅|先|暂时).{0,12}(?:' + activity + r')', text) or
                (re.search(r'(?:不|别|不要|不用|暂停|停止).{0,6}(?:做|开发|执行|实施|开始|落地)', text)
                 and re.search(activity, text)))


def product_analysis_request(question):
    text = str(question)
    if re.search(r'待确认.{0,12}(?:方案|计划)|确认方案并', text):
        return False
    return bool((re.search(r'https?://', text) and re.search(r'拆(?:解|一下|一拆)|分析|研究|调研|反推', text)) or
                (re.search(r'产品|竞品|网站|网页|盈利|获客|商业模式', text) and
                 re.search(r'透彻分析|全面分析|深度分析|分析报告|调研报告|拆解报告|反推', text)))


def analysis_goal(question, room=None):
    """Use the latest human product request; old assistant plans are not evidence."""
    text = str(question).strip()
    explicit = analysis_only(text) or product_analysis_request(text)
    # A new personal topic is not a continuation of an older product report.
    if not explicit and re.search(r'(?:分析|了解|评价|说说)(?:一下)?(?:我|我的|自己|我的性格)|性格|找工作|失业|求职', text):
        return None
    if re.search(r'换个话题|另一个产品|取消项目|结束分析', text):
        return text if explicit else None
    # A concept lesson/local lookup is its own question. A cost-related word
    # must not resurrect an old product report and require its stronger model.
    if not explicit and re.search(r'教(?:教)?我|带我学|两句话|简单讲|解释(?:一下)?|概念|怎么判断|先用知识库补查|只用本库|不联网',text) and not re.search(r'这份报告|上一份报告|刚才.{0,8}分析|上述报告|继续分析',text):
        return None
    followup = bool(len(text) <= 500 and re.search(r'分析|展开|详细|全面|透彻|盈利|获客|收费|文档|下载|报告|交互|实现细节', text)
                    and not re.search(r'开始开发|确认方案|按方案执行|写入知识库|/学习', text))
    if not explicit and not followup:
        return None
    if re.search(r'https?://', text) and explicit:
        return text
    # A vague request to expand or advise belongs to the latest human topic.
    # An old report cache is not a conversation focus. Explicit report returns
    # may still select it, even after intervening ordinary conversation.
    returns_to_report = bool(re.search(r'(?:上一份|之前的|此前的|那份|这份|上述)报告|回到.{0,30}(?:报告|分析)', text))
    latest = latest_dialogue((room or {}).get('messages', []))
    anchor = next((m.get('content', '') for m in latest if m.get('role') == 'user'), '')
    if anchor and not returns_to_report and not (product_analysis_request(anchor) or analysis_only(anchor)):
        return text if explicit else None
    context = (room or {}).get('analysis_context') or {}
    if followup and context.get('goal'):
        return str(context['goal'])[:4800] + '\n\n本轮分析要求：\n' + text
    if explicit or followup:
        humans = [m for m in (room or {}).get('messages', []) if m.get('role') == 'user'][-6:]
        for message in reversed(humans):
            content = str(message.get('content', ''))
            if re.search(r'换个话题|另一个产品|取消项目|结束分析', content):
                break
            if product_analysis_request(content) or (explicit and re.search(r'https?://', content) and re.search(r'产品|方案|开发|拆|分析|研究', content)):
                return content[:4800] + '\n\n本轮分析要求：\n' + text
    return text if explicit else None


ANALYSIS_INSTRUCTIONS = '''
本轮是产品深度分析与报告交付，用户没有授权开发、组群、写库或发布。即使要求实现方案、MVP、接口设计，也只是分析内容，绝不提出待确认执行方案。
用户当前项目是通过主 Agent 和专业 Agent 聊天学习、保存并审核经验的本地知识库，需要来源记录与下载文档。结合项目的建议围绕这些实际任务，不擅自改成 GPU 租赁或模型训练平台。
忽略普通聊天400字的长度建议。根据证据写约2500至6000字的完整分析，优先具体细节，避免为了篇幅重复。不要输出“待确认事项”“确认后执行”或成员分工卡。
报告至少解释这些方面：产品解决的任务与用户；主要功能和完整使用路径；交互中的加载、空数据、错误、权限与移动端细节；可观察技术证据及实现推测；前后端、数据、任务状态、计费和异常处理的参考实现；用户、竞品与市场证据；获客、激活和留存；收费、成本、盈亏假设；结合用户当前知识库项目值得采用的最小范围与验证方法。
每部分明确区分已观察事实、合理推测和建议。事实引用宿主本轮实际提供的URL；没有看到的登录后界面、接口、价格、用户规模和营收不得编造。动态页面读取失败只能标记未验证，不能说产品没有应用或服务已经停运。
市场渠道出现不等于渠道已经有效，套餐价格不等于真实利润。成本测算写明假设、计算过程和需要核实的变量，不承诺盈利。真实技术识别和我们可以采用的实现方案分别说明。
只引用当前用户问题与提供的产品资料，不把历史里无关的赚钱、前端能力或其他项目当成此次分析对象。资料不足仍给出具体分析与验证路径，不能只说无法访问。
按用户的回复语言使用清晰标题和自然段写报告，必要的比较用表格。正文是宿主生成下载文档的内容，不要声称自己调用了文件工具，也不要要求用户确认开发才能下载。宿主会在回答完成后实际保存并提供下载文件。
'''
