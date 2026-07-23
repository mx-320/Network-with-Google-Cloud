#!/usr/bin/env python3
"""Generate Clash.Meta / Mihomo YAML configs, one per device.

Reads deploy.conf (DEVICES, REALITY_PORT, REALITY_SNI, PROJECT_ID, REGION) and
.secrets.env (STATIC_IP, REALITY_PUBLIC, REALITY_SHORTID, HY2_PORT,
ANYTLS_PORT, ANYTLS_PASS, and per-device REALITY_UUID_<dev> / HY2_PASS_<dev>).

Each device gets its OWN Reality UUID and Hysteria2 password so a single device
can be revoked without affecting the others. Primary node is VLESS+Reality;
Hysteria2 and AnyTLS are fallback options for compatible Mihomo clients.
"""
import pathlib
import os
import sys

ROOT = pathlib.Path(os.environ.get("NETWORK_NODE_ROOT", pathlib.Path(__file__).resolve().parent.parent))
PROFILE = os.environ.get("NETWORK_NODE_PROFILE", "").strip()
STATE_DIR = pathlib.Path(
    os.environ.get(
        "NETWORK_NODE_STATE_DIR",
        ROOT / "profiles" / PROFILE if PROFILE else ROOT,
    )
)
OUT_DIR = pathlib.Path(os.environ.get("NETWORK_NODE_CLIENTS_DIR", ROOT / "clash-configs"))


def load_kv(path):
    data = {}
    if not path.exists():
        return data
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data


env = {}
env.update(load_kv(STATE_DIR / "deploy.conf"))
env.update(load_kv(STATE_DIR / ".secrets.env"))

devices = env.get("DEVICES", "mac iphone").split()

# ── CDN 套娃出口（可选）──
# 启用条件：CDN_ENABLE=true 且 CF/WS 参数齐全。启用时把 US-CDN 作为一个普通节点
# 加入现有节点池（节点策略 / 自动测速 / 手动选择），分流规则完全不变；
# 关闭时所有 CDN 占位符为空，与历史行为完全一致（向后兼容）。
CDN_HOSTNAME = env.get("CDN_HOSTNAME", "")
CDN_WS_PATH = env.get("CDN_WS_PATH", "").lstrip("/")
CDN_ONLY = env.get("CDN_ONLY", "false") == "true"
cdn_on = env.get("CDN_ENABLE", "false") == "true" and bool(CDN_HOSTNAME) and bool(CDN_WS_PATH)
if CDN_ONLY and not cdn_on:
    sys.exit("ERROR: CDN_ONLY=true 但 CDN_ENABLE/CDN_HOSTNAME/CDN_WS_PATH 不完整")

WARP_ENABLE = env.get("WARP_ENABLE", "false") == "true"
WARP_REALITY_PORT = env.get("WARP_REALITY_PORT", "").strip()
PRIVACY_MODE = env.get("PRIVACY_MODE", "true") == "true"
if WARP_ENABLE and CDN_ONLY:
    sys.exit("ERROR: WARP_ENABLE=true 不能与 CDN_ONLY=true 同时使用（会重新暴露 VPS 入口）")

required = ["DEVICES"]
if not CDN_ONLY:
    required += [
        "STATIC_IP",
        "REALITY_PORT", "REALITY_PUBLIC", "REALITY_SHORTID",
        "HY2_PORT",
        "ANYTLS_PORT", "ANYTLS_PASS",
    ]
else:
    required += ["CDN_HOSTNAME", "CDN_WS_PATH"]
if WARP_ENABLE:
    required.append("WARP_REALITY_PORT")
missing = [k for k in required if not env.get(k)]
if missing:
    sys.exit(f"ERROR: 缺少必要变量 {missing}（应由部署入口自动生成，请检查 profile 状态）")

HY2_PORT_RANGE = env.get("HY2_PORT_RANGE", "").strip()
HY2_HOP_INTERVAL = env.get("HY2_HOP_INTERVAL", "").strip()
HY2_SNI = env.get("HY2_SNI", "www.bing.com").strip() or "www.bing.com"
HY2_ACME_ENABLE = env.get("HY2_ACME_ENABLE", "false") == "true"
HY2_ACME_DOMAIN = env.get("HY2_ACME_DOMAIN", "").strip()
if HY2_ACME_ENABLE and not HY2_ACME_DOMAIN:
    sys.exit("ERROR: HY2_ACME_ENABLE=true 但缺少 HY2_ACME_DOMAIN")
