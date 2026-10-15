"""Deterministic recipe selection across framework, style and component layers.

This maps user intent to existing local assets. It never downloads dependencies,
grants execution permissions, or borrows another Agent's template directory.
"""
import re


MAX_TEMPLATE_SELECTION = 7  # One Agent standard and at most six task recipes.

# Order resolves overlapping names: React Native is one platform, not React web;
# SCSS and Tailwind CSS are one style mention, not an additional plain CSS choice.
RECIPES = (
    ("expo", "expo-react-native", "framework", r"expo|react[\s_-]*native|rn"),
    ("nextjs", "nextjs-app", "framework", r"next(?:[.\s-]?js)?"),
    ("nuxt", "nuxt-app", "framework", r"nuxt(?:[.\s-]?js)?"),
    ("uniapp", "uniapp-vue", "framework", r"uni[\s-]?app"),
    ("taro", "taro-react", "framework", r"taro"),
    ("wechat", "wechat-miniprogram", "framework",
     r"原生\s*微信(?:\s*小程序)?|微信\s*(?:原生(?:\s*小程序)?|小程序)|"
     r"wechat(?:[\s-]+mini[\s-]?program)?|weixin(?:[\s-]+mini[\s-]?program)?|wx[\s-]?mini[\s-]?program"),
    ("angular", "angular-ts", "framework", r"angular|anglar"),
    ("svelte", "svelte-component", "framework", r"svelte(?:kit)?"),
    ("astro", "astro-content", "framework", r"astro"),
    ("vue", "vue-ts", "framework", r"vue(?:\.?js)?"),
    ("react", "react-ts", "framework", r"react(?:\.?js)?"),
    ("tailwind", "frontend-tailwind", "style", r"tailwind(?:[\s-]?css)?"),
    ("scss", "frontend-scss", "style", r"scss|sass"),
    ("less", "frontend-less", "style", r"less"),
    ("css", "frontend-css", "style", r"css(?:3)?"),
    ("bootstrap", "frontend-bootstrap", "component", r"bootstrap"),
    ("element-plus", "frontend-element-plus", "component", r"element[\s-]?plus"),
    ("ant-design", "frontend-ant-design", "component", r"ant[\s-]?design|antd"),
    ("mui", "frontend-mui", "component", r"mui|material[\s-]?ui"),
)
TEMPLATE_IDS = {name: identifier for name, identifier, _, _ in RECIPES}
WEB_TEMPLATE_IDS = set(TEMPLATE_IDS.values())
DIMENSIONS = ("framework", "style", "component")
_PATTERNS = [(name, identifier, dimension,
              re.compile(r"(?<![a-z0-9_])(?:" + pattern + r")(?:\s*v?\d+(?:\.\d+)*)?(?![a-z0-9_])", re.I))
             for name, identifier, dimension, pattern in RECIPES]
_NEGATION = re.compile(
    r"(?:不要(?:再)?(?:用|使用|采用)?|不用|不使用|不采用|不需要|无需|排除|不是|去掉|移除|"
    r"without|except|exclude|excluding|not|no|don't\s+use|do\s+not\s+use)\s*$", re.I)
_RESET = re.compile(r"(?:但(?:是)?|而是|改为|改用|换成|使用|采用|选择|用|but|instead(?:\s+use)?|use|using)\s*$", re.I)


def supports_frontend_recipes(store, space):
    """Frontend/App descendants own independent copies; siblings are not read."""
    visited = set()
    try:
        current = store._definition(space)
        while current:
            if current["id"] in {"software-frontend", "software-app"}:
                return True
            if current["id"] in visited or not current.get("parent_id"):
                return False
            visited.add(current["id"])
            current = store._definition(current["parent_id"])
    except (ValueError, KeyError, TypeError):
        return False
    return False


def _mentions(text):
    if not isinstance(text, str):
        return []
    occupied, matches = [], []
    for name, identifier, dimension, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            if any(match.start() < end and match.end() > start for start, end in occupied):
                continue
            occupied.append(match.span())
            matches.append({"name": name, "id": identifier, "dimension": dimension,
                            "start": match.start(), "end": match.end()})
    matches.sort(key=lambda item: item["start"])
    previous_end, excluded = 0, False
    for item in matches:
        between = text[previous_end:item["start"]]
        # Carry "不用 Vue 和 React" across its list, but a fresh clause or
        # affirmative choice resets it: "不用 React，使用 Vue".
        if re.search(r"[，,。.;；\n!?！？]", between):
            excluded = False
            between = re.split(r"[，,。.;；\n!?！？]", between)[-1]
        if _NEGATION.search(between):
            excluded = True
        elif _RESET.search(between):
            excluded = False
        item["excluded"] = excluded
        previous_end = item["end"]
    # Last explicit mention within a task wins, as in "不用 Vue，最后还是用 Vue".
    latest = {item["name"]: item for item in matches}
    return sorted(latest.values(), key=lambda item: item["start"])


def _candidates(job):
    values = [(job.get("template_query", job.get("question", "")), "current-task")]
    if job.get("template_fallback"):
        values.append((job["template_fallback"], "current-user-goal"))
    history = job.get("template_history", [])
    if isinstance(history, list):
        values.extend((text, "recent-user-context") for text in reversed(history[-8:]))
    return values


def select_frontend_templates(job):
    """Choose each dimension from its newest explicit instruction.

    A style-only follow-up can retain its framework; a rejected style cannot
    reappear from history. App recipes consume their underlying web starter.
    """
    chosen, resolved = [], set()
    reasons = {}
    for text, reason in _candidates(job):
        mentions = _mentions(text)
        for dimension in DIMENSIONS:
            layer = [item for item in mentions if item["dimension"] == dimension]
            if dimension in resolved or not layer:
                continue
            resolved.add(dimension)
            reasons[dimension] = reason
            chosen.extend({**item, "reason": reason} for item in layer if not item["excluded"])
    names = {item["name"] for item in chosen}
    consumed = set()
    if names & {"nextjs", "taro", "expo"}:
        consumed.add("react")
    if names & {"nuxt", "uniapp"}:
        consumed.add("vue")
    chosen = [item for item in chosen if item["name"] not in consumed]
    # Stable dimension order gives the framework context before style overrides.
    chosen.sort(key=lambda item: (DIMENSIONS.index(item["dimension"]), item["start"]))
    return {"choices": chosen, "explicit": bool(resolved), "resolved_dimensions": sorted(resolved),
            "reasons": reasons}


def select_frameworks(job):
    """Compatibility helper used by callers interested in the framework layer."""
    result = select_frontend_templates(job)
    choices = [item["name"] for item in result["choices"] if item["dimension"] == "framework"]
    reason = result["reasons"].get("framework", "framework-not-specified")
    if "framework" in result["resolved_dimensions"] and not choices:
        reason = "explicit-framework-not-supported-or-excluded"
    return choices, reason


def match_frontend_templates(text):
    """Pure text match for source discovery, with the same aliases/exclusions."""
    return [item["id"] for item in select_frontend_templates({"template_query": text})["choices"]]
