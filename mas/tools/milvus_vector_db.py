'''
Milvus 向量数据库工具

描述
-----------
该工具实现了基于向量的文档存储和相似性搜索，使用了Milvus。它能够高效地存储文档向量，并根据向量相似性搜索检索相似内容。

功能
-------------
1. 向量数据库：使用 Milvus 进行高效的向量存储和相似性搜索
2. 文本嵌入：采用 SentenceTransformer将文本转换为向量 # TODO: enbedding模型待选型测试
3. 操作：
- Store: 文本转换成的向量存储进Milvus 中
- Search: 查找语义上相似的文档

核心方法
-----------
- execute(step_id, agent_state)：主要入口点，处理 Milvus 指令
- _store_document(text, collection)：将文档向量存储在 Milvus 中
- _search_similar(query, collection, top_k)：搜索相似的文档

配置
----
所有配置均在 milvus_config.yaml 文件中管理，包括：
- 向量数据库连接参数
- 嵌入模型设置
- Collection 和索引配置
'''

from typing import Dict, Any, Optional
from pymilvus import connections, Collection, utility, CollectionSchema, FieldSchema, DataType
from sentence_transformers import SentenceTransformer
from mas.agent.base.executor_base import Executor
import yaml
import time
import json
import os

@Executor.register(executor_type="tool", executor_name="milvus_vector_db")
class MilvusTool(Executor):
    def __init__(self):
        super().__init__()
        self.config = self._load_config()
        self.encoder = SentenceTransformer(self.config["vector_db_config"]["embedding"]["model_name"])
        self.connect_milvus()
        self.collection_cache = {}


    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from rag_config.yaml"""
        config_path = os.path.join(os.path.dirname(__file__), "milvus_vector_db_config.yaml")
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def connect_milvus(self) -> None:
        """连接到 Milvus 服务器并实现重试机制"""
        conn_config = self.config["vector_db_config"]["connection"]
        max_retries = conn_config["max_retries"]
        
        for attempt in range(max_retries):
            try:
                connections.connect(
                    alias=conn_config["alias"],
                    host=conn_config["host"],
                    port=conn_config["port"],
                    timeout=conn_config["timeout"]
                )
                return
            except Exception as e:
                if attempt == max_retries - 1:
                    raise ConnectionError(f"Failed to connect to Milvus after {max_retries} attempts: {str(e)}")
                time.sleep(2 ** attempt)  # Exponential backoff

    def get_collection(self, collection_name: str, create_if_missing: bool = True) -> Collection:
        """获取或创建带缓存的 Milvus Collection"""
        if collection_name in self.collection_cache:
            return self.collection_cache[collection_name]
            
        if create_if_missing and not utility.has_collection(collection_name):
            coll_config = self.config["vector_db_config"]["collection"]
             # 定义字段 
            fields = [
                FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),  
                FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=coll_config["max_length"]),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=coll_config["vector_dim"])
                ]
            # 定义集合 schema 
            schema = CollectionSchema(
                fields=fields,
                description="docs embedding collection"
            )
            # 创建集合  
            collection = Collection(name=collection_name, schema=schema)  
            # 创建索引
            collection.create_index(field_name="embedding", index_params={
                "index_type": coll_config["index_type"],
                "metric_type": coll_config["metric_type"],
                "params": {"nlist": coll_config["nlist"]}
            })

            # 加载集合到内存  
            collection.load()  
            # 缓存集合对象 
            self.collection_cache[collection_name] = schema
            return collection
            
        collection = Collection(name=collection_name)
        collection.load()  
        self.collection_cache[collection_name] = collection

        return collection
    
    def validate_params(self, params: Dict[str, Any]) -> None:
        """验证输入参数"""
        if not isinstance(params.get("content", ""), str):
            raise ValueError("内容必须是字符串!")
            
        max_length = self.config["vector_db_config"]["collection"]["max_length"]
        if len(params.get("content", "")) > max_length:
            raise ValueError(f"内容长度超过最大限制 {max_length} 个字符。")
            
        collection_name = params.get("collection_name", "").strip()  
        print(f"检验的 collection_name 值: '{collection_name}'")  
        if not params.get("collection_name", "").isalnum():
            raise ValueError("collection名称必须是字母数字组合")
            
        if "top_k" in params:
            top_k = params["top_k"]
            if not isinstance(top_k, int) or top_k < 1 or top_k > 100:
                raise ValueError("top_k 必须是1~100之间的整数")
            
    def execute(self, step_id: str, agent_state: Dict[str, Any]) -> Dict[str, Any]:
        """根据指令执行MILVUS向量数据库操作"""
        try:
            # 从step中获取指令
            step_state = agent_state["agent_step"].get_step(step_id)[0]
            instruction = step_state.instruction_content
            
            if not instruction:
                raise ValueError("步骤中未找到指令内容")
            
            # 解析指令并验证
            instruction_str = instruction.strip()
            if not (instruction_str.startswith("<MILVUS>") and instruction_str.endswith("</MILVUS>")):
                raise ValueError("指令格式无效。必须用<MILVUS>标签包裹")
                
            params = json.loads(instruction_str[8:-9])  # Remove <MILVUS></MILVUS>
            print(f"解析到的指令参数: {params}")
            self.validate_params(params)
            
            # 执行操作  
            operation = params["operation"]
            content = params["content"]
            collection_name = params["collection_name"]
            top_k = params.get("top_k", 5)
            
            if operation == "store":
                return self._store_document(content, collection_name)
            elif operation == "search":
                return self._search_similar(content, collection_name, top_k)
            elif operation == "retrieve":
                return self._retrieve_context(content, collection_name, top_k)
            else:
                raise ValueError(f"未知的操作: {operation}")
                
        except Exception as e:
            print(f"执行Milvus操作时出错: {str(e)}")
            return {"status": "error", "message": str(e)}
        
    def _store_document(self, text: str, collection_name: str) -> Dict[str, Any]:
        """文本向量存储进 Milvus"""
        try:
            collection = self.get_collection(collection_name)
            embedding = self.encoder.encode(text)
            
            # Insert data
            collection.insert([
                [text],  # text
                [embedding.tolist()]  # embedding
            ])
            
            collection.flush()  # Ensure data is persisted
            return {
                "status": "success", 
                "message": "文档向量存储成功",
                "collection": collection_name
            }
        except Exception as e:
            raise RuntimeError(f"Failed to store document vector: {str(e)}")


    def _search_similar(self, query: str, collection_name: str, top_k: int) -> Dict[str, Any]:
        """通过向量相似性进行相似文本搜索"""
        try:
            collection = self.get_collection(collection_name, create_if_missing=False)
            query_embedding = self.encoder.encode(query)
            
            collection.load()
            coll_config = self.config["vector_db_config"]["collection"]
            results = collection.search(
                data=[query_embedding.tolist()],
                anns_field="embedding",
                param={"metric_type": coll_config["metric_type"], "params": {"nprobe": coll_config["nprobe"]}},
                limit=top_k,
                output_fields=["text"]
            )
            
            return {
                "status": "success",
                "results": [hit.entity.get("text") for hit in results[0]],
                "scores": [hit.distance for hit in results[0]]
            }
            
        except Exception as e:
            raise RuntimeError(f"Failed to search similar documents: {str(e)}")


    def __del__(self):
        """Cleanup connections on object destruction"""
        try:
            connections.disconnect("default")
        except:
            pass

if __name__ == "__main__":
    '''
    测试milvus_vector_db需在Allen根目录下执行 python -m mas.tools.milvus_vector_db
    '''
    from mas.agent.base.agent_base import AgentStep, StepState
    from mas.agent.configs.llm_config import LLMConfig
    from mas.skills.Instruction_generation import InstructionGenerationSkill
    from mas.tools.milvus_vector_db import MilvusTool

    print("Testing MilvusTool...")

    # 构造虚假的agent_state和step_state
    agent_state = {
        "agent_id": "0001",  
        "name": "小白",  
        "role": "向量数据库管理员",  
        "profile": "负责管理Milvus向量数据库的文档存储与检索",  
        "working_state": "Unassigned tasks",  
        "llm_config": LLMConfig.from_yaml("mas/role_config/qwq32b.yaml"),  
        "working_memory": {},  
        "persistent_memory": "",  
        "agent_step": AgentStep("0001"),  
        "skills": ["planning", "reflection", "summary", "instruction_generation"],  # 这里可以添加其他技能  
        "tools": ["milvus_vector_db"],  # 指定使用的工具  
    }
    
    # 由于tool需要依赖instruction_generation这个Skill生成指令，所以这里需要构造一个类型为skill的StepState
    step0 = StepState(
        task_id="task_001",
        stage_id="stage_001",
        agent_id="0001",
        step_intention="生成指令",
        step_type="skill",
        executor="instruction_generation",
        text_content="为下一个工具调用生成指令",
        execute_result={},
    )

    step1 = StepState(
        task_id="task_001",  
        stage_id="stage_001",  
        agent_id="0001",  
        step_intention="存储文档",  
        step_type="tool",  
        executor="milvus_vector_db",  
        text_content="将文档内容存储到Milvus中",  
        execute_result={},  
    )

    step2 = StepState(  
        task_id="task_001",  
        stage_id="stage_001",  
        agent_id="0001",  
        step_intention="查找相似文档",  
        step_type="tool",  
        executor="milvus_vector_db",  
        text_content="查找与文档内容相似的文档",  
        execute_result={},  
    )  

    # 将步骤添加到agent_state  
    agent_state["agent_step"].add_step(step0)  # 添加指令生成步骤
    agent_state["agent_step"].add_step(step1)  
    agent_state["agent_step"].add_step(step2)

    instuct_step_id = agent_state["agent_step"].step_list[0].step_id  # 指令生成为第0个step  
    instruction_generation_skill = InstructionGenerationSkill()
    gen_result = instruction_generation_skill.execute(instuct_step_id, agent_state)

    print("指令生成结果:", gen_result)  # 打印指令生成结果

    # 检查生成的指令格式  
    if gen_result.get("update_stage_agent_state", {}).get("state") == "failed":  
        print("失败原因追踪:")  
        print("LLM响应内容:", agent_state["agent_step"].step_list[0].execute_result.get("raw_response"))  
        print("提取的指令:", agent_state["agent_step"].step_list[0].execute_result.get("instruction_generation"))  

    # 验证指令生成结果  
    if gen_result.get("update_stage_agent_state", {}).get("state") == "finished":  
        # 获取生成的存储操作指令
        store_instruction = agent_state["agent_step"].step_list[1].instruction_content  
        store_step_id = agent_state["agent_step"].step_list[1].step_id
        print(f"生成的存储指令: {store_instruction}，存储步骤ID: {store_step_id}")  

        # 测试存储功能  
        print("\n=== 开始执行存储操作 ===")  
        milvus_tool = MilvusTool()  
        store_result = milvus_tool.execute(store_step_id, agent_state)  
        print("存储结果:", store_result)

        # 获取生成的搜索操作指令 
        # search_instruction = agent_state["agent_step"].step_list[2].instruction_content
        # search_step_id = agent_state["agent_step"].step_list[2].step_id
        # print(f"生成的搜索指令: {search_instruction}，搜索步骤ID: {search_step_id}")

        # # 测试搜索功能  
        # print("\n=== 开始执行搜索操作 ===")   
        # search_result = milvus_tool.execute(search_step_id, agent_state)  
        # print("搜索结果:", search_result)  

    else:
        print("指令生成失败，请检查指令生成步骤的执行状态", gen_result)

    # 打印所有step信息  
    agent_state["agent_step"].print_all_steps()  