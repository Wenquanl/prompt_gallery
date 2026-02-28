import httpx
import os
import time

# 1. 代理配置（建议通过环境变量读取，保持隐私安全）
proxy_url = os.getenv("GOOGLE_PROXY_URL", "socks5h://127.0.0.1:10808")

# 2. 构造模拟的大数据量 (例如 10MB 的随机数据，模拟上传多张大图)
# 10 * 1024 * 1024 bytes = 10MB
large_data = b"0" * (10* 1024 * 1024) 

print(f"正在准备上传测试，数据大小: {len(large_data) / 1024 / 1024:.2f} MB")
print(f"当前代理: {proxy_url}")

# 3. 执行测试
try:
    # 模拟业务代码中的关键配置：禁用 http2，并设置长超时
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    
    start_time = time.time()
    
    with httpx.Client(
        proxy=proxy_url, 
        timeout=300.0,   # 给予充足的写入时间
        http2=False,     # 关键：模拟我们之前讨论的修复方案
        limits=limits
    ) as client:
        print("正在向 Google API 发起大数数据 POST 请求...")
        
        # 注意：向这个地址发送 POST 可能会返回 404 或 405，
        # 但我们的目的是测试【数据写入阶段】是否会触发 "Write Timeout"
        response = client.post(
            "https://gemini-proxy.lenghuhu83.workers.dev", 
            content=large_data
        )
        
        end_time = time.time()
        print(f"连接成功！Google 返回状态码: {response.status_code}")
        print(f"上传耗时: {end_time - start_time:.2f} 秒")
        print(f"平均上传速度: {(len(large_data) / 1024) / (end_time - start_time):.2f} KB/s")

except httpx.WriteTimeout:
    print("❌ 错误：触发了 Write Timeout！说明你的代理在发送大数据时丢包严重或被限速。")
except Exception as e:
    print(f"❌ 测试失败，错误信息: {e}")
    print("结论：请检查代理软件的 MTU 设置或更换节点。")