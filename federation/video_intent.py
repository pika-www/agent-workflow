"""Bounded video intent routing before any model call or generation POST.

Only the current user message is classified. A selected video mode is a
one-turn preference, not authority to turn questions into generation jobs.
"""
import re


def video_intent(content, selected=False, recent_video=False):
    text = content.strip().lower()
    if not text:
        return 'chat'
    # Quoted examples, instructions about prompts, and negations are conversation.
    if re.search(r'^(?:(?:先|暂时|现在|暂)?(?:不要|别|不用|不想|不需要|不必|不是|不生成)|停止|取消|不是让你生成)|^(?:please\s+)?(?:do not|don\x27t|stop|cancel)\b|(?:这句话|这段话|提示词|prompt).{0,12}(?:什么意思|解释|翻译|优化)|^(?:解释|翻译|介绍|写代码|帮我改)', text):
        return 'chat'
    if re.search(r'(?:生成|制作).{0,20}(?:视频|短片|动画)(?:需要|要多久|的(?:原理|方法|步骤|提示词)|提示词)|^(?:可以|能不能|能|你能).{0,6}(?:生成|制作)视频[吗嘛？?。\s]*$|^(?:视频生成|生成视频)(?:失败)?(?:是什么|怎么办|如何|怎么)', text):
        return 'chat'
    if re.search(r'(?:视频|短片|动画)(?:生成)?(?:应用|软件|系统|平台|网站|接口|功能|工具)|(?:解释|翻译|优化|改写|检查).{0,20}(?:提示词|prompt)|^(?:继续|所有的|全部)[。！!\s]*$', text):
        return 'chat'
    create = bool(re.search(r'^(?:(?:请|帮我|给我|麻烦|现在|再|重新|继续|能不能|可以|能|一下)\s*)*(?:生成|制作|做|重做)(?!的).{0,40}(?:视频|短片|动画)|^(?:please\s+)?(?:generate|create|make)\b.{0,70}\b(?:video|clip|animation)\b', text))
    topic = bool(re.search(r'视频|生成任务|渲染|video|render|\bjob\b|[a-f0-9]{8}-[a-f0-9-]{27,}', text))
    progress = bool(re.search(r'进度|状态|生成好|完成了|做好了|成功了|失败了|还没好|还没完|到哪[一了]|还(?:要|需).{0,6}(?:多久|多长)|为什么.{0,8}(?:慢|没|久)|等.{0,8}(?:久|分钟)|(?:好|完|完成)(?:了)?[吗没嘛]|\b(?:status|progress|ready|done|finished|completed|failed)\b|how much longer', text))
    # Explicit new creation wins over words such as "进度条" inside its scene.
    if not create and progress and (topic or recent_video):
        return 'status'
    if create:
        return 'generate'
    question = bool(re.search(r'[?？]|(?:吗|嘛|呢)[。！!\s]*$|什么|为什么|怎么|如何|能否|是否|多少|哪里|哪[个里些]|多久|有没有|^(?:你好|您好|谢谢|好的|收到|明白|在吗|帮我|查一下|查查|检查|搜索|查询|找一下|把.{0,15}(?:视频|文件)|服务器|所有的|全部|发给我|发我|播放|打开|下载|列出)|^(?:hi|hello|thanks|thank you|ok|what|why|how|when|where|who|is|are|can|could|would|check|find|search)\b', text))
    return 'generate' if selected and not question else 'chat'


def recent_video_context(room):
    # Topic changes end implicit follow-ups; explicit "视频进度" remains queryable.
    for message in reversed(room.get('messages', [])):
        if message.get('role') == 'assistant' and message.get('response_origin') in {'host_video_submission', 'host_video_status'}:
            return True
        if message.get('role') == 'user':
            return bool(message.get('video_submission_id') or message.get('video_status_query'))
    return False
