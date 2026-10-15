"""Curated official discovery entries for the installed mainstream recipes.

Entries identify official documentation, not a ranking or guaranteed successful
fetch. The collector still enforces public DNS, robots and body validation.
"""

FRONTEND_SOURCES = {
    "vue-ts": ("https://vuejs.org/guide/introduction.html",),
    "react-ts": ("https://react.dev/learn",),
    "angular-ts": ("https://angular.dev/guide/components",),
    "nextjs-app": ("https://nextjs.org/docs/app",),
    "nuxt-app": ("https://nuxt.com/docs/4.x/getting-started/introduction",),
    "svelte-component": ("https://svelte.dev/docs/svelte/overview",),
    "astro-content": ("https://docs.astro.build/en/getting-started/",),
    "wechat-miniprogram": ("https://developers.weixin.qq.com/miniprogram/dev/framework/",),
    "uniapp-vue": ("https://uniapp.dcloud.net.cn/tutorial/",),
    "taro-react": ("https://docs.taro.zone/docs/",),
    "expo-react-native": ("https://docs.expo.dev/", "https://reactnative.dev/docs/getting-started"),
    "frontend-css": ("https://developer.mozilla.org/en-US/docs/Web/CSS",),
    "frontend-less": ("https://lesscss.org/features/",),
    "frontend-scss": ("https://sass-lang.com/documentation/",),
    "frontend-tailwind": ("https://tailwindcss.com/docs/installation/using-vite",),
    "frontend-bootstrap": ("https://getbootstrap.com/docs/5.3/getting-started/introduction/",),
    "frontend-element-plus": ("https://element-plus.org/en-US/guide/quickstart.html",),
    "frontend-ant-design": ("https://ant.design/docs/react/introduce",),
    "frontend-mui": ("https://mui.com/material-ui/getting-started/",),
}

APP_RECIPE_IDS = ("wechat-miniprogram", "uniapp-vue", "taro-react", "expo-react-native",
                  "frontend-css", "frontend-less", "frontend-scss")


def documentation_seeds(identifiers=None):
    identifiers = FRONTEND_SOURCES if identifiers is None else identifiers
    return tuple(dict.fromkeys(url for identifier in identifiers
                               for url in FRONTEND_SOURCES.get(identifier, ())))


def matched_documentation(seeds, goal):
    """Use the same explicit technology recognition as task template selection."""
    from .frontend_template_selection import match_frontend_templates
    matches = documentation_seeds(match_frontend_templates(goal))
    available = set(seeds)
    return [url for url in matches if url in available]


def resolve_documentation(seeds, goal, research_query=""):
    """Keep explicit exclusions and missing in-scope sources distinct from no topic.

    Only the frontend/App discovery catalogs use these recipes. A backend task
    mentioning its React consumer must still use its backend source profile.
    """
    from .frontend_template_selection import select_frontend_templates, _mentions
    known = set(documentation_seeds())
    if not known.intersection(seeds):
        return None
    selection = select_frontend_templates({"template_query": goal, "template_fallback": research_query})
    if not selection["explicit"]:
        return None
    identifiers = [item["id"] for item in selection["choices"]]
    available = set(seeds)
    missing = [identifier for identifier in identifiers
               if not available.intersection(FRONTEND_SOURCES.get(identifier, ()))]
    # A rejected framework cannot be restored by a model-generated query.
    clean_goal = goal
    for mention in reversed(_mentions(goal)):
        if mention["excluded"]:
            clean_goal = clean_goal[:mention["start"]] + clean_goal[mention["end"]:]
    effective_query = clean_goal + " " + " ".join(item["name"] for item in selection["choices"])
    if missing:
        return {"seeds": [], "missing": missing, "search_goal": effective_query.strip()}
    chosen = [url for url in documentation_seeds(identifiers) if url in available]
    # With only negative choices, use neutral sources, never a different
    # framework. Frontend retains MDN HTML; App retains its native platforms.
    if not identifiers:
        chosen = [url for url in seeds if url not in known]
    return {"seeds": chosen, "missing": [], "search_goal": effective_query.strip()}
