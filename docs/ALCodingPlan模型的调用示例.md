# ALCodingPlan 厂商模型接入与调用示例指南

本指南旨在为您提供关于 **ALCodingPlan** 厂商所有大模型在 **DolphinLitePark AI Gateway** 控制面上的完整接入与调用参考。您可以使用本文档及您专属的 API Key，在其他应用（如 Dify、LangChains、OneAPI 或自研系统）中无缝集成这些模型。

---

## 🔑 接入配置基本信息

在第三方应用中接入时，请统一使用以下标准接口配置：

*   **API 基础 URL (Base URL)**: `https://api-gateway.fusionxlink.com/v1`
*   **API 密钥 (API Key / Token)**: `sk-dlp-ddb7127fcdd3b2abacccbb21144d91c27137fe08548108a998f7facbcc946972`
*   **接口规范**: 完全兼容 **OpenAI REST API v1** 协议标准。

---

## 🤖 ALCodingPlan 模型目录清单

目前 AI Gateway 目录中注册的 `ALCodingPlan` 厂商模型如下表所示。请在请求的 `model` 参数中填写对应的 **公共模型名称 (Public Model Name)**：

### 💬 语言模型 (LLM) 与语音模型 (TTS)

| 序号 | 公共模型名称 (请求用 `model` 值) | 厂商原始模型名称 | 流式输出 | 状态 | 适用场景与描述 |
| :--- | :--- | :--- | :---: | :---: | :--- |
| 1 | **`alicoding/qwen3-coder-plus`** | `qwen3-coder-plus` | 支持 | **激活 (Active)** | 阿里通义千问 3.0 旗舰级代码模型，具备极强的代码生成与修复能力。 |
| 2 | **`alicoding/qwen3-coder-nex`** | `qwen3-coder-next` | 支持 | **激活 (Active)** | 阿里通义千问 3.0 代码模型下一代预览版，针对复杂算法设计进行了深度优化。 |
| 3 | **`alicoding/qwen3-max`** | `qwen3-max-2026-01-23` | 支持 | **激活 (Active)** | 通义千问 3.0 超大规模旗舰模型，综合通用推理与长文本理解能力极佳。 |
| 4 | **`alicoding/kimi-k2.5`** | `kimi-k2.5` | 支持 | **激活 (Active)** | Kimi 最新一代超长上下文推理模型，长文本处理及搜索式推理表现拔尖。 |
| 5 | **`alicoding/glm-5`** | `glm-5` | 支持 | **激活 (Active)** | 智谱清言 GLM-5 旗舰级通用双语大模型，综合推理与中文表达能力出众。 |
| 6 | **`alicoding/glm-4.7`** | `glm-4.7` | 支持 | **激活 (Active)** | 智谱清言 GLM-4.7 高性能版本，响应迅速，性价比极高。 |
| 7 | **`alicoding/MiniMax-M2.5`** | `MiniMax-M2.5` | 支持 | **激活 (Active)** | MiniMax 最新一代大语言模型，擅长角色扮演、多语种对话与创意写作。 |
| 8 | **`qwen3-tts-flash`** | `qwen3-tts-flash` | 否 | **激活 (Active)** | 阿里通义千问大模型高品质语音合成（TTS）闪电版模型，响应快速，音色自然。 |
| 9 | **`alicoding/qwen3.5-plus`** | `qwen3.5-plus` | 支持 | *未激活 (Inactive)* | 通义千问 3.5 进阶版（暂未开放，请优先使用激活模型）。 |

### 🎥 视频与图像多模态模型 (Video & Image Multimodal Models)

| 序号 | 公共模型名称 (请求用 `model` 值) | 输出模态 | 状态 | 适用场景与描述 |
| :--- | :--- | :---: | :---: | :--- |
| 1 | **`happyhorse-1.0-t2v`** | 视频 (Video) | **激活 (Active)** | 阿里 HappyHorse 1.0 旗舰级文生视频模型，生成 1080P 高清视频，带原声音乐。 |
| 2 | **`happyhorse-1.0-i2v`** | 视频 (Video) | **激活 (Active)** | 阿里 HappyHorse 1.0 旗舰级图生视频模型，能够将参考图转化为灵动的动效视频。 |
| 3 | **`wan2.7-i2v`** | 视频 (Video) | **激活 (Active)** | 阿里万相 Wan2.7 视频生成模型，表现卓越的高清图生视频能力。 |
| 4 | **`volcengine/doubao-seedance-1.5-pro`** | 视频 (Video) | **激活 (Active)** | 字节跳动火山引擎豆包视频生成模型 1.5 专业版，镜头运动丰富平滑。 |
| 5 | **`flux-1-schnell`** | 图像 (Image) | **激活 (Active)** | Flux-1-Schnell 顶尖开源文生图模型，响应超快，细节丰富。 |

