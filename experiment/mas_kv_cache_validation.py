'''
此脚本用于测试MAS基础提示词是否可以利用KVCache缓存效果
测试场景：相同MAS基础提示词(前缀不变) + 不同Agent角色
执行流程: 
1. 维护全局唯一的一个LLMClient和LLMContext对象
2. 设置MAS基础提示词（固定前缀）
3. 循环测试不同Agent角色(3次)
   -->发送任务请求-->记录响应时间-->精确清理非前缀部分-->验证前缀完整性
4.分析缓存效果

运行结果示例：
  🔄 第1次测试: 灰风 (多智能体系统管理者)
     开始前Context长度: 1
     添加角色后Context长度: 2
     响应时间: 12.62s

  🔄 第2次测试: 灰风 (多智能体系统管理者)
     开始前Context长度: 1
     添加角色后Context长度: 2
     响应时间: 11.15s

  🔄 第3次测试: 灰风 (多智能体系统管理者)
     开始前Context长度: 1
     添加角色后Context长度: 2
     响应时间: 12.28s

  📈 平均时间: 12.02s
  📊 时间范围: 11.15s - 12.62s

  🔍 效果分析:
     第1次响应时间: 12.62s
     后续平均时间: 11.71s

结论：
由于现在的API都没有真正的会话管理（跨请求的KV Cache保持、对话状态记忆等），而是HTTP请求无状态地调用，并不支持跨请求的KVCache。
目前只支持单请求内的KV Cache，所以KV Cache效果不明显。待后续LLM本地部署后，做额外的API会话管理等优化，才可以实现真正的节约token开销的效果。

'''

import time
import json
import statistics
import yaml
import os
from typing import List, Dict, Any
from mas.agent.base.llm_base import LLMClient, LLMContext
from mas.agent.configs.llm_config import LLMConfig
from mas.agent.base.executor_base import Executor

