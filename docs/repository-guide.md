# 仓库总览与维护说明

这份说明回答三个问题：仓库各部分负责什么、一次部署如何流转、日常修改应该改哪里。

## 一句话定位

这是一个“共享代理核心 + 多 provider 入口 + 每台服务器独立 profile”的自托管节点部署仓库。

- 共享核心负责协议、密钥、服务端配置、Cloudflare 可选出口和 Mihomo YAML 生成。
- provider 只负责服务器生命周期、连接方式和防火墙。
- profile 负责把某一台服务器的地址、密钥、SSH 私钥和客户端状态隔离开。
- `tools/vps_stock.py` 是独立的只读库存监控工具，不参与代理部署。

## 目录职责

```text
deploy-gcp.sh / deploy-vps.sh  用户入口
deploy.sh                      旧 GCP 入口兼容别名
core/                          共享部署核心
providers/                     GCP / 通用 VPS 生命周期适配器
config/                        不含密钥的默认配置模板
profiles/<profile>/            本地敏感状态，不提交
clash-configs/                 生成的客户端 YAML，不提交
tests/                         部署、生成器、下载和库存监控测试
docs/                          架构、排障和运维说明
tools/vps_stock.py             只读 VPS 库存检查
```

### `core/` 内部边界

| 文件 | 责任 |
|---|---|
| `common.sh` | profile 路径、配置/密钥加载、密钥写入和日志辅助函数 |
| `secrets.sh` | 本地生成或复用端口、UUID、密码和可选 CDN 凭据 |
| `deploy.sh` | 编排共享部署流程，调用 provider 和客户端生成器 |
| `cloudflare.sh` | 创建/复用 Tunnel、配置 Ingress、写入 CNAME 和连接 Token |
| `setup-server.sh` | 在远端安装 Xray、Hysteria2、AnyTLS、cloudflared 和 systemd 服务 |
| `download.sh` | 远端二进制下载、重试和超时 |
| `gen-clash.py` | 每个设备生成一份 Mihomo/Clash YAML |

## 两条部署路径

### GCP

`deploy-gcp.sh` → `providers/gcp.sh` → `providers/gcp-provision.sh` → `core/deploy.sh`

GCP 适配器负责项目预检、静态 IP、VM、防火墙和 IAP SSH；协议安装和客户端生成仍由 `core/` 完成。

### 已有 Debian/Ubuntu VPS

```bash
VPS_PROFILE=<profile> \
VPS_SSH_KEY=/path/to/private-key \
./deploy-vps.sh <VPS_PUBLIC_IP>
```

VPS 适配器负责初始 SSH、创建 `mt` 管理员、UFW 和文件上传。每台 VPS 必须使用唯一的 `VPS_PROFILE`，避免误读另一台服务器的状态。

## 一次部署的实际顺序

```text
入口脚本
  ↓
provider 预检与读取 profile
  ↓
生成/复用本地凭据
  ↓
CDN_ENABLE=true 时：先完成 Cloudflare API / Tunnel / DNS
  ↓
连接并加固服务器，配置 UFW
  ↓
上传 server-env.sh 和安装脚本
  ↓
安装并重启服务，回收 Reality 公钥
  ↓
按设备生成 <profile>-<device>.yaml
```

Cloudflare 阶段在服务器修改之前执行。这样 Token、权限或 DNS 配置错误会在本地提前停止，不会先改防火墙再失败。

## 节点和流量关系

默认部署会生成三条直连节点，开启 CDN 后增加一条 CDN 节点：

```text
US-Reality  ───────────────→ VPS IP:443
US-Reality-WARP ───────────→ VPS IP:WARP_REALITY_PORT → WARP → 互联网（可选，手动节点）
US-HY2      ───────────────→ VPS IP:随机 UDP 端口
US-AnyTLS   ───────────────→ VPS IP:随机 TCP 端口
US-CDN      → cdn.example.com → Cloudflare → Tunnel → VPS localhost:8080
```

