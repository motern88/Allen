# Allen

Allen 是我们实现的一种多Agent系统架构 （Multi-Agent System）



## 1. Overview

```python
Allen
├── docs				# 文档
└── mas					# Multi-Agent System 实现代码
requirements.txt		# 环境依赖
```





## 2. Installation

1. 创建虚拟环境，并指定python版本（推荐3.13.1）

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

**配置LLM-Agent的API**

请完善 `mas/role_config` 下所有LLM-Agent的配置文件中 `llm_config` 部分。

```yaml
llm_config:
  api_type: "openai"    # 支持openai或ollama
  base_url: ""			# LLM API 的 URL
  model: ""				# 模型名
  api_key: ""			# API Key
  max_tokens: 8192
  temperature: 0.1
  timeout: 600
```

其中 `管理者_灰风.yaml` 是必须配置的，MAS 系统的启动默认指定其为初始任务管理Agent。



**配置Human-Agent**

请完善 `mas/human_config` 下你想要创建的人类操作端Agent的配置。

其中 `人类操作端_小黑.yaml` 是当前MAS启动时固定唤起的人类操作端Agent。

<span style="background-color:yellow">TODO：我们将会完善在Web UI中新建HumanAgent的方式，而不强制需要预定义human config。</span>



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



