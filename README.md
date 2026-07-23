# Self-hosted Network Node

一套共享代理核心，两个明确入口：自动创建 Google Cloud 节点，或部署到任意已有 Debian/Ubuntu VPS。

One shared proxy core with two explicit deployment paths: Google Cloud or any existing Debian/Ubuntu VPS.

- Primary: VLESS + Reality
- UDP fallback: Hysteria2
- TCP fallback: AnyTLS
- One credential set and YAML per device

## 快速开始

公共依赖：本机安装 `python3`、`openssl` 和 OpenSSH。

### Google Cloud

先安装并登录 `gcloud`，然后运行：

```bash
gcloud auth login
gcloud config set project <你的项目ID>
./deploy-gcp.sh
```

GCP adapter 会预留静态 IP、配置云防火墙、创建 Debian VM，并通过 IAP SSH 安装服务端。

### 已有 Debian/Ubuntu VPS

VPS 安装 Debian/Ubuntu，并把本机公钥加入初始 root 账户，然后运行：

```bash
VPS_PROFILE=frantech \
VPS_SSH_KEY="$HOME/.ssh/frantech_ed25519" \
./deploy-vps.sh <VPS_PUBLIC_IP>
```

`VPS_PROFILE` 必须为每台 VPS 使用一个唯一名称，例如 `dmit`、`frantech`、`new-york-01`。
不要裸跑 `./deploy-vps.sh`，这样可以避免新服务器误用已有 profile。

VPS adapter 会执行以下安全步骤：

1. 验证初始 root 公钥登录。
2. 创建并验证独立的 `mt` sudo 用户。
3. 配置 UFW，只开放 SSH 和三个代理端口。
4. 确认 `mt` 可以登录后才禁用 root 和密码登录。
5. 安装三套协议并生成设备 YAML。

重跑时会直接复用已经创建的 `mt` 用户，不再依赖 root。

不要把私钥复制到服务器、Git 跟踪文件或聊天中。

首次部署后可以把主机专用私钥放在 `profiles/<profile>/ssh/`，也可以继续通过
`VPS_SSH_KEY=/path/to/private-key` 显式指定。后续重跑时使用同一个 `VPS_PROFILE`，脚本会复用该 profile 的 IP、端口和本地密钥。

## 目录结构

```text
deploy-gcp.sh / deploy-vps.sh   用户入口
deploy.sh                       旧 GCP 命令的兼容入口
providers/                      GCP、普通 VPS adapter
core/                           共享部署流水线、密钥、协议安装、规则与 YAML 生成
config/                         不含密钥的配置模板
docs/                           架构说明与排障文档
tools/vps_stock.py              只读 VPS 库存监控
profiles/<profile>/             每台服务器独立状态与 ssh/（不提交）
clash-configs/                  所有 profile 的客户端 YAML（不提交）
```

GCP 和 VPS 真正变化的只有服务器生命周期、连接方式与防火墙；协议和客户端规则只维护一份。详细 seam 和 provider interface 见 [架构说明](docs/architecture.md)。

想快速理解整个仓库，先看[仓库总览与维护说明](docs/repository-guide.md)；它把入口、部署链路、profile、直连/CDN 节点和日常操作放在一处。

## 配置

首次运行会从 `config/deploy.conf.example` 创建当前 profile 的本地状态。GCloud 固定使用
`profiles/gcloud/`；普通 VPS 使用 `VPS_PROFILE` 对应的 `profiles/<profile>/`。整个
`profiles/` 目录都已被 Git 忽略。

