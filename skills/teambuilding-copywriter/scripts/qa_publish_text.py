#!/usr/bin/env python3
"""Check user-facing copy for internal jargon and likely marketing-format leaks.

Usage: python qa_publish_text.py 文案.txt

Deterministic text QA, NOT factual or platform compliance certification.
Run on final copy. Python standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

MARKED_VERSION = re.compile(
    r"<<<VERSION_START:([^>]+)>>>\s*(.*?)\s*<<<VERSION_END>>>", re.S
)
LEAK_TERMS = (
    "全要素", "服务矩阵", "项目标的", "方案定位",
    "综合服务", "咨询方式",
)
BROCHURE_HEADING = re.compile(
    r"(?m)^\s*(?:[一二三四五六七八九十]+[、.]|[0-9]+[.、])"
    r"\s*(?:交通保障|住宿配套|餐饮体验|综合服务|咨询方式|服务矩阵|全要素)"
)
CTA = re.compile(
    r"(?:私信(?:我|获取|咨询)?|加微信|加微\b|留言(?:人数|预算)|"
    r"留[【\[]?\s*人数\s*[+＋和与/]\s*预算|"
    r"领取(?:完整版|专属|详细)?方案|获取(?:完整|专属|详细)?方案|" 
    r"【(?:团建\s*[+＋]\s*)?人数】\s*(?:get|获取|免费)|"
    r"(?:免费\s*get\s*(?:方案|策划|执行))|(?:1\s*[vV]\s*1\s*策划))",
    re.IGNORECASE,
)
# Commercial CTA edition is allowed to use an explicit *on-platform* service request.
# Manual business/industry permissions and actual tool availability must still be verified.
COMMERCIAL_CTA_VERSION = "小红书｜强CTA转化版"
BANNED_EXTERNAL_OR_BAIT = re.compile(
    r"(?:微\s*信|[Ww][Xx](?:号)?|加[Vv]|手机号|联系电话|二维码|扫码|"
    r"免费\s*get|【(?:团建\s*[+＋]\s*)?人数】\s*(?:get|获取)|"
    r"评论(?:区)?\s*(?:扣|打|留)\s*[1１]|全包执行|"
    r"(?:加微信|加微\b)|(?:留|留下)\s*(?:微信|电话|手机号))",
    re.IGNORECASE,
)
# Manual business qualification and the actual permitted contact route require human review.
# Strong conversion is a semantic writing goal, NOT a mandatory DM keyword.
# Reject the disfavored formula without requiring a replacement buzzword.
FIXED_DM_CLICHE = re.compile(
    r"直接\s*私信\s*我|"
    r"本账号已开通的官方站内咨询入口"
)
NON_CONVERSION_SALES_HOOK = re.compile(
    r"站内聊聊|聊聊人数|找我聊|问我就行|"
    r"(?:团建|年会|公司活动).{0,24}(?:还没定|没头绪|想怎么安排).{0,40}(?:聊聊|找我|问我|咨询|帮你)"
)
STIFF_CTA = re.compile(
    r"本账号已开通的官方站内咨询入口|"
    r"进一步沟通实际可提供的活动策划内容|"
    r"本账号已开通.{0,30}(?:咨询入口|服务入口)"
)

EVIDENCE_REVIEW = re.compile(
    r"(?:\d+\s*座(?:正规)?大巴|\d+(?:万|万元?)保额|"
    r"\d+\s*[-—–~至]\s*\d+\s*人(?:皆可定制|可定制|定制|可接)|"
    r"全地暖|中央空调|天然私汤|专属(?:资深)?(?:领队|教练)|"
    r"全程高清抓拍|全额高速|含(?:雪板|雪鞋|雪杖))"
)


# User rejected these repeated filler constructions in the Tonglu test.
# This is an editorial warning gate, not an AI-authorship classifier.
AI_FILLER = {
    "everyone_same": re.compile(r"(?:不必|不用|没必要|不需要|不强求)(?:让|要求)?所有人(?:都|全程)?|不(?:用|必|需要|强求)全员(?:都|统一|全程)"),
    "fill_schedule": re.compile(r"(?:不用|不必|没必要|不需要|别|不要)(?:把)?(?:所有|全部|每样|每个|一天)?[^。！？\n]{0,12}(?:塞满|都安排|全部安排|都塞进去)|(?:不用|不必|没必要)全部(?:都)?(?:安排|塞满|体验)"),
    "lively_quiet": re.compile(r"想(?:热闹|动|安静|放松|歇|慢下来)[^。！？\n]{0,28}[，；、：][^。！？\n]{0,12}想(?:热闹|动|安静|放松|歇|慢下来)"),
    "not_more_better": re.compile(r"(?:项目|玩法|活动|体验)(?:数量)?(?:并)?不(?:是|一定)越多越好"),
    "rhythm_cliche": re.compile(r"(?:把|让)(?:整个|活动|一天的|一天|下午的)?节奏(?:慢慢)?(?:收回来|放慢|降下来)|给不同(?:体力|偏好|兴趣)[^。！？\n]{0,12}留(?:出|点)?(?:选择|空间)"),
}

def editorial_patterns(prose: str) -> dict:
    return {key: len(rx.findall(prose)) for key, rx in AI_FILLER.items() if rx.search(prose)}


# Only explicit line-leading time entries; alternatives and day headings reset the sequence.
TIME_ENTRY = re.compile(r"^\s*(?:[^\w\s]{1,5}\s*)?(\d{1,2})[:：](\d{2})(?:\s*[-—–~至]\s*(\d{1,2})[:：](\d{2}))?\s*[｜|、:：\-—]?\s*(.*)$")
DAY_OR_BRANCH = re.compile(r"^\s*[^\w\s]*(?:day\s*[1-9]|d[1-9]|第[一二三四五六七八九\d]+天|次日|翌日|[ab]\s*(?:线|方案)|方案[一二三四\d])", re.I)

def itinerary_checks(prose):
    errors, warnings = [], []
    prev = None
    for raw in prose.splitlines():
        line = unicodedata.normalize("NFKC", raw).replace("❶", "1").replace("❷", "2").replace("❸", "3").replace("❹", "4")
        if DAY_OR_BRANCH.match(line):
            prev = None
            continue
        m = TIME_ENTRY.match(line)
        if not m:
            continue
        h, minute = int(m[1]), int(m[2])
        if h > 23 or minute > 59:
            errors.append("FAIL_INVALID_CLOCK: " + raw)
            continue
        start = h * 60 + minute
        end = None
        if m[3] is not None:
            eh, em = int(m[3]), int(m[4])
            if eh > 23 or em > 59:
                errors.append("FAIL_INVALID_CLOCK: " + raw)
                continue
            end = eh * 60 + em
            if end <= start:
                errors.append("FAIL_REVERSED_TIME_RANGE: " + raw)
        desc = m[5]
        if prev:
            old_start, old_end, old_desc, old_raw = prev
            gap = start - old_start
            if gap <= 0:
                errors.append("FAIL_TIME_ORDER: " + old_raw + " -> " + raw)
            elif old_end is not None and start < old_end:
                errors.append("FAIL_TIME_OVERLAP: " + old_raw + " -> " + raw)
            elif gap < 15:
                warnings.append("REVIEW_SHORT_INTERVAL: " + old_raw + " -> " + raw)
            if gap > 0:
                if re.search(r"午餐|晚餐|正餐|午宴|晚宴|聚餐|吃饭|鱼头宴|烧烤BBQ", old_desc) and gap < 45:
                    warnings.append("REVIEW_MEAL_DURATION: " + old_raw + " -> " + raw)
                if re.search(r"徒步|爬山|登山", old_desc) and gap < 60:
                    warnings.append("REVIEW_HIKING_DURATION: " + old_raw + " -> " + raw)
                if re.search(r"睡觉|就寝|入睡", desc) and 360 <= start < 1080 and not re.search(r"午睡|午休", desc):
                    warnings.append("REVIEW_DAYTIME_SLEEP: " + raw)
        prev = (start, end, desc, raw)
    return errors, warnings


def extract(content: str) -> list[tuple[str, str]]:
    blocks = MARKED_VERSION.findall(content)
    if blocks:
        return [(name.strip(), body.strip()) for name, body in blocks]
    content = re.sub(r"(?m)^\s*\x60{3}(?:text|markdown)?\s*$", "", content)
    content = re.sub(r"(?m)^\s*\x60{3}\s*$", "", content)
    return [("单篇发布稿", content.strip())]


def check(text: str) -> dict:
    records = []
    pattern_records = []
    for name, body in extract(text):
        errors = []
        for token in LEAK_TERMS:
            if token in body:
                errors.append(f"FAIL_INTERNAL_TERM_LEAK: {token}")
        if BROCHURE_HEADING.search(body):
            errors.append("FAIL_BROCHURE_HEADING: tender/PPT style heading")
        is_commercial_cta = name == COMMERCIAL_CTA_VERSION
        # Only inspect prose, not hashtags, when checking the closing action.
        prose = body.split("#", 1)[0]
        closing = next((line.strip() for line in reversed(prose.splitlines())
                        if line.strip() and line.strip() != "⠀"), "")
        if not is_commercial_cta and (
            CTA.search(body) or NON_CONVERSION_SALES_HOOK.search(closing)
        ):
            errors.append("FAIL_CTA_LEAK_OTHER_VERSIONS: default five drafts must not contain unapproved sales hooks")
        if BANNED_EXTERNAL_OR_BAIT.search(body):
            errors.append("FAIL_EXTERNAL_OR_BAIT_CTA: off-platform contact, comment code, or unsupported sales promise")
        if is_commercial_cta:
            if FIXED_DM_CLICHE.search(body):
                errors.append("FAIL_TEMPLATE_CTA: no hardcoded direct-DM formula or platform-style CTA")
            if STIFF_CTA.search(body):
                errors.append("FAIL_STIFF_CTA: platform qualification/official-entry instructions leaked into public-facing copy")

        title = next((line.strip() for line in body.splitlines() if line.strip()), "")
        if len(title) > 20 and "小红书" in name:
            errors.append(f"FAIL_XHS_TITLE_LENGTH: {len(title)} code points")
        time_errors, time_warnings = itinerary_checks(prose)
        errors.extend(time_errors)
        warnings = time_warnings
        patterns = editorial_patterns(prose)
        pattern_records.append(patterns)
        for key, count in patterns.items():
            warnings.append(f"REVIEW_AI_FILLER: {key} ({count}); delete generic filler or justify concrete reader value")
        if sum(patterns.values()) >= 2:
            errors.append("FAIL_REPEATED_FILLER: multiple stock constructions in one draft")
        if is_commercial_cta:
            warnings.append(
                "REVIEW_BUSINESS_QUALIFICATION: confirm industry permissions, commercial disclosure and permitted contact routes before publishing"
            )
            warnings.append(
                "REVIEW_CTA_CONTEXT: manual review of context-specific CTA strength; no fixed DM keyword required"
            )
        if EVIDENCE_REVIEW.search(body):
            warnings.append(
                "REVIEW_EVIDENCE: specific service, facilities, capacity or inclusion claims"
            )
        records.append({
            "version": name, "title": title, "accepted": not errors,
            "errors": errors, "warnings": warnings,
        })
    repeated = sorted(key for key in AI_FILLER if sum(key in p for p in pattern_records) >= 2)
    if repeated:
        for record, patterns in zip(records, pattern_records):
            for key in repeated:
                if key in patterns:
                    record["errors"].append(f"FAIL_BATCH_STYLE_REPETITION: {key}")
            record["accepted"] = not record["errors"]
    return {
        "accepted": all(x["accepted"] for x in records),
        "repeated_pattern_families": repeated,
        "versions": records,
        "scope": "textual style and itinerary screening only; manual geography, duration, fact and platform validation required",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    result = check(args.file.read_text(encoding="utf-8-sig"))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