- 只有 `US-CDN` 使用域名和 Cloudflare Tunnel。
- `US-Reality-WARP` 直连 VPS，但仅该节点的 Xray 出站经过 WARP；它不隐藏 VPS 入口，只保留为手动可选节点，不加入自动测速或自动故障切换。
- `CDN_ONLY=false` 时，直连节点继续保留，适合先灰度验证 CDN。
- `CDN_ONLY=true` 时，服务端关闭 Reality/Hysteria2/AnyTLS 直连入口，只保留 Cloudflare WS；切换前必须重新生成并导入 YAML。
- `WARP_ENABLE=true` 与 `CDN_ONLY=true` 互斥。
- `🛟 自动故障切换`、`⚡ 自动测速` 只是客户端策略组，不是额外的服务器节点。
- `PRIVACY_MODE=true`（默认）让 `🇨🇳 国内流量` 首次默认走代理；客户端可手动切到 `DIRECT`，`false` 则让该组首次默认直连。局域网与原有 Apple/Spotify 规则不受影响。
- CN 判定依次使用 MetaCubeX `cn` 域名集、`cn-ip` 地址集和 Mihomo `GEOIP,CN` 兜底；AI、Google、Apple、Telegram、广告等更高优先级规则先匹配，`private`/LAN 则始终固定直连。
- `🤖 AI 隐私出口` 只使用共享 Xray IPv4 出口，按 Reality → CDN（启用时）故障切换；STUN 同组，避免 AI HTTP 与 WebRTC UDP 因双栈或 WARP 显示不同地址。
- AI 域名使用 MetaCubeX `category-ai-!cn`；常见国际 AI 主域和多数专属子域已覆盖，但共享登录/CDN、直连 IP 和中国 AI 域名不在其完整保证范围内。

## Profile 和文件安全边界

每台服务器只允许有一个本地状态包：

```text
profiles/<profile>/
├── deploy.conf       # 本机部署参数
├── .secrets.env      # 端口、UUID、密码、Token
└── ssh/              # 本机 SSH 私钥
```

这些内容全部属于敏感本地状态，不应提交、上传或粘贴到聊天。生成的 YAML 也含真实地址和凭据，因此默认只保存在本机/设备同步目录，不进入 Git。

公共代码只应依赖环境变量和 profile 状态，不要把某台服务器的 IP、域名、Token 或 SSH 文件写进 `core/`、`providers/`、`README.md` 或测试样例。

## 常用维护动作

### 重跑同一台服务器

```bash
VPS_PROFILE=<profile> \
VPS_SSH_KEY="$PWD/profiles/<profile>/ssh/id_rsa.pem" \
./deploy-vps.sh
```

重跑会复用本地凭据和已有管理员。只有修改服务端参数、协议凭据或组件版本时，才需要重跑；只改客户端规则时不需要重启服务器。

### 只重新生成客户端 YAML

```bash
NETWORK_NODE_PROFILE=<profile> python3 core/gen-clash.py
```

### 启用 CDN

1. 域名托管到 Cloudflare。
2. 在 `profiles/<profile>/.secrets.env` 写入最小权限 `CF_API_TOKEN`。
3. 在 `profiles/<profile>/deploy.conf` 设置 `CDN_ENABLE=true`、`CDN_ONLY=false`、`CDN_HOSTNAME` 和 `CDN_TUNNEL_NAME`。
4. 重跑对应部署入口。
5. 导入新 YAML，先测试 `US-CDN`，确认后再考虑 CDN-only。

脚本会自动创建/复用 Tunnel、配置 CNAME、生成连接 Token 和客户端节点，不需要手动填写 Tunnel CNAME 目标。

## 修改时的判断规则

- 协议、systemd、服务端入站：改 `core/`。
- GCP/VPS 登录、服务器创建、UFW、文件传输：改 `providers/`。
- 默认参数：改 `config/deploy.conf.example`。
- 用户操作路径和故障处理：改 `README.md` 或 `docs/`。
- 新增或修复行为：先补 `tests/`，再改实现。
- 不要为了单台服务器的特殊值修改共享核心；放入对应 profile。

## 发布前检查

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
bash -n deploy.sh deploy-gcp.sh deploy-vps.sh core/*.sh providers/*.sh
git diff --check
git ls-files profiles
```

最后一条必须没有输出。生成的 profile、SSH 私钥、`.secrets.env` 和客户端 YAML 都不应进入提交。

## Graphify 结构审计摘要

Graphify 对仓库代码进行结构提取后，识别出部署核心、provider 适配器、客户端生成器和独立库存监控四个主要边界；未发现 import cycle。库存监控中的解析器和社交来源测试连接较密集，但不影响代理部署链路，因此不应把它们与 `core/` 合并重构。
