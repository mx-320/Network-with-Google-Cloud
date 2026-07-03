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
import sys

HERE = pathlib.Path(__file__).resolve().parent
OUT_DIR = HERE / "clash-configs"


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
env.update(load_kv(HERE / "deploy.conf"))
env.update(load_kv(HERE / ".secrets.env"))

REQUIRED = [
    "STATIC_IP",
    "REALITY_PORT", "REALITY_SNI", "REALITY_PUBLIC", "REALITY_SHORTID",
    "HY2_PORT",
    "ANYTLS_PORT", "ANYTLS_PASS",
]
missing = [k for k in REQUIRED if not env.get(k)]
if missing:
    sys.exit(f"ERROR: 缺少必要变量 {missing}（应由 deploy.sh 自动生成，请检查 .secrets.env）")

devices = env.get("DEVICES", "mac iphone ipad laptop spare").split()

# ── CDN 套娃出口（可选）──
# 启用条件：CDN_ENABLE=true 且 CF/WS 参数齐全。启用时把 US-CDN 作为一个普通节点
# 加入现有节点池（节点策略 / 自动测速 / 手动选择），分流规则完全不变；
# 关闭时所有 CDN 占位符为空，与历史行为完全一致（向后兼容）。
CDN_HOSTNAME = env.get("CDN_HOSTNAME", "")
CDN_WS_PATH = env.get("CDN_WS_PATH", "").lstrip("/")
cdn_on = env.get("CDN_ENABLE", "false") == "true" and bool(CDN_HOSTNAME) and bool(CDN_WS_PATH)
CDN_REF = '\n      - "US-CDN"' if cdn_on else ""


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

TEMPLATE = """# Clash.Meta / Mihomo config — device: {DEVICE}
# Server: {STATIC_IP}  |  primary: VLESS+Reality:{REALITY_PORT}  |  fallback: Hysteria2:{HY2_PORT}/udp, AnyTLS:{ANYTLS_PORT}/tcp

mixed-port: 7890
allow-lan: false
mode: rule
log-level: info
ipv6: false
geodata-mode: true
find-process-mode: strict
global-client-fingerprint: chrome

sniffer:
  enable: true
  override-destination: true
  sniff:
    - tls
    - http

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
  stack: system
  mtu: 1280
  auto-route: true
  auto-detect-interface: true
  dns-hijack:
    - "any:53"

dns:
  enable: true
  listen: 127.0.0.1:1053
  enhanced-mode: fake-ip
  fake-ip-range: 198.18.0.1/16
  fake-ip-filter:
    - "*.lan"
    - "*.local"
    - "*.apple.com"
    - "*.apple"
    - "app-analytics-services.com"
    - "time.*.com"
    - "ntp.*.com"
    - "*.ntp.org"
    - "stun.*"
    - "+.msftconnecttest.com"
    - "+.msftncsi.com"
    - "localhost.ptlogin2.qq.com"
  nameserver:
    - https://223.5.5.5/dns-query
    - https://1.12.12.12/dns-query
  fallback:
    - https://1.1.1.1/dns-query
    - https://8.8.8.8/dns-query
  fallback-filter:
    geoip: true
    geoip-code: CN
    ipcidr:
      - 240.0.0.0/4

proxies:
  - name: "US-Reality"
    type: vless
    server: {STATIC_IP}
    port: {REALITY_PORT}
    uuid: {DEV_UUID}
    network: tcp
    tls: true
    udp: true
    flow: xtls-rprx-vision
    servername: {REALITY_SNI}
    sni: {REALITY_SNI}
    client-fingerprint: chrome
    reality-opts:
      public-key: {REALITY_PUBLIC}
      short-id: "{REALITY_SHORTID}"

  - name: "US-HY2"
    type: hysteria2
    server: {STATIC_IP}
    port: {HY2_PORT}
    password: "{HY2_PASSWORD}"
    auth: "{HY2_PASSWORD}"
    sni: www.bing.com
    skip-cert-verify: true
    alpn:
      - h3

  - name: "US-AnyTLS"
    type: anytls
    server: {STATIC_IP}
    port: {ANYTLS_PORT}
    password: "{ANYTLS_PASS}"
    sni: www.bing.com
    skip-cert-verify: true
    client-fingerprint: chrome
    udp: true
{CDN_PROXY}
proxy-groups:
  - name: "🚀 代理策略"
    type: select
    proxies:
      - "US-Reality"
      - "⚡ 自动测速"
      - "🔧 手动选择"{CDN_REF}
      - "US-HY2"
      - "US-AnyTLS"
      - DIRECT

  - name: "⚡ 自动测速"
    type: url-test
    lazy: true
    url: https://www.gstatic.com/generate_204
    interval: 600
    tolerance: 150
    proxies:{CDN_REF}
      - "US-Reality"
      - "US-HY2"
      - "US-AnyTLS"

  - name: "🔧 手动选择"
    type: select
    proxies:{CDN_REF}
      - "US-Reality"
      - "US-HY2"
      - "US-AnyTLS"
      - DIRECT

  - name: "🌐 代理流量"
    type: select
    proxies:
      - "🚀 代理策略"
      - "⚡ 自动测速"
      - "🔧 手动选择"{CDN_REF}
      - "US-Reality"
      - "US-HY2"
      - "US-AnyTLS"
      - DIRECT

  - name: "↪️ 直连流量"
    type: select
    proxies:
      - DIRECT
      - "🚀 代理策略"
      - "🔧 手动选择"

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

  # --- [P1] AI / Google 服务优先走代理，避免被国内/Apple/广告规则抢先命中 ---
  - RULE-SET,ai,🌐 代理流量
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

  # --- [P8] 国内直连 ---
  - RULE-SET,private,DIRECT
  - RULE-SET,private-ip,DIRECT,no-resolve
  - RULE-SET,cn,↪️ 直连流量
  - RULE-SET,cn-ip,↪️ 直连流量,no-resolve
  - GEOIP,LAN,DIRECT,no-resolve
  - GEOIP,CN,↪️ 直连流量,no-resolve

  # --- [P9] 兜底 ---
  - MATCH,🎯 兜底策略
"""

OUT_DIR.mkdir(exist_ok=True)
for dev in devices:
    uuid = env.get(f"REALITY_UUID_{dev}")
    hy2pw = env.get(f"HY2_PASS_{dev}")
    if not uuid or not hy2pw:
        sys.exit(f"ERROR: 设备 {dev} 缺少 REALITY_UUID_{dev} / HY2_PASS_{dev}")
    dev_cdn_uuid = env.get(f"CDN_UUID_{dev}", "")
    if cdn_on and not dev_cdn_uuid:
        sys.exit(f"ERROR: CDN_ENABLE=true 但设备 {dev} 缺少 CDN_UUID_{dev}")
    yaml = TEMPLATE.format(
        DEVICE=dev,
        DEV_UUID=uuid,
        HY2_PASSWORD=f"{dev}:{hy2pw}",
        CDN_PROXY=cdn_proxy_block(dev_cdn_uuid),
        CDN_REF=CDN_REF,
        **env,
    )
    path = OUT_DIR / f"{dev}.yaml"
    path.write_text(yaml)
    print(f"  wrote {path.name} ({len(yaml)} bytes)")

print(f"\n全部 {len(devices)} 份配置已写入 {OUT_DIR}")