---

## 💻 接入与调用代码示例

### 1. 命令行 (cURL) 调用示例

cURL 适合在终端、脚本或网关配置中进行直接测试。

#### 1.1 非流式调用 (Non-Streaming)
```bash
curl -X POST https://api-gateway.fusionxlink.com/v1/chat/completions \
  -H "Authorization: Bearer sk-dlp-ddb7127fcdd3b2abacccbb21144d91c27137fe08548108a998f7facbcc946972" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "alicoding/qwen3-coder-plus",
    "messages": [
      {
        "role": "user",
        "content": "请用 Python 写一个快速排序算法"
      }
    ],
    "temperature": 0.2,
    "stream": false
  }'
```

#### 1.2 流式调用 (Streaming SSE)
```bash
curl -X POST https://api-gateway.fusionxlink.com/v1/chat/completions \
  -H "Authorization: Bearer sk-dlp-ddb7127fcdd3b2abacccbb21144d91c27137fe08548108a998f7facbcc946972" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "alicoding/qwen3-coder-plus",
    "messages": [
      {
        "role": "user",
        "content": "用一行代码实现斐波那契数列"
      }
    ],
    "stream": true
  }'
```

#### 1.3 语音合成调用 (Text-to-Speech)
```bash
curl -X POST https://api-gateway.fusionxlink.com/v1/audio/speech \
  -H "Authorization: Bearer sk-dlp-ddb7127fcdd3b2abacccbb21144d91c27137fe08548108a998f7facbcc946972" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-tts-flash",
    "input": "欢迎使用 MaaS 平台语音合成功能，这是一段测试语音。",
    "voice": "alloy",
    "response_format": "mp3"
  }' \
  --output test.mp3
```

#### 1.4 异步视频合成任务调用 (Video Generation - Submission & Polling)

视频生成任务耗时较长，采用 **“提交任务 (201) -> 轮询查询 (200)”** 的异步机制：

##### 1.4.1 提交生成视频任务
```bash
curl -X POST https://api-gateway.fusionxlink.com/v1/video/generations \
  -H "Authorization: Bearer sk-dlp-ddb7127fcdd3b2abacccbb21144d91c27137fe08548108a998f7facbcc946972" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "happyhorse-1.0-t2v",
    "prompt": "a beautiful flying butterfly over a flower, slow motion, 1080p, highly detailed"
  }'
```
*响应返回 `job_id` (示例)：*
```json
{
  "request_id": "f7849b92-30fd-9d3a-826c-3c131ba32700",
  "output": {
    "task_id": "ab53e4da-4eb9-46c2-88a9-ea059b0bfce1",
    "task_status": "PENDING"
  },
  "job_id": "vid-80b61501"
}
```

##### 1.4.2 轮询获取任务结果
使用上一步获取的 `job_id` 拼入 GET 请求中：
```bash
curl -X GET https://api-gateway.fusionxlink.com/v1/video/jobs/vid-80b61501 \
  -H "Authorization: Bearer sk-dlp-ddb7127fcdd3b2abacccbb21144d91c27137fe08548108a998f7facbcc946972"
```
*成功时的响应返回下载链接：*
```json
{
  "request_id": "fb66cdee-28fe-9f63-aeeb-fe12bb01d4de",
  "output": {
    "task_id": "ab53e4da-4eb9-46c2-88a9-ea059b0bfce1",
    "task_status": "SUCCEEDED",
    "end_time": "2026-05-21 20:11:10.735",
    "orig_prompt": "a beautiful butterfly",
    "video_url": "https://dashscope-a717.oss-accelerate.aliyuncs.com/..."
  },
  "status": "succeeded",
  "result_url": "https://dashscope-a717.oss-accelerate.aliyuncs.com/..."
}
```

---

### 2. Python 调用示例 (使用官方 `openai` 库)

请确保本地已安装 OpenAI SDK 客户端：
```bash
pip install openai
```

