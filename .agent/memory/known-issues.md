# 已知问题与风险

## P3（不阻塞交付）
1. js-reverse-skill 上游未声明 LICENSE — 商用分发前确认（skills/reverse/js-reverse/LICENSE-WARNING.md）
2. 17 个存量测试失败需环境治理: 安装 redis 包（5 个）+ Windows bash/echo 依赖（12 个）
3. reason 的 LLM 直调 litellm.completion，未走 clawd provider 路由/降级体系
4. 推理模式与 5 阶段 WorkflowEngine 未深度融合（当前 CLI 胶水接入）
5. MCP stdio 在 Windows 下某些 server 需 cmd /c 包装
6. mcp-gamehacking、hermes-agent 参考目录损坏（hermes 副本在 D:\参考项目\hermes-agent-tmp）

## 安全边界（持续有效）
- 安全工具 catalog 有 scope 门禁 + dangerous 双重确认，仅限授权测试目标
- MCP server 接入默认检疫期，签名变更自动降级，需人工 approve
