"""Validate the shared native tool contract again before host execution."""
import json
import math
import re
from pathlib import Path

CONTRACTS = json.loads(Path(__file__).with_name('tool-contracts.json').read_text())
MAX_REQUEST_BYTES = CONTRACTS['request_bytes']


class ToolContractError(ValueError):
    def __init__(self, field, code, expected):
        super().__init__('参数校验失败：' + field + ' ' + expected)
        self.detail = {'field': field, 'code': code, 'expected': expected, 'retryable': True}


def validate_dynamic_schema(schema, value, field='arguments'):
    """Validate real MCP input schemas; never resolve a schema over the network."""
    from jsonschema import Draft202012Validator
    from referencing import Registry
    from referencing.exceptions import NoSuchResource
    def no_network(uri):
        raise NoSuchResource(ref=uri)
    schema = dict(schema)
    if schema.get('type') == 'object':
        schema.setdefault('additionalProperties', False)
    validator = Draft202012Validator(schema, registry=Registry(retrieve=no_network))
    Draft202012Validator.check_schema(schema)
    error = next(validator.iter_errors(value),None)
    if error:
        at=field+''.join('.'+str(part) for part in error.absolute_path)
        # Schema constraints, not the rejected value, go into the correction.
        expected=json.dumps(error.validator_value,ensure_ascii=False)[:400]
        raise ToolContractError(at,str(error.validator),'约束 '+str(error.validator)+' = '+expected)


def validate_contract(name, args):
    def reject(field, code, expected):
        raise ToolContractError(field, code, expected)
    contract = CONTRACTS['tools'].get(name)
    if not contract:
        reject('$tool', 'unknown_tool', '使用当前允许的工具')
    if not isinstance(args, dict):
        reject('$', 'type', 'JSON 对象')
    schema = contract['schema']
    for field in schema['required']:
        if field not in args:
            reject(field, 'required', '必填字段')
    for field in args:
        if field not in schema['properties']:
            reject(field, 'additional_property', '仅允许字段：' + ', '.join(schema['required']))
    for field, rule in schema['properties'].items():
        value = args[field]
        if not isinstance(value, str):
            reject(field, 'type', '字符串；数字使用十进制字符串')
        if '\0' in value or not rule['minLength'] <= len(value) <= rule['maxLength'] or rule['minLength'] and not value.strip():
            reject(field, 'length', f"长度 {rule['minLength']} 至 {rule['maxLength']}，不含空字符")
        if 'enum' in rule and value not in rule['enum']:
            reject(field, 'enum', '允许值：' + ', '.join(rule['enum']))
        if 'pattern' in rule and not re.fullmatch(rule['pattern'], value):
            reject(field, 'format', rule.get('description', rule['pattern']))
        bounds = contract['numeric'].get(field)
        if bounds and (not math.isfinite(float(value)) or not bounds['minimum'] <= float(value) <= bounds['maximum']):
            reject(field, 'range', f"范围 {bounds['minimum']} 至 {bounds['maximum']}")
    for field in contract['json_fields']:
        try:
            value = json.loads(args[field])
        except (ValueError, TypeError):
            reject(field, 'invalid_json', '完整 JSON 对象字符串')
        if not isinstance(value, dict):
            reject(field, 'type', 'JSON 对象字符串')
        nested = contract.get('variants', {}).get(args.get('action'))
        if nested:
            for key in nested['required']:
                if key not in value:
                    reject(field+'.'+key, 'required', '必填字段')
            for key, item in value.items():
                rule = nested['properties'].get(key)
                at = field+'.'+key
                if rule is None:
                    reject(at, 'additional_property', '仅允许字段：'+', '.join(nested['properties']))
                if rule['type'] == 'integer' and (type(item) is not int or not rule['minimum'] <= item <= rule['maximum']):
                    reject(at, 'range', f"整数 {rule['minimum']} 至 {rule['maximum']}")
                if rule['type'] == 'string' and (not isinstance(item, str) or not rule.get('minLength', 0) <= len(item) <= rule.get('maxLength', float('inf')) or '\0' in item):
                    reject(at, 'type', '符合长度约束的字符串')
                if rule.get('maxBytes') and len(item.encode('utf-8')) > rule['maxBytes']:
                    reject(at, 'byte_length', f"UTF-8 字节数不超过 {rule['maxBytes']}")
                if 'enum' in rule and item not in rule['enum']:
                    reject(at, 'enum', '允许值：'+', '.join(rule['enum']))
    return args
