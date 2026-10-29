# 脉冲台：热点监控

本机运行的多来源热点监控系统。支持关键词核实提醒和领域热点发现，使用 OpenRouter 判读，并通过网页和邮件通知。

## 准备

需要 Python 3.11+ 与 Node.js 20.19+。在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
Copy-Item .env.example .env
```

编辑 `.env`，填写 OpenRouter 与 twitterapi.io 的密钥。如需邮件提醒，还要填写 SMTP 信息。587 端口通常配合 `SMTP_STARTTLS=true`；465 端口可设置 `SMTP_SSL=true`。密钥只由后端读取，不会返回给浏览器。`OFFICIAL_RSS_URLS` 可用英文逗号分隔多个你信任的官方 RSS 地址。

默认 `OPENROUTER_MODEL=nvidia/nemotron-3.5-super-vl:free` 可用于无充值试用。OpenRouter 对免费模型设置每日请求上限，持续监控多个活跃主题时，建议在账户有额度后改为支持 JSON Schema 的付费模型，例如 `google/gemini-2.5-flash`。免费模型的额度说明见 [OpenRouter 官方页面](https://openrouter.ai/collections/free-models)。

### QQ 邮箱发送提醒

先登录 [QQ 邮箱](https://mail.qq.com/)，在“设置 → 帐户”中开启 IMAP/SMTP 服务并生成授权码。`SMTP_PASSWORD` 填授权码，不填 QQ 登录密码。配置示例：

```dotenv
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USER=你的QQ号@qq.com
SMTP_PASSWORD=在QQ邮箱生成的授权码
SMTP_FROM=你的QQ号@qq.com
ALERT_EMAIL=接收提醒的邮箱地址
SMTP_STARTTLS=false
SMTP_SSL=true
```

`SMTP_USER` 和 `SMTP_FROM` 使用同一个完整 QQ 邮箱地址；`ALERT_EMAIL` 可以是同一个邮箱，也可以是另一个收件邮箱。保存 `.env` 后重启后端服务。QQ 邮箱的服务器与端口参见[腾讯云配置说明](https://intl.cloud.tencent.com/zh/document/product/1266/71700)，授权码步骤参见[华为帮助文档](https://consumer.huawei.com/cn/support/content/zh-cn16108643/)。

## 启动

先构建前端，再启动一个后端进程，浏览器访问 `http://127.0.0.1:8000`：

```powershell
cd frontend
npm ci --offline=false --registry=https://registry.npmjs.org
npm run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

开发前端时，可在另一个终端运行 `cd frontend; npm run dev`，访问 `http://127.0.0.1:5173`。Vite 会把 `/api` 请求代理到本机后端。后端需保持运行才能定时监控；首版仅启动单个后端进程，避免重复扫描。

## 使用

1. 在“监控任务”创建关键词或领域监控。关键词默认每 5 分钟、领域默认每 30 分钟扫描，可调整周期。
2. 在“总览”查看结果和来源证据，在“提醒收件箱”查看已核实的关键词事件。
3. 在“连接状态”查看 AI、X、邮件及来源采集状态。配置变更后重启后端。

网页搜索与新闻源可能受网络环境影响。单一来源失败不会阻断其他来源。AI 无密钥或调用失败时，系统不会自动核实线索。邮件未配置时，网页提醒仍会生成，邮件标记为“待配置”。本机环境目前已验证必应网页搜索、Google 新闻和 OpenAI 官方 RSS 可获取内容；OpenRouter、X 和 SMTP 仍需有效凭据完成真实连接测试。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m backend.diagnostics --send-email
.\.venv\Scripts\python.exe -m backend.diagnostics --full-scan
cd frontend
npm test
npm run build
```

第二条命令会调用 OpenRouter、twitterapi.io，并向 `ALERT_EMAIL` 发送一封测试邮件；第三条命令使用临时数据库完成一次四来源真实扫描，不会留下测试监控项或发送热点邮件。两条命令均可能消耗接口额度。

## Agent Skill

仓库中的 [热点监控技能](.cursor/skills/hotspot-monitoring/SKILL.md)可交给支持 Agent Skills 的 AI 使用。它通过本机后端管理任务、触发扫描并读取带证据的事件，不另存一份监控数据。命令行入口为 `.cursor/skills/hotspot-monitoring/scripts/hotspot.py`；后端服务需保持运行。

需求和实施细节见 [需求规格](docs/需求规格.md)、[开发方案](docs/开发方案.md)与[验收步骤](docs/验收步骤.md)。
