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
- **反骚扰**：验证码、限流、关键词 / 语言 / 媒体 / 链接过滤

## 准备

1. [@BotFather](https://t.me/BotFather) 创建 Bot，拿到 token
2. [@userinfobot](https://t.me/userinfobot) 查自己的数字 ID
3. 群收件箱：把 Bot 拉进**超级群**，关闭隐私模式（`/setprivacy` → Disable），并授予 `can_manage_topics`。开启群的 Topics 后，每个用户会自动得到一个主题。

## Docker

```bash
cp .env.example .env
# 填 BOT_TOKEN、ADMIN_IDS，可选 ADMIN_CHAT_ID / WEBHOOK_URL
docker compose up -d --build
```

或直接用 GitHub Container Registry 镜像（需先 `docker login ghcr.io`）：

```bash
docker compose pull
docker compose up -d
```

## Webhook

设置 `WEBHOOK_URL` 后走 Webhook，不再轮询。容器监听 `0.0.0.0:8080`，前面需要 TLS 反代（Caddy / Nginx / Cloudflare Tunnel）。

```
WEBHOOK_URL=https://bot.example.com/telegram
WEBHOOK_SECRET=long-random-string
```

未设置 `WEBHOOK_URL` 时使用 long polling。

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `BOT_TOKEN` | BotFather token |
| `ADMIN_IDS` | 管理员用户 ID，逗号分隔 |
| `ADMIN_CHAT_ID` | 可选。群/超级群 ID。论坛群会按用户建主题 |
| `WEBHOOK_URL` | 可选。公网 HTTPS 地址，设置后启用 webhook |
| `WEBHOOK_LISTEN` | 默认 `0.0.0.0` |
| `WEBHOOK_PORT` | 默认 `8080`。Docker Compose 下这是**宿主机**映射端口，容器内进程固定监听 `8080` |
| `WEBHOOK_PATH` | 默认 `/telegram`（若 URL 里已有 path 则用 URL） |
| `WEBHOOK_SECRET` | 可选。Telegram `secret_token` |
| `DATABASE_PATH` | 默认 `data/bot.db` |
| `TZ` | 默认 `Asia/Shanghai` |
| `LOG_LEVEL` | 默认 `INFO` |

## 管理员

发送 `/admin`。界面语言在「界面」里切换。论坛主题开关也在那里。

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
pip install -r requirements.txt
cp .env.example .env
python -m app
```

```bash
pytest
```
