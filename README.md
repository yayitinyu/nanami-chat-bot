# Nanami Chat Bot

Telegram 私聊客服 / 消息转发机器人。用户把消息发给 Bot，管理员引用即可回复；支持 **Webhook**、**中/英/日界面**、**论坛主题分用户**，以及验证码、限流、关键词 / 语言 / 媒体 / 链接过滤。

镜像：`ghcr.io/yayitinyu/nanami-chat-bot`

## 功能

- **消息转发**：用户私聊 → 管理员；引用该消息即可回复
- **论坛主题分用户**：收件箱为开启 Topics 的超级群时，每个用户一个主题，在主题里直接回复即可
- **Webhook 或 Long Polling**
- **多语言界面**：管理面板中文 / English / 日本語，可跟随客户端或强制指定
- **广播**：立即发送，或按间隔循环
- **关键词自动回复**：包含 / `exact:` / `regex:`
- **启动消息**：自定义 `/start`（HTML）
- **用户管理**：搜索、封禁 / 解禁、重置验证
- **反骚扰**：按钮 / 算术 / Cloudflare Turnstile 验证、限流、关键词 / 语言 / 媒体 / 链接过滤

按钮和算术验证码用于轻量准入；公开 Bot 可选用 Turnstile 做更强的人机验证。建议同时开启消息限流，并按实际骚扰样本维护关键词与链接策略。

## 准备

