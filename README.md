# 校园网延迟调查 Agent（network-latency-agent）

面向**校园网运维工程师**的 AI Agent：调查上联链路 RTT 异常，判断延迟是来自**排队拥塞**、**路由变更**还是**硬件故障**，并给出带证据与置信度的结论。

- 代码仓库：<https://github.com/CodeLark08042/network-latency-agent>
- 在线主页（静态演示）：<https://codelark08042.github.io/network-latency-agent/>

## 1. 项目简介与主要功能

- 接收自然语言故障描述（例如"link-dist-a-sw1 延迟从 5 ms 涨到 85 ms"）
- 自主决定调用哪个工具、调用几次（硬上限 5 轮，防止小模型死循环）
- 用 **M/M/1 排队论**计算理论排队时延，并与实测 RTT 比对
- 把总时延分解为**传播 / 传输 / 排队 / 处理**四部分
- 输出含"支持证据 / 反驳证据 / 置信度"的中文调查报告，并保存完整工具调用 trace

## 2. 使用的 LLM、Agent 框架、Tool 与 Skill

| 项 | 内容 |
| --- | --- |
| LLM | Ollama 本地部署：`qwen3.5:0.8b`（推荐，CPU 可跑）、`qwen3:4b`（效果更好但很慢） |
| Agent 框架 | PydanticAI（`Agent` + `FunctionModel` 桥接 Ollama） |
| Tool 1 | `list_network` — 列出拓扑中的链路 |
| Tool 2 | `get_link_metrics` — 查询链路利用率、RTT、丢包率、队列深度、到达率 |
| Tool 3 | `analyze_delay_components` — 四类时延分解 + 理论/实测 RTT 比对 |
| Tool 4 | `calculate_queue_delay` — M/M/1 模型计算 ρ、Lq、Wq |
| Skill | `skills/network-latency-investigation/SKILL.md` — 延迟调查流程、四条硬性规则、判读表；第三层细节（公式推导、量级参考、完整误判清单）在同目录 `reference.md` |
| Skill 加载器 | `src/skills.py` — 解析 `SKILL.md` 的 YAML 前置元数据与正文，运行时注入 System Prompt（无第三方 YAML 依赖） |
| Web 前端 | `docs/{index.html,style.css,script.js}` — 原生 HTML/CSS/JS，零构建；`docs/demo-data.json` 提供静态演示 |
| Web 后端 | `backend/` — FastAPI + `openai` SDK 直连 DeepSeek（OpenAI 兼容），复用同一套 Agent 与 4 个工具 |

## 3. 环境依赖与安装

```bash
# Python 3.12+
pip install -r requirements.txt

# 模型（二选一）
ollama pull qwen3.5:0.8b     # 快，CPU 可用
ollama pull qwen3:4b         # 慢，效果更好
```

依赖版本：`pydantic-ai>=2.0.0`；Web 后端另需 `fastapi`、`uvicorn[standard]`、`python-dotenv`、`openai`；生成报告图表另需 `matplotlib`、`Pillow`、`markdown`（均已写入 `requirements.txt`）。

## 4. 模型配置

### 4.1 CLI（Ollama，本地）

默认连接 `http://localhost:11434/api/chat`。可用 `--host` 覆盖，或参考 `.env.example`：

```text
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen3.5:0.8b
```

### 4.2 Web 后端（DeepSeek，云端）

```text
DEEPSEEK_API_KEY=你的key
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

也可以不改 `.env`，直接在网页的「接口密钥（可选）」里临时填写。**不配置 Key 也能运行**：后端会自动切换到离线规则判读，并在接口与页面上标注 `source=mock`（非大模型输出）。

## 5. 运行命令

```bash
# 单次调查（--scenario 指定模拟的“当前网络状态”）
python -m src.main --scenario congestion \
  --prompt "校园网工程师报告：link-dist-a-sw1 路径出现严重延迟，请调查"

# 交互模式
python -m src.main --interactive --scenario congestion

# 不使用 Skill（对照组 B：只有工具说明，没有任何领域判断知识）
python -m src.main --no-skill --scenario congestion --prompt "..."

# 指定模型
python -m src.main --model qwen3:4b --scenario congestion --prompt "..."

# 保存报告与 trace
python -m src.main --scenario congestion --prompt "..." \
  --output results/investigation_demo.md \
  --save-trace results/traces/demo.json
```

可用 `--scenario`：`normal` / `congestion` / `route_change` / `packet_loss` / `incomplete_data`。

## 6. 运行测试案例

5 个案例定义在 `tests/cases.json`：

| ID | 场景 | 预期根因 |
| --- | --- | --- |
| case1_congestion | congestion | 拥塞（排队延迟） |
| case2_route_change | route_change | 主链路中断 + 备用路径过载 |
| case3_hardware_fault | packet_loss | 光模块故障高丢包 |
| case4_incomplete_data | incomplete_data | 数据缺失下的谨慎结论 |
| case5_normal | normal | 无异常 |

```bash
python -m src.main --scenario congestion \
  --prompt "校园网工程师报告：从汇聚路由器A到接入交换机1号（link-dist-a-sw1）的路径出现严重延迟，用户反馈网页加载缓慢、视频卡顿。请调查延迟来源并给出建议。"
```

## 7. 复现评测结果

```bash
# 三组对照实验（A: 直接LLM / B: Agent+Tools / C: Agent+Tools+Skill）
python tests/evaluate.py --model qwen3.5:0.8b

