"""Repeatable synthetic evaluation; never loads official user conversations."""
import json
import statistics
import time
from federation.context_extract import literal_excerpt, relevance_score
from federation.context_memory import estimate


def evaluate():
    topics=['退款预算','数据库备份','上线日期','附件权限','接口超时','视频时长','订单折扣','学习进度','服务器路径','用户偏好','日志保留','模型并发']
    documents={topic:'闲聊与无关背景。'*180+f'{topic}必须采用方案 K{i}，不要覆盖已有记录。'+'其他闲聊。'*180 for i,topic in enumerate(topics)}
    details=[]
    for i,topic in enumerate(topics):
        question=f'之前的{topic}要求是什么？';started=time.perf_counter()
        ranks=sorted(documents,key=lambda key:-relevance_score(documents[key],question))
        # Positive relevance threshold avoids filling K with unrelated material.
        selected=[key for key in ranks if relevance_score(documents[key],question)>=2][:3]
        excerpt=literal_excerpt(documents[topic],320,question)
        before=documents[topic][:208]+'…'+documents[topic][-77:]
        details.append({'topic':topic,'k':3,'recall_at_k':int(topic in selected),
            'precision_at_k':int(topic in selected)/3, 'returned_precision':int(topic in selected)/max(1,len(selected)),
            'baseline_constraint_retained':f'方案 K{i}' in before,
            'constraint_retained':f'方案 K{i}' in excerpt and '不要覆盖已有记录' in excerpt,
            'source_estimated_tokens':estimate(documents[topic]),'excerpt_estimated_tokens':estimate(excerpt),
            'selection_ms':round((time.perf_counter()-started)*1000,3)})
    return {'evidence_class':'synthetic-offline-evaluation','cases':len(details),'k':3,
            'recall_at_k':statistics.mean(d['recall_at_k'] for d in details),
            'precision_at_k':statistics.mean(d['precision_at_k'] for d in details),
            'returned_precision':statistics.mean(d['returned_precision'] for d in details),
            'constraint_retention_before':statistics.mean(d['baseline_constraint_retained'] for d in details),
            'constraint_retention_after':statistics.mean(d['constraint_retained'] for d in details),
            'selection_ms_max':max(d['selection_ms'] for d in details),'details':details,
            'limits':'Synthetic literal/topic recall only; not production model accuracy or provider latency.'}


if __name__=='__main__':print(json.dumps(evaluate(),ensure_ascii=False,indent=2))