1. [@BotFather](https://t.me/BotFather) 创建 Bot，拿到 token
2. [@userinfobot](https://t.me/userinfobot) 查自己的数字 ID
3. 群收件箱：把 Bot 拉进**超级群**，关闭隐私模式（`/setprivacy` → Disable），并授予 `can_manage_topics`。开启群的 Topics 后，每个用户会自动得到一个主题。

## Docker

```bash
cp .env.example .env
# 填 BOT_TOKEN、ADMIN_IDS；启用 Webhook 时同时填写 WEBHOOK_URL / WEBHOOK_SECRET
chmod 600 .env
docker compose up -d --build
```

或直接用 GitHub Container Registry 镜像（需先 `docker login ghcr.io`）：

```bash
docker compose pull
docker compose up -d
```

## Webhook

设置 `WEBHOOK_URL` 后走 Webhook，不再轮询。容器内监听 `0.0.0.0:8080`，Compose 默认只把端口发布到宿主机 `127.0.0.1`，由 TLS 反代（Caddy / Nginx / Cloudflare Tunnel）对外提供服务。

```
WEBHOOK_URL=https://bot.example.com/telegram
WEBHOOK_SECRET=replace_with_at_least_32_random_characters
```

未设置 `WEBHOOK_URL` 时使用 long polling。

生产环境请保持 `WEBHOOK_BIND=127.0.0.1`，并确认反向代理保留 Telegram 的 `X-Telegram-Bot-Api-Secret-Token` 请求头。可用 `openssl rand -hex 32` 生成符合要求的随机 secret。

Webhook 的请求体只有 Update JSON，不包含上传文件本体；建议反代仅转发配置的 webhook path、其他路径直接拒绝，并在该 location 将请求体上限设为 `1m`，避免未认证的大请求占用内存。

## Cloudflare Turnstile

Turnstile 为可选的第三种验证码类型；按钮和算术验证仍可在管理面板中切换。Telegram 中的按钮会打开一个短时验证链接，验证页只在 Cloudflare Siteverify 成功且 `hostname`、`action`、`cdata` 全部匹配后放行用户。

先创建 Managed Widget 和 Siteverify Worker，然后同时配置：

```dotenv
CHALLENGE_PUBLIC_URL=https://challenge.example.com
TURNSTILE_SITEKEY=0x4AAAAAA_your_public_sitekey
TURNSTILE_VERIFY_URL=https://turnstile-siteverify-example.workers.dev
```

Bot 在容器内单独监听 `0.0.0.0:8081`。Compose 默认仅发布到宿主机 `127.0.0.1:8081`，将验证域名反代到该端口，例如 Caddy：

```caddyfile
challenge.example.com {
    reverse_proxy 127.0.0.1:8081
}
```

一次性挑战标识放在 URL fragment 中，不会发送给反向代理或进入常规访问日志。请勿记录 `/verify` 的 POST 请求体。Siteverify Secret 只保存在 Cloudflare Worker Secret 中，Bot 无需持有它。

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `BOT_TOKEN` | BotFather token |
| `ADMIN_IDS` | 管理员用户 ID，逗号分隔 |
| `ADMIN_CHAT_ID` | 可选。群/超级群 ID。论坛群会按用户建主题 |
| `WEBHOOK_URL` | 可选。公网 HTTPS 地址，设置后启用 webhook |
| `WEBHOOK_LISTEN` | 容器内监听地址，默认 `0.0.0.0` |
| `WEBHOOK_BIND` | Compose 宿主机发布地址，默认 `127.0.0.1` |
| `WEBHOOK_PORT` | 默认 `8080`。Docker Compose 下这是**宿主机**映射端口，容器内进程固定监听 `8080` |
| `WEBHOOK_PATH` | 默认 `/telegram`（若 URL 里已有 path 则用 URL） |
| `WEBHOOK_SECRET` | Webhook 必填。32–256 位，仅允许字母、数字、`_`、`-` |
| `CHALLENGE_PUBLIC_URL` | 可选。Turnstile 验证页的公网 HTTPS Origin |
| `CHALLENGE_LISTEN` | 验证页容器内监听地址，默认 `0.0.0.0` |
| `CHALLENGE_BIND` | Compose 验证页宿主机发布地址，默认 `127.0.0.1` |
| `CHALLENGE_PORT` | 默认 `8081`；Docker Compose 下为宿主机映射端口，容器内固定监听 `8081` |
| `TURNSTILE_SITEKEY` | Turnstile Widget 的公开 Sitekey |
| `TURNSTILE_VERIFY_URL` | 托管 Siteverify Worker 的 HTTPS 地址 |
| `DATABASE_PATH` | 默认 `data/bot.db` |
| `TZ` | 默认 `Asia/Shanghai` |
| `LOG_LEVEL` | 默认 `INFO` |
| `MAX_CONCURRENT_UPDATES` | 同时处理的更新数，默认 `16`，范围 `1`–`64` |
| `UPDATE_QUEUE_SIZE` | 内存更新队列上限，默认 `256`，范围 `16`–`10000` |
| `WEBHOOK_MAX_CONNECTIONS` | Telegram webhook 最大并发连接数，默认 `10`，范围 `1`–`100` |
| `GLOBAL_RATE_LIMIT_COUNT` | 全局更新预算，默认 `120`；设为 `0` 可关闭 |
| `GLOBAL_RATE_LIMIT_WINDOW` | 全局更新预算时间窗（秒），默认 `60` |
| `MESSAGE_MAP_RETENTION_DAYS` | 回复映射保留天数，默认 `90` |
| `BOT_IMAGE` | Compose 镜像引用；生产环境可填写不可变 digest |

## 管理员

在管理员私聊或配置的收件箱中发送 `/admin`。界面语言在「界面」里切换。论坛主题开关也在那里；管理命令在其他群聊中不会响应。

| 命令 | 说明 |
| --- | --- |
| `/admin` | 管理面板 |
| `/ban` `/unban` | 封禁 / 解禁；可跟 ID、引用消息，或在该用户主题里发送 |
| `/cancel` | 取消当前输入 |
| `/id` | 查看自己的 ID |

回复用户：引用转发消息，或在对应 **Topic** 里直接发送。

## CI 镜像

GitHub Actions 使用 [Docker GitHub Builder](https://docs.docker.com/build/ci/github-actions/multi-platform/)：`linux/amd64` 在 `ubuntu-24.04` 上原生构建，`linux/arm64` 在 `ubuntu-24.04-arm` 上原生构建，**不使用 QEMU**。推送到 `main` 或打 `v*` tag 后写入 GHCR。

首次使用 GHCR 包可能是 private，可在仓库 Packages 设置里改为 public。

## 本地运行

Python 3.12+。

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env
python -m app
```

```bash
pytest
```
