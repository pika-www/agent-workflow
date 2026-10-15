"""Evidence-triggered code upgrades with protected tests, sandbox and rollback."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import uuid

from .autonomy import read_json, digest, parse_time, valid_text
from .autonomy_strategy import sandbox_node
from .core import _now, _write_json

TARGETS = ('federation/retrieval.mjs', 'federation/learning-strategy.mjs', 'federation/tool-strategy.mjs')


async def capability_check(store, filename, testing=False):
    args = [store.node, str(store.project_root / 'federation/autonomy-code-check.mjs'), str(filename)]
    if testing:
        args.append('test')
    process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(process.communicate(), 15)
    except BaseException:
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        lines = err.decode(errors='replace').splitlines()
        reason = next((line for line in lines if line.startswith('Error:')), '\n'.join(lines[:4]))
        raise ValueError('代码能力检查未通过：' + reason[:700])


async def evaluate_candidate(store, directory, proposal):
    edits = proposal.get('edits')
    if not isinstance(edits, list) or not 1 <= len(edits) <= 4:
        raise ValueError('升级需要 1 至 4 项精确修改')
    if not valid_text(proposal.get('regression_test'), 10000) or not valid_text(proposal.get('reason'), 1200):
        raise ValueError('升级需要具体原因和可重复的回归用例')
    before = {}
    for name in TARGETS:
        source = store.project_root / name
        if source.is_symlink():
            raise ValueError('自动升级拒绝符号链接')
        before[name] = source.read_text()
    after = dict(before)
    for edit in edits:
        name = edit.get('path')
        old, new = edit.get('old'), edit.get('new')
        if name not in TARGETS or not valid_text(old, 16000) or not isinstance(new, str) or len(new) > 16000 or old == new:
            raise ValueError('自动升级修改范围或内容无效')
        if after[name].count(old) != 1:
            raise ValueError('代码基线已变化或修改位置不唯一')
        after[name] = after[name].replace(old, new, 1)
    baseline, trial = directory / 'baseline', directory / 'trial'
    for root, files in [(baseline, before), (trial, after)]:
        for name, content in files.items():
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content)
        tests = root / 'tests'
        tests.mkdir(exist_ok=True)
        shutil.copyfile(store.project_root / 'tests/autonomy-policy-baseline.mjs', tests / 'holdout.mjs')
        (tests / 'regression.mjs').write_text(proposal['regression_test'])
    for name in TARGETS:
        await capability_check(store, trial / name)
    await capability_check(store, trial / 'tests/regression.mjs', testing=True)
    results = {}
    for label, root, script in [('baseline_holdout', baseline, 'holdout.mjs'),
                                ('baseline_regression', baseline, 'regression.mjs'),
                                ('trial_holdout', trial, 'holdout.mjs'),
                                ('trial_regression', trial, 'regression.mjs')]:
        code, out, err = await sandbox_node(store.node, root, root / 'tests' / script)
        results[label] = {'exit_code': code, 'stdout': out.decode(errors='replace')[:4000],
                          'stderr': err.decode(errors='replace')[-4000:]}
    _write_json(directory / 'tests.json', results)
    if results['baseline_holdout']['exit_code'] != 0:
        raise ValueError('原版本固定测试未通过，保留当前代码并报告基线问题')
    if results['baseline_regression']['exit_code'] == 0:
        raise ValueError('新用例在原版本已通过，尚无可验证的改进，不替换代码')
    if any(results[k]['exit_code'] != 0 for k in ('trial_holdout', 'trial_regression')):
        raise ValueError('候选代码没有通过固定测试和新增回归用例')
    return before, after, results


def recover_upgrades(store, root):
    for path in (root / 'runs').glob('*/upgrade-transaction.json'):
        tx = read_json(path, {})
        if tx.get('status') != 'prepared':
            continue
        conflicts = []
        for name, previous in tx['before'].items():
            if name not in TARGETS:
                raise ValueError('升级恢复清单含越界路径')
            target = store.project_root / name
            if target.is_symlink():
                conflicts.append(name)
                continue
            current = target.read_text()
            if current == tx['after'][name]:
                from .autonomy import Autonomy
                Autonomy.atomic_bytes(target, previous.encode())
            elif current != previous:
                conflicts.append(name)
        tx.update(status='conflict' if conflicts else 'rolled_back', conflicts=conflicts)
        _write_json(path, tx)


async def maybe_upgrade(manager, force=False):
    state_path = manager.root / 'upgrade.json'
    state = read_json(state_path, {})
    if not force and parse_time(state.get('next_at')) > datetime.now(timezone.utc):
        return None
    if not manager.budget_available(2):
        return None
    run = {'id': uuid.uuid4().hex, 'kind': 'code_upgrade', 'agent_id': 'central',
           'agent_name': '主 Agent · 代码改进', 'status': 'upgrading', 'started_at': _now(),
           'model_calls': [], 'changed_pages': []}
    manager.active = run['id']
    manager.save(run)
    directory = manager.root / 'runs' / run['id']
    try:
        files = {name: (manager.store.project_root / name).read_text() for name in TARGETS}
        receipts = [{k: r.get(k) for k in ('kind', 'agent_name', 'status', 'plan', 'error', 'verification')}
                    for r in manager.runs(35) if r['id'] != run['id']]
        failed = next((r for r in manager.runs(35)
                       if r['kind'] == 'code_upgrade' and r['status'] == 'failed'), None)
        previous_failure = None
        if failed:
            previous_dir = manager.root / 'runs' / failed['id']
            tests = read_json(previous_dir / 'tests.json', {})
            previous_failure = {'error': failed.get('error'),
                'proposal': read_json(previous_dir / 'proposal.json', {}),
                'tests': {label: {'exit_code': result['exit_code'],
                                 'stderr': result.get('stderr', '')[-2500:]}
                          for label, result in tests.items()}}
        proposal = await manager.call(run, '检索、工具选用与行业学习策略的代码改进', {
            'files': files, 'recent_receipts': receipts,
            'previous_failed_candidate': previous_failure,
            'task': '检查当前纯函数实现与实际运行记录，寻找一个可复现的具体缺陷。只修改提供的三个模块中的纯函数。'
                    '无明确问题返回 {"no_change":true,"reason":"原因"}。有明确问题返回 reason、edits（path、old、new 精确单次替换）和 regression_test（完整 Node ESM 测试）。'
                    '测试只允许导入 node:assert/strict、../federation/retrieval.mjs、../federation/learning-strategy.mjs、../federation/tool-strategy.mjs；用断言证明原代码失败而新代码通过。'
                    '不得读取文件、环境、网络，不能改固定测试、权限、预算或隔离规则。策略必须保留原函数签名；不可新增导入、动态属性访问、宿主访问或全局副作用。'
                    '如有上次失败候选，先分析实际测试输出：判断是候选逻辑错误还是新测试预期错误，修正后仍必须复现原行为缺陷，不能删除有效断言来凑通过。'
                    '重点检查中文行业主题、@成员检索、多语言匹配、来源去重与排序。只修复真实行为，不为制造升级随意改变行为。'})
        _write_json(directory / 'proposal.json', proposal)
        if proposal.get('no_change') is True:
            manager.save(run, status='unchanged', note=proposal.get('reason', '没有找到必要修改'))
            return run
        before, after, tests = await evaluate_candidate(manager.store, directory, proposal)
        review = await manager.call(run, '代码修改独立复核', {
            'before': before, 'after': after, 'proposal': proposal, 'tests': tests,
            'task': '检查修改是否解决所述缺陷、测试是否验证实际行为、是否保持其他行为及权限边界。'
                    '拒绝无关改动、通过删除逻辑伪造通过、输入特判只迎合用例。返回 approved（布尔）、issues（字符串数组）、reason。'})
        _write_json(directory / 'review.json', review)
        if review.get('approved') is not True or review.get('issues') != []:
            raise ValueError('代码修改独立复核未通过')
        # Wait for foreground work; do not replace modules during an active turn.
        while not manager.idle():
            await asyncio.sleep(2)
        async with manager.write_lock:
            if not manager.settings()['enabled'] or not manager.settings()['code_enabled']:
                raise ValueError('代码升级已暂停，候选保留')
            for name in TARGETS:
                p = manager.store.project_root / name
                if p.is_symlink() or p.read_text() != before[name]:
                    raise ValueError('有人修改了代码基线，自动升级已保留候选并停止覆盖')
            transaction = directory / 'upgrade-transaction.json'
            tx = {'status': 'prepared', 'before': before, 'after': after}
            _write_json(transaction, tx)
            try:
                for name in TARGETS:
                    if before[name] != after[name]:
                        manager.atomic_bytes(manager.store.project_root / name, after[name].encode())
                for name in TARGETS:
                    if (manager.store.project_root / name).read_text() != after[name]:
                        raise ValueError('代码升级回读失败')
                tx['status'] = 'committed'
                _write_json(transaction, tx)
            except BaseException:
                recover_upgrades(manager.store, manager.root)
                raise
        manager.save(run, status='completed', changed_files=[name for name in TARGETS if before[name] != after[name]],
                     reason=proposal['reason'], verification={'sandbox': 'macOS Seatbelt',
                     'baseline_failure_reproduced': True, 'fixed_checks_passed': True,
                     'candidate_regression_passed': True, 'automatic_review': True, 'readback': True})
        return run
    except asyncio.CancelledError:
        manager.save(run, status='interrupted', error='代码改进中断，未完成候选保留')
        raise
    except Exception as exc:
        manager.save(run, status='failed', error=str(exc)[:1000])
        return run
    finally:
        manager.save(run, finished_at=_now())
        _write_json(state_path, {'last_run': run['id'], 'status': run['status'],
                                 'next_at': (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()})
        manager.active = None
