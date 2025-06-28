from pymilvus import connections

connections.connect(
  alias="default", 
  host='43.142.97.170', 
  port='19530'
)

# 检查连接是否成功  
# 检查连接是否成功  
if connections.has_connection("default"):  # 检查是否有该连接的别名  
    print("连接成功！")  
else:  
    print("连接失败，请检查 IP 和端口是否正确，以及 Milvus 服务是否可用。")  