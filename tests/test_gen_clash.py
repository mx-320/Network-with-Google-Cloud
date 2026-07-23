#!/usr/bin/env python3
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
GENERATOR = PROJECT_ROOT / "core" / "gen-clash.py"


class GenerateClashConfigTest(unittest.TestCase):
    def test_generates_one_config_per_device_from_shared_core(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "deploy.conf").write_text(
                "\n".join(
                    [
                        "REALITY_PORT=443",
                        "REALITY_TARGET=1.1.1.1:443",
                        "REALITY_SNI=",
                        "DEVICES=mac phone",
                        "CDN_ENABLE=false",
                    ]
                )
                + "\n"
            )
            (root / ".secrets.env").write_text(
                "\n".join(
                    [
                        "STATIC_IP=203.0.113.10",
                        "REALITY_PUBLIC=test-public-key",
                        "REALITY_SHORTID=0123456789abcdef",
                        "HY2_PORT=31000",
                        "ANYTLS_PORT=21000",
                        "ANYTLS_PASS=test-anytls-pass",
                        "REALITY_UUID_mac=00000000-0000-4000-8000-000000000001",
                        "HY2_PASS_mac=test-hy2-mac",
                        "REALITY_UUID_phone=00000000-0000-4000-8000-000000000002",
                        "HY2_PASS_phone=test-hy2-phone",
                    ]
                )
                + "\n"
            )

            env = os.environ.copy()
            env["NETWORK_NODE_ROOT"] = str(root)
            env["NETWORK_NODE_STATE_DIR"] = str(root)
            env["NETWORK_NODE_PROFILE"] = "test"
            result = subprocess.run(
                [sys.executable, str(GENERATOR)],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            outputs = sorted((root / "clash-configs").glob("*.yaml"))
            self.assertEqual([path.name for path in outputs], ["test-mac.yaml", "test-phone.yaml"])

            mac_path = root / "clash-configs" / "test-mac.yaml"
            mac = mac_path.read_text()
            self.assertEqual(mac_path.stat().st_mode & 0o777, 0o600)
            self.assertIn("server: 203.0.113.10", mac)
            self.assertIn('name: "US-Reality"', mac)
            self.assertNotIn('name: "US-Reality-WARP"', mac)
            self.assertIn('name: "US-HY2"', mac)
            self.assertIn('name: "US-AnyTLS"', mac)
            self.assertIn("test-hy2-mac", mac)
            self.assertNotIn("test-hy2-phone", mac)
            self.assertIn('name: "🛟 自动故障切换"', mac)
            self.assertIn("type: fallback", mac)
            self.assertIn('      - "US-Reality"', mac)
            self.assertIn("  stack: mixed", mac)
            self.assertIn("  strict-route: true", mac)
            self.assertIn('    - "tcp://any:53"', mac)
            self.assertIn("  ipv6: false\n  enhanced-mode: fake-ip", mac)
            self.assertIn("  respect-rules: true", mac)
            self.assertIn("  follow-rule: true", mac)
            self.assertIn("  proxy-server-nameserver:", mac)
            self.assertIn("https://1.1.1.1/dns-query", mac)
            self.assertNotIn('    - "stun.*"', mac)
            self.assertIn('name: "🤖 AI 隐私出口"', mac)
            ai_group = mac.split('name: "🤖 AI 隐私出口"', 1)[1].split(
                'name: "🛟 自动故障切换"', 1
            )[0]
            self.assertIn("    type: fallback", ai_group)
            self.assertIn('      - "US-Reality"', ai_group)
            self.assertNotIn('      - "US-HY2"', ai_group)
            self.assertIn("  - RULE-SET,ai,🤖 AI 隐私出口", mac)
            self.assertIn("  - DOMAIN-KEYWORD,stun,🤖 AI 隐私出口", mac)
            cn_group = mac.split('name: "🇨🇳 国内流量"', 1)[1].split(
                'name: "🛑 屏蔽流量"', 1
            )[0]
            self.assertIn("    type: select", cn_group)
            self.assertLess(
                cn_group.index('      - "🌐 代理流量"'),
                cn_group.index("      - DIRECT"),
            )
            self.assertIn("  - RULE-SET,cn,🇨🇳 国内流量", mac)
            self.assertIn("  - RULE-SET,cn-ip,🇨🇳 国内流量,no-resolve", mac)
            self.assertIn("  - GEOIP,CN,🇨🇳 国内流量,no-resolve", mac)

            with (root / "deploy.conf").open("a") as conf:
                conf.write("PRIVACY_MODE=false\n")
            split_result = subprocess.run(
                [sys.executable, str(GENERATOR)], env=env, text=True,
                capture_output=True, check=False,
            )
            self.assertEqual(split_result.returncode, 0, split_result.stderr)
            split_config = mac_path.read_text()
            split_cn_group = split_config.split('name: "🇨🇳 国内流量"', 1)[1].split(
                'name: "🛑 屏蔽流量"', 1
            )[0]
            self.assertLess(
                split_cn_group.index("      - DIRECT"),
                split_cn_group.index('      - "🌐 代理流量"'),
            )
            self.assertIn("  - RULE-SET,cn,🇨🇳 国内流量", split_config)
            self.assertIn("  - GEOIP,CN,🇨🇳 国内流量,no-resolve", split_config)

    def test_cdn_only_config_omits_direct_ip_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "deploy.conf").write_text(
                "REALITY_PORT=443\nREALITY_TARGET=1.1.1.1:443\nREALITY_SNI=\n"
                "DEVICES=mac\nCDN_ENABLE=true\nCDN_ONLY=true\n"
                "CDN_HOSTNAME=cdn.example.com\n"
            )
            (root / ".secrets.env").write_text(
                "STATIC_IP=203.0.113.10\nREALITY_PUBLIC=test-public-key\n"
                "REALITY_SHORTID=0123456789abcdef\nHY2_PORT=31000\n"
                "ANYTLS_PORT=21000\nANYTLS_PASS=test-anytls-pass\n"
                "REALITY_UUID_mac=00000000-0000-4000-8000-000000000001\n"
                "HY2_PASS_mac=test-hy2-mac\nCDN_WS_PATH=private-path\n"
                "CDN_UUID_mac=00000000-0000-4000-8000-000000000003\n"
            )
            env = os.environ.copy()
            env["NETWORK_NODE_ROOT"] = str(root)
            env["NETWORK_NODE_STATE_DIR"] = str(root)
            env["NETWORK_NODE_PROFILE"] = "test"
            result = subprocess.run(
                [sys.executable, str(GENERATOR)],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            config = (root / "clash-configs" / "test-mac.yaml").read_text()
            self.assertIn('name: "US-CDN"', config)
            self.assertNotIn('name: "US-Reality"', config)
            self.assertNotIn('name: "US-HY2"', config)
            self.assertNotIn('name: "US-AnyTLS"', config)
            self.assertNotIn("203.0.113.10", config)
            ai_group = config.split('name: "🤖 AI 隐私出口"', 1)[1].split(
                'name: "🛟 自动故障切换"', 1
            )[0]
            self.assertIn("    type: fallback", ai_group)
            self.assertIn('      - "US-CDN"', ai_group)
            self.assertNotIn('      - "US-Reality"', ai_group)
            self.assertNotIn('      - "US-HY2"', ai_group)
            self.assertNotIn('      - "US-AnyTLS"', ai_group)

    def test_ai_privacy_fallback_prefers_reality_then_cdn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "deploy.conf").write_text(
                "REALITY_PORT=443\nREALITY_TARGET=1.1.1.1:443\nREALITY_SNI=\n"
                "DEVICES=mac\nCDN_ENABLE=true\nCDN_ONLY=false\n"
                "CDN_HOSTNAME=cdn.example.com\n"
            )
            (root / ".secrets.env").write_text(
                "STATIC_IP=203.0.113.10\nREALITY_PUBLIC=test-public-key\n"
                "REALITY_SHORTID=0123456789abcdef\nHY2_PORT=31000\n"
                "ANYTLS_PORT=21000\nANYTLS_PASS=test-anytls-pass\n"
                "REALITY_UUID_mac=00000000-0000-4000-8000-000000000001\n"
                "HY2_PASS_mac=test-hy2-mac\nCDN_WS_PATH=private-path\n"
                "CDN_UUID_mac=00000000-0000-4000-8000-000000000003\n"
            )
            env = os.environ.copy()
            env["NETWORK_NODE_ROOT"] = str(root)
            env["NETWORK_NODE_STATE_DIR"] = str(root)
            env["NETWORK_NODE_PROFILE"] = "test"
            result = subprocess.run(
                [sys.executable, str(GENERATOR)],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            config = (root / "clash-configs" / "test-mac.yaml").read_text()
            ai_group = config.split('name: "🤖 AI 隐私出口"', 1)[1].split(
                'name: "🛟 自动故障切换"', 1
            )[0]
            self.assertIn("    type: fallback", ai_group)
            reality_index = ai_group.index('      - "US-Reality"')
            cdn_index = ai_group.index('      - "US-CDN"')
            self.assertLess(reality_index, cdn_index)
            self.assertNotIn('      - "US-HY2"', ai_group)
            self.assertNotIn('      - "US-AnyTLS"', ai_group)
            self.assertNotIn('      - "US-Reality-WARP"', ai_group)

    def test_warp_reality_node_is_manual_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "deploy.conf").write_text(
                "REALITY_PORT=443\nREALITY_TARGET=1.1.1.1:443\nREALITY_SNI=\n"
                "DEVICES=mac\nCDN_ENABLE=false\nWARP_ENABLE=true\n"
            )
            (root / ".secrets.env").write_text(
                "STATIC_IP=203.0.113.10\nREALITY_PUBLIC=test-public-key\n"
                "REALITY_SHORTID=0123456789abcdef\nHY2_PORT=31000\n"
                "ANYTLS_PORT=21000\nANYTLS_PASS=test-anytls-pass\n"
                "REALITY_UUID_mac=00000000-0000-4000-8000-000000000001\n"
                "WARP_REALITY_PORT=42000\n"
                "WARP_REALITY_UUID_mac=00000000-0000-4000-8000-000000000004\n"
                "HY2_PASS_mac=test-hy2-mac\n"
            )
            env = os.environ.copy()
            env["NETWORK_NODE_ROOT"] = str(root)
            env["NETWORK_NODE_STATE_DIR"] = str(root)
            env["NETWORK_NODE_PROFILE"] = "test"
            result = subprocess.run(
                [sys.executable, str(GENERATOR)],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            config = (root / "clash-configs" / "test-mac.yaml").read_text()
            self.assertIn('name: "US-Reality"', config)
            self.assertIn('name: "US-Reality-WARP"', config)
            self.assertIn("port: 42000", config)
            fallback = config.split('name: "🛟 自动故障切换"', 1)[1].split(
                'name: "⚡ 自动测速"', 1
            )[0]
            self.assertIn('      - "US-Reality"', fallback)
            self.assertNotIn('      - "US-Reality-WARP"', fallback)
            auto = config.split('name: "⚡ 自动测速"', 1)[1].split(
                'name: "🔧 手动选择"', 1
            )[0]
            self.assertNotIn('      - "US-Reality-WARP"', auto)
            manual = config.split('name: "🔧 手动选择"', 1)[1].split(
                'name: "🌐 代理流量"', 1
            )[0]
            self.assertIn('      - "US-Reality-WARP"', manual)

    def test_warp_is_rejected_in_cdn_only_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "deploy.conf").write_text(
                "REALITY_PORT=443\nREALITY_TARGET=1.1.1.1:443\nREALITY_SNI=\n"
                "DEVICES=mac\nCDN_ENABLE=true\nCDN_ONLY=true\nWARP_ENABLE=true\n"
                "CDN_HOSTNAME=cdn.example.com\n"
            )
            (root / ".secrets.env").write_text(
                "STATIC_IP=203.0.113.10\nREALITY_PUBLIC=test-public-key\n"
                "REALITY_SHORTID=0123456789abcdef\nHY2_PORT=31000\n"
                "ANYTLS_PORT=21000\nANYTLS_PASS=test-anytls-pass\n"
                "CDN_WS_PATH=private-path\n"
                "CDN_UUID_mac=00000000-0000-4000-8000-000000000003\n"
                "WARP_REALITY_PORT=42000\n"
                "WARP_REALITY_UUID_mac=00000000-0000-4000-8000-000000000004\n"
            )
            env = os.environ.copy()
            env["NETWORK_NODE_ROOT"] = str(root)
            env["NETWORK_NODE_STATE_DIR"] = str(root)
            env["NETWORK_NODE_PROFILE"] = "test"
            result = subprocess.run(
                [sys.executable, str(GENERATOR)],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("不能与 CDN_ONLY=true 同时使用", result.stderr)

    def test_hysteria_optional_obfuscation_and_port_hopping_are_rendered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "deploy.conf").write_text(
                "REALITY_PORT=443\nREALITY_TARGET=1.1.1.1:443\nREALITY_SNI=\n"
                "DEVICES=mac\nCDN_ENABLE=false\nHY2_PORT_RANGE=30000-30010\n"
                "HY2_HOP_INTERVAL=15-30\nHY2_OBFS_ENABLE=true\n"
                "HY2_ACME_ENABLE=true\nHY2_ACME_DOMAIN=hy2.example.com\n"
            )
            (root / ".secrets.env").write_text(
                "STATIC_IP=203.0.113.10\nREALITY_PUBLIC=test-public-key\n"
                "REALITY_SHORTID=0123456789abcdef\nHY2_PORT=31000\n"
                "ANYTLS_PORT=21000\nANYTLS_PASS=test-anytls-pass\n"
                "REALITY_UUID_mac=00000000-0000-4000-8000-000000000001\n"
                "HY2_PASS_mac=test-hy2-mac\nHY2_OBFS_PASSWORD=test-obfs\n"
            )
            env = os.environ.copy()
            env["NETWORK_NODE_ROOT"] = str(root)
            env["NETWORK_NODE_STATE_DIR"] = str(root)
            env["NETWORK_NODE_PROFILE"] = "test"
            result = subprocess.run(
                [sys.executable, str(GENERATOR)],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            config = (root / "clash-configs" / "test-mac.yaml").read_text()
            self.assertIn("server: 203.0.113.10", config)
            self.assertIn("ports: 30000-30010", config)
            self.assertIn("obfs: salamander", config)
            self.assertIn("obfs-password: test-obfs", config)
            self.assertIn("hop-interval: 15-30", config)
            self.assertIn("sni: hy2.example.com", config)
            self.assertIn("skip-cert-verify: false", config)

    def test_only_replaces_yaml_for_the_active_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            clients = root / "clash-configs"
            clients.mkdir()
            unrelated = clients / "gcloud-mac.yaml"
            unrelated.write_text("preserve: true\n")
            stale = clients / "dmit-old.yaml"
            stale.write_text("stale: true\n")
            (root / "deploy.conf").write_text(
                "REALITY_PORT=443\nREALITY_SNI=\nDEVICES=mac\nCDN_ENABLE=false\n"
            )
            (root / ".secrets.env").write_text(
                "STATIC_IP=203.0.113.10\nREALITY_PUBLIC=test-public-key\n"
                "REALITY_SHORTID=0123456789abcdef\nHY2_PORT=31000\n"
                "ANYTLS_PORT=21000\nANYTLS_PASS=test-anytls-pass\n"
                "REALITY_UUID_mac=00000000-0000-4000-8000-000000000001\n"
                "HY2_PASS_mac=test-hy2-mac\n"
            )
            env = os.environ.copy()
            env["NETWORK_NODE_ROOT"] = str(root)
            env["NETWORK_NODE_STATE_DIR"] = str(root)
            env["NETWORK_NODE_PROFILE"] = "dmit"
            result = subprocess.run(
                [sys.executable, str(GENERATOR)], env=env, text=True,
                capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(unrelated.exists())
            self.assertFalse(stale.exists())
            self.assertTrue((clients / "dmit-mac.yaml").exists())


if __name__ == "__main__":
    unittest.main()
