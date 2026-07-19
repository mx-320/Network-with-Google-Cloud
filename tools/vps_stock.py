#!/usr/bin/env python3
"""Read-only stock monitor for US VPS offers.

The monitor never logs in or adds an item to a cart.  It reports ``blocked``
when a provider's anti-bot page prevents an inventory check.
"""

from __future__ import annotations

import argparse
from html import unescape
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from itertools import chain
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree


def _external_command_env() -> Dict[str, str]:
    env = os.environ.copy()
    command_paths = [
        str(Path.home() / ".npm-global" / "bin"),
        str(Path.home() / ".local" / "bin"),
        "/usr/local/bin",
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
    ]
    command_paths.extend(env.get("PATH", "").split(os.pathsep))
    env["PATH"] = os.pathsep.join(dict.fromkeys(path for path in command_paths if path))
    return env


PROVIDERS: List[Dict[str, Any]] = [
    {
        "id": "buyvm-lv",
        "provider": "BuyVM",
        "region": "Las Vegas, US",
        "kind": "frantech_html",
        "url": "https://my.frantech.ca/cart.php?gid=37",
        "priority": "value",
        "network": "standard US West",
        "focus": True,
    },
    {
        "id": "buyvm-ny",
        "provider": "BuyVM",
        "region": "New York, US",
        "kind": "frantech_html",
        "url": "https://my.frantech.ca/cart.php?gid=38",
        "priority": "value",
        "network": "standard US East",
        "focus": True,
    },
    {
        "id": "buyvm-miami",
        "provider": "BuyVM",
        "region": "Miami, US",
        "kind": "frantech_html",
        "url": "https://my.frantech.ca/cart.php?gid=48",
        "priority": "value",
        "network": "standard US East",
        "focus": True,
    },
    {
        "id": "buyvm-switzerland",
        "provider": "BuyVM",
        "region": "Switzerland",
        "kind": "frantech_html",
        "url": "https://my.frantech.ca/cart.php?gid=39",
        "priority": "value",
        "network": "standard Europe",
        "focus": True,
    },
    {
        "id": "greencloud-store",
        "provider": "GreenCloud",
        "region": "US / Canada / Europe / Asia",
        "kind": "counted_html",
        "url": "https://greencloudvps.com/billing/store/",
        "fetch_url": "https://r.jina.ai/https://greencloudvps.com/billing/store/",
        "plan_prefixes": ["BudgetKVM"],
        "priority": "value",
        "network": "multi-location budget KVM",
        "focus": True,
    },
    {
        "id": "colocrossing-cloud-vps-1gb",
        "provider": "ColoCrossing",
        "region": "Multi-location; prefer Los Angeles if offered",
        "kind": "colocrossing_markdown",
        "url": "https://cloud.colocrossing.com/index.php?rp=/store/cloud-virtual-private-servers/1gb-ram",
        "fetch_url": "https://r.jina.ai/https://cloud.colocrossing.com/index.php?rp=/store/cloud-virtual-private-servers/1gb-ram",
        "plan_name": "Cloud Virtual Private Servers - 1GB RAM",
        "target_price": 3.95,
        "priority": "value",
        "network": "China optimization unconfirmed; await provider reply before purchase",
        "focus": True,
    },
    {
        "id": "colocrossing-cloud-vps-2gb",
        "provider": "ColoCrossing",
        "region": "Multi-location; prefer Los Angeles if offered",
        "kind": "colocrossing_markdown",
        "url": "https://cloud.colocrossing.com/index.php?rp=/store/cloud-virtual-private-servers/2gb-ram",
        "fetch_url": "https://r.jina.ai/https://cloud.colocrossing.com/index.php?rp=/store/cloud-virtual-private-servers/2gb-ram",
        "plan_name": "Cloud Virtual Private Servers - 2GB RAM",
        "target_price": 6.95,
        "priority": "value",
        "network": "China optimization unconfirmed; await provider reply before purchase",
        "focus": True,
    },
    {
        "id": "novixlink-ntt-isp-vps",
        "provider": "NovixLink",
        "region": "Los Angeles, US",
        "kind": "novixlink_markdown",
        "url": "https://novixlink.com/store/nttispipvps",
        "fetch_url": "https://r.jina.ai/http://novixlink.com/store/nttispipvps",
        "priority": "cn2",
        "network": "AS9929 / CMIN2 three-network optimized, NTT dual residential ISP",
        "focus": True,
    },
    {
        "id": "novixlink-gtt-isp-vps",
        "provider": "NovixLink",
        "region": "Los Angeles, US",
        "kind": "novixlink_markdown",
        "url": "https://novixlink.com/store/us-lacup-isp",
        "fetch_url": "https://r.jina.ai/http://novixlink.com/store/us-lacup-isp",
        "priority": "cn2",
        "network": "AS9929 / CMIN2 three-network optimized, GTT dual residential ISP",
        "focus": True,
    },
    {
        "id": "dmit-x",
        "provider": "DMIT",
        "region": "US / Japan / Hong Kong",
        "kind": "twitter_search",
        "url": "https://x.com/search?q=DMIT",
        "twitter_query": "DMIT",
        "twitter_keywords": ["dmit"],
        "twitter_official": False,
        "priority": "cn2",
        "network": "community X restock/promotion leads; verify before purchase",
        "focus": True,
    },
    {
        "id": "hostdare-lax-cn2",
        "provider": "HostDare",
        "region": "Los Angeles, US",
        "kind": "counted_html",
        "url": "https://bill.hostdare.com/store/premium-china-optimized-nvme-kvm",
        "fetch_url": "https://r.jina.ai/https://bill.hostdare.com/store/premium-china-optimized-nvme-kvm",
        "plan_prefixes": ["CSSD"],
        "priority": "cn2",
        "network": "CN2 GIA / CU / CM optimized",
        "focus": True,
    },
    {
        "id": "hostdare-lax-cn2-amd",
        "provider": "HostDare",
        "region": "Los Angeles, US",
        "kind": "counted_html",
        "url": "https://bill.hostdare.com/store/premium-china-optimized-amd-kvm-vps-usa",
        "fetch_url": "https://r.jina.ai/https://bill.hostdare.com/store/premium-china-optimized-amd-kvm-vps-usa",
        "plan_prefixes": ["CAMD"],
        "priority": "cn2",
        "network": "CN2 GIA / CU / CM optimized",
        "focus": True,
    },
    {
        "id": "hostdare-lax-cn2-hdd",
        "provider": "HostDare",
        "region": "Los Angeles, US",
        "kind": "counted_html",
        "url": "https://bill.hostdare.com/store/premium-china-optimized-kvm-vps",
        "fetch_url": "https://r.jina.ai/https://bill.hostdare.com/store/premium-china-optimized-kvm-vps",
        "plan_prefixes": ["CKVM"],
        "priority": "cn2",
        "network": "CN2 GIA / CU / CM optimized",
        "focus": True,
    },
    {
        "id": "bwh-lax-cn2",
        "provider": "BWH",
        "region": "Los Angeles, US",
        "kind": "bwh_json",
        "url": "https://bandwagonhost.com/vps-hosting.php",
        "fetch_url": "https://bandwagonhost.com/order/get-data",
        "tiers": ["ecommerce", "ecommerce-sla-elevated"],
        "datacenters": ["USCA_5", "USCA_6", "USCA_9"],
        "priority": "cn2",
        "network": "CN2 GIA / CTGNet / CMIN2 / CU premium",
        "focus": True,
    },
    {
        "id": "zgovps-lax-special-52",
        "provider": "ZgoVPS",
        "region": "Los Angeles, US",
        "kind": "whmcs_offer_html",
        "url": "https://clients.zgovps.com/index.php?/cart/special-offer/",
        "plan_name": "Los Angeles AMD Optimised VPS - Specials - Starter",
        "target_price": 52.0,
        "target_period": "year",
        "priority": "cn2",
        "network": "GIA / 9929 / CMIN2, China Premium Optimised",
        "focus": True,
    },
    {
        "id": "zgovps-lax-optimized-starter-18-quarterly",
        "provider": "ZgoVPS",
        "region": "Los Angeles, US",
        "kind": "whmcs_offer_html",
        "url": "https://clients.zgovps.com/index.php?/cart/los-angeles-amd-optimised-vps/",
        "plan_name": "Starter",
        "target_price": 18.0,
        "target_period": "quarter",
        "priority": "cn2",
        "network": "GIA / 9929 / CMIN2, China Premium Optimised",
        "focus": True,
    },
    {
        "id": "zgovps-hkg-special-52",
        "provider": "ZgoVPS",
        "region": "Hong Kong",
        "kind": "whmcs_offer_html",
        "url": "https://clients.zgovps.com/index.php?/cart/special-offer/",
        "plan_name": "HongKong AMD VPS - Specials - Starter",
        "target_price": 52.0,
        "target_period": "year",
        "priority": "value",
        "network": "BGP, China Optimised",
        "focus": True,
    },
    {
        "id": "dedione-lax-cmin2-1c1g10g-annual",
        "provider": "DediOne",
        "region": "Los Angeles, US",
        "kind": "dedione_html",
        "url": "https://dedione.com/store/los-angeles-kvm-vps-cmin2-cuii",
        "plan_name": "LAX.VPS.CMIN2.1C1G10G-Annual",
        "target_price": 29.99,
        "target_period": "year",
        "priority": "cn2",
        "network": "CMIN2 / AS58807 for China Mobile; CUII / AS9929 for China Unicom; no CN2",
        "focus": True,
    },
]


