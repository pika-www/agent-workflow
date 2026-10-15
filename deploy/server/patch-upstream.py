"""Apply the bounded loopback transport adapter to a known upstream build."""
import hashlib
import json
from pathlib import Path
import shutil

project = Path(__file__).resolve().parents[2]
path = project / 'openwiki-upstream/dist/agent/index.js'
before = path.read_text()
statement = 'import {localModelOptions} from "../../../federation/local-model-transport.mjs";\n'
old = '        apiKey: getProviderApiKey(provider),\n        configuration,\n        model: modelId,'
new = '        apiKey: getProviderApiKey(provider),\n        configuration,\n        ...localModelOptions(baseURL, configuration),\n        model: modelId,'
if statement in before and new in before:
    print(json.dumps({'already_applied': True}))
else:
    assert statement not in before and before.count(old) == 1, 'Upstream build changed; review the adapter before applying'
    backup = project.parent / 'backups/upstream-transport/index.js'
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        assert backup.read_text() == before, 'Different original build already backed up'
    else:
        shutil.copy2(path, backup)
    after = statement + before.replace(old, new)
    temporary = path.with_suffix('.js.transport.tmp')
    temporary.write_text(after)
    temporary.chmod(path.stat().st_mode & 0o777)
    temporary.replace(path)
    print(json.dumps({'applied':True,'before_sha256':hashlib.sha256(before.encode()).hexdigest(),
                      'after_sha256':hashlib.sha256(after.encode()).hexdigest()}))
