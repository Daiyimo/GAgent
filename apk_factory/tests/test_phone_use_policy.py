# -*- coding: utf-8 -*-
"""Agent-facing phone routing and sensitive-app policy regression tests."""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GACORE = ROOT / "app" / "src" / "main" / "assets" / "gacore"
PHONE_USE = GACORE / "memory" / "phone_use.md"
ZH = GACORE / "assets" / "global_mem_insight_template.txt"
EN = GACORE / "assets" / "global_mem_insight_template_en.txt"
DROID = GACORE / "droid.py"

ZH_ROUTE = (
    "通道选择: 用户指定优先; 先满足状态/权限依赖, "
    "再从等价App/webcdp/Python中选预计交互轮次最少者, "
    "同轮次优先已装App; 细则phone_use.md。"
)
EN_ROUTE = (
    "Channel choice: honor the user's route; satisfy state/permission "
    "dependencies, then choose the equivalent app/webcdp/Python path with "
    "the fewest expected interaction rounds, preferring an installed app on "
    "ties; details in phone_use.md."
)
ZH_FAILURE_RULE = (
    "4. 闭环: 操作后等待并验证; 一般任务3次失败后可请求干预; "
    "敏感/账号App导航第2次失败即停止"
)
EN_FAILURE_RULE = (
    "4. Close the loop: wait and verify after actions; general tasks may "
    "request intervention after 3 failures; sensitive/account App navigation "
    "stops on the second failure"
)


def route_line(path):
    prefix = "通道选择:" if path == ZH else "Channel choice:"
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith(prefix)
    ]
    assert len(lines) == 1
    return lines[0]


def failure_rule_line(path):
    prefix = "4. 闭环:" if path == ZH else "4. Close the loop:"
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith(prefix)
    ]
    assert len(lines) == 1
    return lines[0]


def droid_module_doc():
    source = DROID.read_text(encoding="utf-8")
    return ast.get_docstring(ast.parse(source), clean=False) or ""


def test_channel_policy_has_required_decisions():
    text = PHONE_USE.read_text(encoding="utf-8")
    for token in (
        "用户指定",
        "状态/权限",
        "外部写",
        "无状态",
        "交互轮次",
        "同轮次",
        "降级",
    ):
        assert token in text


def test_channel_policy_has_capability_and_fallback_boundaries():
    text = PHONE_USE.read_text(encoding="utf-8")
    for rule in (
        "App/浏览器/Python",
        "结果/状态/权限",
        "账号状态",
        "本机状态",
        "只证明存在可启动候选",
        "只探测一次",
        "不自动安装",
        "Python 仅用于不需要手机 UI",
        "不得绕过 droid",
    ):
        assert rule in text


def test_app_discovery_does_not_consume_initial_probe():
    text = PHONE_USE.read_text(encoding="utf-8")
    assert "pkgs() 发现不消耗这一次探测" in text
    assert "该探测=launch + 一次初始状态/能力检查" in text


def test_l1_routes_are_semantically_equivalent():
    zh = route_line(ZH)
    en = route_line(EN)
    assert "点名 App/品牌" in zh
    assert "named app/brand" in en
    assert all(x in zh for x in ("用户指定", "状态/权限", "交互轮次最少", "已装App"))
    assert all(
        x in en
        for x in (
            "user's route",
            "state/permission",
            "fewest expected interaction rounds",
            "installed app",
        )
    )


def test_l1_failure_rules_distinguish_general_and_sensitive_apps():
    assert failure_rule_line(ZH) == ZH_FAILURE_RULE
    assert failure_rule_line(EN) == EN_FAILURE_RULE


def test_generic_search_is_not_hardwired_to_webcdp():
    zh = ZH.read_text(encoding="utf-8")
    en = EN.read_text(encoding="utf-8")
    assert "网页/搜索/打开URL/登录网站" not in zh
    assert "Web/search/open-URL/site-login" not in en
    assert "明确网页/打开URL/登录网站:" in zh
    assert "Explicit webpage/open-URL/site-login:" in en
    assert zh.index(route_line(ZH)) < zh.index("明确网页/打开URL/登录网站:")
    assert en.index(route_line(EN)) < en.index("Explicit webpage/open-URL/site-login:")