HY2_CLIENT_SNI = HY2_ACME_DOMAIN if HY2_ACME_ENABLE else HY2_SNI
HY2_SKIP_CERT_VERIFY = "false" if HY2_ACME_ENABLE else "true"
HY2_OBFS_ENABLE = env.get("HY2_OBFS_ENABLE", "false") == "true"
HY2_OBFS_PASSWORD = env.get("HY2_OBFS_PASSWORD", "").strip()
if HY2_OBFS_ENABLE and not HY2_OBFS_PASSWORD:
    sys.exit("ERROR: HY2_OBFS_ENABLE=true 但缺少 HY2_OBFS_PASSWORD")
CDN_REF = '\n      - "US-CDN"' if cdn_on else ""

# ── Hysteria2 Brutal 拥塞控制（可选）──
# 只有同时设置 HY2_UP / HY2_DOWN 才注入 up/down，激活 Brutal（无视丢包按固定带宽发送），
# 这是 Hysteria2 在跨太平洋丢包链路上提速的核心。值必须填你实测速度的 ~80%——填太高会
# 自伤丢包反而更慢。留空 = 保持 Hysteria2 默认动态 CC（向后兼容，与历史行为一致）。
HY2_UP = env.get("HY2_UP", "").strip()
HY2_DOWN = env.get("HY2_DOWN", "").strip()
HY2_BW = f'    up: "{HY2_UP}"\n    down: "{HY2_DOWN}"\n' if HY2_UP and HY2_DOWN else ""


def cdn_proxy_block(dev_cdn_uuid):
    """US-CDN 节点（VLESS+WS+TLS，经 Cloudflare）。CDN 关闭时返回空串。"""
    if not cdn_on:
        return ""
    return (
        '  - name: "US-CDN"\n'
        "    type: vless\n"
        f"    server: {CDN_HOSTNAME}\n"
        "    port: 443\n"
        f"    uuid: {dev_cdn_uuid}\n"
        "    network: ws\n"
        "    tls: true\n"
        "    udp: true\n"
        f"    servername: {CDN_HOSTNAME}\n"
        f"    sni: {CDN_HOSTNAME}\n"
        "    client-fingerprint: chrome\n"
        "    ws-opts:\n"
        f'      path: "/{CDN_WS_PATH}"\n'
        "      headers:\n"
        f"        Host: {CDN_HOSTNAME}\n"
    )


def warp_reality_proxy_block(dev_warp_uuid):
    """US-Reality-WARP: direct Reality ingress, WARP-only server egress."""
    if not WARP_ENABLE:
        return ""
    return f'''  - name: "US-Reality-WARP"
    type: vless
    server: {env['STATIC_IP']}
    port: {WARP_REALITY_PORT}
    uuid: {dev_warp_uuid}
    network: tcp
    tls: true
    udp: true
    flow: xtls-rprx-vision
    servername: "{env.get('REALITY_SNI', '')}"
    sni: "{env.get('REALITY_SNI', '')}"
    client-fingerprint: chrome
    reality-opts:
      public-key: {env['REALITY_PUBLIC']}
      short-id: "{env['REALITY_SHORTID']}"
'''


def node_ref_block(names):
    return "\n".join(f'      - "{name}"' for name in names)


