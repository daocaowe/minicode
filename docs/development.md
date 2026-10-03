# MiniCode Harness 开发文档

- 对应设计：功能设计文档（docs/feature-design.md）
- 编码约束：项目编码规范（docs/coding-standards.md）
- 开发语言：Python 3.12+
- 开发方式：以小版本迭代为主，积木作为版本内部的实现任务
- 当前状态：规划文档

## 1. 开发方法

本项目采用“最小核心 -> 可用工具 -> 可恢复状态 -> 可控上下文 -> 安全策略 -> 扩展与评测”的版本迭代方式。每个版本围绕一个可运行的学习目标推进，先完成主流程，再补充失败路径、测试和文档。

积木是版本内部的实现任务，不是必须独立交付的产品单元。可以在一次开发中连续完成多个相关积木，也可以根据学习难度拆成多个小提交。不要为了形式上的积木边界重复搭建流程、接口或测试框架。

每个版本只需要记录四件事：学习目标、功能范围、验证方式、进入下一版本的条件。实现过程中优先保证主链路可运行；安全边界、数据损坏、取消和 Provider 错误等高风险路径必须及时补测。

任何新能力都必须通过稳定接口接入，不能在 CLI 里绕过 Runtime 直接调用文件系统或模型。遇到设计不确定时，保留最小实现和实验记录，在下一个版本再演进，不提前实现全部扩展能力。

## 2. 技术基线

### 2.1 推荐工具链

| 类别 | 选择 | 说明 |
| --- | --- | --- |
| Python | 3.12 或更高 | 使用 asyncio、TaskGroup、typing.Protocol、tomllib |
| 构建 | pyproject.toml | 使用 src 布局和可编辑安装 |
| CLI | 第一阶段 argparse；后续 Typer 可选 | 先学习边界，再优化体验 |
| 网络 | V0 无依赖 Fake Provider；真实 Provider 使用 httpx | 支持官方接口、中转站和自建网关 |
| 数据校验 | dataclasses + 手工校验；V2 可选 Pydantic | 核心协议先保持透明 |
| 日志 | logging 到 stderr | stdout 留给 JSONL 协议 |
| 测试 | pytest、pytest-asyncio | Fake Provider 和临时目录覆盖副作用 |
| 格式化 | ruff format、ruff check | 在版本提交前运行 |
| 类型检查 | pyright 或 mypy | 从公共 Protocol 开始检查 |

V0 尽量只使用标准库和测试依赖。没有 API Key 时，所有核心测试都必须通过。

### 2.2 初始化命令

~~~powershell
py -3.12 -m venv .venv
.venv\\Scripts\\Activate.ps1
python -m pip install -U pip
python -m pip install -e ".[dev]"
python -m pytest -q
~~~

Linux/macOS 使用 .venv/bin/activate。若目标环境没有 py 命令，直接使用 python3.12。

### 2.3 pyproject.toml 最小形态

~~~toml
[project]
name = "minicode-harness"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[project.optional-dependencies]
provider = ["httpx>=0.27,<1"]
dev = ["pytest>=8,<9", "pytest-asyncio>=0.23,<1", "ruff>=0.6,<1", "pyright>=1.1,<2"]

[project.scripts]
minicode = "minicode.cli:main"

[tool.pytest.ini_options]
addopts = "-ra"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
~~~

## 3. 目标目录结构

先创建目录，后续积木只在对应区域增加文件：

~~~text
.
├── pyproject.toml
├── README.md
├── docs/
│   ├── feature-design.md
│   └── development.md
├── src/minicode/
│   ├── __init__.py
│   ├── cli.py
│   ├── errors.py
│   ├── config.py
│   ├── domain/
│   │   ├── messages.py
│   │   ├── tools.py
│   │   ├── runs.py
│   │   └── events.py
│   ├── runtime/
│   │   ├── agent.py
│   │   ├── loop.py
│   │   └── queues.py
│   ├── llm/
│   │   ├── protocol.py
│   │   ├── fake.py
│   │   └── openai_compatible.py
│   ├── tools/
│   │   ├── protocol.py
│   │   ├── registry.py
│   │   ├── filesystem.py
│   │   ├── shell.py
│   │   └── builtin.py
│   ├── session/
│   │   ├── protocol.py
│   │   ├── jsonl_store.py
│   │   ├── projection.py
│   │   └── manager.py
│   ├── context/
│   │   ├── budget.py
│   │   ├── selector.py
│   │   └── compaction.py
│   ├── policy/
│   │   ├── protocol.py
│   │   ├── rules.py
│   │   └── approval.py
│   ├── resources/
│   │   ├── loader.py
│   │   ├── skills.py
│   │   └── extensions.py
│   ├── observability/
│   │   ├── bus.py
│   │   ├── jsonl_trace.py
│   │   └── replay.py
│   └── ui/
│       ├── text.py
│       ├── json.py
│       └── tui.py
└── tests/
    ├── unit/
    ├── integration/
    ├── fixtures/
    └── evals/
