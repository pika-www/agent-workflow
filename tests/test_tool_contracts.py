import json
import subprocess
from pathlib import Path
import pytest
from federation.tool_contracts import validate_contract, ToolContractError


@pytest.mark.parametrize('args,field,code', [
    ({'action':'read','parameters':'{"path":"/tmp/a","offset":-1}'}, 'parameters.offset','range'),
    ({'action':'read','parameters':'{"pah":"/tmp/a"}'}, 'parameters.path','required'),
    ({'action':'delete','parameters':'{"path":"/tmp/a","force":true}'}, 'parameters.force','additional_property'),
    ({'action':'write','parameters':json.dumps({'path':'/tmp/a','content':'中'*7000},ensure_ascii=False)}, 'parameters.content','byte_length'),
])
def test_host_and_provider_share_nested_errors(args,field,code):
    with pytest.raises(ToolContractError) as error:
        validate_contract('server_files',args)
    assert (error.value.detail['field'],error.value.detail['code'])==(field,code)
    script="import {validateContract} from './federation/tool-contracts.mjs';try{validateContract('server_files',JSON.parse(process.argv[1]))}catch(e){console.log(JSON.stringify(e.detail))}"
    result=json.loads(subprocess.check_output(['node','--input-type=module','-e',script,json.dumps(args)],cwd=Path(__file__).resolve().parents[1]))
    assert (result['field'],result['code'])==(field,code)


def test_real_pagination_contract():
    validate_contract('server_files',{'action':'list','parameters':'{"path":"/tmp","offset":200}'})
    with pytest.raises(ToolContractError):
        validate_contract('file_read',{'file_id':'a'*32,'start':'NaN','limit':'18000'})


def test_live_mcp_schema_errors_are_structured_and_private():
    from federation.tool_contracts import validate_dynamic_schema
    schema={'type':'object','properties':{'count':{'type':'integer','maximum':20}},'required':['count']}
    with pytest.raises(ToolContractError) as error:
        validate_dynamic_schema(schema,{'count':'PRIVATE_VALUE'})
    assert error.value.detail['field']=='arguments.count'
    assert 'PRIVATE_VALUE' not in str(error.value)
    with pytest.raises(ToolContractError):validate_dynamic_schema(schema,{'count':2,'invented':'field'})
