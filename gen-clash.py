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
    client-fingerprint: chrome
    reality-opts:
      public-key: {REALITY_PUBLIC}
      short-id: "{REALITY_SHORTID}"

  - name: "US-HY2"
    type: hysteria2
    server: {STATIC_IP}
    port: {HY2_PORT}
    password: "{HY2_PASSWORD}"
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

proxy-groups:
  - name: "🚀 Proxy"
    type: select
    proxies:
      - "US-Reality"
      - "⚡ Auto"
      - "US-HY2"
      - "US-AnyTLS"
      - DIRECT

  - name: "⚡ Auto"
    type: url-test
    lazy: true
    url: https://www.gstatic.com/generate_204
    interval: 600
    tolerance: 150
    proxies:
      - "US-Reality"
      - "US-HY2"
      - "US-AnyTLS"

  - name: "🧠 Anti-Restrict"
    type: select
    proxies:
      - "US-Reality"
      - "⚡ Auto"
      - "US-HY2"
      - "US-AnyTLS"
      - "🚀 Proxy"
      - DIRECT

  - name: "🌎 Global"
    type: select
    proxies:
      - "🚀 Proxy"
      - DIRECT

  - name: "🇨🇳 Direct-CN"
    type: select
    proxies:
      - DIRECT
      - "🚀 Proxy"

  - name: "🎯 Final"
    type: select
    proxies:
      - "🚀 Proxy"
      - DIRECT

