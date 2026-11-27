#!/usr/bin/env python3
"""Select one complete writing reference per slot, never infer facts from references.
Input JSON: {"slots":[{"id":"xhs1","platform":"xiaohongshu","eligible_ids":["R001","G001"]}, ...]}.
Eligibility is determined by the caller from current verified facts and index hints.
This tool selects and reads full text; it does not certify rights, suitability or publication.
"""
from __future__ import annotations
import argparse
import json
import os
import secrets
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = ROOT / "references/raw-example-index-v1.json"
DEFAULT_HISTORY = ROOT / ".cache/raw-example-history-v1.json"

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def read_example(entry, root):
    path = (root / entry["source"]).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Reference path outside selected library")
    with path.open(encoding="utf-8-sig", newline="") as f:
        lines = f.read().split("\n")
    start, end = entry["start_line"], entry["end_line"]
    if not (1 <= start <= end <= len(lines)):
        raise ValueError("Stale line range: " + entry["id"])
    body = "\n".join(lines[start - 1:end])
    if not body.strip() or not body.startswith(entry["title"][:24]):
        raise ValueError("Stale locator or missing original: " + entry["id"])
    return body

def assignment(pools, recent):
    rng = secrets.SystemRandom()
    order = sorted(pools, key=lambda slot: len(pools[slot]))
    def search(i, used, result, exclude_recent):
        if i == len(order):
            return dict(result)
        slot = order[i]
        options = [v for v in pools[slot] if v not in used and (not exclude_recent or v not in recent)]
        rng.shuffle(options)
        # Preserve randomness within groups while preferring fresh candidates.
        options.sort(key=lambda v: v in recent)
        for v in options:
            result[slot] = v
            found = search(i + 1, used | {v}, result, exclude_recent)
            if found is not None:
                return found
            result.pop(slot, None)
        return None
    fresh = search(0, set(), {}, True)
    if fresh is not None:
        return fresh, False
    return search(0, set(), {}, False), True

def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".selection-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    p.add_argument("--avoid-recent", type=int, default=10)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if args.avoid_recent < 0:
        p.error("--avoid-recent must be nonnegative")
    entries = read_json(args.index)["entries"]
    by_id = {e["id"]: e for e in entries}
    if len(by_id) != len(entries):
        p.error("Duplicate example IDs")
    req = read_json(args.request)
    slots = req["slots"]
    if not isinstance(slots, list) or not 1 <= len(slots) <= 6:
        p.error("Expected 1 to 6 slots")
    pools = {}
    bodies = {}
    errors = []
    for slot in slots:
        sid, platform = slot["id"], slot["platform"]
        if sid in pools or platform not in ("xiaohongshu", "douyin"):
            p.error("Duplicate slot ID or invalid platform")
        ids = slot["eligible_ids"]
        if not isinstance(ids, list):
            p.error("eligible_ids must be an array")
        allowed = {platform}
        if platform == "xiaohongshu":
            allowed.add("unknown_xhs_like")
        pool = []
        for eid in dict.fromkeys(ids):
            e = by_id.get(eid)
            if not e or e.get("status") != "candidate" or e.get("platform_hint") not in allowed:
                continue
            try:
                if eid not in bodies:
                    bodies[eid] = read_example(e, args.root)
                pool.append(eid)
            except (OSError, ValueError, KeyError) as exc:
                errors.append({"id": eid, "error": str(exc)})
        pools[sid] = pool
    history = read_json(args.history) if args.history.exists() else []
    if not isinstance(history, list) or not all(isinstance(x, str) for x in history):
        p.error("Invalid history; repair rather than silently discard")
    recent = set(history[-args.avoid_recent:]) if args.avoid_recent else set()
    chosen, relaxed = assignment(pools, recent)
    if chosen is None:
        print(json.dumps({"status":"insufficient_distinct_examples","candidate_counts":{k:len(v) for k,v in pools.items()},"errors":errors}, ensure_ascii=False))
        return 2
    selected = [{"slot_id":s["id"],"example_id":chosen[s["id"]],"source":by_id[chosen[s["id"]]]["source"],"start_line":by_id[chosen[s["id"]]]["start_line"],"end_line":by_id[chosen[s["id"]]]["end_line"],"format_quality":by_id[chosen[s["id"]]]["format_quality"],"raw_text":bodies[chosen[s["id"]]]} for s in slots]
    if not args.dry_run:
        atomic_json(args.history, (history + [e["example_id"] for e in selected])[-300:])
    print(json.dumps({"status":"ok","history_updated":not args.dry_run,"recent_exclusion_relaxed":relaxed,"reused_recent_ids":[e["example_id"] for e in selected if e["example_id"] in recent],"selected":selected,"errors":errors}, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
