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
# The public closing line should sound human. An official tool/qualification check
# happens outside copy; this text-only checker cannot verify the account's permissions.
STRONG_CTA_ACTION = re.compile(
    r"(?:团建|年会|企业活动).{0,100}(?:聊聊|聊一聊|咨询|问问|说说|来聊|私信)"
    r"|(?:聊聊|聊一聊|咨询|问问|说说|来聊|私信).{0,100}(?:团建|年会|企业活动)"
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


def extract(content: str) -> list[tuple[str, str]]:
    blocks = MARKED_VERSION.findall(content)
    if blocks:
        return [(name.strip(), body.strip()) for name, body in blocks]
    content = re.sub(r"(?m)^\s*\x60{3}(?:text|markdown)?\s*$", "", content)
    content = re.sub(r"(?m)^\s*\x60{3}\s*$", "", content)
    return [("单篇发布稿", content.strip())]


def check(text: str) -> dict:
    records = []
    for name, body in extract(text):
        errors = []
        for token in LEAK_TERMS:
            if token in body:
                errors.append(f"FAIL_INTERNAL_TERM_LEAK: {token}")
        if BROCHURE_HEADING.search(body):
            errors.append("FAIL_BROCHURE_HEADING: tender/PPT style heading")
        is_commercial_cta = name == COMMERCIAL_CTA_VERSION
        if CTA.search(body) and not is_commercial_cta:
            errors.append("FAIL_STRONG_CTA: direct solicitation outside the qualified business variant")
        if BANNED_EXTERNAL_OR_BAIT.search(body):
            errors.append("FAIL_EXTERNAL_OR_BAIT_CTA: off-platform contact, comment code, or unsupported sales promise")
        if is_commercial_cta:
            # CTA should be in the last prose section before the hashtags.
            prose = body.split("#", 1)[0]
            closing = next((line.strip() for line in reversed(prose.splitlines())
                            if line.strip() and line.strip() != "⠀"), "")
            if not STRONG_CTA_ACTION.search(closing):
                errors.append("FAIL_WEAK_STRONG_CTA: closing must ask a team-building lead to take one clear conversational action")
            if STIFF_CTA.search(body):
                errors.append("FAIL_STIFF_CTA: platform qualification/official-entry instructions leaked into public-facing copy")
        title = next((line.strip() for line in body.splitlines() if line.strip()), "")
        if len(title) > 20 and "小红书" in name:
            errors.append(f"FAIL_XHS_TITLE_LENGTH: {len(title)} code points")
        warnings = []
        if is_commercial_cta:
            warnings.append(
                "REVIEW_BUSINESS_QUALIFICATION: confirm real industry permissions, disclosure and an enabled official on-platform consultation entry before publishing"
            )
        if EVIDENCE_REVIEW.search(body):
            warnings.append(
                "REVIEW_EVIDENCE: specific service, facilities, capacity or inclusion claims"
            )
        records.append({
            "version": name, "title": title, "accepted": not errors,
            "errors": errors, "warnings": warnings,
        })
    return {
        "accepted": all(x["accepted"] for x in records),
        "versions": records,
        "scope": "textual term/style checks only; not fact or platform validation",
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