| 配置 | 默认值 | 说明 |
|---|---|---|
| `REALITY_PORT` | `443` | Reality 监听端口 |
| `REALITY_TARGET` / `REALITY_SNI` | `1.1.1.1:443` / 空 | Reality 目标与客户端 SNI |
| `HY2_PORT` | 随机 | Hysteria2 UDP 端口 |
| `HY2_PORT_RANGE` | 空 | 可选端口跳跃范围，例如 `30000-30010` |
| `HY2_OBFS_ENABLE` | `false` | 可选 Salamander 混淆；开启后不再表现为标准 HTTP/3 |
| `HY2_ACME_ENABLE` | `false` | 可选 Cloudflare DNS-01 真实证书 |
| `ANYTLS_PORT` | 随机 | AnyTLS TCP 端口 |
| `DEVICES` | `mac iphone` | 每个设备生成独立凭据和 YAML |
| `PRIVACY_MODE` | `true` | 公开 CN 流量与 STUN 走代理；关闭后恢复国内直连分流 |
| `CDN_ENABLE` | `false` | 可选 Cloudflare Tunnel 出口 |
| `CDN_ONLY` | `false` | 仅使用 Cloudflare WS，并关闭直连代理端口 |
| `WARP_ENABLE` | `false` | 可选 Reality-WARP 节点；仅该节点的 Xray 出站经过 WARP |
| `WARP_SOCKS_PORT` | `40000` | 服务器本机 WARP SOCKS5 端口，不对公网开放 |
| `WARP_REALITY_PORT` | 随机 | Reality-WARP 直连端口；开启 WARP 时自动生成 |
| `PROJECT_ID` / `REGION` / `ZONE` | GCP 默认值 | 只由 GCP adapter 使用 |

每个 profile 内的敏感文件均已 gitignore：

- `.secrets.env`
- `deploy.conf`
- `ssh/`

不要提交、转发或粘贴这些文件的内容。

## 导入客户端

部署成功后，每个平台默认得到两份名称明确的 YAML：

- `clash-configs/gcloud-mac.yaml`
- `clash-configs/gcloud-iphone.yaml`
- `clash-configs/<profile>-mac.yaml`
- `clash-configs/<profile>-iphone.yaml`

生成器只替换当前 profile 前缀的文件，例如 `frantech` 只处理 `frantech-*.yaml`，不会覆盖
`dmit-*.yaml` 或 `gcloud-*.yaml`。客户端 YAML 默认权限为 `600`，因为其中含节点地址、UUID 和密码；
这可阻止同一台电脑上的其他系统用户读取。iCloud 副本用于设备同步，不作为项目源状态。

- Clash Verge：Settings → Profiles → Import
- 手机：使用支持 Reality、Hysteria2 和 AnyTLS 的 Mihomo/Clash.Meta 兼容客户端

新生成的配置默认启用 `PRIVACY_MODE=true`，`🇨🇳 国内流量` 默认选择代理，避免检测页面同时观察到国内直连与代理出口；遇到无法使用的 CN 服务时，可在 Stash/Mihomo 里把该组手动切到 `DIRECT`，无需修改 YAML。设置 `PRIVACY_MODE=false` 会让该组首次默认直连，但仍可手动切回代理。局域网地址始终直连，原有 Apple/Spotify 规则保持不变。DNS 在 Stash 使用 `follow-rule`、在 Mihomo 使用 `respect-rules`，并保留独立 bootstrap 解析器防止递归依赖。

普通流量默认使用 `🛟 自动故障切换`：Reality 正常时行为不变，连接失败时按 Reality → CDN → Hysteria2 → AnyTLS 顺序切换。AI 域名和 STUN 使用单独的 `🤖 AI 隐私出口`，按 Reality → CDN（启用时）切换；两条入口共用服务端 Xray IPv4 出口，不加入 HY2、AnyTLS 或 WARP。CDN-only 时该组只使用 CDN。

AI 规则来自 MetaCubeX `category-ai-!cn`，通过域名后缀覆盖 OpenAI、Claude、Gemini、NotebookLM、Perplexity、Copilot、Cursor、Grok 等常见国际 AI 服务及多数专属子域名。它不保证覆盖共享登录/CDN 域名、直接连接的 IP，也不包含 DeepSeek、通义、Kimi、豆包等中国 AI 域名；这些流量继续由后续 Google、CN 或兜底规则处理。

`US-Reality-WARP` 仅保留为手动可选节点，不进入自动测速或自动故障切换，避免自动选择改变公网出口。
如需真正隐藏源站 IP，把 `CDN_ENABLE=true` 和 `CDN_ONLY=true` 同时设置；这会关闭直连 Reality/Hysteria2/AnyTLS，保留 Cloudflare WS 入口。

### WARP 出站（低延迟优先的可选路径）

