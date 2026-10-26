"""R4: 录制器——把一次成功运行的设备操作痕迹机械转成配方（SPEC Phase 1）。

设计要点：
- 输入是 droid 侧记录的 operation trace（每次 launch/tap/swipe/paste/scroll/look/dump/back/home），
  不是模型写的代码——所以录制零模型调用、可离线复现。
- 点的 locator 从「动作点所在的节点」推导（text/desc），解析不到才退 relative 并标记 fragile；
  观测步（look/dump）转成 observe + min_nodes；launch/back/home 用 any 定位器。
- expected 全部来自该动作已有的验证产出（diff/前台），不新造判定。
"""
import sys
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import recipe


def _op(kind, **kw):
    base = {"kind": kind, "args": {}, "result": {}, "obs": None}
    base.update(kw)
    return base


def _obs(nodes, pkg="com.tencent.news", screen=(1200, 2670)):
    return {"nodes": nodes, "detections": [], "screen": screen, "pkg": pkg}


SEARCH_NODE = {"t": "搜索", "x": 645, "y": 598, "b": "182,527,1109,670", "click": 1}
LIST_NODES = [{"t": "新闻%d" % i, "x": 600, "y": 400 + i * 100,
               "b": "0,%d,1200,%d" % (350 + i * 100, 440 + i * 100)} for i in range(5)]


class TraceToRecipeTest(unittest.TestCase):
    def test_launch_lookup_tap_becomes_three_steps(self):
        trace = [
            _op("launch", args={"pkg": "com.tencent.news"},
                result={"pkg": "com.tencent.news"}),
            _op("look", result={"count": 26}),
            _op("tap", args={"x": 645, "y": 598}, result={"diff_pct": 8.0},
                obs=_obs([SEARCH_NODE])),
        ]
        r = recipe.trace_to_recipe(trace, {"app": "腾讯新闻"})
        kinds = [s.action["kind"] for s in r.steps]
        self.assertEqual(kinds, ["launch", "observe", "tap"])
        self.assertEqual(r.app_hint["package"], "com.tencent.news")
        # 点的 locator 从所在节点推导, 不存坐标
        self.assertEqual(r.steps[2].locator, {"kind": "text", "value": "搜索"})
        self.assertEqual(r.steps[2].expected["kind"], "diff_at_least")
        # launch 步期望前台
        self.assertEqual(r.steps[0].expected, {"kind": "foreground_is", "value": "com.tencent.news"})

    def test_observe_step_uses_min_nodes(self):
        trace = [_op("look", result={"count": 26}, obs=_obs(LIST_NODES))]
        r = recipe.trace_to_recipe(trace, {"app": "腾讯新闻"})
        self.assertEqual(r.steps[0].action["kind"], "observe")
        self.assertEqual(r.steps[0].expected["kind"], "min_nodes")
        self.assertEqual(r.steps[0].expected["value"], 5)

    def test_no_effect_tap_becomes_diff_at_most(self):
        trace = [_op("tap", args={"x": 645, "y": 598}, result={"diff_pct": 0.0},
                     obs=_obs([SEARCH_NODE]))]
        r = recipe.trace_to_recipe(trace, {"app": "X"})
        self.assertEqual(r.steps[0].expected["kind"], "diff_at_most")

    def test_point_outside_any_node_falls_back_to_relative_and_marks_fragile(self):
        trace = [_op("tap", args={"x": 60, "y": 2600}, result={"diff_pct": 3.0},
                     obs=_obs([SEARCH_NODE]))]
        r = recipe.trace_to_recipe(trace, {"app": "X"})
        self.assertEqual(r.steps[0].locator["kind"], "relative")
        self.assertTrue(r.fragile)

    def test_scroll_becomes_observe_roi_step(self):
        trace = [_op("scroll", args={"direction": "up"}, result={"scrolled": True})]
        r = recipe.trace_to_recipe(trace, {"app": "X"})
        self.assertEqual(r.steps[0].action["kind"], "swipe")
        self.assertEqual(r.steps[0].locator["kind"], "roi")

    def test_wait_ops_are_dropped(self):
        trace = [_op("launch", args={"pkg": "com.tencent.news"}, result={"pkg": "com.tencent.news"}),
                 _op("wait", args={"seconds": 2}),
                 _op("back", result={"diff_pct": 12.0})]
        r = recipe.trace_to_recipe(trace, {"app": "X"})
        self.assertEqual([s.action["kind"] for s in r.steps], ["launch", "back"])

    def test_paste_step_keeps_value(self):
        trace = [_op("paste", args={"text": "蓝牙"}, result={"hit": True},
                     obs=_obs([{"t": "", "edit": 1, "x": 600, "y": 2300, "b": "100,2200,1100,2300"}]))]
        r = recipe.trace_to_recipe(trace, {"app": "X"})
        self.assertEqual(r.steps[0].action, {"kind": "paste", "value": "蓝牙"})

    def test_empty_trace_rejected(self):
        with self.assertRaises(recipe.RecipeError):
            recipe.trace_to_recipe([], {"app": "X"})

    def test_resulting_recipe_validates(self):
        trace = [
            _op("launch", args={"pkg": "com.tencent.news"}, result={"pkg": "com.tencent.news"}),
            _op("look", result={"count": 26}, obs=_obs(LIST_NODES)),
            _op("tap", args={"x": 645, "y": 598}, result={"diff_pct": 8.0}, obs=_obs([SEARCH_NODE])),
        ]
        d = recipe.recipe_to_dict(recipe.trace_to_recipe(trace, {"app": "腾讯新闻"}))
        recipe.validate_recipe(d)      # 不得抛错——产出必须是合法配方


if __name__ == "__main__":
    unittest.main()
