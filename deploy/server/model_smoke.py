"""Real, bounded inference checks for the migrated local Ollama instance."""
import argparse
import json
from pathlib import Path
import time
import urllib.request


def chat(messages, tools=None):
    value = {'model': 'qwen3.5:9b', 'messages': messages, 'stream': False, 'think': False,
             'options': {'num_ctx': 32768, 'num_predict': 96, 'temperature': 0, 'num_thread': 8}}
    if tools:
        value['tools'] = tools
    request = urllib.request.Request('http://127.0.0.1:11436/api/chat', data=json.dumps(value).encode(),
                                     headers={'Content-Type': 'application/json'})
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=300) as response:
        result = json.load(response)
    return result, round(time.monotonic() - started, 3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result, seconds = chat([{'role': 'user', 'content': '只原样回复：服务器模型正常'}])
    receipt = {'text': result['message']['content'], 'seconds': seconds,
               'eval_count': result.get('eval_count'), 'eval_duration_ns': result.get('eval_duration'),
               'load_duration_ns': result.get('load_duration'), 'num_ctx': 32768}
    receipt['text_verified'] = '服务器模型正常' in receipt['text']
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    print(json.dumps(receipt, ensure_ascii=False), flush=True)
    assert receipt['text_verified']
    messages = [{'role': 'user', 'content': '调用 server_health_echo，marker 必须是 migration_ok。必须调用工具，再原样输出工具返回的文本。'}]
    tools = [{'type': 'function', 'function': {'name': 'server_health_echo', 'description': 'Echo the migration test marker.',
              'parameters': {'type': 'object', 'properties': {'marker': {'type': 'string'}}, 'required': ['marker']}}}]
    call, call_seconds = chat(messages, tools)
    calls = call['message'].get('tool_calls', [])
    assert len(calls) == 1, call['message']
    function = calls[0]['function']
    assert function['name'] == 'server_health_echo' and function['arguments'] == {'marker': 'migration_ok'}, function
    messages.extend([call['message'], {'role': 'tool', 'tool_name': 'server_health_echo', 'content': 'SERVER_TOOL_OK'}])
    final, final_seconds = chat(messages)
    receipt.update(tool_call_verified=True, tool_seconds=call_seconds, tool_result_seconds=final_seconds,
                   tool_result_answer=final['message']['content'],
                   tool_result_verified='SERVER_TOOL_OK' in final['message']['content'])
    with urllib.request.urlopen('http://127.0.0.1:11436/api/ps') as response:
        receipt['loaded_models'] = json.load(response)['models']
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    print(json.dumps(receipt, ensure_ascii=False), flush=True)
    assert receipt['tool_result_verified']


if __name__ == '__main__':
    main()
