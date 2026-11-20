# 版本内容与验收边界

日期：2026-11-20。版本：0.1.0。项目名 V2ICP Lab，非官方标准项目。

| 交付类别 | 路径 | 验收方式 | 状态 |
|---|---|---|---|
| 可视化软件 | `demo/web.py`、`demo/static/`、`start-lab.cmd` | 打开界面并完成收发/改值/异常实验 | 已实现；见验证记录 |
| 协议与网络软件 | `demo/protocol.py`、`demo/network.py`、`demo/lab.py` | 自动测试和真实本机 TLS 收发 | 已实现；非标准认证 |
| 命令行 | `demo/run_demo.py`、`demo/config.json`、`demo/run.ps1` | CLI 输出 PASS | 已实现 |
| 硬件架构资料 | `hardware/architecture.svg`、`hardware/README.md` | 阅读器显示；区分仿真与真机 | 原创参考资料，无实物验证 |
| 选型与接口资料 | `hardware/bom.csv`、`hardware/interfaces.csv` | 逐行核对选型/作用/待定项 | 参考级，不是采购或接线定版 |
| 固件接口参考 | `embedded/` | 主机 C 编译运行示例 | 不含 MCU 驱动和完整协议栈 |
| 上板验证资料 | `hardware/validation-checklist.md`、记录模板 | 由实际集成者填入证据 | 模板已提供，尚无硬件测试结果 |
| 软件与学习文档 | `docs/`、中英文 README | 新环境按步骤复现 | 已编写 |
| 测试和发布资料 | `tests/`、`tools/`、`.github/`、发布文档 | 单元测试、浏览器测试、文件审查 | 本地验证与CI配置分开说明 |
| 法律与协作入口 | LICENSE、NOTICE、SECURITY、CONTRIBUTING | 由仓库所有者做发布权审查 | 原创材料 MIT；不覆盖第三方 |

## 不能理解为已交付的东西

- 没有可制造 PCB、原理图、Gerber、具体板卡已核实的物理引脚表或出厂固件。
- 没有复制私人 EVCC/SECC 源码、CAN DBC、运营后台凭据或标准 PDF。
- 没有 PLC、VAS、IPv6 路由和两条真实车桩连接的上板验证。
- 没有高压充电控制、硬件安全保证、认证或厂商背书。

## 接受交付的最短路径

1. 运行 `python -m demo.web --open` 并完成 quickstart 的六步。
2. 运行 `python -m unittest discover -s tests -v`。
3. 核对 `docs/validation-record.md` 与仓库Actions，区分本机测试、远端CI和硬件验证。
4. 阅读硬件入口，了解所有 `TBD` 都必须由真实板图/测量填入。
5. 在没有私人资料的副本中执行发布检查，再决定是否公开。