def direct_proxy_blocks(dev_uuid, hy2_password):
    if CDN_ONLY:
        return "", "", ""

    hy2_port = (
        f"    ports: {HY2_PORT_RANGE}\n"
        if HY2_PORT_RANGE
        else f"    port: {env['HY2_PORT']}\n"
    )
    hy2_hop = f"    hop-interval: {HY2_HOP_INTERVAL}\n" if HY2_HOP_INTERVAL else ""
    hy2_obfs = ""
    if HY2_OBFS_ENABLE:
        hy2_obfs = (
            "    obfs: salamander\n"
            f"    obfs-password: {HY2_OBFS_PASSWORD}\n"
        )

    reality = f'''  - name: "US-Reality"
    type: vless
    server: {env['STATIC_IP']}
    port: {env['REALITY_PORT']}
    uuid: {dev_uuid}
    network: tcp
    tls: true
    udp: true
    flow: xtls-rprx-vision
    servername: "{env.get('REALITY_SNI', '')}"
    sni: "{env.get('REALITY_SNI', '')}"
    client-fingerprint: chrome
    reality-opts:
      public-key: {env['REALITY_PUBLIC']}
      short-id: "{env['REALITY_SHORTID']}"
'''
    hy2 = f'''  - name: "US-HY2"
    type: hysteria2
    server: {env['STATIC_IP']}
{hy2_port}    password: "{hy2_password}"
    auth: "{hy2_password}"
    sni: {HY2_CLIENT_SNI}
    skip-cert-verify: {HY2_SKIP_CERT_VERIFY}
    alpn:
      - h3
{HY2_BW}{hy2_hop}{hy2_obfs}'''
    anytls = f'''  - name: "US-AnyTLS"
    type: anytls
    server: {env['STATIC_IP']}
    port: {env['ANYTLS_PORT']}
    password: "{env['ANYTLS_PASS']}"
    sni: {HY2_CLIENT_SNI}
    skip-cert-verify: {HY2_SKIP_CERT_VERIFY}
    client-fingerprint: chrome
    udp: true
'''
    return reality, hy2, anytls

