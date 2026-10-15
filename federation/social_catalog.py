"""Official platform references for preparing social-account connections.

Availability describes the cited platform documentation, not an implemented
connector or permissions granted to this application or the user's account.
This module performs no network requests, authorization, or account operations.
"""
from __future__ import annotations

from copy import deepcopy


VERIFY_DATE = "2026-10-04"

PROVIDERS = [
    {
        "id": "douyin",
        "name": "抖音",
        "description": "按应用获批能力连接自己的账号、作品与数据。",
        "verify_date": VERIFY_DATE,
        "portal_url": "https://developer.open-douyin.com/",
        "docs": [
            {
                "label": "入驻主体与应用类型",
                "url": "https://developer.open-douyin.com/docs/resource/zh-CN/developer/join/issues",
            },
            {
                "label": "登录与能力授权",
                "url": "https://developer.open-douyin.com/docs/resource/zh-CN/dop/ability/opensdk/user-authorization/solution",
            },
            {
                "label": "创建视频",
                "url": "https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/video-management/douyin/create-video/video-create",
            },
            {
                "label": "小程序视频评论回复",
                "url": "https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/develop/server/basic-abilities/video-id-convert/video-review-data/video-comment-reply",
            },
        ],
        "capabilities": [
            {
                "id": "read",
                "label": "读取与分析",
                "availability": "documented_application_required",
                "note": "用户信息、内容和数据能力需分别获批并取得账号授权，范围以实际授权为准。",
            },
            {
                "id": "publish",
                "label": "内容发布",
                "availability": "documented_application_required",
                "note": "代发视频需申请对应能力并获得用户授权，提交后仍有平台审核。",
            },
            {
                "id": "comments",
                "label": "评论管理",
                "availability": "limited",
                "note": "已核实小程序可申请回复本人视频评论；当前应用能否使用需另核对。",
            },
            {
                "id": "messages",
                "label": "私信管理",
                "availability": "unverified",
                "note": "通用私信读取与代回复权限待核实，账号登录不代表已开放。",
            },
        ],
        "requirements": [
            "先确认应用类型与主体：个人主体仅支持小程序、小游戏；网站应用需符合平台支持的企业、个体工商户等主体条件。",
            "在应用后台核对各项能力的申请结果。",
            "由账号本人完成对应能力授权。",
        ],
        "next_step": "登记已有应用情况，再按读取、发布和互动分别核对权限。",
    },
    {
        "id": "xiaohongshu",
        "name": "小红书",
        "description": "当前账号授权资料仅确认开放基础身份信息。",
        "verify_date": VERIFY_DATE,
        "portal_url": "https://openaccount.xiaohongshu.com/",
        "docs": [
            {
                "label": "授权范围与开放状态",
                "url": "https://openaccount.xiaohongshu.com/docs/scope",
            },
            {
                "label": "账号授权接入说明",
                "url": "https://openaccount.xiaohongshu.com/docs/quick-start",
            },
        ],
        "capabilities": [
            {
                "id": "read",
                "label": "读取与分析",
                "availability": "planned",
                "note": "基础信息已开放；笔记读取及详细档案在授权目录中仍为规划中。",
            },
            {
                "id": "publish",
                "label": "内容发布",
                "availability": "planned",
                "note": "笔记发布在账号授权目录中仍为规划中，特定场景需单独核实。",
            },
            {
                "id": "comments",
                "label": "评论管理",
                "availability": "unverified",
                "note": "当前账号授权目录未确认评论管理能力。",
            },
            {
                "id": "messages",
                "label": "私信管理",
                "availability": "unverified",
                "note": "当前账号授权目录未确认私信管理能力。",
            },
        ],
        "requirements": [
            "确认是否已有通过审核的账号授权应用。",
            "区分基础身份授权与笔记、评论、私信权限。",
            "向平台核对所需业务场景的当前开放范围。",
        ],
        "next_step": "先确认应用及基础身份授权；笔记和互动能力保留待开放或待核实状态。",
    },
    {
        "id": "bilibili",
        "name": "B站",
        "description": "官方目录包含账号授权、稿件管理和授权后的数据能力。",
        "verify_date": VERIFY_DATE,
        "portal_url": "https://openhome.bilibili.com/",
        "docs": [
            {"label": "开放能力目录", "url": "https://openhome.bilibili.com/doc"},
            {
                "label": "查询视频稿件详情",
                "url": "https://openhome.bilibili.com/doc/4/d9554788-dcef-f139-6217-b487d41c3826",
            },
            {
                "label": "开发者服务协议",
                "url": "https://openhome.bilibili.com/agreement/developer-service",
            },
        ],
        "capabilities": [
            {
                "id": "read",
                "label": "读取与分析",
                "availability": "documented_application_required",
                "note": "目录包含用户与稿件数据，具体接口需申请权限并取得账号授权。",
            },
            {
                "id": "publish",
                "label": "内容发布",
                "availability": "documented_application_required",
                "note": "目录包含视频和专栏稿件发布，需完成应用接入及对应授权。",
            },
            {
                "id": "comments",
                "label": "评论管理",
                "availability": "unverified",
                "note": "已核实的能力目录不足以确认评论读取与代回复权限。",
            },
            {
                "id": "messages",
                "label": "私信管理",
                "availability": "unverified",
                "note": "通用私信管理权限待核实，直播消息能力不等于私信权限。",
            },
        ],
        "requirements": [
            "完成开放平台身份认证与应用接入。",
            "核对稿件、数据等能力的申请结果。",
            "由目标账号接受授权。",
        ],
        "next_step": "确认已有应用及账号授权情况，优先核对作品读取和发布能力。",
    },
    {
        "id": "weibo",
        "name": "微博",
        "description": "官方提供面向智能体的 CLI，可按开通服务调用平台能力。",
        "verify_date": VERIFY_DATE,
        "portal_url": "https://open.weibo.com/cli",
        "docs": [
            {"label": "官方 CLI 使用手册", "url": "https://open.weibo.com/cli/quickstart"},
            {"label": "官方 CLI 能力介绍", "url": "https://open.weibo.com/cli"},
        ],
        "capabilities": [
            {
                "id": "read",
                "label": "读取与分析",
                "availability": "documented_application_required",
                "note": "官方 CLI 包含内容、用户和分析能力；可用命令取决于认证、服务及额度。",
            },
            {
                "id": "publish",
                "label": "内容发布",
                "availability": "documented_application_required",
                "note": "官方 CLI 包含发文能力，需核对当前账号服务中开放的发布命令。",
            },
            {
                "id": "comments",
                "label": "评论管理",
                "availability": "documented_application_required",
                "note": "官方资料列有评论获取和回复；实际范围以授权后的命令清单为准。",
            },
            {
                "id": "messages",
                "label": "私信管理",
                "availability": "limited",
                "note": "手册提及私信写操作，是否具备所需读取和回复命令仍需核对。",
            },
        ],
        "requirements": [
            "完成微博开发者认证。",
            "开通适用的体验或正式服务并核对额度。",
            "官方 CLI 尚未接入本系统，需完成本机配置与账号授权。",
        ],
        "next_step": "先确认开发者认证和服务状态，再接入官方 CLI 并读取可用命令清单。",
    },
    {
        "id": "wechat_official",
        "name": "微信公众号",
        "description": "公众号单独接入，能力以账号类型、认证状态和后台权限为准。",
        "verify_date": VERIFY_DATE,
        "portal_url": "https://mp.weixin.qq.com/",
        "docs": [
            {
                "label": "公众号开发文档入口",
                "url": "https://developers.weixin.qq.com/doc/offiaccount/Getting_Started/Overview.html",
            },
            {
                "label": "接口权限说明入口",
                "url": "https://developers.weixin.qq.com/doc/offiaccount/Getting_Started/Explanation_of_interface_privileges.html",
            },
        ],
        "capabilities": [
            {
                "id": "read",
                "label": "读取与分析",
                "availability": "unverified",
                "note": "本轮未取得官方文档正文，文章和统计数据的适用权限待核对。",
            },
            {
                "id": "publish",
                "label": "内容发布",
                "availability": "unverified",
                "note": "需核对该公众号的草稿、发布和群发权限，不能视为同一项能力。",
            },
            {
                "id": "comments",
                "label": "评论管理",
                "availability": "unverified",
                "note": "留言读取、回复及管理权限需结合该公众号后台核实。",
            },
            {
                "id": "messages",
                "label": "私信管理",
                "availability": "unverified",
                "note": "用户消息与客服回复的适用范围待核实，不代表个人微信聊天权限。",
            },
        ],
        "requirements": [
            "确认订阅号或服务号及认证状态。",
            "核对公众号后台实际接口权限。",
            "确定由自有开发应用还是获准的第三方应用接入。",
        ],
        "next_step": "先登记公众号类型和认证状态，再核对后台显示的接口权限。",
    },
    {
        "id": "wechat_channels",
        "name": "视频号",
        "description": "视频号与公众号分别登记，按视频号实际开放能力接入。",
        "verify_date": VERIFY_DATE,
        "portal_url": "https://channels.weixin.qq.com/",
        "docs": [
            {"label": "视频号助手", "url": "https://channels.weixin.qq.com/"},
        ],
        "capabilities": [
            {
                "id": "read",
                "label": "读取与分析",
                "availability": "unverified",
                "note": "尚未核实适用于该账号的作品和统计数据开放接口。",
            },
            {
                "id": "publish",
                "label": "内容发布",
                "availability": "unverified",
                "note": "尚未核实通用代发布权限，后台能发布不等于可通过接口发布。",
            },
            {
                "id": "comments",
                "label": "评论管理",
                "availability": "unverified",
                "note": "评论读取和回复的官方接入范围待核实。",
            },
            {
                "id": "messages",
                "label": "私信管理",
                "availability": "unverified",
                "note": "视频号私信开放范围待核实，不能沿用公众号的用户消息权限。",
            },
        ],
        "requirements": [
            "确认视频号主体、认证状态及管理员权限。",
            "在视频号官方后台核实所需能力是否对该账号开放。",
            "分别核对内容运营与电商能力，避免混用权限。",
        ],
        "next_step": "先确认视频号账号情况与官方接入入口，再决定可连接的功能。",
    },
]


def list_providers() -> list[dict]:
    """Return a detached catalog so callers cannot mutate shared metadata."""
    return deepcopy(PROVIDERS)


def get_provider(provider_id: str) -> dict:
    """Return a detached provider record or reject an unknown identifier."""
    for provider in PROVIDERS:
        if provider["id"] == provider_id:
            return deepcopy(provider)
    raise ValueError("未知社交平台：" + str(provider_id))