class MASFocusedKVCacheTest(Executor):
    """专注测试MAS基础提示词缓存效果的验证器"""
    
    def __init__(self, config_path: str):
        self.config = LLMConfig.from_yaml(config_path)
        self.llm_client = LLMClient(self.config)
        self.test_results = []
        
        # 预加载MAS基础提示词
        self.mas_base_prompt = self.get_base_prompt()
        print(f"📋 MAS基础提示词长度: {len(self.mas_base_prompt)} 字符")

    def execute(self, step_id: str, agent_state: Dict[str, Any], mcp_client=None):
        """实现Executor抽象方法"""
        return {"step_id": step_id, "result": "KVCache测试", "status": "finished"}

    def load_agent_config(self, agent_config: str) -> Dict[str, Any]:
        """加载Agent配置文件"""
        config_path = f"mas/role_config/{agent_config}"
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def run_focused_test(self):
        """运行KVCache测试"""
        print("🚀 开始MAS基础提示词缓存效果测试...")
        print("="*60)
        # 测试场景：相同MAS基础提示词(前缀不变) + 不同Agent角色
        self.test_true_prefix_preservation()


    def test_true_prefix_preservation(self):
        """真正的前缀保持测试"""
        print("\n📊 测试：真正的MAS前缀保持不变")
        
        # 🔑 关键：设置固定的MAS基础提示词，之后绝不动
        persistent_context = LLMContext(context_size=30)
        persistent_context.add_message("user", self.mas_base_prompt)

        # 📍 记录MAS基础提示词对象的ID，后续验证是否被动过
        mas_message_id = id(persistent_context.history[0])
        mas_message_content_hash = hash(persistent_context.history[0]["content"])
        
        print(f"  🔒 MAS基础提示词已设置（位置0）")
        print(f"  📏 MAS基础提示词长度: {len(self.mas_base_prompt)} 字符")
        print(f"  🆔 MAS消息对象ID: {mas_message_id}")
        print(f"  #️⃣  MAS内容哈希: {mas_message_content_hash}")
        
        # 加载Agent配置
        agent_configs = ["管理者_灰风.yaml", "管理者_灰风.yaml", "管理者_灰风.yaml"]
        true_kv_times = []
        
        for i, config_file in enumerate(agent_configs):
            try:
                agent_config = self.load_agent_config(config_file)
                agent_name = agent_config.get("name", f"Agent{i+1}")
                agent_role = agent_config.get("role", "未知角色")
                
                # 构建Agent状态
                agent_state = {
                    "agent_id": f"agent_{i+1:03d}",
                    "name": agent_name,
                    "role": agent_role,
                    "profile": agent_config.get("profile", "无描述")
                }
                
                print(f"\n  🔄 第{i+1}次测试: {agent_name} ({agent_role})")
                print(f"     开始前Context长度: {len(persistent_context.get_history())}")
                
                # 📝 记录添加前的长度，用于后续精确清理
                initial_length = len(persistent_context.get_history())

                agent_role_prompt = self.get_agent_role_prompt(agent_state)
                persistent_context.add_message("user", agent_role_prompt)
                
                print(f"     添加角色后Context长度: {len(persistent_context.get_history())}")
                
                # 发送任务请求
                task_prompt = "请根据你的角色制定一个技术项目的执行计划，包括关键步骤和注意事项。"
                
                start_time = time.time()
                response = self.llm_client.call(task_prompt, persistent_context)
                end_time = time.time()
                
                response_time = end_time - start_time
                true_kv_times.append(response_time)
                
                print(f"     响应时间: {response_time:.2f}s")
                # print(f"     完成后Context长度: {len(persistent_context.get_history())}")
                
                # 只删除非前缀部分，保持MAS基础提示词不动

                current_length = len(persistent_context.get_history())
                message_to_delete = current_length - initial_length

                # print(f"     需要删除的消息数: {message_to_delete}")

                # 逐个删除后续添加的消息
                for j in range(message_to_delete):
                    if len(persistent_context.get_history()) > initial_length:
                        persistent_context.remove_last_message()
                        # print(f"     已删除第{j+1}条消息, 剩余{len(persistent_context.get_history())}")
                        
                final_length = len(persistent_context.get_history())
                # print(f"     清理完成，最终Context长度: {final_length}")


                # 🔍 验证MAS基础提示词对象是否被动过
                current_mas_id = id(persistent_context.history[0])
                current_mas_hash = hash(persistent_context.history[0]["content"])
                
                mas_object_unchanged = (current_mas_id == mas_message_id)
                mas_content_unchanged = (current_mas_hash == mas_message_content_hash)
                
                # if mas_object_unchanged and mas_content_unchanged:
                #     print(f"     🎉 MAS基础提示词对象完全未动过！")
                # else:
                #     print(f"     ⚠️  MAS基础提示词对象被改动了！")
                
                time.sleep(2)
            except Exception as e:
                print(f"  ❌ 处理 {config_file} 时出错: {e}")
                continue

         # 分析KVCache效果
        if true_kv_times:
            avg_time = statistics.mean(true_kv_times)
            print(f"\n  📈 平均时间: {avg_time:.2f}s")
            print(f"  📊 时间范围: {min(true_kv_times):.2f}s - {max(true_kv_times):.2f}s")
            
            if len(true_kv_times) >= 3:
                first_time = true_kv_times[0]
                subsequent_times = true_kv_times[1:]
                avg_subsequent = statistics.mean(subsequent_times)
                
                improvement = ((first_time - avg_subsequent) / first_time) * 100
                
                print(f"\n  🔍 效果分析:")
                print(f"     第1次响应时间: {first_time:.2f}s")
                print(f"     后续平均时间: {avg_subsequent:.2f}s")
                print(f"     性能提升: {improvement:+.1f}%")
                
                if improvement > 25:
                    print(f"     🎉 强烈的KVCache效果！策略非常有效")
                elif improvement > 15:
                    print(f"     ✅ 明显的KVCache效果，前缀完全保持策略有效")
                elif improvement > 5:
                    print(f"     🤔 轻微的KVCache效果")
                else:
                    print(f"     ❌ 未检测到明显的KVCache效果")
                    print(f"     💡 可能是服务器不支持或网络延迟影响")

        self.test_results.append({
            "test_name": "absolutely_no_touch_prefix",
            "times": true_kv_times,
            "average": statistics.mean(true_kv_times) if true_kv_times else 0,
            "description": "不动MAS基础提示词对象测试",
            "strategy": "使用remove_last_message精确清理，MAS对象完全不动"
        })
        
        # 保存详细结果
        with open("absolutely_no_touch_kv_cache_results.json", "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": time.time(),
                "test_strategy": "绝对不动MAS基础提示词对象",
                "mas_object_preservation": "完全保持对象引用不变",
                "cleanup_method": "remove_last_message逐个删除",
                "results": self.test_results
            }, f, indent=2, ensure_ascii=False)
            


def main():
    """运行MAS KVCache测试"""
    try:
        tester = MASFocusedKVCacheTest("mas/agent/configs/test_llm_config.yaml")
        tester.run_focused_test()
    except Exception as e:
        print(f"❌ 测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    '''
    测试mas_kv_cache_validation需在Allen根目录下执行 python -m experiment.mas_kv_cache_validation
    '''
    main()