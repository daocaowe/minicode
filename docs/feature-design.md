# MiniCode Harness 功能设计文档

- 文档状态：Draft v0.1
- 技术方向：Python 3.12+、本地优先、CLI 优先
- 项目定位：用于学习 Agent Runtime / Harness 的可运行 Coding Agent

## 1. 背景与目标

本项目参考 [earendil-works/pi](https://github.com/earendil-works/pi)，但不直接 Fork 或复制实现。目标是亲手用 Python 构建一个可观察、可恢复、可扩展的 Coding Agent，逐层理解：用户任务 -> 会话与上下文 -> Agent Loop -> LLM -> Tool Call -> 本地工具 -> Tool Result -> 继续推理、验证与恢复。

项目成功标准不是短期内做出一个比 Codex 更强的产品，而是每个阶段都能独立运行、可测试、可回放，并能解释 Agent 为什么做出某个动作。

### 1.1 学习目标

1. 理解消息、工具调用、工具结果和停止条件组成的 Agent Loop。
2. 理解会话持久化、分支、恢复和上下文投影。
3. 理解 Token 预算、上下文选择和压缩，而不是只把历史消息全部拼接给模型。
4. 理解文件、Shell、Git、网络等副作用的权限决策。
5. 理解 Skill、MCP、Extension 如何在稳定核心之上扩展。
6. 理解事件流、Trace、Replay、Evaluation 和 Recovery 如何构成 Harness。

### 1.2 产品目标

- 在本地代码仓库中完成“读取 -> 修改 -> 执行测试 -> 根据结果继续修改”的闭环。
- 支持至少一个 OpenAI-compatible Provider，并提供 Fake Provider 供离线测试。
- 支持流式输出、会话恢复、自动压缩、工具审批和 JSONL 事件导出。
- 提供稳定的 Python API，使 CLI、JSON 模式、未来 TUI/RPC 共用同一运行时。

### 1.3 非目标

- 第一阶段不做 GUI、IDE 插件、云端协作和多租户服务。
- 不追求兼容 Codex、Pi 或任何现有产品的全部命令与协议。
- 不在 V0 自研模型、向量数据库、代码索引或多 Agent 编排。
- 不把自动执行任意 Shell 当作默认体验；安全策略必须先于高级自动化。

## 2. 设计原则

| 原则 | 具体要求 |
| --- | --- |
| 可观察 | 每次模型请求、工具调用、权限决策和状态变化都有结构化事件。 |
| 可恢复 | 关键状态写入追加式日志；进程中断后可以从最后一个一致边界继续。 |
| 小核心 | Agent Loop、Tool Protocol、Session Store 先保持简单，复杂能力以扩展层加入。 |
| 副作用可控 | 文件、进程、网络操作经过统一 Policy；默认拒绝高风险动作。 |
| 提供商隔离 | Provider 只负责协议和流式响应，不能把业务逻辑泄漏到 Loop。 |
| 离线可学 | Fake LLM、固定工具结果和 Replay 让核心测试不依赖 API Key。 |
| 渐进交付 | 每个阶段都有最小演示、测试和明确的完成条件。 |

## 3. 参考项目提炼

本设计参考 pi 仓库在 2026-10-03 拉取到的 main 快照，commit 为 a276dabe57911253350bffb93cb7d7aff6a73261。关键启发如下：

| Pi 的边界 | MiniCode 的对应设计 |
| --- | --- |
| packages/agent：通用 Agent 状态与循环 | runtime/agent.py：不感知 CLI 的 Agent Runtime |
| packages/ai：多 Provider 与统一消息类型 | llm/：Provider Protocol、OpenAI-compatible、Fake Provider |
| packages/coding-agent：会话、工具、资源和运行模式 | session/、tools/、resources/、cli.py |
| JSONL 会话树与 Compaction | 先做线性追加日志，再做带 parent_id 的分支树和压缩边界 |
| read/write/edit/bash 默认工具 | V0 保持四类核心工具，后续再加 grep/find/ls/git |
| Skills、Extensions、MCP | V4 以后逐层引入，先定义稳定协议再加载第三方代码 |
| TUI、JSON、RPC 多模式 | CLI 和 JSONL 先共用 Runtime，TUI/RPC 列为后续模式 |
| Pi 没有内置权限系统 | MiniCode 将 Permission/Policy 作为学习重点，但独立于工具实现 |

参考资料：

- [Pi README](https://github.com/earendil-works/pi)
- [Pi Agent Loop](https://github.com/earendil-works/pi/tree/main/packages/agent)
- [Pi Session Format](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/session-format.md)
- [Pi JSON Event Stream](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/json.md)
- [Pi Extensions](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md)
- 用户提供的聊天记录：[ChatGPT 分享链接](https://chatgpt.com/s/t_6abfd84af7dc8191ae021a09cf33555e)

## 4. 用户与典型场景

### 4.1 主要用户

- 学习者：通过实现一个真实可用的 Coding Agent 学习 Harness。
- 项目作者：看到 Agent 的上下文、工具动作、失败原因和恢复过程。
- 实验开发者：替换模型、工具或策略，而不修改核心循环。

### 4.2 V0 场景

~~~text
$ minicode "找出项目启动失败的原因并修复，最后运行测试"

用户：找出项目启动失败的原因并修复，最后运行测试
Agent：我先读取项目入口和依赖配置。
Tool  read(package.json)
Tool  read(src/main.py)
Agent：发现启动命令引用了不存在的模块，我先修复它。
Tool  edit(src/main.py) -> approval: auto
Tool  bash(pytest -q) -> exit=0
Agent：已修复并通过测试。
~~~

### 4.3 V1 以后场景

- resume：中断后继续当前任务。
- fork：保留原任务，尝试另一种修复方案。
- compact：上下文过长时保留摘要和最近工作。
- approve：只允许本次执行一个被阻止的命令。
- replay：使用保存的事件重放工具调用，不再次触发外部副作用。
- json：让脚本或未来 UI 消费结构化事件。

## 5. 总体架构

~~~mermaid
flowchart TB
    U[用户 / CLI] --> S[Session Runtime]
    S --> L[Agent Loop]
    L --> C[Context Engine]
    L --> P[LLM Provider]
    L --> R[Tool Registry]
    R --> Q[Permission Policy]
    Q --> T[Tool Executor]
    T --> FS[文件系统]
    T --> SH[Shell / 进程]
    T --> G[Git 可选]
    L --> E[Event Bus]
    E --> J[JSONL Trace]
    S --> D[Session Store]
    L --> X[Extension / Skill / MCP]
    P --> O[OpenAI-compatible API]
~~~

### 5.1 模块职责

| 模块 | 负责 | 不负责 |
| --- | --- | --- |
| cli | 参数解析、输入、展示事件、退出码 | Agent 决策、直接执行工具 |
| runtime | Agent 状态、循环、队列、停止与取消 | 文件路径解析、Provider 细节 |
| llm | Provider 请求、流式增量、错误标准化 | 是否执行工具、权限决策 |
| tools | 参数校验、实际工具动作、结果截断 | 决定是否允许执行 |
| policy | 风险分类、审批、沙箱边界 | 运行命令本身 |
| context | 消息选择、Token 预算、摘要与压缩 | 修改原始会话历史 |
| session | 追加日志、恢复、分支、索引 | 生成模型摘要 |
| events | 发布、订阅、JSONL 序列化、Trace | 业务状态持久化策略 |
| resources | 配置、项目指令、Skill、Extension 加载 | 执行未信任代码 |
| ui | CLI/JSON/TUI 适配 | 核心状态和策略 |

### 5.2 运行时状态

~~~text
Run
├── run_id
├── session_id
├── task_status: idle | running | waiting_approval | completed | failed | aborted
├── model: provider + model + thinking_level
├── context: projected messages + token estimate
├── pending_tool_calls
├── usage: input/output/cache/cost
└── cancellation / retry state
~~~

## 6. 功能设计

### 6.1 Agent Loop

行为：

1. 接收用户消息并写入当前会话。
2. 构造系统提示、历史消息、工具声明和项目上下文。
3. 调用 LLM，消费文本和工具调用增量。
4. 对工具参数做 JSON Schema 校验。
5. 请求 Policy 决策；允许时执行，阻止时生成可解释的错误 Tool Result。
6. 将 Assistant Message 和 Tool Result 写回会话。
7. 若存在工具调用，继续下一轮；否则根据停止原因结束。
8. 处理取消、Provider 错误、上下文溢出和可重试错误。

停止条件：模型返回 stop 且没有待处理工具调用；用户取消；达到最大轮次、工具数或运行时间；或发生不可恢复错误。

V0 只支持顺序执行，便于理解日志和副作用。V3 以后允许工具声明 sequential 或 parallel；写文件、Shell、Git 默认顺序执行。

### 6.2 LLM Provider

Provider Protocol 至少提供异步 stream 接口，接收 LLMRequest 并产生 AsyncIterator[LLMEvent]。标准化事件：response_start、text_delta、thinking_delta、tool_call_start、tool_call_delta、tool_call_end、usage、response_end、provider_error。

#### 6.2.1 Provider 适配层

Runtime 只依赖统一的 LLMProvider，具体协议通过 Adapter 实现：

| Adapter | 用途 | 协议 |
| --- | --- | --- |
| FakeProvider | 离线测试和 Evaluation | 本地脚本 |
| OpenAICompatibleAdapter | 官方 OpenAI、国内外中转站和自建网关 | /chat/completions，可选 /responses |
| AnthropicAdapter | Anthropic 原生接口 | /v1/messages |

中转站不得在 Runtime 中单独写分支。只要实现 OpenAI-compatible 请求和响应格式，就通过 OpenAICompatibleAdapter 接入。

#### 6.2.2 Provider 配置

每个 Provider 使用独立配置，支持官方地址、中转站地址和自建代理：

~~~toml
[providers.openai]
adapter = "openai-compatible"
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"
default_model = "gpt-4o-mini"
timeout_seconds = 120
max_retries = 2

[providers.my-relay]
adapter = "openai-compatible"
base_url = "https://relay.example.com/v1"
api_key_env = "MY_RELAY_API_KEY"
default_model = "provider/model-name"
timeout_seconds = 180
max_retries = 3
~~~

配置规则：

- base_url 必须由用户显式配置；不得根据模型名猜测地址。
- API Key 只通过环境变量或凭据存储读取，不写入配置文件、Session 或 Trace。
- 支持自定义请求头，但默认禁止把 Key 放入 URL 查询参数。
- model 允许使用中转站要求的原始模型名，并支持可选的本地别名映射。
- 记录 provider、adapter、base_url 主机名、model 和 request_id；不记录认证头和完整请求内容。

#### 6.2.3 请求与兼容策略

OpenAI-compatible Adapter 负责：

1. 将统一消息、工具声明和 thinking 参数转换为目标接口格式。
2. 使用 SSE 或兼容的 JSON 流解析增量文本、工具调用和 usage。
3. 兼容中转站常见差异：末尾 /v1、自定义模型名、缺少 usage、工具参数分片和非标准错误字段。
4. 对非流式响应提供降级路径，但事件层仍输出同样的标准化事件。
5. 将 HTTP 状态码、服务商错误码、request_id 和可重试性转换为 provider_error。

默认重试只针对超时、连接断开、429 和 5xx；认证失败、模型不存在、参数错误不自动重试。每次重试都写入 Trace，并遵守 max_retries 和指数退避上限。

#### 6.2.4 Provider 选择

CLI 通过 --provider 选择配置，通过 --model 覆盖默认模型；也允许使用 provider/model 形式一次指定两者：

~~~text
minicode run --provider my-relay --model provider/model-name "修复测试失败"
minicode run --model my-relay/provider/model-name "修复测试失败"
~~~

启动时执行配置校验和可选的 auth check，在真正运行前明确报告 base URL、模型和认证是否可用；不得把 API Key 打印到终端。

### 6.3 核心工具

| 工具 | 输入 | 输出 | 默认策略 |
| --- | --- | --- | --- |
| read | 相对路径、起止行、最大字节数 | 文件内容、实际范围、截断信息 | 自动允许 |
| write | 相对路径、完整内容 | 写入字节数、文件哈希 | 新文件可自动允许，覆盖需询问 |
| edit | 相对路径、唯一旧文本、新文本 | 替换数、差异摘要 | 询问或按配置自动允许 |
| bash | 命令、超时、工作目录 | stdout、stderr、退出码、耗时 | 默认询问 |

共同要求：结构化参数；面向模型的短文本和面向 Trace 的 details；输出按字节和行数截断；携带 tool_call_id；路径归一化并阻止越界访问和符号链接逃逸。V2 以后再加入 grep、find、ls、git_diff、git_status。

### 6.4 Session

采用追加式 JSONL，第一行是 Header，后续每行一个 Entry。原始历史只追加不改写；上下文删除或替换通过新 Entry 表达。

~~~json
{
  "type": "session",
  "version": 1,
  "session_id": "01J...",
  "cwd": "/repo",
  "created_at": "2026-10-03T10:00:00Z"
}
~~~

~~~json
{
  "type": "message",
  "entry_id": "e01",
  "parent_id": null,
  "timestamp": "2026-10-03T10:00:01Z",
  "message": {"role": "user", "content": "修复测试失败"}
}
~~~

Entry 类型按阶段演进：message、run、approval、compaction、branch、custom。恢复时只重放当前叶子到根的路径；分支和压缩不删除历史。

### 6.5 Context Engine

Context Engine 为每次模型调用生成投影，不直接修改 Session Store。输入包括系统提示、项目指令、当前分支消息、文件与 Git 摘要、Skill、工具声明和 Token 预算。

策略顺序：先估算 Token；再移除冗余工具输出和重复文件内容；保留最近一轮完整链路；仍超限时调用摘要模型生成 compaction Entry；摘要失败时回退到确定性的截断策略并报告。

### 6.6 Permission / Policy

权限层接收规范化 Action：kind、target、workspace、destructive、open_world 和 metadata。策略结果为 allow、ask 或 deny。策略决定必须进入事件流。

| 动作 | 默认 | 说明 |
| --- | --- | --- |
| 读取工作区内普通文本文件 | allow | 超过大小限制仍需截断 |
| 写入新文件 | ask | 可配置为 allow |
| 覆盖已有文件 | ask | 展示差异摘要 |
| Shell 命令 | ask | 按命令和参数分类 |
| rm -rf、磁盘格式化、凭据读取 | deny | 不提供绕过开关 |
| 外部网络访问 | ask | V4 以后按域名白名单 |
| Git 提交、重置、推送 | ask | 破坏性操作更严格 |

### 6.7 Skill、Extension 与 MCP

Skill 是受控 Markdown 资源，提供领域说明、流程和约束，不直接执行代码。Extension 通过注册表声明工具、生命周期 Hook、Slash Command、事件订阅器和自定义 Session Entry；它不能绕过 Policy。MCP 放在适配层中，负责远程工具发现、参数转换、结果转换和工具注解到本地 Policy 的映射，V4 以后默认延迟加载。

### 6.8 Event、Trace 与 Replay

事件使用版本化 JSONL，字段至少为 event_id、run_id、seq、timestamp、type、payload。核心事件包括 run_start、turn_start、llm_request、llm_delta、tool_call_start、policy_decision、tool_execution_start、tool_execution_end、message_append、compaction_start、compaction_end、run_end、run_error。

Replay 只重放消息和决策；标记为 replay_safe 的工具可以复用保存结果；写文件、Shell、网络等副作用工具默认阻止再次执行。

### 6.9 Evaluation

Evaluation 不依赖真实 API，使用固定工作区 Fixture、Fake Provider 脚本、预期工具序列、文件差异、测试结果以及 Token、轮数和恢复次数。第一批任务为读取文件、改单文件、修复测试失败、权限拒绝、压缩后继续和 Provider 失败重试。

## 7. CLI 设计

V0 命令：

~~~text
minicode [OPTIONS] [PROMPT]
minicode run "..."
minicode resume [SESSION_ID]
minicode sessions
minicode inspect <RUN_OR_SESSION_ID>
minicode replay <RUN_ID>
minicode config
~~~

建议参数：cwd、model、provider、no-session、json、approve、max-turns、tools、verbose。退出码为 0 完成、1 运行失败、2 参数或 Provider 不可用、130 用户中断。

## 8. 配置与目录

~~~text
~/.minicode/
├── config.toml
├── sessions/<workspace-key>/*.jsonl
├── traces/<run-id>.jsonl
├── skills/
└── extensions/

<repo>/.minicode/
├── config.toml
├── instructions.md
└── skills/
~~~

配置优先级：命令行 > 项目配置 > 用户配置 > 内置默认值。Provider 配置按名称管理，至少包含 adapter、base_url、api_key_env、default_model、timeout_seconds 和 max_retries。敏感配置只读取环境变量或凭据存储；Trace 不写入 API Key、完整环境变量或未经确认的文件内容。

## 9. 非功能要求

| 类别 | V0 要求 | V1+ 目标 |
| --- | --- | --- |
| Python | 3.12+ | 3.13 兼容 |
| 可测试性 | Loop、Tool、Store 有单元测试 | Fixture/Eval/Property Test |
| 可观测性 | stderr 日志 + JSONL 事件 | Trace 查询、统计和回放 |
| 稳定性 | 工具错误转为 Tool Result | 重试、断点恢复和幂等键 |
| 性能 | 单次交互可用 | 输出截断、异步工具、并行只读工具 |
| 安全 | 工作区边界、审批 | 沙箱、网络白名单、凭据隔离 |
| 兼容 | OpenAI-compatible 官方接口和中转站、Fake Provider | Anthropic Adapter、多 Provider、MCP、RPC |

## 10. 风险与应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 过早做 TUI | 核心循环难测试 | 先做 CLI/JSON，UI 只消费事件 |
| 上下文不可控 | 长任务中断或错误继续 | 从 V2 起记录 Token 估算和压缩边界 |
| Shell 权限过宽 | 破坏工作区或泄露凭据 | Policy 默认 ask/deny，敏感路径阻断 |
| Provider 差异 | Loop 被单个 API 绑死 | 统一 Provider Event 和 Fake Provider |
| 只验证最终文件 | 不知道 Agent 如何成功 | 保存事件、工具参数、策略决策 |
| 扩展过早稳定 | API 难以演进 | V0-V3 稳定核心 Protocol，V4 发布扩展接口 |

## 11. 版本目标与验收

| 版本 | 关键能力 | 可演示结果 |
| --- | --- | --- |
| V0 | Fake/OpenAI-compatible Provider、Agent Loop、read/write/edit/bash、CLI | 解决小型测试失败任务 |
| V1 | JSONL Session、resume、fork、JSON 输出 | 中断后继续任务 |
| V2 | Context Engine、Token 预算、Compaction | 长对话压缩后继续 |
| V3 | Permission Policy、审批、路径边界、取消 | 危险命令被阻止，普通动作可执行 |
| V4 | Skill、Extension、MCP 适配 | 不改核心代码增加工具和知识 |
| V5 | Trace、Replay、Retry、Recovery、Evaluation | 回放失败并比较策略 |
| V6 | TUI、RPC、可选多 Agent | Runtime 被多个客户端复用 |

每个版本都必须有文档、可运行示例、自动化测试、失败路径和升级说明。

## 12. 待决策项

1. 是否加入 Anthropic 原生协议。  答复：Adapter 架构，加入 Anthropic
2. Session Store 长期使用 JSONL，还是 V5 增加 SQLite 索引。答复：长期使用 JSONL
3. Shell 隔离选择本机 Policy、容器、Windows Sandbox 还是外部执行器。答复：本机docker容器
4. Extension 是否只允许可信目录，还是增加签名与版本校验。答复：只允许可信目录
5. 是否把 git 工具做成独立 Policy Domain。答复：独立 Policy Domain

## 13. 术语

- **Agent Loop**：模型响应、工具执行、工具结果再送回模型的循环。
- **Harness**：围绕 Agent 的状态、工具、策略、恢复、观测和评测运行时。
- **Projection**：从原始 Session 历史计算出的、实际发送给模型的消息视图。
- **Compaction**：将较早历史摘要为较短上下文，同时保留原始日志。
- **Replay**：使用已保存的事件或工具结果复现运行，不重复副作用。

## 14. 结论

MiniCode 的核心学习顺序是：可运行 Loop -> 可持久化 Session -> 可控 Context -> 可解释 Permission -> 可扩展 Resource -> 可回放 Harness。只要每一级都通过真实场景和离线测试验证，项目就能逐步接近可用 Coding Agent，同时保留为什么这样设计的学习价值。