~~~

依赖方向固定为：domain -> protocol -> adapter/runtime -> ui/cli。底层模块不能导入 cli；工具不能直接导入 Session Manager；UI 只能订阅事件。

## 4. 核心协议先行

### 4.1 消息模型

先使用 dataclass，保持字段可见：

~~~python
@dataclass(frozen=True)
class TextPart:
    text: str

@dataclass(frozen=True)
class ToolCallPart:
    call_id: str
    name: str
    arguments: dict[str, object]

@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: tuple[TextPart | ToolCallPart, ...]
    timestamp: datetime
    tool_call_id: str | None = None
    tool_name: str | None = None
    is_error: bool = False
~~~

模型可见的消息和 UI/Trace 专用数据分开；Tool Result 必须能定位到原始 Tool Call；不要把任意 Python 对象塞进消息。

### 4.2 LLM 协议

~~~python
class LLMProvider(Protocol):
    name: str

    async def stream(
        self,
        request: LLMRequest,
        *,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[LLMEvent]: ...
~~~

LLMRequest 至少包含 model、messages、tools、system_prompt、temperature、max_tokens 和 metadata。LLMEvent 为带 type 字段的不可变数据；参数不完整或解析失败时发出 provider_error，不让 Provider 异常穿透 Loop。

### 4.3 Tool 协议

~~~python
class Tool(Protocol):
    name: str
    description: str
    input_schema: dict[str, object]
    replay_safe: bool
    default_execution: Literal["sequential", "parallel"]

    async def execute(
        self,
        call: ToolCall,
        context: ToolContext,
    ) -> ToolResult: ...
~~~

ToolContext 提供 workspace、cancel、event_sink、policy 和只读配置。Tool 不接收 CLI 对象，也不自己读取用户输入。

### 4.4 事件协议

~~~python
@dataclass(frozen=True)
class Event:
    event_id: str
    run_id: str
    sequence: int
    timestamp: datetime
    type: str
    payload: dict[str, object]
    schema_version: int = 1
~~~

EventBus 负责发布和订阅；JsonlTrace 负责持久化；TextUI 和 JsonUI 是两个不同订阅者。这样加入 TUI 或 RPC 时，不需要改 Agent Loop。

## 5. 版本演进图

~~~mermaid
flowchart LR
    V0[ V0 最小 Loop ] --> V1[ V1 可用 Coding Agent ]
    V1 --> V2[ V2 Session 与恢复 ]
    V2 --> V3[ V3 Context Engine ]
    V3 --> V4[ V4 Permission 与 Docker 隔离 ]
    V4 --> V5[ V5 Skill、Extension、MCP ]
    V5 --> V6[ V6 Trace、Replay、Evaluation ]
    V6 --> V7[ V7 TUI、RPC、可选多 Agent ]
~~~

## 6. 版本迭代记录

下面的版本是唯一的开发入口。开始开发时先选择当前 V 版本，再按照映射完成对应的 B 任务；B 任务可以在同一版本内合并实现，也可以拆成多个提交。未完成当前版本的必需 B 任务，不进入下一版本。

| 版本 | 对应 B 任务 | 学习目标 | 主要功能 | 进入下一版的条件 |
| --- | --- | --- | --- | --- |
| V0 | B0-B4 | 看懂 Agent Loop | 工程骨架、领域模型、Fake Provider、Tool Registry、顺序 Loop | 能完成一次两轮任务，测试不依赖 API Key |
| V1 | B5-B7（B2 的真实 Provider 部分） | 做出可用 Coding Agent | read/write/edit/bash、OpenAI-compatible 与中转站、文本/JSON 输出 | 能修复 fixture 项目并运行测试 |
| V2 | B8-B9 | 理解 durable state | JSONL Session、resume、fork、run 状态和事件 | 中断后能恢复当前分支，原始日志不改写 |
| V3 | B10 | 理解 Context Engineering | Projection、Token 预算、工具输出裁剪、Compaction | 压缩后仍能继续任务，历史可追溯 |
| V4 | B6（Docker 加固）、B11 | 理解安全运行时 | allow/ask/deny、审批、路径边界、Git Policy、Docker Shell | 危险动作被阻止，普通任务可审批执行 |
| V5 | B12-B13（B2 的 Anthropic Adapter 部分） | 理解可扩展 Harness | Skill、Extension、Anthropic Adapter、MCP | 不修改核心 Loop 即可增加能力 |
| V6 | B14-B15 | 理解观测与评测 | Trace、Replay、Retry、Recovery、Evaluation | 可离线复盘运行并比较版本质量 |
| V7 | B16 | 扩展客户端形态 | TUI、RPC，按需要评估多 Agent | 多客户端复用同一 Runtime，权限边界不被破坏 |

说明：B2 负责 Provider 抽象和 Fake Provider，V1 才接入真实 OpenAI-compatible/中转站，V5 再接入 Anthropic Adapter。B6 先在 V1 实现受控 Shell，V4 增加 Docker 隔离和更严格策略。一个 B 任务跨版本时，以表格中的“当前版本增量”作为实现范围。

每个版本的记录建议包含：完成日期、变更摘要、关键决策、演示命令、测试结果、遗留问题和下一版本入口。这样可以把编码过程变成可回顾的 Agent 学习日志。

## 7. 版本内部实现任务

以下 B 任务是实现清单，不是独立开发流程。任务标题保留稳定编号，具体完成范围以第 6 节版本映射为准。

### B0：工程骨架与可重复测试

**目标**：创建可安装、可测试、可格式化的 Python 项目。

**实现步骤**：

1. 创建 pyproject.toml、src/minicode 和 tests。
2. 添加空的 cli.main，执行 minicode --help 能退出 0。
3. 添加 errors.py，定义 ConfigurationError、ProviderError、ToolError、PolicyDenied、RunAborted。
4. 添加 pytest、ruff、类型检查配置。
5. 在 README 中写明安装、测试和 Fake 模式。

**测试**：包可编辑安装、CLI 返回码、异常类层次和临时目录可用。

**演示**：执行 python -m minicode.cli --help，输出项目名和版本。

**完成条件**：新机器按初始化命令可安装；pytest、ruff check、ruff format --check 全部通过。

### B1：领域模型与序列化

**目标**：定义 Message、ToolCall、ToolResult、LLMRequest、Run、Event，建立稳定数据边界。

**实现步骤**：

1. 所有模型使用 frozen dataclass 或明确的工厂函数。
2. 为每个模型实现 to_dict 和 from_dict；JSON 中只出现基本类型。
3. 对 role、stop_reason、tool 状态、Run 状态做显式字符串校验。
4. 为未知事件字段保留兼容空间，但未知核心类型必须报错。

**测试**：往返序列化、缺少字段、错误 role、嵌套 Tool Call、非 JSON 值拒绝。

**演示**：短脚本构造用户消息和工具结果，打印稳定 JSON。

**完成条件**：事件、会话和 Provider 都只依赖 domain 模型，不再在各模块复制字典结构。

### B2：Fake Provider 与流式事件

**目标**：不连接真实 API 就能驱动一次完整模型响应。

**实现步骤**：

1. FakeProvider 接受事件脚本，例如文本响应、工具调用、错误和延迟。
2. 按事件顺序异步 yield；支持 cancel 被设置后发出 aborted。
3. 增加 ScriptedScenario，允许测试按第几轮返回不同内容。
4. 记录收到的 LLMRequest，方便断言上下文和工具声明。
5. 定义 ProviderConfig：adapter、base_url、api_key_env、default_model、timeout_seconds、max_retries 和 headers。
6. 实现 OpenAICompatibleAdapter：支持 /chat/completions、SSE 增量、工具调用分片、usage 缺失和中转站自定义模型名。
7. 将超时、连接断开、429、5xx 标记为可重试；认证失败、模型不存在和参数错误不自动重试。
8. 实现 AnthropicAdapter，保持与 OpenAI-compatible Adapter 相同的 LLMEvent 输出，不修改 Agent Loop。
9. API Key 只从环境变量或凭据存储读取；Trace 只记录 Provider 名、主机名、模型和 request_id。

**测试**：文本流、工具调用流、Provider 错误、取消、多个轮次、官方 OpenAI-compatible 地址、中转站 base_url、SSE 分片、重试分类、缺失 usage、认证失败和 Anthropic Adapter。

**演示**：Fake Provider 对用户问题先调用 read，再返回总结。

**完成条件**：后续任何 Agent Loop 测试都不需要 API Key；用户只修改 Provider 配置和环境变量即可切换官方接口、中转站或 Anthropic；Agent Loop 不包含 Provider 分支。

### B3：Tool Protocol 与 Registry

**目标**：以统一方式注册、查找、校验和执行工具。

**实现步骤**：

1. 定义 Tool、ToolCall、ToolResult、ToolContext。
2. Registry 的 register、get、list、declarations 方法保持确定性排序。
3. 执行前校验工具名、调用 ID 和参数 schema。
4. 异常转换为 is_error=true 的 ToolResult，同时向 EventBus 发出错误事件。
5. 工具输出提供 max_bytes、max_lines 和 truncated 字段。

**测试**：重复注册、未知工具、错误参数、结构化结果、输出截断。

**演示**：注册 echo 工具，Fake Provider 调用它并得到 Tool Result。

**完成条件**：Runtime 只依赖 Registry，不依赖具体 read、bash 实现。

### B4：最小 Agent Loop

**目标**：完成用户消息 -> LLM -> 工具 -> LLM -> 最终回答。

**推荐循环**：

~~~text
append user message
while run is active:
    build context
    stream provider events
    append assistant message
    if no tool call:
        finish run
    for tool call in source order:
        validate arguments
        execute tool
        append tool result
    check limits and cancellation
~~~

**实现步骤**：

1. AgentState 保存 messages、tools、model、run_id、turn_index。
2. Loop 每轮发布 turn_start、llm_request、message_append、tool_execution_* 和 turn_end。
3. 工具结果必须追加后再请求下一轮。
4. max_turns、max_tool_calls、cancel 和 Provider error 都有明确终态。
5. 先只实现顺序工具调用，不做并行。

**测试**：无工具文本回答、一次工具调用、连续两轮、工具异常、Provider 错误、达到上限、取消。

**演示**：Fake Provider 调用 echo 后完成任务，终端打印每轮事件。

**完成条件**：不经过 CLI 也能用一个 asyncio 测试启动和结束 Run。

### B5：工作区文件工具

**目标**：实现安全可测试的 read、write、edit。

**实现步骤**：

1. WorkspaceResolver 将输入路径解析为工作区内绝对路径。
2. 拒绝 .. 越界、绝对路径（除非显式允许）和符号链接逃逸。
3. read 支持行号、最大字节、编码错误提示和截断。
4. write 区分新文件与覆盖，先写临时文件再原子替换。
5. edit 要求旧文本匹配次数为 1；0 次或多次都返回可解释错误。
6. 计算修改前后 SHA-256 和简短 unified diff，写入 details。

**测试**：正常读取、空文件、二进制拒绝、越界路径、符号链接、原子写、唯一替换和失败不改文件。

**演示**：在 tests/fixtures/workspace 中让 Agent 修改一个有失败断言的 Python 文件。

**完成条件**：文件工具不需要 CLI，也不读取环境变量中的审批开关。

### B6：Shell 工具与取消

**目标**：在受控条件下运行测试命令，正确处理超时和输出。

**实现步骤**：

1. 使用 asyncio.create_subprocess_exec，避免通过 shell 字符串拼接参数。
2. V0 提供 command、cwd、timeout；是否允许由后续 Policy 决定。
3. 持续读取 stdout/stderr，发布增量事件，达到限制后继续消费但只保留摘要。
4. 超时先 terminate，再在宽限期后 kill；记录 signal、exit_code 和 duration。
5. 将 Windows 和 POSIX 进程终止差异隔离在 shell.py。

**测试**：退出 0、非 0、stdout/stderr、超时、取消、大输出、工作目录。

**演示**：Agent 运行 pytest -q，读取失败输出后调用 edit，再次运行成功。

**完成条件**：Shell 结果对模型简短，对 Trace 完整；不会阻塞事件消费。

### B7：CLI 与双模式输出

**目标**：让 Runtime 成为用户可操作的命令行程序。

**实现步骤**：

1. argparse 解析 prompt、cwd、provider、model、no-session、json、max-turns、timeout 和 max-retries。
2. TextUI 订阅事件，文本增量直接打印，工具调用显示名称、参数摘要和结果状态。
3. JsonUI 每行输出一个 Event，stdout 只放协议数据，诊断放 stderr。
4. Ctrl+C 设置 cancel event，不直接杀死子进程。
5. 统一退出码和错误信息。

**测试**：参数解析、文本模式、JSONL 模式、stdin prompt、Ctrl+C 状态转换和退出码。

**演示**：执行 minicode run 任务；再执行 minicode run --json 任务并将事件写入文件。

**完成条件**：CLI 不包含 Agent Loop 逻辑，只负责组装依赖和展示；--provider 选择配置，--model 覆盖默认模型，并支持 provider/model 形式。

### B8：Session JSONL Store

**目标**：让一次运行可被保存、检查和恢复。

**实现步骤**：

1. SessionStore 提供 create、append、read、list、find。
2. Header 记录 session_id、cwd、created_at 和 version。
3. 每个 Entry 有 entry_id、parent_id、timestamp、type 和 payload。
4. append 使用换行 flush；必要时使用临时文件和锁，防止半行写入。
5. 读取时忽略最后一个不完整行并发出诊断，不破坏之前的 Entry。
6. Message、Run、Approval 和 Compaction 先都作为类型字符串存储。

**测试**：追加读取、进程中断半行、工作区分组、并发追加策略、错误 JSON 行和版本字段。

**演示**：一次任务生成 session.jsonl，inspect 命令显示消息数、工具数和最后状态。

**完成条件**：关闭进程后重新启动可以读取完整历史；原始日志不被改写。

### B9：Resume、Fork 与当前分支

**目标**：实现可恢复会话树，但先保持规则简单。

**实现步骤**：

1. 从当前叶子沿 parent_id 回溯，反转得到根到叶子的路径。
2. SessionManager 保存 current_leaf_id，创建新 Entry 时以叶子为 parent。
3. resume 选择最近会话或指定 ID。
4. fork 复制 Header，parent_session 指向来源，叶子从指定 Entry 继续。
5. 先不做跨分支自动摘要；保留 BranchSummary 接口供 B10 使用。

**测试**：线性恢复、两条分支、指定叶子、fork 后独立追加、缺失 parent 的诊断。

**演示**：在同一用户消息后 fork 两条方案，分别运行不同 Fake Provider 脚本。

**完成条件**：resume 不会把另一条分支消息发送给模型；fork 不会修改原会话。

### B10：Context Engine 与 Compaction

**目标**：把原始历史与发送给模型的上下文分离。

**实现步骤**：

1. ProjectionBuilder 从 SessionManager 取得当前分支消息。
2. TokenEstimator 提供确定性的字符/Token 估算，记录估算方法和误差提示。
3. ContextSelector 按优先级保留系统提示、最新用户任务、最近工具链和关键文件摘要。
4. 超过预算时先裁剪长工具输出，再生成 CompactionEntry。
5. 摘要 Provider 可复用 LLMProvider，但必须标记用途为 summarization。
6. 压缩失败时使用确定性 fallback，并将失败事件写入 Trace。

**测试**：预算未超限、长工具结果、保留最近链路、压缩 Entry、压缩后重建和摘要失败回退。

**演示**：Fake Provider 生成 50 轮工具输出；Context inspect 显示压缩前后 Token 和保留范围。

**完成条件**：Session 原始日志仍完整；模型只接收 Projection；用户能看到压缩摘要和边界。

### B11：Permission Policy 与审批

**目标**：让副作用可解释、可暂停和可拒绝。

**实现步骤**：

1. ActionNormalizer 把工具调用转换为 read、write、execute、network、git Action。
2. PolicyEngine 根据 workspace、路径、命令分类和工具注解返回 allow、ask、deny。
3. ApprovalManager 提供 once、session、always、deny 结果；V0 只实现 once 和 deny。
4. ask 时 Loop 进入 waiting_approval，保留 pending_tool_call，不重复调用模型。
5. TextUI 提供简短确认；JsonUI 发出 approval_request，等待外部 approval_response。
6. 所有决策写入 Approval Entry 和 policy_decision Event。

**测试**：自动允许读取、覆盖文件询问、危险命令拒绝、用户拒绝后的 Tool Result、超时取消和 JSON 审批。

**演示**：Agent 请求执行删除命令，Policy 阻止并给出替代建议；普通 pytest 命令可批准后执行。

**完成条件**：任何工具都不能绕过 Policy；拒绝后 Agent 能继续或正常结束。

### B12：配置、项目指令与 Skill

**目标**：让 Agent 具备项目级上下文，但不自动执行未信任资源。

**实现步骤**：

1. ConfigLoader 合并 CLI、项目、用户和默认配置。
2. ResourceLoader 查找项目 instructions.md 和 Skill Markdown。
3. 解析有限的 front matter：name、description、enabled、trust_required。
4. 将 Skill 内容以 system/context section 注入 Projection，不直接修改 Tool Registry。
5. no-context-files 和显式 Skill 参数覆盖自动发现。
6. 对项目资源输出来源、哈希和信任状态。

**测试**：优先级、重复资源、非法 front matter、禁用资源、越界路径和未信任资源提示。

**演示**：加入一个 Python 调试 Skill，让 Agent 在修改后先运行 pytest，再汇报失败测试。

**完成条件**：同一 Runtime 可以切换不同 Skill；资源不会静默执行 Python 代码。

### B13：Extension 与 MCP 适配

**目标**：在稳定核心之上添加外部工具和生命周期 Hook。

**实现步骤**：

1. 定义 ExtensionManifest：name、version、entrypoint、capabilities、trust。
2. ExtensionContext 只暴露受控的 registry、event_sink、session append 和 policy。
3. 支持 session_start、before_tool、after_tool、session_end Hook；Hook 异常按 fail-safe 处理。
4. 先实现本地示例 Extension，再接入 MCP client。
5. MCP 工具映射为本地 Tool；服务器注解转换为 Action metadata。
6. 未激活或 deferred 工具不进入 LLM 工具声明。

**测试**：加载失败、Hook 超时、工具注册、策略阻止 MCP 工具、连接断开、重连和工具结果截断。

**演示**：不改 Agent Loop，安装一个提供 project_info 工具的 Extension；再用 Fake MCP Server 提供只读工具。

**完成条件**：扩展能力不需要修改核心模块；所有远程工具仍经过本地 Policy。

### B14：Trace、Replay、Retry 与 Recovery

**目标**：把可观察性升级为可回放的 Harness。

**实现步骤**：

1. JsonlTrace 以 run_id 命名文件，保证 sequence 单调递增。
2. TraceSanitizer 删除 API Key、Authorization、敏感环境变量和超长原始内容。
3. ReplayReader 重建消息、Policy 决策和可回放工具结果。
4. 为工具增加 replay_safe 标记；副作用工具在 Replay 中默认 deny。
5. Provider retry 使用指数退避和最大次数；每次尝试发布 retry_start 和 retry_end。
6. RecoveryManager 从最后一个 durable boundary 恢复，避免重复写入。

**测试**：Trace 顺序、脱敏、回放只读工具、阻止副作用、Provider 重试、进程中断和重复事件去重。

**演示**：记录一次失败运行，离线 replay 后得到同样的模型上下文和工具结果，但不修改工作区。

**完成条件**：可以用 inspect、replay 命令解释一次运行的完整轨迹。

### B15：Evaluation Harness

**目标**：用固定任务比较 Loop、Context 和 Policy 的变化。

**实现步骤**：

1. 每个 Eval 包含 fixture workspace、prompt、Fake Provider script、expected files、expected events。
2. Runner 创建临时工作区，运行一次或多次，保存结果和 Trace。
3. Scorer 比较文件差异、最终状态、工具序列、是否越权和 Token 预算。
4. 输出单任务 JSON 和汇总表，不把模型自然语言当作唯一指标。
5. 为每次架构变化保留基线，检测工具调用次数、失败恢复和上下文长度回归。

**首批任务**：读取并总结、单文件修复、测试失败修复、拒绝危险命令、压缩后继续、Provider 临时失败重试。

**完成条件**：没有真实 API Key 时也能运行完整评测；失败结果包含第一个不一致事件。

### B16：TUI、RPC 与多 Agent（可选）

**目标**：验证 Runtime 与 UI/传输完全解耦。

**实现顺序**：

1. 先实现 JSONL RPC：stdin 接收 command，stdout 输出 response/event。
2. 再实现 Rich TUI，只消费 EventBus，不复制 Loop 状态机。
3. 最后评估 Planner/Worker 多 Agent；每个 Worker 必须拥有独立 Session、Policy 和 Trace。

多 Agent 会放大权限、上下文、取消、成本和恢复复杂度，只有单 Agent Harness 稳定后才进入。

## 8. 关键实现规则

### 8.1 错误边界

- Provider 错误：转成 ProviderError 和 run_error Event，可按策略重试。
- Tool 错误：转成 is_error Tool Result，让模型决定是否修复。
- Policy 拒绝：不调用 Tool，生成可解释的拒绝结果。
- 用户取消：停止等待新工具，清理子进程，写入 aborted 状态。
- 数据损坏：保留原文件，报告具体行号，允许从最后完整 Entry 恢复。

### 8.2 异步与取消

- 所有外部 I/O 都提供 cancel 参数或检查点。
- 不在工具内吞掉 CancelledError。
- 子进程、HTTP 流和审批等待都要有最终清理路径。
- 只在一个地方决定 Run 的最终状态，避免 agent_end、run_end 重复写入。

### 8.3 输出与上下文

- 模型看到的是短、稳定、可操作的 Tool Result。
- Trace 保存截断摘要和必要元数据，原始敏感内容按配置决定是否保留。
- Tool Result 的结构化 details 不直接假设模型能理解；面向模型的 content 仍是唯一上下文入口。

### 8.4 安全默认值

- 工作区外路径拒绝。
- 覆盖、Shell、网络和 Git 写操作询问。
- 凭据文件、环境变量和危险命令拒绝。
- Extension/MCP 未信任时不加载或只加载元数据。
- Replay 永远不自动执行副作用工具。

## 9. 测试策略

### 9.1 测试层级

| 层级 | 内容 | 是否联网 |
| --- | --- | --- |
| 单元测试 | domain、selector、policy、path resolver、serializer | 否 |
| Runtime 测试 | Fake Provider + Fake Tool + EventBus | 否 |
| 工具集成测试 | 临时目录、真实子进程、Windows/POSIX 分支 | 否 |
| Session 测试 | JSONL 中断、恢复、分支和压缩 | 否 |
| Eval 测试 | 固定 fixture 和脚本化模型 | 否 |
| Provider 冒烟 | OpenAI-compatible 最小请求 | 是，可选 |

### 9.2 最低质量门槛

开发过程中先运行受影响的检查；每个版本提交或合并前运行完整检查：

~~~powershell
python -m pytest -q
ruff check src tests
ruff format --check src tests
pyright
~~~

涉及工具、Policy、Session 的变更必须增加失败路径测试。涉及 Event schema 的变更要更新示例和版本说明。

### 9.3 必测不变量

1. 一个 Tool Call 最多对应一个最终 Tool Result。
2. Tool Result 写入会话后才能发起下一次模型请求。
3. 当前分支之外的 Entry 不进入 Projection。
4. Policy deny 不调用工具执行函数。
5. Replay 不执行非 replay_safe 工具。
6. Session 原始 JSONL 只追加，不因压缩或分支被改写。
7. Event sequence 在同一 run 内单调递增。
8. API Key 和 Authorization 不出现在 Trace。

## 10. 学习检查点

| 完成积木 | 应能回答的问题 |
| --- | --- |
| B4 | 为什么工具结果必须回到下一次 LLM 请求？停止条件有哪些？ |
| B8 | Session 与普通聊天历史有什么区别？为什么要追加式日志？ |
| B10 | 原始历史、Projection 和 Compaction 的关系是什么？ |
| B11 | 为什么工具本身不能决定是否允许执行？审批等待时 Loop 处于什么状态？ |
| B13 | Extension 如何增加能力又不破坏核心？MCP 工具注解如何进入 Policy？ |
| B14 | 如何重放一次运行而不重复副作用？哪些边界需要 durable record？ |
| B15 | 如何证明一次优化让 Harness 变好，而不是只让回答文字更长？ |

## 11. 建议提交顺序

提交按版本目标组织，积木编号只用于定位实现任务；相关积木可以合并在同一个版本提交中：

~~~text
feat(core): B1 add domain messages and event schema
feat(llm): B2 add scripted fake provider
feat(runtime): B4 add sequential agent loop
feat(tools): B5 add workspace file tools
feat(cli): B7 add text and json event modes
feat(session): B8 add append-only jsonl store
feat(context): B10 add projection and compaction
feat(policy): B11 add approval policy
feat(harness): B14 add trace replay and recovery
~~~

提交应包含实现、测试和必要文档，不把未说明的半成品版本留在主分支上。除非明确需要，不要在一个提交中同时跨越无关的 Runtime、UI、Provider 和存储层。

## 12. 第一条可运行路线

为了尽快看到成果，先完成 V0 和 V1 的最小主链路。下面 7 步是推荐顺序，不是必须拆成 7 个独立交付单元：

1. B0：能安装和跑测试。
2. B1：能序列化一条用户消息。
3. B2：Fake Provider 能流式返回文本和工具调用。
4. B3：echo Tool 能被注册、校验和执行。
5. B4：Agent Loop 能完成两轮对话。
6. B5：read/edit 能修改 fixture 文件。
7. B7：CLI 能展示一次完整修复任务。

完成第 7 步就得到一个真正可用的 Mini Coding Agent；之后进入 V2-V6，把它逐步提升为可恢复、可控、可扩展、可评测的 Harness。

## 13. 每版本验收脚本

### V0 验收

~~~powershell
minicode run --no-session --provider fake "调用 echo 工具并返回结果"
~~~

期望：Fake Provider 完成文本响应和 echo 工具调用，Agent Loop 正确结束，所有事件可看到。

### V1 验收

~~~powershell
minicode run --provider my-relay --model provider/model-name "读取 fixture/app.py，修复失败测试并运行 pytest"
~~~

期望：read -> edit -> bash -> final answer，文件差异正确；中转站请求、流式响应和 CLI 输出正常。

### V2 验收

~~~powershell
minicode run "开始一个会被中断的任务"
minicode resume
minicode sessions
~~~

期望：恢复后只使用当前分支，Session JSONL 可读，原始日志不改写。

### V3 验收

~~~powershell
minicode run --max-turns 40 "生成很多工具输出后继续修复"
minicode inspect <session-id>
~~~

期望：发生 compaction，原始日志仍完整，Projection Token 低于模型预算。

### V4 验收

~~~powershell
minicode run "检查项目并执行测试"
~~~

期望：读取自动允许；Shell 展示审批；危险命令被拒绝；Shell 在 Docker 容器中运行。

### V5 验收

~~~powershell
minicode run --provider anthropic "根据项目 Skill 修复测试"
~~~

期望：Skill、Extension 或 MCP 工具通过接口加载；Anthropic Adapter 不修改 Agent Loop。

### V6 验收

~~~powershell
minicode replay <run-id>
~~~

期望：输出与原运行一致的事件摘要，不修改工作区，不向 Provider 发真实请求。

## 14. 后续扩展判断

只有满足以下条件，才进入下一版本：

- 没有 API Key 时核心测试仍通过。
- 每次工具调用都能定位到 Session Entry 和 Trace Event。
- 取消、错误、拒绝和压缩都有测试。
- 新 Provider 不需要修改 Agent Loop。
- 新 UI 不需要复制 Runtime 状态机。
- 真实场景失败时能用 inspect 或 replay 找到第一个错误边界。

如果某一条不满足，应先补齐当前版本的核心问题，而不是增加新的产品功能。
