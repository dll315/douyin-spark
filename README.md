# 抖音自动续火花（Web 控制台版）

通过一个自托管的网站后台，驱动浏览器自动打开**抖音网页版**私信，每天定时给你指定的好友发一句话，保持火花不灭。全程在电脑上运行，**不需要手机脚本、不需要root**。

## 工作原理

```
浏览器控制台(Web UI)
        │ HTTP API
        ▼
FastAPI 后端 ──► APScheduler 每日定时（含随机延迟防风控）
        │
        ▼
Playwright 驱动 Chromium ──► douyin.com 私信页
        │  找到会话 → 输入话术 → 回车发送
        ▼
结果写回 JSON 存储，页面实时展示日志
```

- 登录：页面点击「扫码登录」，后端截取抖音网页版二维码返回前端，用抖音 App 扫码即可；凭证保存在 `data/douyin_state.json`。
- 联系人：按**私信会话列表中的昵称**匹配（续火花的对象本来就在你的会话列表里）。
- 话术：全局默认话术池随机选用，也可给单个联系人配置专属话术。

## 功能

- 扫码登录 / 掉线检测 / 一键退出
- 联系人增删改、启用开关、独立话术
- 每天定时发送 + 随机延迟（可配），手动「立即执行一轮」
- 运行日志、每联系人上次发送结果、失败自动截图到 `data/screenshots/`

## 快速开始

要求：Python 3.10+

```bash
cd douyin-spark
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000 ：

1. 点击「扫码登录」→ 用抖音 App 扫描二维码
2. 添加要续火花的联系人昵称（与私信列表显示一致）
3. 设置每天发送时间和随机延迟，保存即可

服务器部署时加 `--host 0.0.0.0` 并配合 systemd / NSSM 等常驻进程管理；注意**只能单 worker 运行**（状态保存在进程内存和本地文件中）。

## 目录结构

```
douyin-spark/
├── app/
│   ├── main.py          # FastAPI 入口与 API
│   ├── douyin_bot.py    # Playwright 自动化核心（选择器常量在此）
│   ├── scheduler.py     # APScheduler 定时任务
│   ├── store.py         # JSON 数据存储
│   └── static/index.html# Web 控制台
├── data/                # 运行数据（自动生成，勿提交）
│   ├── data.json        # 配置/联系人/日志
│   ├── douyin_state.json# 登录 Cookie（含敏感凭证！）
│   └── screenshots/     # 失败排查截图
├── requirements.txt
└── README.md
```

## 常见问题

- **找不到会话 / 输入框**：抖音前端改版导致选择器失效。编辑 `app/douyin_bot.py` 顶部的 `CONVERSATION_SELECTORS` / `CHAT_INPUT_SELECTORS`，失败截图在 `data/screenshots/` 可辅助定位。
- **二维码不出现**：先尝试关闭「无头模式」重试；仍不行说明登录页结构变化，需调整 `QR_SELECTORS`。
- **掉线**：Cookie 有效期有限，掉线后重新扫码即可。

## ⚠️ 免责声明

自动化操作抖音可能违反其用户协议，存在被限制功能或封号的风险。本项目仅供学习交流，请控制频率（默认每日一次）、仅用于维护自己真实的好友关系，由此产生的账号风险自行承担。
