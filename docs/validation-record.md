# 本地验证记录

日期：2026-11-20（Asia/Shanghai）。以下为0.1.0本地验证记录，不是硬件或规范认证。远端CI以仓库Actions对应提交为准。

## 环境

| 项目 | 版本/条件 |
|---|---|
| 系统 | Windows，本机IPv6回环`::1`可用 |
| Python | 3.13.7 |
| OpenSSL命令行 | 3.3.0（9 Apr 2024） |
| GCC | MinGW.org GCC 6.3.0-1 |
| 浏览器验收 | Chrome 157.0.8103.79，headless；Playwright驱动 |
| UI窗口 | 1440×1050，并检查390×844布局 |
| 网络 | 本机随机TCP端口；没有接入PLC、真实车/桩/运营后台 |

Python的TLS库版本可能与命令行OpenSSL不同；如需诊断以`python -c "import ssl; print(ssl.OPENSSL_VERSION)"`输出为准。

## 已完成

| 验证项 | 命令/证据 | 结果 |
|---|---|---|
| Python协议、真实网络、控制器、API、发布工具规则 | `python -m unittest discover -s tests -v` | 65项通过 |
| CLI两轮收发 | `python -m demo.run_demo --interval 0.1 --cycles 2` | PASS；证书校验、TLS1.2与双向流量 |
| JavaScript语法 | `node --check demo/static/app.js` | 通过；Node仅用于开发检查 |
| Python语法编译 | `python -m compileall -q demo tests tools` | 通过 |
| C主机接纳边界 | GCC C99 + Wall/Wextra/Werror/pedantic后运行 | PASS；未访问MCU或CAN |
| GUI真实浏览器 | `tools/gui_smoke.py` | 自动/改SOC/拒绝seq/重传/停止/手动重启/窄屏/无JS异常通过 |
| 界面截图 | `docs/images/dashboard.png` | 真实运行界面，使用公开合成数据，已视觉查看 |
| 发布资料与链接 | `python tools/release_check.py` | 已完成基本检查；发布时另检查Git暂存/跟踪清单 |
| BOM与接口CSV | UTF-8 CSV解析、每行列数一致 | BOM11条/8列；接口8条/9列，通过 |
| 原创硬件架构图 | XML解析、浏览器渲染与视觉查看 | 通过；不代表硬件实测 |
| 真实浏览器报告下载 | 窄屏单步、下载JSON、检查身份/密码不出现 | 通过；下载文件仅留本地output |
| 干净副本复现 | 仅复制52个公开候选文件到含空格的临时目录，无旧证书/报告，再执行测试/CLI/发布检查 | 65项通过、CLI两轮PASS、发布检查PASS |

修改文件或暂存清单后应重新执行`python tools/release_check.py --require-git`。工作区扫描不等于历史审查；测试结果仅对记录中的环境与版本成立。

## GitHub CI

2026-11-20，提交 `67ca85a` 的首轮远端工作流已全部通过：

| Runner | Python / 编译器 | 结果 |
|---|---|---|
| ubuntu-latest | Python 3.10 | 65项测试、CLI和发布检查通过 |
| ubuntu-latest | Python 3.13 | 65项测试、CLI和发布检查通过 |
| windows-latest | Python 3.10 | 65项测试、CLI和发布检查通过 |
| windows-latest | Python 3.13 | 65项测试、CLI和发布检查通过 |
| ubuntu-latest | GCC C99主机示例 | 编译与断言通过 |

记录地址：`https://github.com/Elsa-is-My-Muse/v2icp-lab/actions/runs/44713999754`。后续提交以各自的Actions记录为准；远端CI通过不增加硬件或规范认证范围。

## 没有执行或不包含

- 真实Linux桌面/macOS浏览器操作、macOS自动测试：未测；Linux与Python3.10的自动化结果仅指上述CI。
- 远端Actions：独立记录在仓库的Actions页面，不作为本地测量结果。
- EVCC/SECC硬件供电、烧录、PLC/SLAC、VAS、IPv6网关、双连接实物测量、CAN执行、整车测试：未测。
- 标准全文的逐条核对、一致性认证、安规/EMC/绝缘与生产可靠性：未做。

## 可复现性说明

协议与网络测试使用合成身份、测试CA和本机端口，不依赖公司固件或真实后台。浏览器测试是可选开发工具，请传入实际浏览器路径。测试命令不会上传证书或报告。
