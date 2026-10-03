# MiniCode

MiniCode 是一个按开发文档逐步实现的 Python Coding Agent。当前已完成 B0、B1、B2、B3、B4 的最小能力：领域消息、Fake Provider、OpenAI-compatible 中转站、工具注册表，以及顺序 Agent Loop。

## 安装

要求 Python 3.12 或更高版本：

~~~powershell
python -m pip install -e .
~~~

## 离线 Fake 模式

Fake 模式用于开发文档中的可重复测试，不需要 API Key：

~~~powershell
minicode run --provider fake "调用 echo 工具"
~~~

## 接入中转站

MiniCode 使用 OpenAI-compatible 的 /chat/completions 接口。中转站地址默认是 https://coloful-rose.com/v1，API Key 只从环境变量读取，不会写入配置、日志或输出。

~~~powershell
$env:MINICODE_API_KEY = "你的中转站 Key"
$env:MINICODE_BASE_URL = "https://coloful-rose.com/v1"
minicode run --provider relay --model gpt6.1sol --reasoning-effort high "请介绍这个项目"
~~~

可用模型名由中转站提供，例如 gpt6.0sol、gpt6.0luna、gpt6.1sol。MiniCode 会原样发送模型名，不根据模型名猜测地址。

推理强度支持 low（轻度）、medium（中度）、high（高度）和 xhigh（极高）。

也可以自定义 Key 环境变量：

~~~powershell
$env:COLOFUL_KEY = "你的中转站 Key"
minicode run --provider relay --api-key-env COLOFUL_KEY --model gpt6.0luna "你好"
~~~

## 开发检查

~~~powershell
python -m pytest -q
ruff check src tests
ruff format --check src tests
pyright
~~~