_SOCIAL_BRANDS: List[Dict[str, Any]] = [
    {
        "id": "dmit",
        "provider": "DMIT",
        "region": "US / Japan / Hong Kong",
        "priority": "cn2",
        "network": "community Reddit sale and restock leads; verify before purchase",
        "query": "DMIT",
        "keywords": ["dmit"],
        "sources": ["reddit"],
        "focus": True,
    },
    {
        "id": "racknerd",
        "provider": "RackNerd",
        "region": "Los Angeles, US",
        "priority": "value",
        "network": "community social sale and restock leads; verify before purchase",
        "query": "RackNerd",
        "keywords": ["racknerd", "rack nerd"],
        "sources": ["x", "reddit"],
        "focus": True,
    },
    {
        "id": "cloudcone",
        "provider": "CloudCone",
        "region": "Los Angeles, US",
        "priority": "value",
        "network": "community social sale and restock leads; verify before purchase",
        "query": "CloudCone",
        "keywords": ["cloudcone", "cloud cone"],
        "sources": ["x", "reddit"],
        "focus": True,
    },
]

SOCIAL_PROVIDERS: List[Dict[str, Any]] = []
for _brand in _SOCIAL_BRANDS:
    for _source in _brand["sources"]:
        SOCIAL_PROVIDERS.append(
            {
                "id": "%s-%s" % (_brand["id"], _source),
                "provider": _brand["provider"],
                "region": _brand["region"],
                "kind": "%s_search" % ("twitter" if _source == "x" else "reddit"),
                "url": "https://x.com/search?q=%s" % _brand["query"] if _source == "x" else "https://www.reddit.com/search/?q=%s" % _brand["query"],
                "%s_query" % ("twitter" if _source == "x" else "reddit"): _brand["query"],
                "%s_keywords" % ("twitter" if _source == "x" else "reddit"): _brand["keywords"],
                "priority": _brand["priority"],
                "network": _brand["network"],
                "focus": _brand["focus"],
            }
        )


_DISCOVERY_QUERIES = (
    ("vps-restock", "VPS restock", "value"),
    ("vps-sale", "VPS sale", "value"),
    ("cn2-vps", "CN2 VPS", "cn2"),
    ("cheap-vps", "cheap VPS", "value"),
)
DISCOVERY_PROVIDERS: List[Dict[str, Any]] = []
for _query_id, _query, _priority in _DISCOVERY_QUERIES:
    for _source in ("reddit", "x"):
        DISCOVERY_PROVIDERS.append(
            {
                "id": "vps-discovery-%s-%s" % (_source, _query_id),
                "provider": "VPS discovery",
                "region": "global",
                "kind": "%s_discovery" % ("reddit" if _source == "reddit" else "twitter"),
                "url": (
                    "https://www.reddit.com/search/?%s" % urlencode({"q": _query})
                    if _source == "reddit"
                    else "https://x.com/search?%s" % urlencode({"q": _query})
                ),
                "%s_query" % ("reddit" if _source == "reddit" else "twitter"): _query,
                "priority": _priority,
                "network": "community discovery leads; verify before purchase",
                "focus": True,
            }
        )