rules:
  # --- Local / private networks: DIRECT ---
  - DOMAIN-SUFFIX,lan,DIRECT
  - DOMAIN-SUFFIX,local,DIRECT
  - IP-CIDR,127.0.0.0/8,DIRECT,no-resolve
  - IP-CIDR,10.0.0.0/8,DIRECT,no-resolve
  - IP-CIDR,172.16.0.0/12,DIRECT,no-resolve
  - IP-CIDR,192.168.0.0/16,DIRECT,no-resolve
  - IP-CIDR,100.64.0.0/10,DIRECT,no-resolve
  - IP-CIDR,224.0.0.0/4,DIRECT,no-resolve
  - IP-CIDR6,fc00::/7,DIRECT,no-resolve
  - IP-CIDR6,fe80::/10,DIRECT,no-resolve

  # --- Work / CN business platforms: DIRECT ---
  - DOMAIN-SUFFIX,e.kuaishou.com,DIRECT
  - DOMAIN-SUFFIX,business.oceanengine.com,DIRECT
  - DOMAIN-SUFFIX,cas.baidu.com,DIRECT
  - DOMAIN-SUFFIX,e.qq.com,DIRECT
  - DOMAIN-SUFFIX,oceanengine.com,DIRECT
  - DOMAIN-SUFFIX,kylin.baidu.com,DIRECT

  # --- Anti-restrict services ---
  - DOMAIN-SUFFIX,openai.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,chatgpt.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,oaistatic.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,oaiusercontent.com,🧠 Anti-Restrict
  - DOMAIN-KEYWORD,openai,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,anthropic.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,claude.ai,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,claudeusercontent.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,dify.ai,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,coze.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,gemini.google.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,bard.google.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,makersuite.google.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,aistudio.google.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,generativelanguage.googleapis.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,perplexity.ai,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,pplx.ai,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,x.ai,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,grok.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,mistral.ai,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,huggingface.co,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,character.ai,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,poe.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,cohere.ai,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,cohere.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,stability.ai,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,replicate.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,runwayml.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,midjourney.com,🧠 Anti-Restrict

  # --- Ads / attribution / business dashboards ---
  - DOMAIN-SUFFIX,ads.google.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,adwords.google.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,analytics.google.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,googletagmanager.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,googleadservices.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,googlesyndication.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,googletagservices.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,ads.tiktok.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,business.tiktok.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,tradingview.com,🧠 Anti-Restrict
  - DOMAIN,dash.applovin.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,applovin.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,applvn.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,applovinedge.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,appsflyer.com,🧠 Anti-Restrict
  - DOMAIN,suite.adjust.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,adjust.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,adj.st,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,kochava.com,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,branch.io,🧠 Anti-Restrict
  - DOMAIN-SUFFIX,singular.net,🧠 Anti-Restrict

  # --- Streaming (DIRECT — GCP IPs usually blocked) ---
  - DOMAIN-SUFFIX,netflix.com,🇨🇳 Direct-CN
  - DOMAIN-SUFFIX,nflxvideo.net,🇨🇳 Direct-CN
  - DOMAIN-SUFFIX,hulu.com,🇨🇳 Direct-CN
  - DOMAIN-SUFFIX,disneyplus.com,🇨🇳 Direct-CN
  - DOMAIN-SUFFIX,hbomax.com,🇨🇳 Direct-CN
  - DOMAIN-SUFFIX,max.com,🇨🇳 Direct-CN
  - DOMAIN-SUFFIX,peacocktv.com,🇨🇳 Direct-CN

  # --- Google / YouTube / common Western sites: Proxy ---
  - DOMAIN-SUFFIX,google.com,🌎 Global
  - DOMAIN-KEYWORD,google,🌎 Global
  - DOMAIN-SUFFIX,googleapis.com,🌎 Global
  - DOMAIN-SUFFIX,gstatic.com,🌎 Global
  - DOMAIN-SUFFIX,ggpht.com,🌎 Global
  - DOMAIN-SUFFIX,youtube.com,🌎 Global
  - DOMAIN-SUFFIX,ytimg.com,🌎 Global
  - DOMAIN-SUFFIX,googlevideo.com,🌎 Global
  - DOMAIN-SUFFIX,github.com,🌎 Global
  - DOMAIN-SUFFIX,githubusercontent.com,🌎 Global
  - DOMAIN-SUFFIX,githubassets.com,🌎 Global
  - DOMAIN-SUFFIX,twitter.com,🌎 Global
  - DOMAIN-SUFFIX,x.com,🌎 Global
  - DOMAIN-SUFFIX,twimg.com,🌎 Global
  - DOMAIN-SUFFIX,reddit.com,🌎 Global
  - DOMAIN-SUFFIX,redditstatic.com,🌎 Global
  - DOMAIN-SUFFIX,redd.it,🌎 Global
  - DOMAIN-SUFFIX,wikipedia.org,🌎 Global
  - DOMAIN-SUFFIX,wikimedia.org,🌎 Global
  - DOMAIN-SUFFIX,stackoverflow.com,🌎 Global
  - DOMAIN-SUFFIX,medium.com,🌎 Global

  # --- CN domains: DIRECT ---
  - DOMAIN-SUFFIX,cn,DIRECT
  - DOMAIN-KEYWORD,-cn,DIRECT
  - DOMAIN-SUFFIX,baidu.com,DIRECT
  - DOMAIN-SUFFIX,qq.com,DIRECT
  - DOMAIN-SUFFIX,weixin.qq.com,DIRECT
  - DOMAIN-SUFFIX,bilibili.com,DIRECT
  - DOMAIN-SUFFIX,taobao.com,DIRECT
  - DOMAIN-SUFFIX,tmall.com,DIRECT
  - DOMAIN-SUFFIX,alipay.com,DIRECT
  - DOMAIN-SUFFIX,zhihu.com,DIRECT
  - DOMAIN-SUFFIX,douban.com,DIRECT
  - DOMAIN-SUFFIX,sina.com.cn,DIRECT
  - DOMAIN-SUFFIX,163.com,DIRECT
  - DOMAIN-SUFFIX,126.com,DIRECT
  - DOMAIN-SUFFIX,douyin.com,DIRECT
  - DOMAIN-SUFFIX,xiaohongshu.com,DIRECT

  # --- GeoIP fallback ---
  - GEOIP,CN,DIRECT
  - GEOIP,PRIVATE,DIRECT,no-resolve

  # --- Default ---
  - MATCH,🎯 Final
"""

OUT_DIR.mkdir(exist_ok=True)
for dev in devices:
    uuid = env.get(f"REALITY_UUID_{dev}")
    hy2pw = env.get(f"HY2_PASS_{dev}")
    if not uuid or not hy2pw:
        sys.exit(f"ERROR: 设备 {dev} 缺少 REALITY_UUID_{dev} / HY2_PASS_{dev}")
    yaml = TEMPLATE.format(
        DEVICE=dev,
        DEV_UUID=uuid,
        HY2_PASSWORD=f"{dev}:{hy2pw}",
        **env,
    )
    path = OUT_DIR / f"{dev}.yaml"
    path.write_text(yaml)
    print(f"  wrote {path.name} ({len(yaml)} bytes)")

print(f"\n全部 {len(devices)} 份配置已写入 {OUT_DIR}")
