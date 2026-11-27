#!/usr/bin/env python3
"""Select one complete writing reference per slot, never infer facts from references.
Input JSON: {"slots":[{"id":"xhs1","platform":"xiaohongshu","eligible_ids":["R001","G001"]}, ...]}.
Eligibility is determined by the caller from current verified facts and index hints.
Restricted fallback: each slot may supply restricted_reasons: {"example_id":"specific topic fit reason"}.
Restricted IDs must also be in eligible_ids. Regular candidates are exhausted first.
This tool selects and reads full text; it does not certify rights, suitability or publication.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import hashlib
import secrets
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEXES = [ROOT / "references/xiaohongshu-examples/index.json",
                   ROOT / "references/douyin-examples/index.json"]
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

def normalized_fingerprint(body):
    normalized = re.sub(r"[\W_]+", "", body, flags=re.UNICODE).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def prose_count(body):
    # Approved raw files contain one title,正文, then hashtags; metadata lives in index.
    lines = [line.strip() for line in body.splitlines() if line.strip() and line.strip() != "⠀"]
    prose = [line for line in lines[1:] if not line.startswith("#")]
    return len(re.sub(r"\s+", "", "\n".join(prose)).replace("⠀", ""))

def approved(entry, platform):
    q = entry.get("quality_review", {})
    return (entry.get("status") == "approved"
            and entry.get("selection_tier", "regular") == "regular"
            and q.get("decision") == "pass"
            and bool(q.get("reviewer")) and bool(q.get("reason"))
            and entry.get("format_quality") == "linebreaks_present"
            and entry.get("platform_hint") == platform
            and bool(entry.get("style_cluster"))
            and bool(entry.get("source_group"))
            and entry.get("rights_status") in ("authorized", "owned"))

def trial_eligible(entry, platform, restricted_reasons=None):
    t = entry.get("trial_use", {})
    tier = entry.get("selection_tier", "regular")
    reason = (restricted_reasons or {}).get(entry["id"])
    tier_ok = tier == "regular" or (tier == "restricted" and isinstance(reason, str) and bool(reason.strip()))
    return (tier_ok and entry.get("status") == "trial"
            and t.get("enabled") is True
            and t.get("authorized_by") == "user"
            and t.get("platform_pool") == platform
            and entry.get("format_quality") == "linebreaks_present"
            and bool(entry.get("style_cluster"))
            and bool(entry.get("source_group")))

def assignment(pools, recent, entries, fingerprints, max_restricted=0):
    rng = secrets.SystemRandom()
    order = sorted(pools, key=lambda slot: len(pools[slot]))
    def search(i, used, result, exclude_recent, strict_source):
        if i == len(order):
            return dict(result)
        slot = order[i]
        options = [v for v in pools[slot]
                   if v not in used and (not exclude_recent or v not in recent)
                   and (entries[v].get("selection_tier") != "restricted" or sum(entries[u].get("selection_tier") == "restricted" for u in used) < max_restricted)
                   and all(fingerprints[v] != fingerprints[u] for u in used)
                   and all(entries[v]["style_cluster"] != entries[u]["style_cluster"] for u in used)
                   and (not strict_source or all(entries[v]["source_group"] != entries[u]["source_group"] for u in used))]
        rng.shuffle(options)
        # Preserve randomness within groups while preferring fresh candidates.
        options.sort(key=lambda v: (entries[v].get('selection_tier') == 'restricted', entries[v].get('status') != 'approved', v in recent))
        for v in options:
            result[slot] = v
            found = search(i + 1, used | {v}, result, exclude_recent, strict_source)
            if found is not None:
                return found
            result.pop(slot, None)
        return None
    for strict_source, exclude_recent in ((True, True), (True, False), (False, True), (False, False)):
        chosen = search(0, set(), {}, exclude_recent, strict_source)
        if chosen is not None:
            return chosen, not exclude_recent, not strict_source
    return None, False, False

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
    p.add_argument("--index", type=Path, action="append", help="Custom index; repeat to combine. Defaults to the two platform pools.")
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    p.add_argument("--avoid-recent", type=int, default=10)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if args.avoid_recent < 0:
        p.error("--avoid-recent must be nonnegative")
    index_paths = args.index or DEFAULT_INDEXES
    entries = [entry for path in index_paths for entry in read_json(path)["entries"]]
    by_id = {e["id"]: e for e in entries}
    if len(by_id) != len(entries):
        p.error("Duplicate example IDs")
    req = read_json(args.request)
    slots = req["slots"]
    if not isinstance(slots, list) or not 1 <= len(slots) <= 6:
        p.error("Expected 1 to 6 slots")
    pools = {}
    bodies = {}
    fingerprints = {}
    errors = []
    for slot in slots:
        sid, platform = slot["id"], slot["platform"]
        if sid in pools or platform not in ("xiaohongshu", "douyin"):
            p.error("Duplicate slot ID or invalid platform")
        ids = slot["eligible_ids"]
        if not isinstance(ids, list):
            p.error("eligible_ids must be an array")
        restricted_reasons = slot.get("restricted_reasons", {})
        if not isinstance(restricted_reasons, dict) or not all(isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in restricted_reasons.items()):
            p.error("restricted_reasons must map IDs to nonempty topic-fit explanations")
        pool = []
        for eid in dict.fromkeys(ids):
            e = by_id.get(eid)
            if not e or not (approved(e, platform) or trial_eligible(e, platform, restricted_reasons)):
                continue
            try:
                if eid not in bodies:
                    bodies[eid] = read_example(e, args.root)
                    fingerprints[eid] = normalized_fingerprint(bodies[eid])
                if prose_count(bodies[eid]) > 0:
                    pool.append(eid)
            except (OSError, ValueError, KeyError) as exc:
                errors.append({"id": eid, "error": str(exc)})
        pools[sid] = pool
    history = read_json(args.history) if args.history.exists() else []
    if not isinstance(history, list) or not all(isinstance(x, str) for x in history):
        p.error("Invalid history; repair rather than silently discard")
    recent = set(history[-args.avoid_recent:]) if args.avoid_recent else set()
    approved_pools = {k: [v for v in vs if by_id[v].get('status') == 'approved'] for k, vs in pools.items()}
    chosen, relaxed, source_relaxed = assignment(approved_pools, recent, by_id, fingerprints)
    if chosen is None:
        regular_pools = {k: [v for v in vs if by_id[v].get("selection_tier") != "restricted"] for k, vs in pools.items()}
        chosen, relaxed, source_relaxed = assignment(regular_pools, recent, by_id, fingerprints)
    if chosen is None:
        for limit in range(1, len(slots) + 1):
            chosen, relaxed, source_relaxed = assignment(pools, recent, by_id, fingerprints, max_restricted=limit)
            if chosen is not None:
                break
    if chosen is None:
        print(json.dumps({"status":"insufficient_eligible_diverse_examples","candidate_counts":{k:len(v) for k,v in pools.items()},"errors":errors}, ensure_ascii=False))
        return 2
    selected = [{"slot_id":s["id"],"example_id":chosen[s["id"]],"reference_status":by_id[chosen[s["id"]]]["status"],"selection_tier":by_id[chosen[s["id"]]].get("selection_tier","regular"),"restricted_fit_reason":s.get("restricted_reasons",{}).get(chosen[s["id"]]) if by_id[chosen[s["id"]]].get("selection_tier")=="restricted" else None,"rights_status":by_id[chosen[s["id"]]].get("rights_status","unverified"),"source":by_id[chosen[s["id"]]]["source"],"start_line":by_id[chosen[s["id"]]]["start_line"],"end_line":by_id[chosen[s["id"]]]["end_line"],"format_quality":by_id[chosen[s["id"]]]["format_quality"],"style_cluster":by_id[chosen[s["id"]]]["style_cluster"],"source_group":by_id[chosen[s["id"]]]["source_group"],"reference_prose_chars":prose_count(bodies[chosen[s["id"]]]),"raw_text":bodies[chosen[s["id"]]]} for s in slots]
    if not args.dry_run:
        atomic_json(args.history, (history + [e["example_id"] for e in selected])[-300:])
    print(json.dumps({"status":"ok","history_updated":not args.dry_run,"recent_exclusion_relaxed":relaxed,"source_diversity_relaxed":source_relaxed,"reused_recent_ids":[e["example_id"] for e in selected if e["example_id"] in recent],"selected":selected,"errors":errors}, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
