import httpx
import os
import time

# 1. 确保环境变量设置正确，或直接在这里指定你的机场代理端口
proxy_url = os.getenv("GOOGLE_PROXY_URL", "socks5h://127.0.0.1:10808") 
# 替换为你买域名后绑定的 Worker 地址
target_url = "https://gemini-proxy.lenghuhu83.workers.dev/v1beta/models/gemini-1.5-flash:generateContent" 

print(f"当前测试代理: {proxy_url}")
print(f"当前测试目标: {target_url}")

# 2. 模拟一个真实的 API 请求报文，而不是纯 0 字节流
test_payload = {
    "contents": [{"parts": [{"text": "Explain quantum physics in detail to make this request take time."}]}]
}

try:
    # 模拟 ai_providers.py 中的配置：禁用 http2
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    
    start_time = time.time()
    
    # 将 timeout 设置为一个复合元组：(连接, 读取, 写入, 池超时)
    # 重点关注第二个参数（读取），如果机场在 60s 断连，这里会抛出 ReadTimeout
    timeout_config = httpx.Timeout(connect=10.0, read=300.0, write=300.0, pool=10.0)

    with httpx.Client(
        proxy=proxy_url, 
        timeout=timeout_config,
        http2=False, # 保持与业务代码一致
        limits=limits
    ) as client:
        print("正在发起请求并等待响应（模拟生图等待）...")
        
        # 注意：这里需要带上你的 API KEY 才能得到正确响应，否则仅测试连通性
        api_key = os.getenv("GEMINI_API_KEY", "YOUR_KEY_HERE")
        response = client.post(
            f"{target_url}?key={api_key}", 
            json=test_payload
        )
        
        end_time = time.time()
        print(f"✅ 连接成功！状态码: {response.status_code}")
        print(f"任务总耗时: {end_time - start_time:.2f} 秒")

except httpx.ReadTimeout:
    elapsed = time.time() - start_time
    print(f"❌ 错误：触发了 Read Timeout！耗时: {elapsed:.2f} 秒")
    if 55 <= elapsed <= 65:
        print("结论：极大概率是机场（代理服务商）设置了 60 秒强制断连。")
except httpx.WriteTimeout:
    print("❌ 错误：触发了 Write Timeout！说明上传大数据时被机场拦截。")
except Exception as e:
    print(f"❌ 测试失败: {e}")