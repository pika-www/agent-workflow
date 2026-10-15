"""Real local embeddings against synthetic Chinese cases, isolated from live data."""
import argparse
import json
import time
from pathlib import Path
from federation.vector_index import LocalEmbedder,VectorIndex

DOCUMENTS={
 '/refund.md':'消费者在付款后的七天内可以取消订单，款项按原支付渠道退回。已经履约的数字内容不适用此规则。',
 '/backup.md':'每天凌晨将数据库做增量备份，每周保留一份完整快照。恢复前先校验文件哈希，不能用开发环境覆盖生产数据。',
 '/ssh.md':'设备离开办公室局域网后，私有 IP 地址无法直接访问。远程管理需要 VPN 或经过验证的异地 SSH 入口。',
 '/concurrency.md':'无依赖关系的任务可以同时执行，线程池设置最大并发数。有先后关系的节点必须等待上游任务完成。',
 '/memory.md':'对话很长时，对旧消息提取与当前问题相关的原文片段，原始记录永久保留，下一轮允许按需重新读取。',
 '/id.md':'工具引用文件时，只能使用当前会话实际附件清单中的标识符，不能使用其他会话的文件，也不能凭空编造 ID。',
 '/video.md':'视频生成任务提交后返回任务编号。查询生成进度只发送 GET 请求，不能重新提交相同的生成任务。',
 '/food.md':'番茄炒鸡蛋需要先炒鸡蛋，再把番茄煮软，最后混合并调味。',
 '/sport.md':'马拉松比赛需要循序渐进训练，周末进行长距离慢跑，训练后保证休息。',
 '/garden.md':'植物需要适当的水分和阳光，浇水前可以先查看盆土是否干燥。',
}
CASES=[('买完以后不想要了，钱怎么拿回来？','/refund.md'),('历史资料丢了，怎样找回旧版本？','/backup.md'),
 ('人在外面为什么打不开家里电脑？','/ssh.md'),('几个同事各干各的，如何一起推进工作？','/concurrency.md'),
 ('聊了很久以后，早先说的话还能找回来吗？','/memory.md'),('传给工具的附件编号能自己随便填吗？','/id.md'),
 ('想知道影片做到了哪一步，是否要再点一次生成？','/video.md')]


def evaluate(config,database):
    embed=LocalEmbedder(config);index=VectorIndex(database,embed,embed.version)
    started=time.perf_counter();updated=index.update('synthetic-evaluation',DOCUMENTS,max_chunks=32);build=time.perf_counter()-started
    details=[]
    try:
        for question,expected in CASES:
            begin=time.perf_counter();result=index.search('synthetic-evaluation',DOCUMENTS,question,k=3,min_score=config.get('min_score',.35));elapsed=time.perf_counter()-begin
            selected=[r['path'] for r in result['matches']]
            details.append({'question':question,'expected':expected,'matches':result['matches'],'recall_at_3':int(expected in selected),
                            'precision_at_3':int(expected in selected)/3,'top1_correct':bool(selected and selected[0]==expected),'seconds':round(elapsed,3)})
        return {'evidence_class':'real-local-embedding-with-synthetic-documents','model':config['model'],'model_digest':config['digest'],
                'documents':len(DOCUMENTS),'queries':len(CASES),'updated_chunks':updated,'build_seconds':round(build,3),
                'recall_at_3':sum(d['recall_at_3'] for d in details)/len(details),'top1_accuracy':sum(d['top1_correct'] for d in details)/len(details),
                'precision_at_3':sum(d['precision_at_3'] for d in details)/len(details),'returned_precision':sum(d['recall_at_3'] for d in details)/max(1,sum(len(d['matches']) for d in details)),'details':details}
    finally:index.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--database',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=evaluate(json.loads(a.config.read_text()),a.database);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='details'}))