def test_sensitive_apps_stop_on_security_boundaries():
    text = PHONE_USE.read_text(encoding="utf-8")
    for token in ("登录失效", "账号异常", "验证码", "安全验证", "设备证明"):
        assert token in text
    assert "只提交一次" in text
    assert "第二次失败" in text


def test_sensitive_app_state_machine_requires_verified_single_actions():
    text = PHONE_USE.read_text(encoding="utf-8")
    assert "探测 → 单一动作 → 条件等待 → 验证 → 下一步" in text
    for token in ("目标上下文", "唯一载荷", "输入确认", "输入框清空", "精确的新气泡/状态"):
        assert token in text
    for forbidden_fallback in (
        "不自动重试",
        "不切换输入法",
        "不使用 ADB 文本注入",
        "不转交厂商助手",
        "不自动登录",
    ):
        assert forbidden_fallback in text


def test_policy_does_not_recommend_evasion():
    phone = PHONE_USE.read_text(encoding="utf-8")
    droid = DROID.read_text(encoding="utf-8")
    assert "降低合成输入指纹" not in droid
    assert "微信等风控 App 建议开" not in droid
    assert "绕过检测" not in phone
    assert "不得使用随机抖动、拟人化或隐藏自动化" in phone


def test_sensitive_apps_gate_a11y_dump_in_code_and_sop():
    """微信等敏感 App 读控件树=封号元凶: paste/scroll 内部 dump 必须代码级门控, SOP 单源说明。"""
    droid = DROID.read_text(encoding="utf-8")
    assert "SENSITIVE_APPS" in droid and "com.tencent.mm" in droid   # 单一真相源=策略注册表 SENSITIVE_APPS(SENSITIVE_PKGS 为其派生)
    assert "_app_policy" in droid            # 单一策略漏斗: dump/scroll/paste 共用, 无内联复制漂移
    assert "_sensitive_fg" in droid          # 便宜的 ping().pkg 判定, 不读 a11y 树
    assert "fail-closed" in droid            # 前台未解析→按敏感处理, 安全方向不可回退
    sop = PHONE_USE.read_text(encoding="utf-8")
    assert "SENSITIVE_APPS" in sop           # SOP 措辞指向代码注册表(单一真相源), 不复制清单
    for token in ("封号元凶", "视觉路径"):
        assert token in sop


def test_tap_docstring_documents_safety_not_evasion():
    droid = DROID.read_text(encoding="utf-8")
    expected = (
        '    """human=True only adds small motor-tolerance jitter; '
        "it is not an anti-abuse bypass.\n"
        "    Sensitive apps must use state-driven waits and stop on "
        'security checks."""'
    )
    assert expected in droid


def test_droid_quick_reference_matches_paste_runtime_contract():
    doc = droid_module_doc()
    for token in (
        "hit=True=已确认上屏",
        "hit=False, uncertain=True=验证不可用/结论不确定",
        "禁止重复输入或盲目降级",
        "ime_label 仅为元数据",
        "只有 ime_hint 可点击",
    ):
        assert token in doc
    assert "hit=False=没上屏" not in doc


def test_droid_quick_reference_matches_scroll_runtime_contract():
    doc = droid_module_doc()
    for token in (
        "必须检查 scrolled/evidence/uncertain",
        "uncertain=True=观察不可用/结论不确定",
        "不是已验证未滚动",
        "禁盲目重试",
    ):
        assert token in doc


def test_paste_and_scroll_contracts_are_current():
    text = PHONE_USE.read_text(encoding="utf-8")
    for token in ("uncertain=True", "ime_label", "ime_hint", "times=1"):
        assert token in text
    assert "hit=True=已确认上屏" in text
    assert "hit=False, uncertain=True=未知" in text
    assert "ime_label 仅是元数据" in text
    assert "只有 ime_hint 可点击" in text
    assert "verify=False 永远不能证明输入成功" in text
    assert "times>1 仅用于明确遍历" in text
    assert "scroll() 自己负责文本/像素证据" in text
    assert "scrolled 恒为 False" not in text


def test_stale_paste_and_scroll_guidance_is_removed():
    text = PHONE_USE.read_text(encoding="utf-8")
    for stale in (
        "hit=False=未上屏",
        '若 ime_hint 是"来自剪贴板"标签',
        "times=3 多滚",
        "scrolled **恒为 False**",
        "网页里 scrolled=False 也常是漏报",
        "以 shot 前后对比为准",
        "调用方自行截图",
    ):
        assert stale not in text
