# Allen

Allen 是多Agent系统架构(Multi-Agent System)的其中一种构形。其优势在于Agent能够自主改变自身的行为模式，而无需开发者为每个具体任务都编排具体的工作逻辑。我们的技术报告：[Allen: Rethinking MAS Design through Step-Level Policy Autonomy](http://arxiv.org/abs/2508.11294)

我们的Agent在任务中协作的总览架构图：

![多Agent协同执行](./docs/asset/多Agent协同执行.jpg)
其中每个Agent执行具体Step示意图：

![v4工作流动图](./docs/asset/v4工作流动图.gif)

## News

- **25.8** 由于人员变动，该项目即将不再继续维护。





## 1. Overview

```python
Allen
├── docs                # 文档
├── experiment			# 存放与运行无关的验证与实验
└── mas                 # Multi-Agent System 实现代码
requirements.txt        # 环境依赖
```



## 2. Installation

1. 创建虚拟环境，并指定Python版本（推荐Python 3.13.1）

```powershell
conda create -n mas python=3.13.1
```

2. 激活刚刚创建的名为mas的conda环境

```powershell
conda activate mas
```

3. **进入到项目根目录**，并执行安装依赖

```powershell
pip install -r requirements.txt
```



## 3. Quick Start

### 3.1 Finish Agent Config

**1. 配置LLM-Agent的API**

请完善 `mas/role_config` 下所有LLM-Agent的配置文件中 `llm_config` 部分。

> 其中 `mas/role_config/管理者_灰风.yaml` 是**必须配置**的，MAS 系统的启动默认指定其为初始任务管理Agent。

```yaml
llm_config:
  api_type: "openai"    # 支持openai或ollama
  base_url: ""          # LLM API 的 URL
  model: ""             # 模型名
  api_key: ""           # API Key
  max_tokens: 8192
  temperature: 0.1
  timeout: 600
```



**2. 配置Human-Agent**

请完善 `mas/human_config` 下你想要创建的人类操作端Agent的配置。

其中 `人类操作端_小黑.yaml` 是当前MAS启动时固定唤起的人类操作端Agent。

<span style="background-color:yellow">TODO：我们需要完善在Web UI中新建HumanAgent的方式，而不强制需要预定义human config。</span>



**3. 配置默认LLM Config**

请在 `mas/agent/configs/default_llm_config.yaml` 中配置有效的LLM API。

该处配置的 LLM Config 会在 MAS 创建未在`mas/role_config`中预定义的新Agent时使用。



### 3.2 Start System and Web UI

在项目根目录下执行命令：

```powershell
python -m mas.mas
```

该命令会具体执行 `MultiAgentSystem.start_system()` 函数来启动系统。

随后网页打开本地端口 5000 即可查看 MAS 运行状态：

```powershell
http://127.0.0.1:5000
```



## 4. TODO

- 四种状态的离线保存与加载
- 任务完成后Agent轨迹收集与日志存档
- 人类操作端使用Agent管理技能
- 在前端WebUI中增加新建Human-Agent功能，而不强制需要预定义human config

