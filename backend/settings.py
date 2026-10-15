"""Local configuration. Secrets never leave this module's public projection."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


DEFAULTS = {
    "name": "知行", "provider": "disabled", "base_url": "http://127.0.0.1:11434",
    "model": "", "api_key": "", "watch_inbox": False,
    "purpose": "帮助我整理资料、维护有来源的知识页面，并依据知识库回答问题。",
}


class Settings:
    def __init__(self, root: Path):
        self.path = root / "settings.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self):
        return {**DEFAULTS, **(json.loads(self.path.read_text()) if self.path.exists() else {})}

    def public(self):
        value = self.read()
        value["api_key_set"] = bool(value.pop("api_key", ""))
        value["configured"] = value["provider"] != "disabled" and bool(value["model"].strip())
        return value

    def update(self, patch):
        value = self.read()
        old_provider, old_url = value["provider"], value["base_url"]
        for key in DEFAULTS:
            if key in patch and patch[key] is not None:
                if key == "api_key" and not patch[key]:
                    continue
                value[key] = patch[key]
        if patch.get("clear_api_key"):
            value["api_key"] = ""
        if value["provider"] not in ("disabled", "ollama", "compatible"):
            raise ValueError("不支持的模型连接类型")
        for key in ("name", "model", "base_url", "purpose", "api_key"):
            if not isinstance(value[key], str):
                raise ValueError("配置字段格式不正确")
        value["name"] = value["name"].strip()[:60] or "知行"
        value["model"] = value["model"].strip()[:160]
        value["base_url"] = value["base_url"].strip().rstrip("/")
        if (old_provider != value["provider"] or old_url != value["base_url"]) and not patch.get("api_key"):
            # Credentials belong to one service, never forward an old key to a new URL.
            value["api_key"] = ""
        parts = urlsplit(value["base_url"])
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("请填写不包含账号、密钥或查询参数的 HTTP/HTTPS 服务地址")
        if value["provider"] != "disabled" and not value["model"]:
            raise ValueError("请填写模型名称")
        value["watch_inbox"] = bool(value["watch_inbox"]) and value["provider"] != "disabled"
        value["purpose"] = value["purpose"][:2000]
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)
        return self.public()