```python
import os
from openai import OpenAI

# 初始化客户端，配置 API Key 以及网关 Custom Base URL
client = OpenAI(
    api_key="sk-dlp-ddb7127fcdd3b2abacccbb21144d91c27137fe08548108a998f7facbcc946972",
    base_url="https://api-gateway.fusionxlink.com/v1"
)

# 1. 非流式调用示例
def test_non_stream():
    print("--- 正在发起非流式请求 ---")
    response = client.chat.completions.create(
        model="alicoding/qwen3-coder-plus",
        messages=[
            {"role": "system", "content": "你是一个资深软件架构师。"},
            {"role": "user", "content": "列出 Redis 常见的 3 种缓存淘汰策略。"}
        ],
        temperature=0.3
    )
    print("回复内容:")
    print(response.choices[0].message.content)
    print(f"Token 统计: 输入 {response.usage.prompt_tokens} | 输出 {response.usage.completion_tokens}")


# 2. 流式调用示例
def test_stream():
    print("\n--- 正在发起流式请求 ---")
    stream = client.chat.completions.create(
        model="alicoding/qwen3-coder-plus",
        messages=[
            {"role": "user", "content": "用一句话解释什么是高内聚低耦合。"}
        ],
        stream=True
    )
    print("实时流输出: ", end="", flush=True)
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end="", flush=True)
    print()


# 3. 语音合成 (TTS) 调用示例
def test_tts():
    print("\n--- 正在发起语音合成请求 ---")
    response = client.audio.speech.create(
        model="qwen3-tts-flash",
        voice="alloy", # 自动映射为百炼 Cherry 音色
        input="欢迎使用 MaaS 平台语音合成功能，这是一段测试语音。"
    )
    # 将二进制流存入本地文件
    output_path = "test.mp3"
    with open(output_path, "wb") as f:
        f.write(response.content)
    print(f"语音已合成并成功存入: {output_path}")


# 4. 异步视频合成 (AI Video) 提交与状态轮询示例
def test_video_generation():
    import requests
    import time
    
    print("\n--- 正在发起异步视频生成请求 ---")
    headers = {
        "Authorization": "Bearer sk-dlp-ddb7127fcdd3b2abacccbb21144d91c27137fe08548108a998f7facbcc946972",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "happyhorse-1.0-t2v",
        "prompt": "a beautiful flying butterfly over a flower, slow motion, 1080p, highly detailed"
    }
    
    # 4.1 提交合成任务
    submit_url = "https://api-gateway.fusionxlink.com/v1/video/generations"
    res = requests.post(submit_url, json=payload, headers=headers).json()
    job_id = res.get("job_id")
    print(f"任务提交成功！Job ID: {job_id} | 状态: {res.get('output', {}).get('task_status')}")
    
    # 4.2 轮询获取完成链接
    status_url = f"https://api-gateway.fusionxlink.com/v1/video/jobs/{job_id}"
    for i in range(30):
        time.sleep(10)
        job_res = requests.get(status_url, headers=headers).json()
        status = job_res.get("status")
        print(f"[{i+1}/30] 当前合成进度/状态: {status}")
        
        if status == "succeeded":
            video_url = job_res.get("result_url")
            print(f"🎉 视频生成成功！合成视频下载链接: {video_url}")
            return video_url
        elif status == "failed":
            print("❌ 视频生成失败！")
            return None
    print("⏰ 视频生成任务查询超时。")
    return None

if __name__ == "__main__":
    test_non_stream()
    test_stream()
    test_tts()
    test_video_generation()
```

---

### 3. Node.js / TypeScript 调用示例 (使用官方 `openai` 库)

安装依赖：
```bash
npm install openai
```

