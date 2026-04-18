## 启动脚本：start_web.sh

## 快速创作-分镜类型里面有
- 静态样式：无 AI 媒体，纯文字/CSS 排版；速度最快；免费
- 生成插图：每帧 AI 生成一张图片作为背景；较慢；消耗图像额度
- 生成视频：每帧 AI 生成一段视频作为背景；最慢；消耗视频额度

TTS 默认用的是 edge-tts（本地模式），这是微软的免费语音服务

https://rh-images.xiaoyaoyou.com/696271ff119880c07253c3fa1d66d189/output/audio/ComfyUI_00001_uutyy_1776392333.mp3  RunningHub 的 CDN 地址，用于托管生成的媒体文件。


架构是这样的：
Pixelle-Video
    ↓
ComfyKit（统一工作流执行引擎）
    ↓
   ├── 本地 ComfyUI（selfhost 模式）
   └── RunningHub（runninghub 模式）← 我的配置
ComfyKit 是 ComfyUI 生态的通用客户端，RunningHub 底层也跑的是 ComfyUI 工作流，只是把执行引擎从本地搬到了云端。所以界面上显示 "ComfyUI 合成" 是指通过 ComfyKit 的工作流引擎执行，实际调用的是你配置的 RunningHub 云端服务。
这是统一抽象的好处——无论用本地 ComfyUI 还是 RunningHub，代码层都是同一套 ComfyKit 接口。


静态样式的完整流程（不调用 RunningHub 媒体生成）：
1. ✅ LLM → 生成文案（MiniMax）
2. ✅ Edge-TTS → 合成语音（免费微软语音）
3. ❌ 不生成图片/视频
4. ✅ HTML 模板 + Playwright → 渲染帧截图
5. ✅ FFmpeg → 合成最终视频
所以用静态样式 + 默认 Edge-TTS + MiniMax LLM，全程不花任何云服务费用。

生成插图模式：
1. ✅ LLM → 生成文案
2. ✅ Edge-TTS → 合成语音（免费）
3. ✅ RunningHub（ComfyUI工作流）→ 生成 AI 图片 ← 这里消耗额度
4. ✅ HTML 模板 + Playwright → 把 AI 图片嵌入模板渲染帧
5. ✅ FFmpeg → 合成视频


分镜类型=生成视频，模板的作用：
┌─────────────────────────────┐
│  背景图片层 (.background-image) │  ← 全屏铺满
├─────────────────────────────┤
│     视频叠加层 (.video-overlay)  │  ← 中央区域播放AI生成的视频
├─────────────────────────────┤
│        文字标题层 (.title)     │  ← 覆盖在最上层
└─────────────────────────────┘
模板决定了视频在画面中的位置和大小，但背后仍然需要：
- 背景图片 → AI 生成（消耗图片额度）
- 视频叠加 → AI 生成（消耗视频额度）
模板的作用是排版布局，即视频该放在画面哪个位置、多大尺寸、标题文字怎么排——而不是决定"要不要生成视频"。
所以"分镜类型"决定的是生成什么媒体，"模板"决定的是这些媒体在画面里怎么摆放。


# 快速创作-分镜类型-生成插图
- 提示词在：/Users/azm/MyProject/Pixelle-Video/config.yaml 
- 工作流ID：workflows/runninghub/image_Z-image.json #旧的ID=1995319131513794562


templates/1080x1920/image_blur_card.html 页面中
- meta name="template:media-width" content="1024"> #图片宽度 
- meta name="template:media-height" content="1024"> # 图片高度
- meta name="viewport" content="width=1080, height=1920"> # 浏览器视口大小，用于渲染时模拟
 
# TODO
- 更换工作流ID
- 口播视频，对口型
- 插图生成，支持提示词模板
 