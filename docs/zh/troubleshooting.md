# 故障排查

遇到问题？这里有一些常见问题的解决方案。

---

## 安装问题

### 依赖安装失败

```bash
# 清理缓存
uv cache clean

# 重新安装
uv sync
```

---

### 提取文案报错：No module named 'faster_whisper'

**症状**: 点击"提取文案"后提示 `No module named 'faster_whisper'`

**原因**: 项目缺少 `faster-whisper` 依赖。本地模式（local mode）依赖 `faster-whisper` 进行语音转文字，该库之前未被加入 `pyproject.toml` 的 dependencies。

**解决方案**:

```bash
# 方案一：直接安装（推荐，最快）
uv pip install "faster-whisper>=1.0.0"

# 方案二：重新同步所有依赖
uv sync
```

安装后重启应用即可。

> 如果通过 `uv sync` 安装时报错 `onnxruntime 无 macOS x86_64 wheel`，需要在 `pyproject.toml` 中添加平台约束：
> ```toml
> [tool.uv]
> override-dependencies = ["onnxruntime>=1.23.0,<1.24.0"]
> ```
> 原因：`onnxruntime>=1.24.0` 在 macOS Intel 架构上缺少预编译 wheel，`uv` 锁定版本时会解析到最新不兼容版本。

---

### 依赖安装报错：onnxruntime 无 macOS x86_64 wheel

**症状**: `uv sync` 或 `uv run` 时报错 `Distribution onnxruntime==1.24.x can't be installed because it doesn't have a source distribution or wheel for the current platform (macosx_26_0_x86_64)`

**原因**: `faster-whisper` 的依赖 `onnxruntime`，版本 `>=1.24.0` 仅发布了 Linux/Windows/macOS ARM 的 wheel，macOS Intel (x86_64) 无预编译包。`uv` 在解析依赖时可能锁定到最新不兼容版本。

**解决方案**:

在 `pyproject.toml` 末尾添加：

```toml
[tool.uv]
override-dependencies = ["onnxruntime>=1.23.0,<1.24.0"]
```

然后执行：

```bash
uv sync
```

这将约束 `onnxruntime` 到最后一个支持 macOS Intel 的版本（`1.23.x`），`faster-whisper` 在该版本下完全正常工作。

---

## 配置问题

### ComfyUI 连接失败

**可能原因**:
- ComfyUI 未运行
- URL 配置错误
- 防火墙阻止

**解决方案**:
1. 确认 ComfyUI 正在运行
2. 检查 URL 配置（默认 `http://127.0.0.1:8188`）
3. 在浏览器中访问 ComfyUI 地址测试
4. 检查防火墙设置

### LLM API 调用失败

**可能原因**:
- API Key 错误
- 网络问题
- 余额不足

**解决方案**:
1. 检查 API Key 是否正确
2. 检查网络连接
3. 查看错误提示中的具体原因
4. 检查账户余额

---

## 生成问题

### 视频生成失败

**可能原因**:
- 工作流文件损坏
- 模型未下载
- 资源不足

**解决方案**:
1. 检查工作流文件是否存在
2. 确认 ComfyUI 已下载所需模型
3. 检查磁盘空间和内存

### 图像生成失败

**解决方案**:
1. 检查 ComfyUI 是否正常运行
2. 尝试在 ComfyUI 中手动测试工作流
3. 检查工作流配置

### TTS 生成失败

**解决方案**:
1. 检查 TTS 工作流是否正确
2. 如使用声音克隆，检查参考音频格式
3. 查看错误日志

---

## 性能问题

### 生成速度慢

**优化建议**:
1. 使用本地 ComfyUI（比云端快）
2. 减少分镜数量
3. 使用更快的 LLM（如 Qianwen）
4. 检查网络连接

---

## 其他问题

仍有问题？

1. 查看项目 [GitHub Issues](https://github.com/AIDC-AI/Pixelle-Video/issues)
2. 提交新的 Issue 描述你的问题
3. 包含错误日志和配置信息以便快速定位

---

## 日志查看

日志文件位于项目根目录：
- `api_server.log` - API 服务日志
- `test_output.log` - 测试日志
- `web.log` - Web UI 日志（Streamlit 应用日志）