`WARP_ENABLE=true` 会在 VPS 上安装 Cloudflare WARP 的 SOCKS5 代理，并额外生成 `US-Reality-WARP`：客户端仍直连 VPS，只有该节点的 Xray 出站经过 WARP。现有 `US-Reality`、`US-HY2` 和 `US-AnyTLS` 不变。

这条路径不隐藏 VPS 入口 IP，因此不能和 `CDN_ONLY=true` 同时启用。WARP 只接入 Xray/Reality，Hysteria2 和 AnyTLS 暂不走全局策略路由；服务端会每 60 秒检查一次真实 SOCKS 出口并尝试自愈。

`HY2_PORT_RANGE`、`HY2_OBFS_ENABLE`、`HY2_ACME_ENABLE` 均为可选增强：开启后需要重新部署服务端并重新生成客户端 YAML；默认关闭时不改变已有协议行为。

修改 `DEVICES` 后重跑同一个 profile 的入口，即可增加或撤销设备。

### Cloudflare CDN 首次启用

先把域名接入 Cloudflare，并在目标 profile 的 `.secrets.env` 写入最小权限 API Token：

```text
Account → Cloudflare Tunnel → Edit
Zone → Zone → Read
Zone → DNS → Edit
```

Zone 资源只选择目标域名。然后在该 profile 的 `deploy.conf` 设置：

```text
CDN_ENABLE=true
CDN_ONLY=false
CDN_HOSTNAME=cdn.example.com
CDN_TUNNEL_NAME=<profile>-cdn
```

重新运行对应部署入口即可自动创建/复用 Tunnel、配置 Ingress、写入橙云 CNAME 并生成 `US-CDN`。
首次建议保持 `CDN_ONLY=false`，确认 CDN 节点可用后再单独切换 CDN-only。缺少 API Token 或
Cloudflare 权限不足时，部署会在修改服务器前停止，不会留下半套 VPS 配置。

## 重跑与维护

- 两个入口均按幂等方式设计，会复用已有服务器和本地密钥。
- 只重新生成某个 profile 的客户端 YAML：`NETWORK_NODE_PROFILE=<profile> python3 core/gen-clash.py`
- 服务端组件版本在 `deploy.conf` 中固定；升级前先改版本并重新部署，避免重跑时无意升级。
- GCP 旧命令 `./deploy.sh` 仍可使用，但会提示改用 `./deploy-gcp.sh`。
- 通用排障见 [Troubleshooting](docs/troubleshooting.md)。
- 新服务器接入和隔离规则见 [Provider Onboarding](docs/provider-onboarding.md)。
- VPS 库存监控见 [VPS Stock Monitor](docs/vps-stock-monitor.md)。

## VPS 库存监控

从仓库根目录运行只读检查：

```bash
python3 tools/vps_stock.py --state-file ~/.cache/network-node/vps-stock.json
```

库存状态放在仓库外，不会进入 Git；监控不会登录、下单或修改任何供应商账户。

## English

### Choose one entry point

```bash
# Provision a new Google Cloud node
./deploy-gcp.sh

# Configure an existing Debian/Ubuntu VPS
VPS_PROFILE=frantech VPS_SSH_KEY="$HOME/.ssh/frantech_ed25519" ./deploy-vps.sh <VPS_PUBLIC_IP>
```

Both entry points run the same shared pipeline:

1. Validate provider-specific requirements.
2. Generate per-device credentials locally.
3. Provision or secure a reachable host.
4. Install BBR, Xray/Reality, Hysteria2, AnyTLS, systemd units, and security updates.
5. Recover the Reality public key and generate one Mihomo YAML per device.

The provider adapters only own host lifecycle, connectivity, and firewall behaviour. Key generation, server configuration, routing rules, optional Cloudflare setup, and client generation remain in `core/`.

For a non-default VPS key:

```bash
VPS_PROFILE=<profile> VPS_SSH_KEY=/path/to/private-key ./deploy-vps.sh <VPS_PUBLIC_IP>
```

Never copy private keys or `.secrets.env` into Git-tracked files, onto the server, or into chat.

## License

MIT — see [LICENSE](LICENSE).
