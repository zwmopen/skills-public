#!/usr/bin/env python3
"""在已核实的本批事实条件下，随机选择一个小红书强转化结构模板。

用法：
 python scripts/select_strong_cta_style.py --facts /path/to/current-facts.json \
   --history /path/to/.cache/strong-cta-history.json

facts 是模型先从本批用户素材提取的 JSON（字段见 references/strong-cta-style-pool-v1.json）。
不允许把上次样本的景点、时间、人数或服务权益用于推断本批 facts。
默认打印 JSON 结果；仅在传了 --history 的情况下更新本机历史，不修改仓库。
"""
from __future__ import annotations

import argparse
import json
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "references" / "strong-cta-style-pool-v1.json"


def load_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def eligible(template: dict, facts: dict) -> bool:
    try:
        if int(facts.get("project_count", 0)) < int(template.get("min_project_count", 0)):
            return False
        for key, needed in template.get("requirements", {}).items():
            if key == "min_route_count":
                if int(facts.get("route_count", 0)) < int(needed):
                    return False
            elif needed is True and facts.get(key) is not True:
                return False
            elif needed is False and facts.get(key) is not False:
                return False
        return True
    except (TypeError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--facts", type=Path, required=True)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--avoid-recent", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    facts = load_json(args.facts, {})
    if not isinstance(facts, dict):
        parser.error("--facts 必须是 JSON object")
    manifest = load_json(MANIFEST, {})
    templates = manifest.get("templates", [])
    qualified = [t for t in templates if eligible(t, facts)]

    if not qualified:
        print(json.dumps({
            "status": "needs_more_facts",
            "reason": "当前素材不足以匹配任何结构模板；不能强造项目、时长或路线。",
            "eligible_template_ids": []
        }, ensure_ascii=False))
        return 2

    previous = load_json(args.history, []) if args.history else []
    if not isinstance(previous, list):
        previous = []
    prior_ids = [str(v) for v in previous if isinstance(v, str)]
    recent = set(prior_ids[-max(0, args.avoid_recent):]) if args.avoid_recent else set()
    fresh = [t for t in qualified if t["id"] not in recent]
    candidates = fresh if fresh else qualified

    picked = secrets.choice(candidates)
    result = {
        "status": "ok",
        "selected_template_id": picked["id"],
        "selected_template_name": picked["name"],
        "qualified_template_ids": [t["id"] for t in qualified],
        "avoided_recent_ids": sorted(recent),
        "history_updated": bool(args.history and not args.dry_run),
        "reference": "references/strong-cta-style-pool-v1.md",
        "note": "仅选择结构；必须用当前批次的真实地点、活动与已知时间重写内容。"
    }

    if args.history and not args.dry_run:
        args.history.parent.mkdir(parents=True, exist_ok=True)
        args.history.write_text(
            json.dumps((prior_ids + [picked["id"]])[-60:], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8"
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