def fetch(url: str, timeout: int = 20) -> Tuple[int, str]:
    request = Request(url, headers={"User-Agent": "network-node-vps-stock/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        return int(exc.code), body
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(str(exc)) from exc


def _base_result(provider: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": provider["id"],
        "provider": provider["provider"],
        "region": provider["region"],
        "priority": provider["priority"],
        "network": provider["network"],
        "source": provider["url"],
        "checked_via": provider.get("fetch_url", provider["url"]),
        "status": "unknown",
        "confidence": "none",
        "plans": [],
        "reason": "",
        "checked_at": int(time.time()),
    }


_COUNTED_PLAN = re.compile(
    r"(?P<plan>[A-Za-z][A-Za-z0-9._-]{2,64})\s+(?P<count>\d+)\s+"
    r"(?P<label>Available|Disponible|可用|Dostupne|Saadaval)",
    re.IGNORECASE,
)
_NOVIXLINK_PLAN = re.compile(r"(?m)^###\s+(?P<plan>LAX-[^\n]+)\s*$")
_NOVIXLINK_CAD_PRICE = re.compile(r"\$\s*(?P<amount>\d+(?:\.\d+)?)\s*CAD\b", re.IGNORECASE)
_NOVIXLINK_USD_PRICE = re.compile(r"~\s*\$\s*(?P<amount>\d+(?:\.\d+)?)\s*USD\b", re.IGNORECASE)

_TWITTER_POSITIVE = ("coupon", "sale", "discount", "promo", "restock", "in stock", "available", "优惠", "折扣", "优惠码", "补货", "有货", "上架", "开售")
_TWITTER_NEGATIVE = ("out of stock", "sold out", "unavailable", "无货", "缺货", "断货", "售罄", "抢空")
_SOCIAL_AD_TERMS = (
    "affiliate", "referral", "invite code", "invite link", "coupon code", "promo code", "discount code",
    "邀请码", "优惠码", "推广", "推广链接", "传送门", "购买链接", "充值", "返利", "返现", "交流群",
)
SOCIAL_LOOKBACK_DAYS = 3

_DISCOVERY_SIGNAL_TERMS = _TWITTER_POSITIVE + ("deal", "offer", "低价", "特价")
_DISCOVERY_NOISE_TERMS = (
    "referral", "affiliate", "invite code", "invite link", "邀请码", "返利", "推广链接",
    "传送门", "闭眼冲", "购买链接", "推广",
)
_DISCOVERY_OFF_TOPIC_TERMS = (
    "forex", "copy trading", "serverless", "lambda", "cloud functions", "crypto", "blockchain",
    "robinhood chain", "tokenized stocks", "email scraper", "lead generation", "cold outreach",
)
_DISCOVERY_KNOWN_PROVIDER_TERMS = (
    "dmit", "bandwagonhost", "搬瓦工", "racknerd", "cloudcone", "buyvm", "greencloud", "hostdare", "zgovps",
)
_DISCOVERY_VPS_CONTEXT = re.compile(r"\b(?:vps|vds|kvm|virtual private server|virtual server)\b|虚拟服务器|云服务器|云主机", re.IGNORECASE)
_DISCOVERY_NEGATED_VPS = re.compile(r"(?:no|without|无需|不需要)\s+(?:a\s+)?vps\b", re.IGNORECASE)
_DISCOVERY_ROUTE_TERMS = (
    ("CN2 GIA", ("cn2 gia",)),
    ("CN2", ("cn2",)),
    ("CTGNet", ("ctgnet",)),
    ("CMIN2", ("cmin2",)),
    ("9929", ("9929",)),
    ("China optimized", ("china optimized", "china-optimized", "中国优化")),
    ("three-network", ("three network", "three-network", "三网")),
)
_DISCOVERY_LOCATION_TERMS = (
    ("Los Angeles", ("los angeles", "la, us", "洛杉矶")),
    ("Hong Kong", ("hong kong", "香港")),
    ("New York", ("new york", "纽约")),
    ("Tokyo", ("tokyo", "东京")),
    ("Singapore", ("singapore", "新加坡")),
    ("Japan", ("japan", "日本")),
)
_DISCOVERY_RESOURCE = re.compile(
    r"\b(?:\d+(?:\.\d+)?\s*(?:gb|tb|mb|gbit|mbps|tbps)|\d+\s*(?:v?cpu|core)|nvme|ssd|kvm|traffic|bandwidth)\b",
    re.IGNORECASE,
)
_DISCOVERY_PRICE = re.compile(
    r"(?P<currency>[$€£])?\s*(?P<amount>\d+(?:\.\d+)?)\s*"
    r"(?P<code>USD|EUR|GBP)?\s*(?:/|per\s+)?"
    r"(?P<period>month|monthly|mo|m|year|yearly|annual|annually|yr|y)\b",
    re.IGNORECASE,
)
_DISCOVERY_GENERIC_WORDS = {
    "cheap", "china", "cn2", "cn2gia", "deal", "discount", "hosting", "new",
    "offer", "provider", "restock", "sale", "server", "stock", "vds", "vps",
}


class _FrantechPackageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.plan = ""
        self.plans: List[Dict[str, Any]] = []
        self._capture_plan = False
        self._capture_qty = False
        self._capture_price = False
        self._plan_text: List[str] = []
        self._qty_text: List[str] = []
        self._price_text: List[str] = []
        self.price: Optional[Dict[str, Any]] = None

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        classes = set(dict(attrs).get("class", "").split())
        if tag == "h3" and "package-name" in classes:
            self._capture_plan = True
            self._plan_text = []
            self.price = None
        elif tag == "div" and "package-qty" in classes:
            self._capture_qty = True
            self._qty_text = []
        elif tag == "div" and "price" in classes:
            self._capture_price = True
            self._price_text = []

    def handle_data(self, data: str) -> None:
        if self._capture_plan:
            self._plan_text.append(data)
        if self._capture_qty:
            self._qty_text.append(data)
        if self._capture_price:
            self._price_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h3" and self._capture_plan:
            self.plan = " ".join("".join(self._plan_text).split())
            self._capture_plan = False
        elif tag == "div" and self._capture_qty:
            match = re.search(r"(?P<count>\d+)\s+Available", " ".join(self._qty_text), re.IGNORECASE)
            if self.plan and match:
                count = int(match.group("count"))
                plan = {"plan": self.plan, "count": count, "available": count > 0}
                if self.price:
                    self.price["monthly_equivalent"] = self.price["amount"]
                    self.price["price_eligible"] = self.price["amount"] <= 12
                    plan["price"] = self.price
                self.plans.append(plan)
            self.plan = ""
            self._capture_qty = False
        elif tag == "div" and self._capture_price:
            raw = " ".join(" ".join(self._price_text).split())
            match = re.search(r"(?P<currency>[$€£]|[A-Z]{3})\s*(?P<amount>\d+(?:\.\d+)?)\s*(?:[A-Z]{3})?.*?/(?P<period>mo|month|yr|year)", raw, re.IGNORECASE)
            if match:
                currency = {"$": "USD", "€": "EUR", "£": "GBP"}.get(match.group("currency"), match.group("currency").upper())
                period = match.group("period").lower()
                self.price = {
                    "amount": float(match.group("amount")),
                    "currency": currency,
                    "period": "month" if period in ("mo", "month") else "year",
                }
            self._capture_price = False


def _discovery_post_text(post: Dict[str, Any], source: str) -> str:
    if source == "x":
        return str(post.get("text", ""))
    return "%s\n%s" % (post.get("title", ""), post.get("selftext", ""))


def _discovery_post_created_at(post: Dict[str, Any], source: str) -> Optional[float]:
    if source == "x":
        value = post.get("createdAtISO", "")
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    try:
        return float(post.get("created_utc", 0))
    except (TypeError, ValueError):
        return None


def _discovery_provider_guess(title: str) -> str:
    tokens = re.findall(r"\b[A-Za-z][A-Za-z0-9.-]{2,}\b", title)
    for index, token in enumerate(tokens):
        if token.lower() not in _DISCOVERY_GENERIC_WORDS and not token.isupper():
            next_token = tokens[index + 1].lower() if index + 1 < len(tokens) else ""
            if re.search(r"[A-Z].*[A-Z]", token) or next_token in {"vps", "vds", "kvm", "hosting", "server"}:
                return token
    return "未识别供应商"


def _discovery_prices(text: str) -> List[Dict[str, Any]]:
    prices = []
    for match in _DISCOVERY_PRICE.finditer(text):
        period_label = match.group("period").lower()
        is_month = period_label in ("month", "monthly", "mo", "m")
        amount = float(match.group("amount"))
        period = "month" if is_month else "year"
        monthly_equivalent = amount if is_month else round(amount / 12, 2)
        prices.append(
            {
                "amount": amount,
                "currency": {"$": "USD", "€": "EUR", "£": "GBP"}.get(match.group("currency"), match.group("code") or "USD"),
                "period": period,
                "monthly_equivalent": monthly_equivalent,
                "price_eligible": amount <= 12 if is_month else amount <= 80,
            }
        )
    return prices


def _discovery_matches(text: str, terms: Tuple[Tuple[str, Tuple[str, ...]], ...]) -> List[str]:
    normalized = text.lower()
    return [label for label, needles in terms if any(needle in normalized for needle in needles)]


def filter_discovery_posts(
    posts: Iterable[Dict[str, Any]], now: Optional[float] = None, source: str = "reddit"
) -> List[Dict[str, Any]]:
    now = time.time() if now is None else now
    leads = []
    seen = set()
    for post in posts:
        post_id = str(post.get("id", ""))
        url = str(post.get("url", ""))
        if not post_id or post_id in seen:
            continue
        created_at = _discovery_post_created_at(post, source)
        if created_at is None or created_at < now - SOCIAL_LOOKBACK_DAYS * 24 * 60 * 60:
            continue
        text = _discovery_post_text(post, source)
        normalized = text.lower()
        if not any(term in normalized for term in _DISCOVERY_SIGNAL_TERMS):
            continue
        if not _DISCOVERY_VPS_CONTEXT.search(text) or _DISCOVERY_NEGATED_VPS.search(text):
            continue
        if any(term in normalized for term in _DISCOVERY_OFF_TOPIC_TERMS):
            continue
        if any(term in normalized for term in _SOCIAL_AD_TERMS):
            continue
        if any(term in normalized for term in _DISCOVERY_KNOWN_PROVIDER_TERMS):
            continue
        if any(term in normalized for term in _TWITTER_NEGATIVE):
            continue

        prices = _discovery_prices(text)
        routes = _discovery_matches(text, _DISCOVERY_ROUTE_TERMS)
        locations = _discovery_matches(text, _DISCOVERY_LOCATION_TERMS)
        resources = sorted(set(match.group(0) for match in _DISCOVERY_RESOURCE.finditer(text)), key=str.lower)
        title = str(post.get("title", "")) or text[:160]
        provider = _discovery_provider_guess(title)
        noise = [term for term in _DISCOVERY_NOISE_TERMS if term in normalized]
        concrete = bool(prices or routes or locations or resources)
        if not concrete or (prices and not any(price["price_eligible"] for price in prices)):
            continue
        if provider == "未识别供应商" and not (routes or locations or resources):
            continue
        if noise and not prices:
            continue

        score = 1 + (2 if prices else 0) + (2 if routes else 0) + (1 if locations else 0) + (1 if resources else 0)
        if score < 3:
            continue
        seen.add(post_id)
        author = post.get("author", "")
        if isinstance(author, dict):
            author = author.get("screenName", "")
        if source == "x" and not url:
            url = "https://x.com/%s/status/%s" % (author, post_id)
        leads.append(
            {
                "id": "%s:%s" % (source, post_id),
                "label": "待官网复核线索",
                "provider": provider,
                "author": str(author),
                "created_at": post.get("createdAtISO", int(created_at)),
                "title": title[:300],
                "text": text[:500],
                "url": url,
                "prices": prices,
                "evidence": {
                    "routes": routes,
                    "locations": locations,
                    "resources": resources,
                    "signals": [term for term in _DISCOVERY_SIGNAL_TERMS if term in normalized],
                },
                "score": score,
                "reason": "近期讨论包含库存/交易信号和具体价格、线路、地区或配置证据；待官网复核",
            }
        )
    return leads[:10]


def check_frantech_html(provider: Dict[str, Any], status_code: int, text: str) -> Dict[str, Any]:
    result = _base_result(provider)
    if status_code in (401, 403, 429):
        result["status"] = "blocked"
        result["reason"] = "provider anti-bot or rate-limit response (HTTP %s)" % status_code
        return result
    if status_code >= 400:
        result["status"] = "unreachable"
        result["reason"] = "HTTP %s" % status_code
        return result

    parser = _FrantechPackageParser()
    parser.feed(text)
    prefixes = tuple(x.lower() for x in provider.get("plan_prefixes", []))
    result["plans"] = [
        plan for plan in parser.plans
        if not prefixes or plan["plan"].lower().startswith(prefixes)
    ]
    if result["plans"]:
        result["status"] = "available" if any(x["available"] for x in result["plans"]) else "out_of_stock"
        result["confidence"] = "high"
        result["reason"] = "public FranTech cart page exposes per-plan inventory counts"
    else:
        result["status"] = "unknown"
        result["reason"] = "public FranTech cart page has no matching inventory count"
    return result


def check_counted_html(provider: Dict[str, Any], status_code: int, text: str) -> Dict[str, Any]:
    result = _base_result(provider)
    if status_code in (401, 403, 429):
        result["status"] = "blocked"
        result["reason"] = "provider anti-bot or rate-limit response (HTTP %s)" % status_code
        return result
    if status_code >= 400:
        result["status"] = "unreachable"
        result["reason"] = "HTTP %s" % status_code
        return result

    prefixes = tuple(x.lower() for x in provider.get("plan_prefixes", []))
    matches = []
    for match in _COUNTED_PLAN.finditer(re.sub(r"\s+", " ", text)):
        plan = match.group("plan").strip()
        if prefixes and not plan.lower().startswith(prefixes):
            continue
        count = int(match.group("count"))
        matches.append({"plan": plan, "count": count, "available": count > 0})
    result["plans"] = matches
    if matches:
        result["status"] = "available" if any(x["available"] for x in matches) else "out_of_stock"
        result["confidence"] = "high"
        result["reason"] = "public page exposes per-plan inventory counts"
    else:
        result["status"] = "unknown"
        result["reason"] = "public page has no matching inventory count"
    return result


def check_novixlink_markdown(provider: Dict[str, Any], status_code: int, text: str) -> Dict[str, Any]:
    result = _base_result(provider)
    if status_code in (401, 403, 429):
        result["status"] = "blocked"
        result["reason"] = "provider anti-bot or rate-limit response (HTTP %s)" % status_code
        return result
    if status_code >= 400:
        result["status"] = "unreachable"
        result["reason"] = "HTTP %s" % status_code
        return result

    plans = []
    headings = list(_NOVIXLINK_PLAN.finditer(text))
    for index, heading in enumerate(headings):
        section_end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        section = text[heading.end() : section_end]
        cad_match = _NOVIXLINK_CAD_PRICE.search(section)
        if not cad_match:
            continue
        usd_match = _NOVIXLINK_USD_PRICE.search(section)
        cad_amount = float(cad_match.group("amount"))
        usd_amount = float(usd_match.group("amount")) if usd_match else None
        monthly_equivalent = usd_amount if usd_amount is not None else cad_amount
        price = {
            "amount": cad_amount,
            "currency": "CAD",
            "period": "month",
            "monthly_equivalent": monthly_equivalent,
            "price_eligible": monthly_equivalent <= 12,
        }
        if usd_amount is not None:
            price["monthly_equivalent_currency"] = "USD"
        product_match = re.search(r"\]\((https?://[^)]+/store/[^)]+)\)", section)
        product_url = product_match.group(1) if product_match else None
        if product_url and product_url.startswith("http://novixlink.com/"):
            product_url = "https://novixlink.com/" + product_url.split("http://novixlink.com/", 1)[1]
        sold_out = bool(re.search(r"全部售罄|out of stock|sold out|unavailable", section, re.IGNORECASE))
        order_signal = bool(re.search(r"立即购买|order now|add to cart", section, re.IGNORECASE))
        plans.append(
            {
                "plan": heading.group("plan").strip(),
                "price": price,
                "product_url": product_url,
                "available": order_signal and not sold_out,
            }
        )

    result["plans"] = plans
    if not plans:
        result["status"] = "unknown"
        result["reason"] = "NovixLink page has no matching plan price or order state"
    elif any(plan["available"] for plan in plans):
        result["status"] = "available"
        result["confidence"] = "high"
        result["reason"] = "official NovixLink page exposes per-plan price and order or sold-out state"
    else:
        result["status"] = "out_of_stock"
        result["confidence"] = "high"
        result["reason"] = "official NovixLink page marks all parsed plans sold out"
    return result


def check_colocrossing_markdown(provider: Dict[str, Any], status_code: int, text: str) -> Dict[str, Any]:
    result = _base_result(provider)
    if status_code in (401, 403, 429):
        result["status"] = "blocked"
        result["reason"] = "provider anti-bot or rate-limit response (HTTP %s)" % status_code
        return result
    if status_code >= 400:
        result["status"] = "unreachable"
        result["reason"] = "HTTP %s" % status_code
        return result

    plan_name = provider["plan_name"]
    target_price = float(provider["target_price"])
    plan_match = plan_name.lower() in text.lower()
    monthly_prices = []
    for match in re.finditer(
        r"(?:Monthly\s+\$\s*(?P<amount>\d+(?:\.\d+)?)\s*USD|"
        r"\$\s*(?P<amount_after>\d+(?:\.\d+)?)\s*USD\s+Monthly)",
        text,
        re.IGNORECASE,
    ):
        amount = match.group("amount") or match.group("amount_after")
        monthly_prices.append(float(amount))
    price_match = any(amount == target_price for amount in monthly_prices)
    normalized = re.sub(r"\s+", " ", text).lower()
    sold_out = bool(re.search(r"out of stock|sold out|unavailable|product not found", normalized))
    order_signal = bool(re.search(r"\bcontinue\b|add to cart", normalized))

    if plan_match and price_match:
        result["plans"] = [
            {
                "plan": plan_name,
                "product_url": provider["url"],
                "price": {
                    "amount": target_price,
                    "currency": "USD",
                    "period": "month",
                    "monthly_equivalent": target_price,
                    "price_eligible": target_price <= 12,
                },
                "available": order_signal and not sold_out,
            }
        ]

    if not result["plans"]:
        result["status"] = "unknown"
        result["reason"] = "official ColoCrossing configuration page has no matching plan and monthly price"
    elif sold_out:
        result["status"] = "out_of_stock"
        result["confidence"] = "medium"
        result["reason"] = "official ColoCrossing configuration page marks the target plan unavailable"
    elif order_signal:
        result["status"] = "available"
        result["confidence"] = "medium"
        result["reason"] = "official ColoCrossing page exposes the target price and configuration action; inventory and location may still change"
    else:
        result["status"] = "catalog_only"
        result["confidence"] = "low"
        result["reason"] = "official ColoCrossing page exposes the target plan and price but no configuration action"
    return result


def check_bwh_json(provider: Dict[str, Any], status_code: int, text: str) -> Dict[str, Any]:
    result = _base_result(provider)
    if status_code in (401, 403, 429):
        result["status"] = "blocked"
        result["reason"] = "provider anti-bot or rate-limit response (HTTP %s)" % status_code
        return result
    if status_code >= 400:
        result["status"] = "unreachable"
        result["reason"] = "HTTP %s" % status_code
        return result

    try:
        payload = json.loads(text)
        products = payload["products"]
    except (ValueError, TypeError, KeyError) as exc:
        result["status"] = "unknown"
        result["reason"] = "cannot parse BWH public order data: %s" % exc
        return result

    target_tiers = set(provider.get("tiers", []))
    target_datacenters = set(provider.get("datacenters", []))
    matches = []
    for product in products:
        if not isinstance(product, dict):
            continue
        if target_tiers and not target_tiers.intersection(product.get("tiers", [])):
            continue
        offered_datacenters = product.get("datacenters", {})
        if not isinstance(offered_datacenters, dict):
            continue
        matched_datacenters = sorted(target_datacenters.intersection(offered_datacenters))
        if not matched_datacenters:
            continue
        prices = product.get("prices", [])
        parsed_prices = []
        for price in prices:
            if not isinstance(price, dict) or not price.get("period") or price.get("cents") is None:
                continue
            amount = float(price["cents"]) / 100
            period = str(price["period"])
            months = {"Monthly": 1, "Quarterly": 3, "Semi-Annually": 6, "Annually": 12}.get(period)
            monthly_equivalent = round(amount / months, 2) if months else None
            parsed_prices.append(
                {
                    "amount": amount,
                    "currency": price.get("currency", "USD"),
                    "period": period,
                    "monthly_equivalent": monthly_equivalent,
                    "price_eligible": bool(
                        monthly_equivalent is not None
                        and (monthly_equivalent <= 12 or (period == "Annually" and amount <= 80))
                    ),
                }
            )
        billing_cycles = [price["period"] for price in parsed_prices]
        available = not bool(product.get("outOfStock", True))
        matches.append(
            {
                "plan": str(product.get("name", product.get("id", "unknown"))),
                "product_id": product.get("id"),
                "datacenters": matched_datacenters,
                "billing_cycles": billing_cycles,
                "prices": parsed_prices,
                "available": available,
            }
        )

    result["plans"] = matches
    if not matches:
        result["status"] = "unknown"
        result["reason"] = "public BWH order data has no matching Los Angeles CN2 product"
    elif any(plan["available"] for plan in matches):
        result["status"] = "available"
        result["confidence"] = "high"
        result["reason"] = "public BWH order data exposes matching datacenters and product outOfStock state"
    else:
        result["status"] = "out_of_stock"
        result["confidence"] = "high"
        result["reason"] = "public BWH order data marks all matching products out of stock"
    return result


def check_html(provider: Dict[str, Any], status_code: int, text: str) -> Dict[str, Any]:
    result = _base_result(provider)
    if status_code in (401, 403, 429):
        result["status"] = "blocked"
        result["reason"] = "provider anti-bot or rate-limit response (HTTP %s)" % status_code
        return result
    if status_code >= 400:
        result["status"] = "unreachable"
        result["reason"] = "HTTP %s" % status_code
        return result

    normalized = re.sub(r"\s+", " ", text).lower()
    if provider.get("stock_signal") == "catalog":
        result["status"] = "catalog_only"
        result["confidence"] = "low"
        result["reason"] = "catalog page is reachable; checkout inventory is not exposed publicly"
        return result
    out_count = len(re.findall(r"out of stock|sold out|unavailable", normalized))
    order_count = len(re.findall(r"order now|order this package|deploy server|add to cart", normalized))
    if out_count and out_count >= order_count:
        result["status"] = "out_of_stock"
        result["confidence"] = "medium"
        result["reason"] = "public page contains no stronger order signal"
    elif order_count:
        result["status"] = "available"
        result["confidence"] = "medium"
        result["reason"] = "public page exposes an order/provision action; inventory may still change at checkout"
    else:
        result["status"] = "catalog_only"
        result["confidence"] = "low"
        result["reason"] = "product page is reachable but does not expose inventory"
    return result


def check_dedione_html(provider: Dict[str, Any], status_code: int, text: str) -> Dict[str, Any]:
    result = _base_result(provider)
    if status_code in (401, 403, 429):
        result["status"] = "blocked"
        result["reason"] = "provider anti-bot or rate-limit response (HTTP %s)" % status_code
        return result
    if status_code >= 400:
        result["status"] = "unreachable"
        result["reason"] = "HTTP %s" % status_code
        return result

    target_name = provider["plan_name"]
    target_price = float(provider["target_price"])
    matches = []
    for section in re.split(r"(?=<div\b[^>]*class=[\"']package[\"'])", text, flags=re.IGNORECASE):
        name_match = re.search(r"<h3\b[^>]*class=[\"'][^\"']*\bpackage-title\b[^\"']*[\"'][^>]*>(.*?)</h3>", section, re.IGNORECASE | re.DOTALL)
        if not name_match:
            continue
        plan_name = _html_text(name_match.group(1))
        if plan_name != target_name:
            continue
        price_match = re.search(r"<div\b[^>]*class=[\"'][^\"']*\bprice-amount\b[^\"']*[\"'][^>]*>\s*([$€£])\s*(\d+(?:\.\d+)?)\s*([A-Z]{3})?", section, re.IGNORECASE | re.DOTALL)
        cycle_match = re.search(r"<div\b[^>]*class=[\"'][^\"']*\bprice-cycle\b[^\"']*[\"'][^>]*>\s*(Monthly|Quarterly|Semi-Annually|Annually|Yearly)", section, re.IGNORECASE | re.DOTALL)
        if not (price_match and cycle_match):
            continue
        amount = float(price_match.group(2))
        period_label = cycle_match.group(1).lower()
        period = "month" if period_label == "monthly" else "year"
        if amount != target_price or (provider.get("target_period") and period != provider["target_period"]):
            continue
        button_match = re.search(r"<a\b[^>]*class=[\"'][^\"']*\bbtn-order-now\b[^\"']*[\"'][^>]*>(.*?)</a>", section, re.IGNORECASE | re.DOTALL)
        section_text = _html_text(section).lower()
        available = bool(button_match) and not bool(re.search(r"out of stock|sold out|unavailable|not available", section_text))
        monthly_equivalent = amount if period == "month" else round(amount / 12, 2)
        matches.append(
            {
                "plan": plan_name,
                "price": {
                    "amount": amount,
                    "currency": {"$": "USD", "€": "EUR", "£": "GBP"}.get(price_match.group(1), price_match.group(3) or "USD"),
                    "period": period,
                    "monthly_equivalent": monthly_equivalent,
                    "price_eligible": amount <= 80 if period == "year" else monthly_equivalent <= 12,
                },
                "available": available,
            }
        )

    result["plans"] = matches
    if not matches:
        result["status"] = "unknown"
        result["reason"] = "official DediOne page has no matching product name, price, and billing cycle"
    elif any(plan["available"] for plan in matches):
        result["status"] = "available"
        result["confidence"] = "medium"
        result["reason"] = "official DediOne product card exposes an order action; checkout inventory may still change"
    else:
        result["status"] = "out_of_stock"
        result["confidence"] = "medium"
        result["reason"] = "official DediOne product card has no enabled order action"
    return result


def _html_text(value: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", value)).split())


def check_whmcs_offer_html(provider: Dict[str, Any], status_code: int, text: str) -> Dict[str, Any]:
    result = _base_result(provider)
    if status_code in (401, 403, 429):
        result["status"] = "blocked"
        result["reason"] = "provider anti-bot or rate-limit response (HTTP %s)" % status_code
        return result
    if status_code >= 400:
        result["status"] = "unreachable"
        result["reason"] = "HTTP %s" % status_code
        return result

    matches = []
    for form in re.findall(r"<form\b[^>]*>(.*?)</form>", text, re.IGNORECASE | re.DOTALL):
        name_match = re.search(r"<strong\b[^>]*>(.*?)</strong>", form, re.IGNORECASE | re.DOTALL)
        id_match = re.search(r"<input\b[^>]*name=[\"']id[\"'][^>]*value=[\"'](\d+)[\"']", form, re.IGNORECASE)
        option_match = re.search(
            r"<option\b[^>]*>\s*([$€£])\s*(\d+(?:\.\d+)?)\s*([A-Z]{3})?\s*(Monthly|Quarterly|Annually|Yearly)\s*</option>",
            form,
            re.IGNORECASE,
        )
        button_match = re.search(r"<button\b([^>]*)>(.*?)</button>", form, re.IGNORECASE | re.DOTALL)
        if not (name_match and option_match and button_match):
            continue

        plan_name = _html_text(name_match.group(1))
        amount = float(option_match.group(2))
        period_label = option_match.group(4).lower()
        period = {
            "monthly": "month",
            "quarterly": "quarter",
            "annually": "year",
            "yearly": "year",
        }[period_label]
        if provider.get("plan_name") and plan_name != provider["plan_name"]:
            continue
        if provider.get("target_price") is not None and amount != float(provider["target_price"]):
            continue
        if provider.get("target_period") and period != provider["target_period"]:
            continue

        button_attrs = button_match.group(1).lower()
        button_text = _html_text(button_match.group(2)).lower()
        available = "disabled" not in button_attrs and "out of stock" not in button_text
        currency = {"$": "USD", "€": "EUR", "£": "GBP"}.get(option_match.group(1), option_match.group(3) or "USD")
        billing_months = {"month": 1, "quarter": 3, "year": 12}[period]
        monthly_equivalent = round(amount / billing_months, 2)
        price = {
            "amount": amount,
            "currency": currency,
            "period": period,
            "monthly_equivalent": monthly_equivalent,
            "price_eligible": amount <= 80 if period == "year" else monthly_equivalent <= 12,
        }
        matches.append(
            {
                "plan": plan_name,
                "product_id": int(id_match.group(1)) if id_match else None,
                "price": price,
                "available": available,
            }
        )

    result["plans"] = matches
    if not matches:
        result["status"] = "unknown"
        result["reason"] = "official WHMCS offer page has no matching plan and billing price"
    elif any(plan["available"] for plan in matches):
        result["status"] = "available"
        result["confidence"] = "high"
        result["reason"] = "official WHMCS offer page exposes an enabled order action"
    else:
        result["status"] = "out_of_stock"
        result["confidence"] = "high"
        result["reason"] = "official WHMCS offer page marks the matching plan out of stock"
    return result


def check_twitter(provider: Dict[str, Any], timeout: int = 20, since: Optional[str] = None) -> Dict[str, Any]:
    result = _base_result(provider)
    since = since or (date.today() - timedelta(days=SOCIAL_LOOKBACK_DAYS)).isoformat()
    query = provider.get("twitter_query", "")
    if provider.get("twitter_from"):
        query = "from:%s %s" % (provider["twitter_from"], query)
    try:
        tweets = _search_twitter(query, since, timeout)
    except RuntimeError as exc:
        result["status"] = "unreachable"
        result["reason"] = "Twitter/X check failed: %s" % exc
        return result

    leads = []
    for tweet in tweets:
        text = str(tweet.get("text", ""))
        normalized = text.lower()
        if not any(keyword in normalized for keyword in provider.get("twitter_keywords", [])):
            continue
        if not any(term in normalized for term in _TWITTER_POSITIVE):
            continue
        if any(term in normalized for term in _TWITTER_NEGATIVE):
            continue
        if any(term in normalized for term in _SOCIAL_AD_TERMS):
            continue
        author = tweet.get("author", {})
        screen_name = str(author.get("screenName", ""))
        tweet_id = str(tweet.get("id", ""))
        if not screen_name or not tweet_id:
            continue
        leads.append(
            {
                "id": "x:%s" % tweet_id,
                "author": screen_name,
                "created_at": tweet.get("createdAtISO", ""),
                "text": text[:500],
                "url": "https://x.com/%s/status/%s" % (screen_name, tweet_id),
            }
        )
    result["posts"] = leads[:10]
    result["status"] = "lead" if leads else "no_recent_signal"
    result["confidence"] = "medium" if provider.get("twitter_official") else "low"
    if leads:
        origin = "official" if provider.get("twitter_official") else "community"
        result["reason"] = "%s X posts mention a current sale or restock; verify before purchase" % origin
    else:
        result["reason"] = "no recent X sale or restock signal"
    return result


def _reddit_http_search(provider: Dict[str, Any], timeout: int) -> List[Dict[str, Any]]:
    query = urlencode(
        {
            "q": provider["reddit_query"],
            "sort": "new",
            "t": "month",
            "limit": "30",
            "raw_json": "1",
        }
    )
    status_code, text = fetch("https://www.reddit.com/search.json?%s" % query, timeout=timeout)
    if status_code >= 400:
        raise RuntimeError("HTTP %s" % status_code)
    payload = json.loads(text)
    if isinstance(payload, list):
        return payload
    children = payload.get("data", {}).get("children", [])
    if not isinstance(children, list):
        raise ValueError("Reddit JSON has no post list")
    return [child.get("data", {}) for child in children if isinstance(child, dict)]


def _reddit_rss_search(provider: Dict[str, Any], timeout: int) -> List[Dict[str, Any]]:
    query = urlencode(
        {
            "q": provider["reddit_query"],
            "sort": "new",
            "t": "month",
            "limit": "30",
        }
    )
    status_code, text = fetch("https://www.reddit.com/search.rss?%s" % query, timeout=timeout)
    if status_code >= 400:
        raise RuntimeError("HTTP %s" % status_code)
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise ValueError("Reddit RSS returned invalid XML") from exc

    atom = "{http://www.w3.org/2005/Atom}"
    posts = []
    for entry in root.findall("%sentry" % atom):
        raw_id = entry.findtext("%sid" % atom, default="")
        if not raw_id.startswith("t3_"):
            continue
        updated = entry.findtext("%supdated" % atom, default="")
        try:
            created_utc = datetime.fromisoformat(updated.replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            continue
        link = entry.find("%slink" % atom)
        author = entry.find("%sauthor" % atom)
        content = entry.findtext("%scontent" % atom, default="")
        posts.append(
            {
                "id": raw_id[3:],
                "title": entry.findtext("%stitle" % atom, default=""),
                "selftext": re.sub(r"<[^>]+>", " ", unescape(content)),
                "author": author.findtext("%sname" % atom, default="") if author is not None else "",
                "created_utc": created_utc,
                "url": link.get("href", "") if link is not None else "",
            }
        )
    return posts


def _terminate_process_group(process: subprocess.Popen) -> None:
    if os.name == "nt":
        process.kill()
        process.wait()
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def _run_reddit_opencli(command: List[str], timeout: float, env: Dict[str, str]) -> subprocess.CompletedProcess:
    process = subprocess.Popen(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=os.name != "nt",
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(process)
        raise RuntimeError("Reddit OpenCLI timed out after %.1fs" % timeout) from exc
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _run_twitter_opencli(command: List[str], timeout: float, env: Dict[str, str]) -> subprocess.CompletedProcess:
    process = subprocess.Popen(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=os.name != "nt",
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(process)
        raise RuntimeError("Twitter OpenCLI timed out after %.1fs" % timeout) from exc
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _twitter_timestamp_to_iso(value: Any) -> str:
    """OpenCLI reports Twitter's legacy stamp; downstream filters only read ISO."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return text
    except ValueError:
        pass
    try:
        return datetime.strptime(text, "%a %b %d %H:%M:%S %z %Y").isoformat()
    except ValueError:
        return text


def _parse_twitter_posts(stdout: str, source: str) -> List[Dict[str, Any]]:
    payload = json.loads(stdout)
    if isinstance(payload, dict):
        if payload.get("ok") is False:
            error = payload.get("error", {})
            message = error.get("message", "Twitter returned an error") if isinstance(error, dict) else str(error)
            raise ValueError(message)
        posts = payload.get("data", [])
    elif isinstance(payload, list):
        posts = payload
    else:
        raise ValueError("Twitter response has no post list")
    if not isinstance(posts, list):
        raise ValueError("Twitter response has no post list")
    if source != "opencli":
        return posts

    normalized = []
    for post in posts:
        if not isinstance(post, dict):
            continue
        author = post.get("author", "")
        if isinstance(author, dict):
            screen_name = author.get("screenName") or author.get("username") or author.get("screen_name") or ""
        else:
            screen_name = author
        normalized.append(
            {
                "id": post.get("id", ""),
                "text": post.get("text", ""),
                "author": {"screenName": str(screen_name)},
                "createdAtISO": _twitter_timestamp_to_iso(post.get("created_at", "")),
            }
        )
    return normalized


def _search_twitter(query: str, since: str, timeout: int) -> List[Dict[str, Any]]:
    twitter_command = [
        "twitter",
        "search",
        "--type",
        "latest",
        "--since",
        since,
        "--max",
        "30",
        "--json",
    ]
    if query:
        twitter_command.append(query)

    twitter_failure = ""
    try:
        completed = subprocess.run(
            twitter_command,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=_external_command_env(),
        )
        if completed.returncode == 0:
            try:
                return _parse_twitter_posts(completed.stdout, source="twitter")
            except (ValueError, TypeError) as exc:
                twitter_failure = str(exc)
        else:
            twitter_failure = completed.stderr.strip() or "exited with status %s" % completed.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        twitter_failure = str(exc)

    opencli_query = "%s since:%s" % (query, since) if query else "since:%s" % since
    opencli_command = [
        "opencli",
        "twitter",
        "search",
        opencli_query,
        "--product",
        "live",
        "--limit",
        "30",
        "-f",
        "json",
    ]
    try:
        fallback = _run_twitter_opencli(opencli_command, timeout, _external_command_env())
        if fallback.returncode == 0:
            return _parse_twitter_posts(fallback.stdout, source="opencli")
        opencli_failure = fallback.stderr.strip() or "exited with status %s" % fallback.returncode
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        opencli_failure = str(exc)
    raise RuntimeError("twitter-cli: %s; OpenCLI: %s" % (twitter_failure, opencli_failure))


def _reddit_search_posts(provider: Dict[str, Any], timeout: int) -> List[Dict[str, Any]]:
    command = [
        "opencli",
        "reddit",
        "search",
        provider["reddit_query"],
        "--sort",
        "new",
        "--time",
        "month",
        "--limit",
        "30",
        "-f",
        "json",
    ]
    deadline = time.monotonic() + timeout
    try:
        cli_timeout = min(10.0, max(0.1, deadline - time.monotonic()))
        completed = _run_reddit_opencli(command, cli_timeout, _external_command_env())
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Reddit check failed: %s" % exc) from exc
    except RuntimeError as exc:
        failure_reason = str(exc)
        posts = None
    else:
        failure_reason = ""
        if completed.returncode != 0:
            failure_reason = completed.stderr.strip() or "opencli exited with status %s" % completed.returncode
            posts = None
        else:
            try:
                posts = json.loads(completed.stdout)
                if not isinstance(posts, list):
                    raise ValueError("opencli response is not a post list")
            except (ValueError, TypeError):
                failure_reason = "opencli returned an unreadable response"
                posts = None
    if posts is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("%s; public fallbacks skipped because the timeout budget expired" % failure_reason)
        try:
            posts = _reddit_http_search(provider, min(5.0, remaining))
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            json_failure_reason = str(exc)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    "Reddit check failed: %s; public JSON fallback failed: %s; RSS fallback skipped because the timeout budget expired"
                    % (failure_reason, json_failure_reason)
                ) from exc
            try:
                posts = _reddit_rss_search(provider, remaining)
            except (OSError, RuntimeError, ValueError, TypeError) as rss_exc:
                raise RuntimeError(
                    "Reddit check failed: %s; public JSON fallback failed: %s; RSS fallback failed: %s"
                    % (failure_reason, json_failure_reason, rss_exc)
                ) from rss_exc
    return posts


def check_reddit(provider: Dict[str, Any], timeout: int = 20) -> Dict[str, Any]:
    result = _base_result(provider)
    try:
        posts = _reddit_search_posts(provider, timeout)
    except RuntimeError as exc:
        result["status"] = "unreachable"
        result["reason"] = str(exc)
        return result

    cutoff = time.time() - SOCIAL_LOOKBACK_DAYS * 24 * 60 * 60
    leads = []
    for post in posts:
        created_at = float(post.get("created_utc", 0))
        text = "%s\n%s" % (post.get("title", ""), post.get("selftext", ""))
        normalized = text.lower()
        if created_at < cutoff or not any(keyword in normalized for keyword in provider["reddit_keywords"]):
            continue
        if not any(term in normalized for term in _TWITTER_POSITIVE):
            continue
        if any(term in normalized for term in _TWITTER_NEGATIVE):
            continue
        if any(term in normalized for term in _SOCIAL_AD_TERMS):
            continue
        post_id = str(post.get("id", ""))
        url = str(post.get("url", ""))
        if not post_id or not url:
            continue
        leads.append(
            {
                "id": "reddit:%s" % post_id,
                "author": str(post.get("author", "")),
                "created_at": int(created_at),
                "text": text[:500],
                "url": url,
            }
        )
    result["posts"] = leads[:10]
    result["status"] = "lead" if result["posts"] else "no_recent_signal"
    result["confidence"] = "low"
    result["reason"] = "community Reddit posts mention a current sale or restock; verify before purchase" if result["posts"] else "no recent Reddit sale or restock signal"
    return result


def check_twitter_discovery(provider: Dict[str, Any], timeout: int = 20) -> Dict[str, Any]:
    result = _base_result(provider)
    since = (date.today() - timedelta(days=SOCIAL_LOOKBACK_DAYS)).isoformat()
    try:
        posts = _search_twitter(provider["twitter_query"], since, timeout)
    except RuntimeError as exc:
        result["status"] = "unreachable"
        result["reason"] = "Twitter/X discovery failed: %s" % exc
        return result

    result["posts"] = filter_discovery_posts(posts, source="x")
    result["status"] = "lead" if result["posts"] else "no_recent_signal"
    result["confidence"] = "low"
    result["reason"] = "community X discovery posts contain concrete VPS evidence; verify before purchase" if result["posts"] else "no recent concrete VPS discovery signal on X"
    return result


def check_reddit_discovery(provider: Dict[str, Any], timeout: int = 20) -> Dict[str, Any]:
    result = _base_result(provider)
    try:
        posts = _reddit_search_posts(provider, timeout)
    except RuntimeError as exc:
        result["status"] = "unreachable"
        result["reason"] = str(exc)
        return result
    result["posts"] = filter_discovery_posts(posts, source="reddit")
    result["status"] = "lead" if result["posts"] else "no_recent_signal"
    result["confidence"] = "low"
    result["reason"] = "community Reddit discovery posts contain concrete VPS evidence; verify before purchase" if result["posts"] else "no recent concrete VPS discovery signal on Reddit"
    return result


def check_provider(provider: Dict[str, Any], timeout: int = 20) -> Dict[str, Any]:
    if provider["kind"] == "twitter_search":
        return check_twitter(provider, timeout)
    if provider["kind"] == "reddit_search":
        return check_reddit(provider, timeout)
    if provider["kind"] == "twitter_discovery":
        return check_twitter_discovery(provider, timeout)
    if provider["kind"] == "reddit_discovery":
        return check_reddit_discovery(provider, timeout)
    try:
        status_code, text = fetch(provider.get("fetch_url", provider["url"]), timeout=timeout)
    except RuntimeError as exc:
        result = _base_result(provider)
        result["status"] = "unreachable"
        result["reason"] = str(exc)
        return result
    if provider["kind"] == "frantech_html":
        result = check_frantech_html(provider, status_code, text)
    elif provider["kind"] == "counted_html":
        result = check_counted_html(provider, status_code, text)
    elif provider["kind"] == "bwh_json":
        result = check_bwh_json(provider, status_code, text)
    elif provider["kind"] == "whmcs_offer_html":
        result = check_whmcs_offer_html(provider, status_code, text)
    elif provider["kind"] == "dedione_html":
        result = check_dedione_html(provider, status_code, text)
    elif provider["kind"] == "novixlink_markdown":
        result = check_novixlink_markdown(provider, status_code, text)
    elif provider["kind"] == "colocrossing_markdown":
        result = check_colocrossing_markdown(provider, status_code, text)
    else:
        result = check_html(provider, status_code, text)
    result["http_status"] = status_code
    return result


def select_providers(cn2_only: bool = False, all_providers: bool = False) -> Iterable[Dict[str, Any]]:
    for provider in PROVIDERS:
        if not all_providers and not provider.get("focus", False):
            continue
        if cn2_only and provider["priority"] != "cn2":
            continue
        yield provider


def select_social_providers(cn2_only: bool = False, all_providers: bool = False) -> Iterable[Dict[str, Any]]:
    for provider in SOCIAL_PROVIDERS:
        if not all_providers and not provider.get("focus", False):
            continue
        if cn2_only and provider["priority"] != "cn2":
            continue
        yield provider


def select_non_social_providers(cn2_only: bool = False, all_providers: bool = False) -> Iterable[Dict[str, Any]]:
    for provider in select_providers(cn2_only=cn2_only, all_providers=all_providers):
        if provider["kind"] in ("twitter_search", "reddit_search"):
            continue
        yield provider


def select_sources(cn2_only: bool = False, all_providers: bool = False) -> Iterable[Dict[str, Any]]:
    return chain(
        select_providers(cn2_only=cn2_only, all_providers=all_providers),
        select_social_providers(cn2_only=cn2_only, all_providers=all_providers),
        (
            provider
            for provider in DISCOVERY_PROVIDERS
            if (all_providers or provider.get("focus", False))
            and (not cn2_only or provider["priority"] == "cn2")
        ),
    )


def monitorability(cn2_only: bool = False, all_providers: bool = False) -> List[Dict[str, str]]:
    rows = []
    for provider in select_non_social_providers(cn2_only=cn2_only, all_providers=all_providers):
        kind = provider["kind"]
        if kind == "frantech_html":
            level = "stock"
            reason = "public FranTech cart page exposes per-plan inventory counts"
        elif kind == "counted_html":
            level = "stock"
            reason = "public page exposes per-plan inventory counts when reachable"
        elif kind == "bwh_json":
            level = "stock"
            reason = "public order JSON exposes matching datacenters and product outOfStock state"
        elif kind == "whmcs_offer_html":
            level = "stock"
            reason = "official WHMCS offer page exposes per-plan enabled or out-of-stock order state"
        elif kind == "novixlink_markdown":
            level = "stock"
            reason = "official NovixLink page exposes per-plan price and order or sold-out state"
        elif kind == "colocrossing_markdown":
            level = "order_signal"
            reason = "official configuration page exposes the target monthly price and configure action, but not inventory counts or per-location stock"
        elif kind == "dedione_html":
            level = "order_signal"
            reason = "official DediOne product card exposes the target price and order action, but not a numeric inventory count"
        elif provider.get("stock_signal") == "catalog":
            level = "catalog_only"
            reason = "public catalog is reachable, but checkout inventory is not exposed"
        elif kind == "html":
            level = "order_signal"
            reason = "public page exposes order/provision text, but checkout inventory may still change"
        else:
            level = "unknown"
            reason = "no non-social stock signal is configured"
        rows.append(
            {
                "id": provider["id"],
                "provider": provider["provider"],
                "region": provider["region"],
                "priority": provider["priority"],
                "level": level,
                "source": provider["url"],
                "reason": reason,
            }
        )
    return rows


def _state_path(value: Optional[str]) -> Path:
    if value:
        return Path(value).expanduser()
    return Path.home() / ".cache" / "network-node" / "vps-stock.json"


def _social_post_created_at(post: Dict[str, Any]) -> Optional[float]:
    value = post.get("created_at", post.get("created_utc"))
    if isinstance(value, (int, float)):
        return float(value)
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _discovery_state_post_is_valid(post: Dict[str, Any], source_id: str, now: float) -> bool:
    if not source_id.startswith("vps-discovery-"):
        return True
    post_id = str(post.get("id", ""))
    source = "x" if post_id.startswith("x:") else "reddit"
    raw_post = dict(post)
    raw_post["id"] = post_id.split(":", 1)[-1]
    if source == "x":
        raw_post["createdAtISO"] = post.get("created_at", "")
        raw_post["text"] = post.get("text", post.get("title", ""))
    else:
        raw_post["created_utc"] = post.get("created_at", 0)
        raw_post["title"] = post.get("title", "")
        raw_post["selftext"] = post.get("text", "")
    return bool(filter_discovery_posts([raw_post], now=now, source=source))


def prune_state_posts(state: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else now
    cutoff = now - SOCIAL_LOOKBACK_DAYS * 24 * 60 * 60
    cleaned = {}
    for source_id, item in state.items():
        if not isinstance(item, dict):
            continue
        copied = dict(item)
        posts = item.get("posts")
        if isinstance(posts, list):
            copied["posts"] = []
            for post in posts:
                if not isinstance(post, dict):
                    continue
                created_at = _social_post_created_at(post)
                if created_at is None or created_at < cutoff:
                    continue
                if _discovery_state_post_is_valid(post, source_id, now):
                    copied["posts"].append(post)
        cleaned[source_id] = copied
    return cleaned


def dedupe_discovery_results(results: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    cleaned = []
    for result in results:
        copied = dict(result)
        if str(result.get("id", "")).startswith("vps-discovery-"):
            posts = []
            for post in result.get("posts", []):
                post_id = post.get("id") if isinstance(post, dict) else None
                if post_id and post_id in seen:
                    continue
                if post_id:
                    seen.add(post_id)
                posts.append(post)
            copied["posts"] = posts
            if result.get("status") == "lead" and not posts:
                copied["status"] = "no_recent_signal"
                copied["reason"] = "duplicate discovery posts were removed"
        cleaned.append(copied)
    return cleaned


def compact_memory(content: str, keep_lines: int = 20) -> str:
    lines = [line for line in content.splitlines() if line.strip()]
    if keep_lines <= 0:
        return ""
    lines = lines[-keep_lines:]
    return "\n".join(lines) + ("\n" if lines else "")


def _append_memory_line(line: str) -> None:
    path = Path.home() / ".codex" / "automations" / "vps" / "memory.md"
    try:
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(compact_memory(existing + line.rstrip() + "\n"), encoding="utf-8")
    except OSError as exc:
        print("memory write failed: %s" % exc, file=sys.stderr)


def _notify(url: str, transitions: List[Dict[str, Any]], timeout: int) -> None:
    payload = json.dumps({"event": "vps_stock_transition", "items": transitions}).encode("utf-8")
    request = Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=timeout) as response:
        if int(response.status) >= 300:
            raise RuntimeError("notification HTTP %s" % response.status)


def find_transitions(results: Iterable[Dict[str, Any]], old: Dict[str, Any]) -> List[Dict[str, Any]]:
    transitions = []
    for result in results:
        previous = old.get(result["id"], {})
        stock_transition = result["status"] == "available" and previous.get("status") != "available"
        current_posts = {post["id"] for post in result.get("posts", [])}
        previous_posts = {post["id"] for post in previous.get("posts", [])}
        twitter_transition = bool(current_posts - previous_posts)
        if stock_transition:
            event = dict(result)
            transitions.append(event)
        elif twitter_transition:
            event = dict(result)
            event["event"] = "social_lead"
            event["new_post_ids"] = sorted(current_posts - previous_posts)
            transitions.append(event)
    return transitions


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cn2-only", action="store_true", help="only monitor CN2-optimized US offers")
    parser.add_argument("--all", action="store_true", help="include non-focus sources")
    parser.add_argument("--no-social", action="store_true", help="skip X/Reddit lead checks")
    parser.add_argument("--monitorability", action="store_true", help="print non-social monitorability matrix and exit")
    parser.add_argument("--state-file", help="state file for transition deduplication")
    parser.add_argument("--notify-url", help="optional webhook URL; sent only on availability transitions")
    parser.add_argument("--full", action="store_true", help="include all checked items in stdout")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args(argv)

    if args.monitorability:
        print(json.dumps({"items": monitorability(args.cn2_only, args.all)}, ensure_ascii=False, indent=2), flush=True)
        return 0

    source_iter = select_non_social_providers(args.cn2_only, args.all) if args.no_social else select_sources(args.cn2_only, args.all)
    results = dedupe_discovery_results(check_provider(provider, args.timeout) for provider in source_iter)
    state_file = _state_path(args.state_file)
    old: Dict[str, Any] = {}
    if state_file.exists():
        try:
            old = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = {}
    old = prune_state_posts(old)
    transitions = find_transitions(results, old)
    if args.notify_url and transitions:
        try:
            _notify(args.notify_url, transitions, args.timeout)
        except (OSError, RuntimeError) as exc:
            print("notification failed: %s" % exc, file=sys.stderr)
            return 2
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps({x["id"]: x for x in results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print("state write failed: %s" % exc, file=sys.stderr)
        return 2
    output = {
        "checked_at": int(time.time()),
        "transitions": transitions,
        "exceptions": [
            {
                "id": result["id"],
                "provider": result["provider"],
                "status": result["status"],
                "reason": result.get("reason", ""),
            }
            for result in results
            if result.get("status") in {"blocked", "unreachable", "unknown"}
        ],
    }
    if args.full:
        output["items"] = results
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")), flush=True)
    _append_memory_line(
        "%s: check complete; transitions=%d; exceptions=%d; discovery_leads=%d"
        % (
            date.today().isoformat(),
            len(transitions),
            len(output["exceptions"]),
            sum(len(result.get("posts", [])) for result in results if str(result.get("id", "")).startswith("vps-discovery-")),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())