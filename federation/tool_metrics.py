"""Bounded read-only aggregation of persisted tool receipts, without arguments."""
import json


def summary(base,limit=300):
    totals={key:0 for key in ('attempts','executed','failed','invalid_arguments','repeat_blocked','first_attempts','first_successes','correction_attempts','correction_successes')}
    tools={};measured=0
    paths=sorted((base/'jobs').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:limit]
    for path in paths:
        if path.is_symlink() or path.stat().st_size>8_000_000:continue
        try:metrics=(json.loads(path.read_text()).get('workflow') or {}).get('tool_metrics')
        except (OSError,ValueError):continue
        if not metrics:continue
        measured+=1
        for key in totals:totals[key]+=metrics.get(key,0)
        for name,row in metrics.get('by_tool',{}).items():
            value=tools.setdefault(name,{'attempts':0,'failed':0,'codes':{}})
            value['attempts']+=row['attempts'];value['failed']+=row['failed']
            for code,count in row['codes'].items():value['codes'][code]=value['codes'].get(code,0)+count
    return {**totals,'by_tool':tools,'sampled_jobs':len(paths),'measured_jobs':measured,
            'first_attempt_success_rate':totals['first_successes']/totals['first_attempts'] if totals['first_attempts'] else None,
            'correction_success_rate':totals['correction_successes']/totals['correction_attempts'] if totals['correction_attempts'] else None,
            'scope':'latest 300 jobs; older jobs without metrics are not counted as zero failures'}
