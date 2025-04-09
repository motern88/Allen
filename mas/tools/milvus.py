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
from pymilvus import connections, Collection, utility
from sentence_transformers import SentenceTransformer
from mas.agent.base.executor_base import Executor
import yaml
import time
import json
import os

@Executor.register(executor_type="tool", executor_name="milvus")
class MilvusTool(Executor):
    def __init__(self):
        super().__init__()
        self.config = self.load_config()
        self.encoder = SentenceTransformer(self.config["vector_db_config"]["embedding"]["model_name"])
        self.connect_milvus()
        self.collection_cache = {}


    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from rag_config.yaml"""
        config_path = os.path.join(os.path.dirname(__file__), "milvus_config.yaml")
        with open(config_path, 'r') as f:
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
            fields = [
                {"name": "id", "dtype": "INT64", "is_primary": True},
                {"name": "text", "dtype": "VARCHAR", "max_length": coll_config["max_length"]},
                {"name": "embedding", "dtype": "FLOAT_VECTOR", "dim": coll_config["vector_dim"]}
            ]
            schema = Collection(
                name=collection_name,
                fields=fields,
                index_params={
                    "index_type": coll_config["index_type"],
                    "metric_type": coll_config["metric_type"],
                    "params": {"nlist": coll_config["nlist"]}
                }
            )
            schema.create_index(field_name="embedding")
            self.collection_cache[collection_name] = schema
            return schema
            
        collection = Collection(name=collection_name)
        self.collection_cache[collection_name] = collection
        return collection
    
    def validate_params(self, params: Dict[str, Any]) -> None:
        """验证输入参数"""
        if not isinstance(params.get("content", ""), str):
            raise ValueError("内容必须是字符串!")
            
        max_length = self.config["vector_db_config"]["collection"]["max_length"]
        if len(params.get("content", "")) > max_length:
            raise ValueError(f"内容长度超过最大限制 {max_length} 个字符。")
            
        if not params.get("collection", "").isalnum():
            raise ValueError("collection名称必须是字母数字组合")
            
        if "top_k" in params:
            top_k = params["top_k"]
            if not isinstance(top_k, int) or top_k < 1 or top_k > 100:
                raise ValueError("top_k 必须是1~100之间的整数")
            
    def execute(self, step_id: str, agent_state: Dict[str, Any]) -> Dict[str, Any]:
        """根据指令执行RAG操作"""
        try:
            # 从step中获取指令
            step_state = agent_state["agent_step"].get_step(step_id)[0]
            instruction = step_state.instruction_content
            
            if not instruction:
                raise ValueError("步骤中未找到指令内容")
            
            # 解析指令并验证
            instruction_str = instruction.strip()
            if not (instruction_str.startswith("<RAG>") and instruction_str.endswith("</RAG>")):
                raise ValueError("指令格式无效。必须用<RAG>标签包裹")
                
            params = json.loads(instruction_str[5:-6])  # Remove <RAG></RAG>
            self.validate_params(params)
            
            # 执行操作  
            operation = params["operation"]
            content = params["content"]
            collection_name = params["collection"]
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
                [utility.gen_unique_id()],  # id
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