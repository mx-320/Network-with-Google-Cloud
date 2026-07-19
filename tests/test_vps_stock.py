import json
import io
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import vps_stock  # noqa: E402

from vps_stock import (  # noqa: E402
    check_bwh_json,
    check_colocrossing_markdown,
    check_counted_html,
    check_dedione_html,
    check_frantech_html,
    check_html,
    check_novixlink_markdown,
    check_reddit,
    check_twitter_discovery,
    check_twitter,
    check_whmcs_offer_html,
    compact_memory,
    dedupe_discovery_results,
    find_transitions,
    filter_discovery_posts,
    _parse_twitter_posts,
    main,
    monitorability,
    prune_state_posts,
    select_non_social_providers,
    select_providers,
    select_sources,
)


class VpsStockParsingTests(unittest.TestCase):
    def test_colocrossing_config_page_parses_target_monthly_plan(self):
        provider = {
            "id": "colocrossing-cloud-vps-1gb",
            "provider": "ColoCrossing",
            "region": "Multi-location",
            "priority": "value",
            "network": "route optimization unconfirmed",
            "url": "https://cloud.colocrossing.com/index.php?rp=/store/cloud-virtual-private-servers/1gb-ram",
            "plan_name": "Cloud Virtual Private Servers - 1GB RAM",
            "target_price": 3.95,
        }
        markdown = """
# Configure
## Cloud Virtual Private Servers - 1GB RAM
## Choose Billing Cycle
###### Monthly
$3.95 USD
Total Due Today
$3.95 USD
Continue
Add to Cart
"""
        result = check_colocrossing_markdown(provider, 200, markdown)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["confidence"], "medium")
        self.assertEqual(result["plans"][0]["price"]["amount"], 3.95)
        self.assertTrue(result["plans"][0]["price"]["price_eligible"])

    def test_colocrossing_config_page_detects_sold_out_target_plan(self):
        provider = {
            "id": "colocrossing-cloud-vps-2gb",
            "provider": "ColoCrossing",
            "region": "Multi-location",
            "priority": "value",
            "network": "route optimization unconfirmed",
            "url": "https://cloud.colocrossing.com/index.php?rp=/store/cloud-virtual-private-servers/2gb-ram",
            "plan_name": "Cloud Virtual Private Servers - 2GB RAM",
            "target_price": 6.95,
        }
        markdown = """
## Cloud Virtual Private Servers - 2GB RAM
###### Monthly
$6.95 USD
Out of Stock
"""
        result = check_colocrossing_markdown(provider, 200, markdown)
        self.assertEqual(result["status"], "out_of_stock")
        self.assertFalse(result["plans"][0]["available"])

    def test_buyvm_cart_parses_per_plan_available_counts(self):
        provider = {
            "id": "buyvm-lv",
            "provider": "BuyVM",
            "region": "Las Vegas, US",
            "priority": "value",
            "network": "standard",
            "url": "https://my.frantech.ca/cart.php?gid=37",
        }
        html = """
        <h3 class="package-name">LV RYZEN KVM 512MB</h3>
        <div class="price"><span>$</span>3.00 USD<span>/mo</span></div>
        <div class="package-qty">0 Available</div>
        <h3 class="package-name">LV RYZEN KVM 1GB</h3>
        <div class="price"><span>$</span>5.00 USD<span>/mo</span></div>
        <div class="package-qty">3 Available</div>
        """
        result = check_frantech_html(provider, 200, html)
        self.assertEqual(result["status"], "available")
        self.assertFalse(result["plans"][0]["available"])
        self.assertTrue(result["plans"][1]["available"])
        self.assertEqual(result["plans"][1]["price"]["amount"], 5.0)
        self.assertEqual(result["plans"][1]["price"]["period"], "month")
        self.assertTrue(result["plans"][1]["price"]["price_eligible"])

    def test_buyvm_sources_cover_all_four_frantech_amd_categories(self):
        sources = {
            item["id"]: item["url"]
            for item in select_providers()
            if item["provider"] == "BuyVM"
        }
        self.assertEqual(
            sources,
            {
                "buyvm-lv": "https://my.frantech.ca/cart.php?gid=37",
                "buyvm-ny": "https://my.frantech.ca/cart.php?gid=38",
                "buyvm-miami": "https://my.frantech.ca/cart.php?gid=48",
                "buyvm-switzerland": "https://my.frantech.ca/cart.php?gid=39",
            },
        )

    def test_counted_html_treats_zero_as_out_of_stock(self):
        provider = {
            "id": "greencloud-us",
            "provider": "GreenCloud",
            "region": "US",
            "priority": "value",
            "network": "standard",
            "url": "https://example.invalid/store",
            "plan_prefixes": ["BudgetKVM"],
        }
        html = "BudgetKVMLA-1 0 Available BudgetKVMLA-2 3 Available"
        result = check_counted_html(provider, 200, html)
        self.assertEqual(result["status"], "available")
        self.assertFalse(result["plans"][0]["available"])
        self.assertTrue(result["plans"][1]["available"])

    def test_counted_html_reports_cloudflare_as_blocked(self):
        provider = {
            "id": "greencloud-us",
            "provider": "GreenCloud",
            "region": "US",
            "priority": "value",
            "network": "standard",
            "url": "https://example.invalid/store",
            "plan_prefixes": ["BudgetKVM"],
        }
        result = check_counted_html(provider, 403, "Just a moment")
        self.assertEqual(result["status"], "blocked")

    def test_novixlink_markdown_parses_cad_usd_prices_and_sold_out_state(self):
        provider = {
            "id": "novixlink-ntt-isp-vps",
            "provider": "NovixLink",
            "region": "Los Angeles, US",
            "priority": "cn2",
            "network": "AS9929 / CMIN2",
            "url": "https://novixlink.com/store/nttispipvps",
        }
        markdown = """
### LAX-CUPN Lite 轻量版

 $6.99 CAD

 ~ $4.89 USD

[立即购买](https://novixlink.com/store/nttispipvps/lax-cupn-lite)

全部售罄

### LAX-CUPN Pro 进阶版

 $15.99 CAD

 ~ $11.19 USD

[立即购买](https://novixlink.com/store/nttispipvps/lax-cupn-pro)
"""
        result = check_novixlink_markdown(provider, 200, markdown)

        self.assertEqual(result["status"], "available")
        self.assertEqual(len(result["plans"]), 2)
        self.assertFalse(result["plans"][0]["available"])
        self.assertTrue(result["plans"][1]["available"])
        self.assertEqual(result["plans"][0]["price"]["currency"], "CAD")
        self.assertEqual(result["plans"][0]["price"]["monthly_equivalent"], 4.89)
        self.assertTrue(result["plans"][1]["price"]["price_eligible"])
        self.assertIn("lax-cupn-lite", result["plans"][0]["product_url"])

    def test_hostdare_store_counts_cover_the_three_cn2_categories(self):
        provider = {
            "id": "hostdare-lax-cn2-hdd",
            "provider": "HostDare",
            "region": "Los Angeles, US",
            "priority": "cn2",
            "network": "CN2",
            "url": "https://bill.hostdare.com/store/premium-china-optimized-kvm-vps",
            "plan_prefixes": ["CKVM"],
        }
        html = "CKVM1 0 Available CKVM5 2 Available CKVM8 0 Available"
        result = check_counted_html(provider, 200, html)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["plans"][1]["count"], 2)

    def test_bwh_json_uses_public_product_and_datacenter_inventory(self):
        provider = {
            "id": "bwh-lax-cn2",
            "provider": "BWH",
            "region": "Los Angeles, US",
            "priority": "cn2",
            "network": "CN2 GIA",
            "url": "https://bandwagonhost.com/order/get-data",
            "tiers": ["ecommerce"],
            "datacenters": ["USCA_6", "USCA_9"],
        }
        payload = {
            "products": [
                {
                    "id": 87,
                    "name": "SPECIAL 20G KVM PROMO V5 - CN2 GIA ECOMMERCE",
                    "outOfStock": False,
                    "tiers": ["ecommerce"],
                    "datacenters": {"USCA_6": 50},
                    "prices": [{"period": "Quarterly", "cents": 4999}],
                },
                {
                    "id": 88,
                    "name": "Sold out CN2 plan",
                    "outOfStock": True,
                    "tiers": ["ecommerce"],
                    "datacenters": {"USCA_9": 55},
                    "prices": [{"period": "Quarterly", "cents": 8999}],
                },
            ]
        }
        result = check_bwh_json(provider, 200, json.dumps(payload))
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["plans"][0]["product_id"], 87)
        self.assertTrue(result["plans"][0]["available"])
        self.assertFalse(result["plans"][1]["available"])
        self.assertEqual(result["plans"][0]["prices"][0]["amount"], 49.99)
        self.assertFalse(result["plans"][0]["prices"][0]["price_eligible"])

    def test_catalog_page_is_not_reported_as_stock(self):
        provider = {
            "id": "hostdare-lax-cn2",
            "provider": "HostDare",
            "region": "Los Angeles, US",
            "priority": "cn2",
            "network": "CN2",
            "url": "https://example.invalid/catalog",
            "stock_signal": "catalog",
        }
        result = check_html(provider, 200, "Order Now")
        self.assertEqual(result["status"], "catalog_only")

    def test_zgovps_whmcs_offer_parses_target_annual_plan_stock(self):
        provider = {
            "id": "zgovps-lax-special-52",
            "provider": "ZgoVPS",
            "region": "Los Angeles, US",
            "priority": "cn2",
            "network": "GIA / 9929 / CMIN2",
            "url": "https://clients.zgovps.com/index.php?/cart/special-offer/",
            "plan_name": "Los Angeles AMD Optimised VPS - Specials - Starter",
            "target_price": 52.0,
            "target_period": "year",
        }
        html = """
        <form method="post">
          <input name="id" type="hidden" value="134">
          <strong>Los Angeles AMD Optimised VPS - Specials - Starter</strong>
          <div><li>1 Core AMD EPYC</li><li>GIA&amp;9929&amp;CMIN2</li></div>
          <select name="cycle"><option value="a" selected>$52.00 USD Annually</option></select>
          <button disabled="disabled">Out of stock!</button>
        </form>
        <form method="post">
          <input name="id" type="hidden" value="121">
          <strong>HongKong AMD VPS - Specials - Starter</strong>
          <select name="cycle"><option value="a" selected>$52.00 USD Annually</option></select>
          <button>Continue</button>
        </form>
        """
        result = check_whmcs_offer_html(provider, 200, html)
        self.assertEqual(result["status"], "out_of_stock")
        self.assertEqual(len(result["plans"]), 1)
        self.assertEqual(result["plans"][0]["product_id"], 134)
        self.assertEqual(result["plans"][0]["price"]["amount"], 52.0)
        self.assertEqual(result["plans"][0]["price"]["period"], "year")
        self.assertTrue(result["plans"][0]["price"]["price_eligible"])
        self.assertFalse(result["plans"][0]["available"])

    def test_zgovps_whmcs_offer_parses_target_quarterly_plan_stock(self):
        provider = {
            "id": "zgovps-lax-optimized-starter-18-quarterly",
            "provider": "ZgoVPS",
            "region": "Los Angeles, US",
            "priority": "cn2",
            "network": "GIA / 9929 / CMIN2",
            "url": "https://clients.zgovps.com/index.php?/cart/los-angeles-amd-optimised-vps/",
            "plan_name": "Starter",
            "target_price": 18.0,
            "target_period": "quarter",
        }
        html = """
        <form method="post">
          <input name="id" type="hidden" value="142">
          <strong class="mb-3">Starter</strong>
          <select name="cycle">
            <option value="q" selected="selected">$18.00 USD Quarterly</option>
            <option value="s">$34.00 USD Semi-Annually</option>
          </select>
          <button disabled="disabled">Out of stock!</button>
        </form>
        """
        result = check_whmcs_offer_html(provider, 200, html)
        self.assertEqual(result["status"], "out_of_stock")
        self.assertEqual(result["plans"][0]["product_id"], 142)
        self.assertEqual(result["plans"][0]["price"]["period"], "quarter")
        self.assertEqual(result["plans"][0]["price"]["monthly_equivalent"], 6.0)
        self.assertTrue(result["plans"][0]["price"]["price_eligible"])
        self.assertFalse(result["plans"][0]["available"])

    def test_zgovps_52_dollar_offers_are_separate_default_sources(self):
        sources = {item["id"]: item for item in select_providers()}
        self.assertEqual(sources["zgovps-lax-special-52"]["target_price"], 52.0)
        self.assertEqual(sources["zgovps-lax-optimized-starter-18-quarterly"]["target_price"], 18.0)
        self.assertEqual(sources["zgovps-lax-optimized-starter-18-quarterly"]["target_period"], "quarter")
        self.assertEqual(sources["zgovps-hkg-special-52"]["target_price"], 52.0)
        self.assertEqual(sources["zgovps-lax-special-52"]["priority"], "cn2")

    def test_dedione_html_parses_target_annual_product_card(self):
        provider = {
            "id": "dedione-lax-cmin2-1c1g10g-annual",
            "provider": "DediOne",
            "region": "Los Angeles, US",
            "priority": "cn2",
            "network": "CMIN2 / AS58807; CUII / AS9929; no CN2",
            "url": "https://dedione.com/store/los-angeles-kvm-vps-cmin2-cuii",
            "plan_name": "LAX.VPS.CMIN2.1C1G10G-Annual",
            "target_price": 29.99,
            "target_period": "year",
        }
        html = """
        <div class="package" id="product243">
          <h3 class="package-title">LAX.VPS.CMIN2.1C1G10G-Annual</h3>
          <div class="price-amount">$29.99 USD</div>
          <div class="price-cycle">Annually</div>
          <a class="btn btn-primary btn-order-now">Order Now</a>
        </div>
        <div class="package" id="product244">
          <h3 class="package-title">LAX.VPS.CMIN2.2C2G20G-Annual</h3>
          <div class="price-amount">$59.99 USD</div>
          <div class="price-cycle">Annually</div>
          <a class="btn btn-primary btn-order-now">Order Now</a>
        </div>
        """
        result = check_dedione_html(provider, 200, html)
        self.assertEqual(result["status"], "available")
        self.assertEqual(len(result["plans"]), 1)
        self.assertEqual(result["plans"][0]["price"]["amount"], 29.99)
        self.assertEqual(result["plans"][0]["price"]["monthly_equivalent"], 2.5)
        self.assertTrue(result["plans"][0]["price"]["price_eligible"])
        self.assertTrue(result["plans"][0]["available"])

    def test_dedione_html_marks_target_product_without_order_action_sold_out(self):
        provider = {
            "id": "dedione-lax-cmin2-1c1g10g-annual",
            "provider": "DediOne",
            "region": "Los Angeles, US",
            "priority": "cn2",
            "network": "CMIN2 / AS58807; CUII / AS9929; no CN2",
            "url": "https://dedione.com/store/los-angeles-kvm-vps-cmin2-cuii",
            "plan_name": "LAX.VPS.CMIN2.1C1G10G-Annual",
            "target_price": 29.99,
            "target_period": "year",
        }
        html = """
        <div class="package" id="product243">
          <h3 class="package-title">LAX.VPS.CMIN2.1C1G10G-Annual</h3>
          <div class="price-amount">$29.99 USD</div>
          <div class="price-cycle">Annually</div>
          <span>Out of stock</span>
        </div>
        """
        result = check_dedione_html(provider, 200, html)
        self.assertEqual(result["status"], "out_of_stock")
        self.assertFalse(result["plans"][0]["available"])

    def test_novixlink_sources_are_separate_cn2_stock_sources(self):
        sources = {item["id"]: item for item in select_providers()}
        self.assertEqual(
            sources["novixlink-ntt-isp-vps"]["url"],
            "https://novixlink.com/store/nttispipvps",
        )
        self.assertEqual(
            sources["novixlink-gtt-isp-vps"]["url"],
            "https://novixlink.com/store/us-lacup-isp",
        )
        self.assertEqual(sources["novixlink-ntt-isp-vps"]["priority"], "cn2")

    def test_default_selection_is_the_focus_group(self):
        focused = {item["id"] for item in select_providers()}
        self.assertIn("colocrossing-cloud-vps-1gb", focused)
        self.assertIn("colocrossing-cloud-vps-2gb", focused)
        self.assertIn("buyvm-lv", focused)
        self.assertIn("greencloud-store", focused)
        self.assertIn("dmit-x", focused)
        self.assertIn("hostdare-lax-cn2", focused)
        self.assertIn("hostdare-lax-cn2-amd", focused)
        self.assertIn("hostdare-lax-cn2-hdd", focused)
        self.assertIn("bwh-lax-cn2", focused)
        self.assertIn("zgovps-lax-optimized-starter-18-quarterly", focused)
        self.assertIn("dedione-lax-cmin2-1c1g10g-annual", focused)
        self.assertNotIn("greencloud-x", focused)
        self.assertNotIn("racknerd-lax", focused)
        self.assertNotIn("cloudcone-lax", focused)

    def test_all_selection_includes_low_priority_fallbacks(self):
        all_ids = {item["id"] for item in select_providers(all_providers=True)}
        self.assertNotIn("cloudcone-lax", all_ids)
        self.assertNotIn("racknerd-lax", all_ids)

    def test_default_sources_include_social_checks_for_default_providers(self):
        sources = {item["id"] for item in select_sources()}
        self.assertIn("dmit-x", sources)
        self.assertIn("dmit-reddit", sources)
        self.assertIn("racknerd-reddit", sources)
        self.assertIn("racknerd-x", sources)
        self.assertIn("cloudcone-x", sources)
        self.assertIn("cloudcone-reddit", sources)
        self.assertNotIn("buyvm-x", sources)
        self.assertNotIn("greencloud-reddit", sources)
        self.assertNotIn("hostdare-x", sources)
        self.assertNotIn("bwh-reddit", sources)
        self.assertIn("vps-discovery-reddit-vps-restock", sources)
        self.assertIn("vps-discovery-x-cn2-vps", sources)

    def test_non_social_selection_excludes_x_and_reddit_sources(self):
        sources = {item["id"] for item in select_non_social_providers()}
        self.assertIn("buyvm-lv", sources)
        self.assertIn("greencloud-store", sources)
        self.assertIn("bwh-lax-cn2", sources)
        self.assertNotIn("dmit-x", sources)
        self.assertNotIn("racknerd-lax", sources)
        self.assertNotIn("cloudcone-lax", sources)

    def test_monitorability_describes_non_social_boundaries(self):
        rows = {item["id"]: item for item in monitorability()}
        self.assertEqual(rows["buyvm-lv"]["level"], "stock")
        self.assertEqual(rows["buyvm-ny"]["level"], "stock")
        self.assertEqual(rows["buyvm-miami"]["level"], "stock")
        self.assertEqual(rows["buyvm-switzerland"]["level"], "stock")
        self.assertEqual(rows["greencloud-store"]["level"], "stock")
        self.assertEqual(rows["hostdare-lax-cn2"]["level"], "stock")
        self.assertEqual(rows["hostdare-lax-cn2-amd"]["level"], "stock")
        self.assertEqual(rows["hostdare-lax-cn2-hdd"]["level"], "stock")
        self.assertEqual(rows["bwh-lax-cn2"]["level"], "stock")
        self.assertEqual(rows["zgovps-lax-special-52"]["level"], "stock")
        self.assertEqual(rows["zgovps-lax-optimized-starter-18-quarterly"]["level"], "stock")
        self.assertEqual(rows["dedione-lax-cmin2-1c1g10g-annual"]["level"], "order_signal")
        self.assertEqual(rows["zgovps-hkg-special-52"]["level"], "stock")
        self.assertEqual(rows["novixlink-ntt-isp-vps"]["level"], "stock")
        self.assertEqual(rows["novixlink-gtt-isp-vps"]["level"], "stock")
        self.assertEqual(rows["colocrossing-cloud-vps-1gb"]["level"], "order_signal")
        self.assertEqual(rows["colocrossing-cloud-vps-2gb"]["level"], "order_signal")
        self.assertNotIn("dmit-x", rows)
        self.assertNotIn("racknerd-lax", rows)

    def test_cn2_selection_keeps_official_cn2_and_dmit_social_sources(self):
        sources = {item["id"] for item in select_sources(cn2_only=True)}
        self.assertEqual(
            sources,
            {
                "dmit-x",
                "hostdare-lax-cn2",
                "hostdare-lax-cn2-amd",
                "hostdare-lax-cn2-hdd",
                "bwh-lax-cn2",
                "novixlink-ntt-isp-vps",
                "novixlink-gtt-isp-vps",
                "zgovps-lax-special-52",
                "zgovps-lax-optimized-starter-18-quarterly",
                "dedione-lax-cmin2-1c1g10g-annual",
                "dmit-reddit",
                "vps-discovery-reddit-cn2-vps",
                "vps-discovery-x-cn2-vps",
            },
        )

    @patch("vps_stock.subprocess.run")
    def test_twitter_check_reports_community_restock_lead(self, run):
        run.return_value.returncode = 0
        run.return_value.stderr = ""
        run.return_value.stdout = json.dumps(
            {
                "data": [
                    {
                        "id": "123",
                        "text": "DMIT 洛杉矶补货了，快去看看。",
                        "author": {"screenName": "vps_watcher"},
                        "createdAtISO": "2026-07-12T00:00:00+00:00",
                    },
                    {
                        "id": "456",
                        "text": "DMIT 补货后已经被抢空。",
                        "author": {"screenName": "vps_watcher"},
                        "createdAtISO": "2026-07-12T00:00:00+00:00",
                    },
                    {
                        "id": "789",
                        "text": "DMIT 补货了，使用我的优惠码购买。",
                        "author": {"screenName": "promoter"},
                        "createdAtISO": "2026-07-12T00:00:00+00:00",
                    },
                ]
            }
        )
        provider = {
            "id": "dmit-x",
            "provider": "DMIT",
            "region": "US",
            "priority": "cn2",
            "network": "community X leads",
            "url": "https://x.com/search?q=DMIT",
            "twitter_query": "DMIT 补货",
            "twitter_keywords": ["dmit"],
            "twitter_official": False,
        }
        result = check_twitter(provider, since="2026-07-01")
        self.assertEqual(result["status"], "lead")
        self.assertEqual(result["confidence"], "low")
        self.assertEqual([post["id"] for post in result["posts"]], ["x:123"])

    @patch("vps_stock.subprocess.run")
    def test_twitter_default_search_window_is_three_days(self, run):
        run.return_value.returncode = 0
        run.return_value.stderr = ""
        run.return_value.stdout = json.dumps({"data": []})
        provider = {
            "id": "dmit-x",
            "provider": "DMIT",
            "region": "US",
            "priority": "cn2",
            "network": "community X leads",
            "url": "https://x.com/search?q=DMIT",
            "twitter_query": "DMIT",
            "twitter_keywords": ["dmit"],
        }
        check_twitter(provider)
        command = run.call_args.args[0]
        since = command[command.index("--since") + 1]
        self.assertEqual(since, (date.today() - timedelta(days=3)).isoformat())

    @patch("vps_stock._run_twitter_opencli")
    @patch("vps_stock.subprocess.run")
    def test_twitter_check_falls_back_to_opencli_after_twitter_cli_error(self, run, opencli):
        run.return_value.returncode = 1
        run.return_value.stderr = "Twitter API error (HTTP 404)"
        run.return_value.stdout = ""
        opencli.return_value.returncode = 0
        opencli.return_value.stderr = ""
        opencli.return_value.stdout = json.dumps(
            [
                {
                    "id": "789",
                    "text": "DMIT 洛杉矶补货了。",
                    "author": "vps_watcher",
                    "created_at": "Fri Jul 17 06:36:38 +0000 2026",
                }
            ]
        )
        provider = {
            "id": "dmit-x",
            "provider": "DMIT",
            "region": "US",
            "priority": "cn2",
            "network": "community X leads",
            "url": "https://x.com/search?q=DMIT",
            "twitter_query": "DMIT",
            "twitter_keywords": ["dmit"],
        }

        result = check_twitter(provider, since="2026-07-15")

        self.assertEqual(result["status"], "lead")
        self.assertEqual(result["posts"][0]["id"], "x:789")
        fallback_command = opencli.call_args.args[0]
        self.assertIn("since:2026-07-15", fallback_command[3])

    def test_opencli_legacy_timestamp_is_normalized_to_iso(self):
        posts = _parse_twitter_posts(
            json.dumps([{"id": "1", "text": "restock", "author": "w", "created_at": "Fri Jul 17 06:36:38 +0000 2026"}]),
            source="opencli",
        )
        self.assertEqual(posts[0]["createdAtISO"], "2026-07-17T06:36:38+00:00")

    def test_discovery_keeps_opencli_lead_carrying_a_legacy_timestamp(self):
        now = 2_000_000_000
        text = "NovaHost VPS restock: Los Angeles CN2 GIA $5/mo, 2GB RAM, 40GB NVMe, currently in stock."
        posts = _parse_twitter_posts(
            json.dumps([{"id": "np", "text": text, "author": "vps_user", "created_at": "Tue May 17 12:00:00 +0000 2033"}]),
            source="opencli",
        )

        leads = filter_discovery_posts(posts, now=now, source="x")

        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["provider"], "NovaHost")

    @patch("vps_stock._run_reddit_opencli")
    def test_reddit_check_reports_recent_restock_lead(self, run):
        run.return_value.returncode = 0
        run.return_value.stderr = ""
        recent_timestamp = time.time() - 3600
        run.return_value.stdout = json.dumps(
            [
                {
                    "id": "abc",
                    "title": "RackNerd VPS restock is live",
                    "selftext": "Limited sale inventory is available.",
                    "author": "vps_user",
                    "created_utc": recent_timestamp,
                    "url": "https://www.reddit.com/r/example/comments/abc",
                },
                {
                    "id": "def",
                    "title": "RackNerd stock sold out",
                    "selftext": "",
                    "author": "vps_user",
                    "created_utc": recent_timestamp,
                    "url": "https://www.reddit.com/r/example/comments/def",
                },
            ]
        )
        provider = {
            "id": "racknerd-reddit",
            "provider": "RackNerd",
            "region": "US",
            "priority": "value",
            "network": "community Reddit leads",
            "url": "https://www.reddit.com/search/?q=RackNerd",
            "reddit_query": "RackNerd",
            "reddit_keywords": ["racknerd"],
        }
        result = check_reddit(provider)
        self.assertEqual(result["status"], "lead")
        self.assertEqual([post["id"] for post in result["posts"]], ["reddit:abc"])

    def test_reddit_opencli_timeout_terminates_process_group(self):
        runner = getattr(vps_stock, "_run_reddit_opencli", None)
        self.assertIsNotNone(runner)
        command = ["opencli", "reddit", "search", "cheap VPS"]
        process = unittest.mock.MagicMock()
        process.pid = 12345
        process.communicate.side_effect = subprocess.TimeoutExpired(command, 10)
        process.wait.return_value = None

        with patch("vps_stock.subprocess.Popen", return_value=process):
            with patch("vps_stock.os.killpg") as killpg:
                with self.assertRaises(RuntimeError):
                    runner(command, timeout=10, env={})

        killpg.assert_called_once_with(12345, signal.SIGTERM)

    @patch("vps_stock._run_reddit_opencli")
    def test_reddit_cli_env_restores_user_command_paths(self, run):
        run.return_value.returncode = 0
        run.return_value.stderr = ""
        run.return_value.stdout = "[]"
        provider = {
            "id": "racknerd-reddit",
            "provider": "RackNerd",
            "region": "US",
            "priority": "value",
            "network": "community Reddit leads",
            "url": "https://www.reddit.com/search/?q=RackNerd",
            "reddit_query": "RackNerd",
            "reddit_keywords": ["racknerd"],
        }

        with patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
            check_reddit(provider)

        command_path = run.call_args.args[2]["PATH"].split(os.pathsep)
        self.assertIn(str(Path.home() / ".npm-global" / "bin"), command_path)
        self.assertIn("/usr/local/bin", command_path)
        self.assertIn("/opt/homebrew/bin", command_path)
        self.assertIn("/usr/bin", command_path)

    @patch("vps_stock._run_reddit_opencli")
    def test_reddit_excludes_posts_older_than_three_days(self, run):
        run.return_value.returncode = 0
        run.return_value.stderr = ""
        run.return_value.stdout = json.dumps(
            [
                {
                    "id": "recent",
                    "title": "RackNerd VPS restock is live",
                    "selftext": "Limited sale inventory is available.",
                    "author": "vps_user",
                    "created_utc": int(time.time()) - 2 * 24 * 60 * 60,
                    "url": "https://www.reddit.com/r/example/comments/recent",
                },
                {
                    "id": "old",
                    "title": "RackNerd VPS restock is live",
                    "selftext": "Limited sale inventory is available.",
                    "author": "vps_user",
                    "created_utc": int(time.time()) - 4 * 24 * 60 * 60,
                    "url": "https://www.reddit.com/r/example/comments/old",
                },
            ]
        )
        provider = {
            "id": "racknerd-reddit",
            "provider": "RackNerd",
            "region": "US",
            "priority": "value",
            "network": "community Reddit leads",
            "url": "https://www.reddit.com/search/?q=RackNerd",
            "reddit_query": "RackNerd",
            "reddit_keywords": ["racknerd"],
        }
        result = check_reddit(provider)
        self.assertEqual([post["id"] for post in result["posts"]], ["reddit:recent"])

    @patch("vps_stock.fetch")
    @patch("vps_stock._run_reddit_opencli")
    def test_reddit_falls_back_to_public_json_after_opencli_html_error(self, run, fetch):
        run.return_value.returncode = 1
        run.return_value.stderr = "SyntaxError: Unexpected token '<'"
        run.return_value.stdout = "<body class=error>blocked</body>"
        fetch.return_value = (
            200,
            json.dumps(
                {
                    "data": {
                        "children": [
                            {
                                "data": {
                                    "id": "fallback",
                                    "title": "RackNerd VPS restock is live",
                                    "selftext": "Limited sale inventory is available.",
                                    "author": "vps_user",
                                    "created_utc": time.time() - 3600,
                                    "url": "https://www.reddit.com/r/example/comments/fallback",
                                }
                            }
                        ]
                    }
                }
            ),
        )
        provider = {
            "id": "racknerd-reddit",
            "provider": "RackNerd",
            "region": "US",
            "priority": "value",
            "network": "community Reddit leads",
            "url": "https://www.reddit.com/search/?q=RackNerd",
            "reddit_query": "RackNerd",
            "reddit_keywords": ["racknerd"],
        }

        result = check_reddit(provider)

        self.assertEqual(result["status"], "lead")
        self.assertEqual([post["id"] for post in result["posts"]], ["reddit:fallback"])
        self.assertIn("search.json", fetch.call_args.args[0])

    @patch("vps_stock.fetch")
    @patch("vps_stock._run_reddit_opencli")
    def test_reddit_falls_back_to_atom_after_json_is_forbidden(self, run, fetch):
        run.return_value.returncode = 1
        run.return_value.stderr = "Detached while handling command"
        run.return_value.stdout = ""
        updated = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        atom = """
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <author><name>vps_user</name></author>
            <content type="html">&lt;div&gt;Limited sale inventory is available.&lt;/div&gt;</content>
            <id>t3_atom-fallback</id>
            <link href="https://www.reddit.com/r/example/comments/atom-fallback/" />
            <updated>%s</updated>
            <title>RackNerd VPS restock is live</title>
          </entry>
        </feed>
        """ % updated
        fetch.side_effect = [(403, "blocked"), (200, atom)]
        provider = {
            "id": "racknerd-reddit",
            "provider": "RackNerd",
            "region": "US",
            "priority": "value",
            "network": "community Reddit leads",
            "url": "https://www.reddit.com/search/?q=RackNerd",
            "reddit_query": "RackNerd",
            "reddit_keywords": ["racknerd"],
        }

        result = check_reddit(provider)

        self.assertEqual(result["status"], "lead")
        self.assertEqual([post["id"] for post in result["posts"]], ["reddit:atom-fallback"])
        self.assertIn("search.rss", fetch.call_args_list[1].args[0])

    @patch("vps_stock._append_memory_line")
    @patch("vps_stock.check_provider")
    @patch("vps_stock.select_sources")
    def test_main_stdout_keeps_transition_summary_parseable(self, select_sources_mock, check_provider_mock, append_memory):
        provider = {
            "id": "dmit-reddit",
            "provider": "DMIT",
            "region": "US",
            "priority": "cn2",
            "network": "community Reddit leads",
            "url": "https://www.reddit.com/search/?q=DMIT",
            "kind": "reddit_search",
        }
        result = {
            "id": "dmit-reddit",
            "provider": "DMIT",
            "region": "US",
            "status": "lead",
            "confidence": "low",
            "posts": [{"id": "reddit:new"}],
        }
        select_sources_mock.return_value = [provider]
        check_provider_mock.return_value = result

        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.json"
            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                exit_code = main(["--state-file", str(state_file)])

        self.assertEqual(exit_code, 0)
        output = json.loads(stdout.getvalue())
        self.assertIn("transitions", output)
        self.assertEqual(output["transitions"][0]["event"], "social_lead")
        self.assertNotIn("items", output)

    def test_new_twitter_post_is_a_transition(self):
        result = {
            "id": "dmit-x",
            "status": "lead",
            "posts": [{"id": "123"}],
        }
        old = {
            "dmit-x": {"status": "lead", "posts": [{"id": "100"}]}
        }
        transitions = find_transitions([result], old)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["event"], "social_lead")

    def test_discovery_filter_keeps_recent_concrete_unlisted_vps_lead(self):
        now = 2_000_000_000
        posts = [
            {
                "id": "new-provider",
                "title": "NovaHost VPS restock: Los Angeles CN2 GIA $5/mo",
                "selftext": "2GB RAM, 40GB NVMe, 2TB traffic, currently in stock.",
                "author": "vps_user",
                "created_utc": now - 24 * 60 * 60,
                "url": "https://www.reddit.com/r/example/comments/new-provider",
            }
        ]

        leads = filter_discovery_posts(posts, now=now)

        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["id"], "reddit:new-provider")
        self.assertEqual(leads[0]["label"], "待官网复核线索")
        self.assertEqual(leads[0]["provider"], "NovaHost")
        self.assertEqual(leads[0]["prices"][0]["monthly_equivalent"], 5.0)
        self.assertIn("CN2", leads[0]["evidence"]["routes"])

    def test_discovery_filter_rejects_noise_old_sold_out_and_over_budget_posts(self):
        now = 2_000_000_000
        posts = [
            {
                "id": "referral",
                "title": "Cheap VPS referral code",
                "selftext": "Use my invite link for a discount.",
                "author": "affiliate",
                "created_utc": now - 60 * 60,
                "url": "https://www.reddit.com/r/example/comments/referral",
            },
            {
                "id": "old",
                "title": "Old VPS restock $5/mo",
                "selftext": "CN2 and in stock.",
                "author": "vps_user",
                "created_utc": now - 4 * 24 * 60 * 60,
                "url": "https://www.reddit.com/r/example/comments/old",
            },
            {
                "id": "sold-out",
                "title": "VPS restock sold out",
                "selftext": "CN2, $5/mo, no stock left.",
                "author": "vps_user",
                "created_utc": now - 60 * 60,
                "url": "https://www.reddit.com/r/example/comments/sold-out",
            },
            {
                "id": "expensive",
                "title": "Premium VPS sale $25/mo",
                "selftext": "Los Angeles, 8GB RAM, available now.",
                "author": "vps_user",
                "created_utc": now - 60 * 60,
                "url": "https://www.reddit.com/r/example/comments/expensive",
            },
        ]

        self.assertEqual(filter_discovery_posts(posts, now=now), [])

    @patch("vps_stock.subprocess.run")
    def test_twitter_discovery_uses_the_shared_concrete_evidence_filter(self, run):
        run.return_value.returncode = 0
        run.return_value.stderr = ""
        run.return_value.stdout = json.dumps(
            {
                "data": [
                    {
                        "id": "x-new-provider",
                        "text": "NovaHost VPS restock in Los Angeles CN2 GIA $5/mo, 2GB RAM, available now",
                        "author": {"screenName": "vps_watcher"},
                        "createdAtISO": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
                    }
                ]
            }
        )
        provider = {
            "id": "vps-discovery-x-vps-restock",
            "provider": "VPS discovery",
            "region": "global",
            "priority": "value",
            "network": "community discovery leads",
            "url": "https://x.com/search?q=VPS+restock",
            "twitter_query": "VPS restock",
        }

        result = check_twitter_discovery(provider)

        self.assertEqual(result["status"], "lead")
        self.assertEqual(result["posts"][0]["id"], "x:x-new-provider")
        self.assertEqual(result["posts"][0]["provider"], "NovaHost")

    def test_prune_state_posts_removes_social_posts_older_than_three_days(self):
        now = 2_000_000_000
        state = {
            "dmit-reddit": {
                "status": "lead",
                "posts": [
                    {"id": "reddit:recent", "created_at": now - 2 * 24 * 60 * 60},
                    {"id": "reddit:old", "created_at": now - 4 * 24 * 60 * 60},
                ],
            }
        }

        cleaned = prune_state_posts(state, now=now)

        self.assertEqual([post["id"] for post in cleaned["dmit-reddit"]["posts"]], ["reddit:recent"])
        self.assertEqual([post["id"] for post in state["dmit-reddit"]["posts"]], ["reddit:recent", "reddit:old"])

    def test_prune_state_posts_revalidates_discovery_filter_rules(self):
        now = 2_000_000_000
        state = {
            "vps-discovery-x-vps-sale": {
                "status": "lead",
                "posts": [
                    {
                        "id": "x:bad-ad",
                        "created_at": now - 60 * 60,
                        "title": "Forex copy trading sale",
                        "text": "$499 for 1 year, no VPS required.",
                        "url": "https://x.com/example/status/bad-ad",
                    }
                ],
            }
        }

        cleaned = prune_state_posts(state, now=now)

        self.assertEqual(cleaned["vps-discovery-x-vps-sale"]["posts"], [])

    def test_dedupe_discovery_results_keeps_one_copy_of_a_cross_query_post(self):
        results = [
            {"id": "vps-discovery-reddit-vps-sale", "status": "lead", "posts": [{"id": "reddit:same"}]},
            {"id": "vps-discovery-reddit-cheap-vps", "status": "lead", "posts": [{"id": "reddit:same"}]},
        ]

        cleaned = dedupe_discovery_results(results)

        self.assertEqual([post["id"] for post in cleaned[0]["posts"]], ["reddit:same"])
        self.assertEqual(cleaned[1]["posts"], [])
        self.assertEqual(cleaned[1]["status"], "no_recent_signal")

    def test_compact_memory_keeps_only_recent_nonempty_lines(self):
        content = "\n".join("run-%02d" % index for index in range(25)) + "\n"

        compacted = compact_memory(content, keep_lines=20)

        self.assertNotIn("run-04", compacted)
        self.assertIn("run-05", compacted)
        self.assertIn("run-24", compacted)
        self.assertEqual(len(compacted.strip().splitlines()), 20)

    def test_discovery_filter_rejects_off_topic_ads_and_affiliate_articles(self):
        now = 2_000_000_000
        posts = [
            {
                "id": "forex-ad",
                "title": "Best US30 Forex copy trading flash sale",
                "selftext": "$499 for 1 year, no VPS or computer required.",
                "author": "trader",
                "created_utc": now - 60 * 60,
                "url": "https://www.reddit.com/r/example/comments/forex-ad",
            },
            {
                "id": "affiliate-vps",
                "title": "CN2 GIA VPS recommendations",
                "selftext": "搬瓦工和 DMIT 最近补货，闭眼冲。传送门: https://t.co/example",
                "author": "affiliate",
                "created_utc": now - 60 * 60,
                "url": "https://www.reddit.com/r/example/comments/affiliate-vps",
            },
            {
                "id": "serverless",
                "title": "Cheap VPS infrastructure is a serverless trap",
                "selftext": "Serverless costs $1.5/mo at small scale; this is a technical essay, not a VPS offer.",
                "author": "engineer",
                "created_utc": now - 60 * 60,
                "url": "https://www.reddit.com/r/example/comments/serverless",
            },
            {
                "id": "crypto-ad",
                "title": "VPS sale: build on the Robinhood Chain",
                "selftext": "Crypto infrastructure is available now for $1.2/mo with a limited sale.",
                "author": "crypto_marketer",
                "created_utc": now - 60 * 60,
                "url": "https://www.reddit.com/r/example/comments/crypto-ad",
            },
            {
                "id": "coupon-ad",
                "title": "CSTserver CN2 VPS restock",
                "selftext": "Los Angeles CN2, 16GB RAM, $9/mo, use coupon code CSTOU4.",
                "author": "vps_promoter",
                "created_utc": now - 60 * 60,
                "url": "https://www.reddit.com/r/example/comments/coupon-ad",
            },
            {
                "id": "generic-available",
                "title": "My AI coding setup is available for $1/mo",
                "selftext": "I use a VPS for development, but there is no provider, location, route, or configuration here.",
                "author": "developer",
                "created_utc": now - 60 * 60,
                "url": "https://www.reddit.com/r/example/comments/generic-available",
            },
        ]

        self.assertEqual(filter_discovery_posts(posts, now=now), [])


if __name__ == "__main__":
    unittest.main()