TEMPLATE = """# Clash.Meta / Mihomo config — device: {DEVICE}
# Server: {SERVER_LABEL}

mixed-port: 7890
allow-lan: false
mode: rule
log-level: info
ipv6: false
geodata-mode: true
find-process-mode: strict
sniffer:
  enable: true
  sniff:
    HTTP:
      ports:
        - 80
        - 8080-8880
      override-destination: true
    TLS:
      ports:
        - 443
        - 8443
    QUIC:
      ports:
        - 443
        - 8443

skip-proxy:
  - 127.0.0.1
  - 192.168.0.0/16
  - 10.0.0.0/8
  - 172.16.0.0/12
  - 100.64.0.0/10
  - localhost
  - "*.local"
  - captive.apple.com

tun:
  enable: true
  stack: mixed
  mtu: 1280
  auto-route: true
  auto-detect-interface: true
  strict-route: true
  dns-hijack:
    - "any:53"
    - "tcp://any:53"

dns:
  enable: true
  listen: 127.0.0.1:1053
  ipv6: false
  enhanced-mode: fake-ip
  fake-ip-range: 198.18.0.1/16
  # Mihomo 与 Stash 分别使用 respect-rules / follow-rule。
  respect-rules: true
  follow-rule: true
  fake-ip-filter:
    - "*.lan"
    - "*.local"
    - "*.apple.com"
    - "*.apple"
    - "app-analytics-services.com"
    - "time.*.com"
    - "ntp.*.com"
    - "*.ntp.org"
    - "+.msftconnecttest.com"
    - "+.msftncsi.com"
    - "localhost.ptlogin2.qq.com"
  default-nameserver:
    - 223.5.5.5
    - 1.1.1.1
  # 仅用于代理节点域名的 bootstrap，避免 DNS 经代理时递归依赖。
  proxy-server-nameserver:
    - https://223.5.5.5/dns-query
    - https://1.12.12.12/dns-query
  # 业务 DNS 按代理规则出站；IP 形式避免再次解析 DoH 主机名。
  nameserver:
    - https://1.1.1.1/dns-query
    - https://8.8.8.8/dns-query

proxies:
{REALITY_PROXY}{HY2_PROXY}{ANYTLS_PROXY}
{WARP_PROXY}
{CDN_PROXY}
proxy-groups:
  - name: "🚀 代理策略"
    type: select
    proxies:
      - "🛟 自动故障切换"
      - "⚡ 自动测速"
      - "🔧 手动选择"{CDN_REF}
      - DIRECT

  # AI 与 STUN 只使用共享 Xray IPv4 出口；Reality 失败时可经 CDN 进入同一 Xray。
  - name: "🤖 AI 隐私出口"
    type: fallback
    lazy: true
    url: https://www.gstatic.com/generate_204
    interval: 300
    proxies:
{AI_PROXIES}

  - name: "🛟 自动故障切换"
    type: fallback
    lazy: true
    url: https://www.gstatic.com/generate_204
    interval: 300
    proxies:
{FALLBACK_PROXIES}

  - name: "⚡ 自动测速"
    type: url-test
    lazy: true
    url: https://www.gstatic.com/generate_204
    interval: 600
    tolerance: 150
    proxies:
{AUTO_PROXIES}

  - name: "🔧 手动选择"
    type: select
    proxies:
{MANUAL_PROXIES}
      - DIRECT

  - name: "🌐 代理流量"
    type: select
    proxies:
      - "🚀 代理策略"
      - "⚡ 自动测速"
      - "🔧 手动选择"
{ALL_PROXIES}
      - DIRECT

  - name: "↪️ 直连流量"
    type: select
    proxies:
      - DIRECT
      - "🚀 代理策略"
      - "🔧 手动选择"

  # PRIVACY_MODE 只决定默认顺序；可在客户端随时切换 CN 流量出口。
  - name: "🇨🇳 国内流量"
    type: select
    proxies:
{CN_POLICY_OPTIONS}

  - name: "🛑 屏蔽流量"
    type: select
    proxies:
      - REJECT
      - DIRECT
      - "🚀 代理策略"

  - name: "🎯 兜底策略"
    type: select
    proxies:
      - "🚀 代理策略"
      - DIRECT

rule-providers:
  # --- MetaCubeX: AI / Google ---
  ai:
    type: http
    behavior: domain
    format: mrs
    url: "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geosite/category-ai-%21cn.mrs"
    path: ./ruleset/meta_ai.mrs
    interval: 86400

  google:
    type: http
    behavior: domain
    format: mrs
    url: "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geosite/google.mrs"
    path: ./ruleset/meta_google.mrs
    interval: 86400

  # --- blackmatrix7: iOS / Apple 功能补丁 ---
  siri:
    type: http
    behavior: classical
    format: yaml
    url: "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Siri/Siri.yaml"
    path: ./ruleset/bm7_siri.yaml
    interval: 86400

  icloud-private-relay:
    type: http
    behavior: classical
    format: yaml
    url: "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/iCloudPrivateRelay/iCloudPrivateRelay.yaml"
    path: ./ruleset/bm7_icloud_private_relay.yaml
    interval: 86400

  # --- MetaCubeX: Apple 基础直连 ---
  icloud:
    type: http
    behavior: domain
    format: mrs
    url: "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geosite/icloud.mrs"
    path: ./ruleset/meta_icloud.mrs
    interval: 86400

  apple-cn:
    type: http
    behavior: domain
    format: mrs
    url: "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geosite/apple-cn.mrs"
    path: ./ruleset/meta_apple_cn.mrs
    interval: 86400

  # --- blackmatrix7: 轻量广告拦截 ---
  ads-lite:
    type: http
    behavior: classical
    format: yaml
    url: "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/AdvertisingLite/AdvertisingLite.yaml"
    path: ./ruleset/bm7_ads_lite.yaml
    interval: 86400

  # --- MetaCubeX: 国内直连 ---
  private:
    type: http
    behavior: domain
    format: mrs
    url: "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geosite/private.mrs"
    path: ./ruleset/meta_private.mrs
    interval: 86400

  private-ip:
    type: http
    behavior: ipcidr
    format: mrs
    url: "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geoip/private.mrs"
    path: ./ruleset/meta_private_ip.mrs
    interval: 86400

  cn:
    type: http
    behavior: domain
    format: mrs
    url: "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geosite/cn.mrs"
    path: ./ruleset/meta_cn.mrs
    interval: 86400

  cn-ip:
    type: http
    behavior: ipcidr
    format: mrs
    url: "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geoip/cn.mrs"
    path: ./ruleset/meta_cn_ip.mrs
    interval: 86400

  # --- MetaCubeX: 通讯 / 海外服务 ---
  telegram:
    type: http
    behavior: domain
    format: mrs
    url: "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geosite/telegram.mrs"
    path: ./ruleset/meta_telegram.mrs
    interval: 86400

  telegram-ip:
    type: http
    behavior: ipcidr
    format: mrs
    url: "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geoip/telegram.mrs"
    path: ./ruleset/meta_telegram_ip.mrs
    interval: 86400

  tiktok:
    type: http
    behavior: domain
    format: mrs
    url: "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geosite/tiktok.mrs"
    path: ./ruleset/meta_tiktok.mrs
    interval: 86400

rules:
  # --- [P0] 规则更新 / GitHub raw 走代理，避免大陆网络下规则集刷新失败 ---
  - DOMAIN-SUFFIX,raw.githubusercontent.com,🌐 代理流量

  # --- [P1] STUN 与 AI 固定到同一个 IPv4 Xray 出口，避免 Web/UDP 出口漂移 ---
  - DOMAIN-KEYWORD,stun,🤖 AI 隐私出口
  - RULE-SET,ai,🤖 AI 隐私出口
  - RULE-SET,google,🌐 代理流量

  # --- [P2] iOS / Apple 海外能力：Siri 与 iCloud Private Relay 相关域名走代理 ---
  - RULE-SET,siri,🌐 代理流量
  - DOMAIN,guzzoni.smoot.apple.com,🌐 代理流量
  - DOMAIN,probe.siri.apple.com,🌐 代理流量
  - DOMAIN,seed.siri.apple.com,🌐 代理流量
  - DOMAIN,seed-sequoia.siri.apple.com,🌐 代理流量
  - DOMAIN,seed-swallow.siri.apple.com,🌐 代理流量
  - DOMAIN,sequoia.apple.com,🌐 代理流量
  - DOMAIN,swallow.apple.com,🌐 代理流量
  - RULE-SET,icloud-private-relay,🌐 代理流量

  # --- [P3] 业务/归因/广告平台保护：必须放在广告拦截前，避免误杀 ---
  - DOMAIN-SUFFIX,tradingview.com,🌐 代理流量
  - DOMAIN-SUFFIX,applovin.com,🌐 代理流量
  - DOMAIN-SUFFIX,applvn.com,🌐 代理流量
  - DOMAIN-SUFFIX,applovinedge.com,🌐 代理流量
  - DOMAIN-SUFFIX,appsflyer.com,🌐 代理流量
  - DOMAIN-SUFFIX,adjust.com,🌐 代理流量
  - DOMAIN-SUFFIX,adj.st,🌐 代理流量
  - DOMAIN-SUFFIX,kochava.com,🌐 代理流量
  - DOMAIN-SUFFIX,branch.io,🌐 代理流量
  - DOMAIN-SUFFIX,singular.net,🌐 代理流量
  - DOMAIN-SUFFIX,ads.google.com,🌐 代理流量
  - DOMAIN-SUFFIX,adwords.google.com,🌐 代理流量
  - DOMAIN-SUFFIX,analytics.google.com,🌐 代理流量
  - DOMAIN-SUFFIX,googletagmanager.com,🌐 代理流量
  - DOMAIN-SUFFIX,googleadservices.com,🌐 代理流量
  - DOMAIN-SUFFIX,googlesyndication.com,🌐 代理流量
  - DOMAIN-SUFFIX,googletagservices.com,🌐 代理流量
  - DOMAIN-SUFFIX,ads.tiktok.com,🌐 代理流量
  - DOMAIN-SUFFIX,business.tiktok.com,🌐 代理流量

  # --- [P4] 原手写保留项：未确认是否仍需直连，先按旧配置保守保留 ---
  - DOMAIN-KEYWORD,spotify,↪️ 直连流量
  - DOMAIN-SUFFIX,scdn.co,↪️ 直连流量

  # --- [P5] 轻量广告拦截 ---
  - RULE-SET,ads-lite,🛑 屏蔽流量

  # --- [P6] Apple 基础服务直连：放在 Siri/Private Relay 后，避免海外能力被直连抢走 ---
  - RULE-SET,icloud,↪️ 直连流量
  - RULE-SET,apple-cn,↪️ 直连流量

  # --- [P7] 通讯 / 海外 App ---
  - RULE-SET,telegram,🌐 代理流量
  - RULE-SET,telegram-ip,🌐 代理流量,no-resolve
  - RULE-SET,tiktok,🌐 代理流量

  # --- [P8] 内网始终直连；公开 CN 流量可在客户端手动切换 ---
  - RULE-SET,private,DIRECT
  - RULE-SET,private-ip,DIRECT,no-resolve
  - RULE-SET,cn,🇨🇳 国内流量
  - RULE-SET,cn-ip,🇨🇳 国内流量,no-resolve
  - GEOIP,LAN,DIRECT,no-resolve
  - GEOIP,CN,🇨🇳 国内流量,no-resolve

  # --- [P9] 兜底 ---
  - MATCH,🎯 兜底策略
"""