```javascript
const { OpenAI } = require('openai');

// 初始化客户端
const openai = new OpenAI({
  apiKey: 'sk-dlp-ddb7127fcdd3b2abacccbb21144d91c27137fe08548108a998f7facbcc946972',
  baseURL: 'https://api-gateway.fusionxlink.com/v1'
});

async function main() {
  // 1. 非流式响应
  console.log('--- 非流式请求中 ---');
  const response = await openai.chat.completions.create({
    model: 'alicoding/qwen3-coder-plus',
    messages: [{ role: 'user', content: '写一个 Node.js 异步读取文件的简单示例' }],
    temperature: 0.1
  });
  console.log('回答:\n', response.choices[0].message.content);

  // 2. 流式响应
  console.log('\n--- 流式请求中 ---');
  const stream = await openai.chat.completions.create({
    model: 'alicoding/qwen3-coder-plus',
    messages: [{ role: 'user', content: '说一句鼓舞人心的话' }],
    stream: true
  });
  
  process.stdout.write('实时流回答: ');
  for await (const chunk of stream) {
    process.stdout.write(chunk.choices[0]?.delta?.content || '');
  }
  console.log();

  // 3. 语音合成 (TTS)
  console.log('\n--- 语音合成中 ---');
  const mp3 = await openai.audio.speech.create({
    model: 'qwen3-tts-flash',
    voice: 'alloy', // 自动映射为百炼 Cherry 音色
    input: '欢迎使用 MaaS 平台语音合成功能，这是一段测试语音。',
  });
  const fs = require('fs');
  const buffer = Buffer.from(await mp3.arrayBuffer());
  await fs.promises.writeFile('test.mp3', buffer);
  console.log('语音已合成并成功存入 test.mp3');

  // 4. 异步视频生成 (AI Video)
  console.log('\n--- 视频生成中 ---');
  const axios = require('axios');
  
  const headers = {
    'Authorization': 'Bearer sk-dlp-ddb7127fcdd3b2abacccbb21144d91c27137fe08548108a998f7facbcc946972',
    'Content-Type': 'application/json'
  };

  try {
    // 4.1 提交任务
    const submitRes = await axios.post(
      'https://api-gateway.fusionxlink.com/v1/video/generations',
      {
        model: 'happyhorse-1.0-t2v',
        prompt: 'a beautiful flying butterfly over a flower, slow motion, 1080p, highly detailed'
      },
      { headers }
    );
    const jobId = submitRes.data.job_id;
    console.log(`视频生成任务提交成功！Job ID: ${jobId}`);

    // 4.2 轮询查询
    const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
    for (let i = 0; i < 30; i++) {
      await delay(10000);
      const statusRes = await axios.get(
        `https://api-gateway.fusionxlink.com/v1/video/jobs/${jobId}`,
        { headers }
      );
      const status = statusRes.data.status;
      console.log(`[${i + 1}/30] 视频当前合成进度: ${status}`);

      if (status === 'succeeded') {
        console.log(`🎉 视频合成成功！链接: ${statusRes.data.result_url}`);
        break;
      } else if (status === 'failed') {
        console.log('❌ 视频合成失败！');
        break;
      }
    }
  } catch (err) {
    console.error('视频任务出错:', err.message);
  }
}

main().catch(console.error);
```

---

### 4. Go 调用示例 (使用 `sashabaranov/go-openai`)

安装依赖：
```bash
go get github.com/sashabaranov/go-openai
```

```go
package main

import (
	"context"
	"fmt"
	"io"
	"errors"

	"github.com/sashabaranov/go-openai"
)

func main() {
	config := openai.DefaultConfig("sk-dlp-ddb7127fcdd3b2abacccbb21144d91c27137fe08548108a998f7facbcc946972")
	config.BaseURL = "https://api-gateway.fusionxlink.com/v1"

	client := openai.NewClientWithConfig(config)
	ctx := context.Background()

	// 发起非流式对话
	req := openai.ChatCompletionRequest{
		Model: "alicoding/qwen3-coder-plus",
		Messages: []openai.ChatCompletionMessage{
			{
				Role:    openai.ChatMessageRoleUser,
				Content: "介绍下 ALCodingPlan 模型。",
			},
		},
	}

	resp, err := client.CreateChatCompletion(ctx, req)
	if err != nil {
		fmt.Printf("ChatCompletion 错误: %v\n", err)
		return
	}

	fmt.Println("模型回答:")
	fmt.Println(resp.Choices[0].Message.Content)
}
```

---

## 🛡️ 错误处理与重试机制说明

AI Gateway 本身内置了负载均衡与重载路由机制。如果在高并发或极端网络环境下遇到 HTTP 状态码错误，建议您的客户端应用加入如下标准的指数避让重试机制：

*   **HTTP 401 Unauthorized**: API Key 错误，请核对密钥。
*   **HTTP 429 Too Many Requests**: 触发了网关每分钟请求数限制（RPM）或账户额度余额耗尽。
*   **HTTP 502/504 Bad Gateway / Gateway Timeout**: 上游服务偶尔发生网络抖动，客户端应当隔 1s, 2s, 4s 进行 3 次重试。
