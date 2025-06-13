### MAS:Muti Agent System

------

总览

```python
├──agent  # 单Agent组件实现
├──role_config  # 角色配置文件
├──skills  # 技能
├──tools  # 工具
```



agent 中实现单个 agent 所需的组件



暂时Debug笔记：

```
实例化一个新的Agent并赋予它一个新的写作任务。任务名称：写作。任务目标：向人类Agent询问具体需求，然后根据需求写一篇作文。其他详细细节由这个新的协作Agent去询问。
```



> ## 如何暴露接口到公网
>
> #### 步骤一：注册 ngrok 账号并获取 authtoken
>
> 1. 打开官网：https://dashboard.ngrok.com/signup
>
> 2. 注册并登录账号
>
> 3. 获取你的 authtoken：
>     进入：https://dashboard.ngrok.com/get-started/your-authtoken
>     你会看到一行类似这样的命令：
>
>    ```
>    bash
>    
>    
>    复制编辑
>    ngrok config add-authtoken 1a2bcD34EfG56HiJ78klMnoPqr9stuXvYzABcDeFgH
>    ```
>
> ------
>
> #### 步骤二：手动配置 authtoken（只需做一次）
>
> 复制上面的命令并在你的终端中执行：
>
> ```
> bash
> 
> 
> 复制编辑
> ngrok config add-authtoken 你的_token
> ```
>
> 示例：
>
> ```
> bash
> 
> 
> 复制编辑
> ngrok config add-authtoken 1a2bcD34EfG56HiJ78klMnoPqr9stuXvYzABcDeFgH
> ```
>
> ------
>
> #### 步骤三：再次运行 ngrok
>
> 一旦配置完成，你就可以运行：
>
> ```
> bash
> 
> 
> 复制编辑
> ngrok http 5000
> ```
>
> 你将看到输出类似这样：
>
> ```
> nginx
> 
> 
> 复制编辑
> Forwarding  https://abc123.ngrok.io -> http://localhost:5000
> ```