# 只跑某一组
python tests/evaluate.py --model qwen3.5:0.8b --only C_Agent_Tools_Skill
```

输出：

```text
results/evaluation.csv     逐案例逐组指标
results/summary.json       三组汇总指标
results/traces/*.json      每个案例每个组的完整工具调用 trace 与输出
```

生成报告用的图表与截图：

```bash
python scripts/make_figures.py       # 架构图、流程图、结果图 → docs/
python scripts/make_screenshots.py   # 由真实输出渲染截图 → docs/screenshots/
python scripts/build_pdf.py          # report.md → report.html → report.pdf
```

## 8. 评测指标定义

| 指标 | 计算方式 |
| --- | --- |
| 任务成功率 | 最终答案命中该案例"区分性关键词"的比例 |
| 证据完整度 | 命中的预期证据点数 ÷ 预期证据点总数 |
| 工具调用正确率 | 是否调用 `get_link_metrics`、`analyze_delay_components`、是否查询目标链路，各占 1/3 |
| 执行成本 | 平均 LLM 调用次数、端到端耗时 |

## 9. 已知限制

- **使用模拟数据**，不连接真实网络设备；`--scenario` 切换的是模拟的"当前网络状态"。
- **M/M/1 模型**假设泊松到达与指数服务，不适用于单条大象流或高度突发流量；工具输出中已用 `note` 字段声明。
- **0.8B 模型能力有限**：存在多次运行结果波动。Skill v2 已消除"数据缺失时编造其他链路正常"的幻觉，但仍会在"利用率低 + 高丢包"的硬件故障案例上选错原因，且在要求逐条列证据时会陷入模板循环（详见报告 5.5 节）。
- **`qwen3:4b` 在纯 CPU 环境上极慢**：单次完整调查可能需要 20 分钟以上，建议用于少量演示而非全量评测。
- 未实现多轮对话记忆与真实设备接入。

## 10. Web 工作台（前端 + 后端）

前端是零构建的静态页面（`docs/`），后端是 FastAPI（`backend/`），两者共用与 CLI 完全相同的 Agent、4 个工具和 Skill。

### 10.1 启动

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
# 打开 http://127.0.0.1:8000
```

后端会把 `docs/` 挂载在 `/`，所以同一个目录既能本地联调，也能直接发布到 GitHub Pages。

### 10.2 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 服务状态、模型名、是否已配置 Key、可用场景 |
| GET | `/api/cases` | 读取 `tests/cases.json` |
| GET | `/api/network?scenario=congestion` | 拓扑 + 当前场景的链路指标 |
| POST | `/api/investigate` | 运行一次调查，返回报告 + trace + 统计 |

### 10.3 两种运行模式

- **实时模式**（后端在线）：调用 DeepSeek，`source=deepseek`；无 Key 时自动规则判读，`source=mock` 并在页面横幅说明。
- **静态模式**（无后端，如 GitHub Pages）：读取 `docs/demo-data.json` 回放 `results/repeat/run4` 中的真实 trace，页面标注"非本次实时生成"。

### 10.4 自检

```bash
python -m backend.main
```

## 11. 设计文档

| 文档 | 内容 |
| --- | --- |
| [docs/01-项目介绍文档.md](docs/01-项目介绍文档.md) | 背景、用户、目标、功能/非功能需求、架构概览、技术选型、验收指标 |
| [docs/02-前端界面设计文档.md](docs/02-前端界面设计文档.md) | 设计思维四问、信息架构、布局栅格、视觉规范、组件状态、双模式数据流、可访问性 |
| [docs/03-后端HLD.md](docs/03-后端HLD.md) | 系统上下文、分层架构、模块职责、时序流程、接口契约、ADR、降级矩阵、部署与遗留问题 |

## 12. GitHub Pages 部署（纯静态演示）

GitHub Pages 不能运行 Python，因此线上只启用静态模式：

1. 仓库已公开：<https://github.com/CodeLark08042/network-latency-agent>
2. 仓库 `Settings → Pages → Build and deployment → Deploy from a branch`；
3. 分支选 `main`，目录选 `/docs`（本项目的静态站点就在 `docs/`）；
4. 在线主页：<https://codelark08042.github.io/network-latency-agent/>

页面会自动探测后端；探测失败即切换为静态演示，并通过横幅与 `SOURCE` 读数说明数据来源。

## 13. 课堂过程材料（证明投入）

| 材料 | 路径 | 说明 |
| --- | --- | --- |
| 多轮实验记录 | `results/repeat/`（run2 / run3 / run4） | 每次包含 15 条 trace + `evaluation.csv` + `summary.json` + 控制台日志 |
| 最终实验汇总 | `results/repeat/run4/` | 报告第 5 章引用的数据来源 |
| 完整工具调用 trace | `results/repeat/run4/traces/*_C_Agent_Tools_Skill.json` | 5 个案例的 Agent+Tools+Skill 全量轨迹 |
| 评测脚本 | `tests/evaluate.py` | 一条命令复现三组对照实验 |
| 图表生成 | `scripts/make_figures.py` | 架构图、流程图、结果图 |
| 运行截图 | `docs/screenshots/` | Agent 运行、工具轨迹、评测结果 |
| 静态演示数据 | `docs/demo-data.json` | 由 `scripts/build_demo_data.py` 从真实 trace 生成 |

## 14. 提交清单

```text
学号-姓名-校园网延迟调查Agent/
├── report.pdf
├── README.md
├── requirements.txt
├── .env.example
├── backend/                  # FastAPI + DeepSeek 桥接 + 规则回退
├── src/                      # Agent / Tools / Skill 加载器 / CLI 入口
├── skills/                   # SKILL.md + reference.md
├── data/sample_data.json
├── tests/                    # cases.json + evaluate.py
├── results/                  # 对照实验、trace、汇总
├── docs/                     # 三份设计文档 + 前端代码 + 图表 + 截图
└── scripts/                  # 图表、截图、PDF、demo-data 生成
```