OUT_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
OUT_DIR.chmod(0o700)
stale_pattern = f"{PROFILE}-*.yaml" if PROFILE else "*.yaml"
for stale in OUT_DIR.glob(stale_pattern):
    stale.unlink()
for dev in devices:
    uuid = env.get(f"REALITY_UUID_{dev}")
    hy2pw = env.get(f"HY2_PASS_{dev}")
    if not CDN_ONLY and (not uuid or not hy2pw):
        sys.exit(f"ERROR: 设备 {dev} 缺少 REALITY_UUID_{dev} / HY2_PASS_{dev}")
    dev_cdn_uuid = env.get(f"CDN_UUID_{dev}", "")
    if cdn_on and not dev_cdn_uuid:
        sys.exit(f"ERROR: CDN_ENABLE=true 但设备 {dev} 缺少 CDN_UUID_{dev}")
    dev_warp_uuid = env.get(f"WARP_REALITY_UUID_{dev}", "")
    if WARP_ENABLE and not dev_warp_uuid:
        sys.exit(f"ERROR: WARP_ENABLE=true 但设备 {dev} 缺少 WARP_REALITY_UUID_{dev}")

    reality_proxy, hy2_proxy, anytls_proxy = direct_proxy_blocks(
        uuid or "", f"{dev}:{hy2pw}" if hy2pw else ""
    )
    warp_proxy = warp_reality_proxy_block(dev_warp_uuid)
    direct_nodes = [] if CDN_ONLY else ["US-Reality", "US-HY2", "US-AnyTLS"]
    warp_nodes = ["US-Reality-WARP"] if WARP_ENABLE else []
    ai_nodes = ["US-CDN"] if CDN_ONLY else ["US-Reality"]
    if cdn_on and not CDN_ONLY:
        ai_nodes.append("US-CDN")
    cn_policy_options = (
        '      - "🌐 代理流量"\n      - DIRECT'
        if PRIVACY_MODE
        else '      - DIRECT\n      - "🌐 代理流量"'
    )
    fallback_nodes = direct_nodes[:1]
    if cdn_on:
        fallback_nodes.append("US-CDN")
    fallback_nodes.extend(direct_nodes[1:])
    auto_nodes = fallback_nodes
    all_nodes = (["US-CDN"] if cdn_on else []) + direct_nodes + warp_nodes
    if not fallback_nodes:
        sys.exit("ERROR: 没有可用的代理节点")

    yaml = TEMPLATE.format(
        DEVICE=dev,
        SERVER_LABEL=(
            f"{env['STATIC_IP']} | primary: VLESS+Reality:{env['REALITY_PORT']} | "
            f"fallback: Hysteria2:{env['HY2_PORT']}/udp, AnyTLS:{env['ANYTLS_PORT']}/tcp"
            if not CDN_ONLY
            else "Cloudflare Tunnel only"
        ),
        REALITY_PROXY=reality_proxy,
        HY2_PROXY=hy2_proxy,
        ANYTLS_PROXY=anytls_proxy,
        WARP_PROXY=warp_proxy,
        CDN_PROXY=cdn_proxy_block(dev_cdn_uuid),
        CDN_REF=CDN_REF,
        AI_PROXIES=node_ref_block(ai_nodes),
        CN_POLICY_OPTIONS=cn_policy_options,
        FALLBACK_PROXIES=node_ref_block(fallback_nodes),
        AUTO_PROXIES=node_ref_block(auto_nodes),
        MANUAL_PROXIES=node_ref_block(all_nodes),
        ALL_PROXIES=node_ref_block(all_nodes),
        **env,
    )
    filename = f"{PROFILE}-{dev}.yaml" if PROFILE else f"{dev}.yaml"
    path = OUT_DIR / filename
    path.write_text(yaml)
    path.chmod(0o600)
    print(f"  wrote {path.name} ({len(yaml)} bytes)")

print(f"\n全部 {len(devices)} 份配置已写入 {OUT_DIR}")
