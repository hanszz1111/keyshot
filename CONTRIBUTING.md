# 贡献与验证

本项目主要在 Windows 上运行，Mac 侧可以检查代码与文档，但不能把没有 NVIDIA GPU 的代码自检称为 Windows 出图验收。

## 修改前

1. 先读 [README](README.md)、[文档索引](docs/README.md) 和 [过程文档](00-AI白模渲染器-过程文档.md) 的当前状态。
2. 双电脑并行工作时按 [AI 协作协议](AI/README.md) 记录基线、执行端、复审端与证据；不要直接覆盖另一端未合并的工作。
3. 从最新基线建 `codex/` 分支。发现未提交的用户改动时保留它们，不用强制重置。

## 修改后

- 代码或行为变化：更新对应的用户文档，并在过程文档“二、变更记录”追加一行，写明**已验证**与**待验证**。
- 前端/后端改动：运行 `python web/selftest.py`；JS 修改可另做语法检查，Windows 上还需用真实模型和服务做端到端验证。与本轮提示词/掩膜相关的单测：

  | 命令 | 覆盖 | 需要的解释器 |
  |---|---|---|
  | `python web/selftest.py` | 后端契约（提示词合并、负面约束幂等、引擎注册表、任务队列） | 任意 Python（仅标准库） |
  | `node web/test_prompt_pipeline.cjs` | 前端提示词拼装与「白模→成品」改写 | Node |
  | `node web/test_progress_time.cjs` | 进度与剩余时间估算 | Node |
  | `python web/test_product_base.py` | 保形底图场景契约 | 任意 Python（仅标准库） |
  | `python web/test_design_consistency.py` | 设计预设签名与冲突防护 | 任意 Python（仅标准库） |
  | `python web/test_cmf_guide.py` | CMF 配色引导图 | **需带 numpy**（ComfyUI 的 `python_embeded` 可用） |
  | `python scripts/roi_crop.py --help` | ROI 裁切依赖自检 | **需带 numpy/Pillow** |
- 启停脚本改动：在 Windows 测试启动、停止、重复启动和端口被占用的情况；注意 `.bat/.ps1` 的编码、BOM 和 CRLF 约束，详见 [GITHUB.md](GITHUB.md)。
- 模型、机位或成图质量改动：至少保存“输入模型 → 机位白模/深度/法线 → 最终成图”的同机位对照，不只报告任务成功率。
- 公开提交前检查差异，确保不含 `assets/`、`outputs/`、`.env`、任务数据库、客户图、密钥或本机私有路径。

本仓库当前没有单独声明代码开源许可证；在许可证确定前，请勿自行添加或声称许可条款。
