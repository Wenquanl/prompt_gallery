import httpx

# 测试你的 v2ray SOCKS5 代理隧道是否通畅
proxy_url = "socks5h://127.0.0.1:10808"

print("正在通过代理连接 Google API...")
try:
    with httpx.Client(proxy=proxy_url, timeout=10.0) as client:
        response = client.get("https://generativelanguage.googleapis.com")
        print(f"连接成功！Google 返回状态码: {response.status_code}")
except Exception as e:
    print(f"代理连接失败，错误信息: {e}")
    print("结论：你的梯子节点彻底连不上 Google API，请更换代理软件或节点！")