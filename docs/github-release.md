# 维护与版本发布

本文面向维护者，约定源文件范围、发布检查和版本流程。新贡献者从 [CONTRIBUTING](../CONTRIBUTING.md) 开始。

## 发布范围

- 发布原创代码、文档、示意图、参考BOM和有权分享的测试证据。
- 不发布标准PDF、私人固件/图纸/DBC、第三方未授权包、私钥、真实凭据和生产抓包。
- `.demo_certs/`、`output/`与缓存属于本地生成内容，不进入Git和发布附件。
- 硬件未测、规范复核缺口和不适用范围必须写进版本说明；不把PC测试称作整车认证。

## 检查清单

```powershell
python -m unittest discover -s tests -v
python -m demo.run_demo --interval 0.1 --cycles 2
python tools/release_check.py --require-git
git diff --check
git status --short
```

UI或C接口有变动时，补跑 [testing](testing.md) 中的对应验收。新截图只使用合成数据。

检查器扫描Git暂存/跟踪清单与工作区内容，不扫描完整历史，也不能证明许可证或图片隐私安全。检查暂存区完整差异，不仅看统计；已经进入历史的密钥要先撤销/轮换，再按适用流程处理历史，不能只加gitignore。

## 准备版本

1. 在CHANGELOG和`docs/releases/`记录本版功能、验证环境与已知限制。
2. 确认版本号、文档命令、截图和默认配置一致。
3. 提交审核过的文件，检查Actions对应提交的所有任务结果。
4. 在通过的提交上创建版本标签与GitHub Release；预览阶段明确标为pre-release。
5. 默认只使用GitHub生成的源码归档，不添加证书、原始日志、私人固件或本机输出目录。

## 仓库设置

仓库公开前确认描述与MIT许可范围一致，启用Issues和私密漏洞报告。CI只需读取代码，不配置生产secret；维护者按协作需要设置分支保护与审核规则。

发布是人工决定，不由测试工作流自动打tag或上传附件。对外只承诺版本中已有且经过记录的能力。
