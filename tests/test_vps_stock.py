import json
import io
import os
import sys
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from vps_stock import (  # noqa: E402
    check_bwh_json,
    check_counted_html,
    check_frantech_html,
    check_html,
    check_reddit,
    check_twitter_discovery,
    check_twitter,
    check_whmcs_offer_html,
    compact_memory,
    dedupe_discovery_results,
    find_transitions,
    filter_discovery_posts,
    main,
    monitorability,
    prune_state_posts,
    select_non_social_providers,
    select_providers,
    select_sources,
)


class VpsStockParsingTests(unittest.TestCase):
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

    def test_zgovps_52_dollar_offers_are_separate_default_sources(self):
        sources = {item["id"]: item for item in select_providers()}
        self.assertEqual(sources["zgovps-lax-special-52"]["target_price"], 52.0)
        self.assertEqual(sources["zgovps-hkg-special-52"]["target_price"], 52.0)
        self.assertEqual(sources["zgovps-lax-special-52"]["priority"], "cn2")

    def test_default_selection_is_the_focus_group(self):
        focused = {item["id"] for item in select_providers()}
        self.assertIn("buyvm-lv", focused)
        self.assertIn("greencloud-store", focused)
        self.assertIn("dmit-x", focused)
        self.assertIn("hostdare-lax-cn2", focused)
        self.assertIn("hostdare-lax-cn2-amd", focused)
        self.assertIn("hostdare-lax-cn2-hdd", focused)
        self.assertIn("bwh-lax-cn2", focused)
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
        self.assertEqual(rows["zgovps-hkg-special-52"]["level"], "stock")
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
                "zgovps-lax-special-52",
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

    @patch("vps_stock.subprocess.run")
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

    @patch("vps_stock.subprocess.run")
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

        command_path = run.call_args.kwargs["env"]["PATH"].split(os.pathsep)
        self.assertIn(str(Path.home() / ".npm-global" / "bin"), command_path)
        self.assertIn("/usr/local/bin", command_path)
        self.assertIn("/opt/homebrew/bin", command_path)
        self.assertIn("/usr/bin", command_path)

    @patch("vps_stock.subprocess.run")
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
    @patch("vps_stock.subprocess.run")
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
    @patch("vps_stock.subprocess.run")
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
        ]

        self.assertEqual(filter_discovery_posts(posts, now=now), [])


if __name__ == "__main__":
    unittest.main()
