# 测试与复现

## 1. 基础自动测试

项目根目录执行：

```powershell
python -m unittest discover -s tests -v
```

当前65个测试：协议/网络37项，实验控制器/Web API20项，发布检查8项。网络测试使用真正的IPv6回环、OpenSSL生成的临时测试证书和TLS连接，不是mock全部网络。临时证书测试后自动清理，不依赖你之前生成的`.demo_certs`是否过期。

测试覆盖：全量/增量、序号回绕、SNA、长度与类型、重复JSON键、CA/主机名、密码、响应seq/VIN、503、分片、超长、同连接超时重发与三次上限；控制器停止/重启、动态参数、脱敏；API Host/Origin/token、路径白名单、输入上限；发布工具基本规则。

不能据此推断所有HTTP异常、所有攻击场景、完整恢复、硬件或标准一致性都已覆盖。

## 2. CLI冒烟

```powershell
python -m demo.run_demo --interval 0.1 --cycles 2
```

期望末尾 `[PASS] 2 request/response cycles`。0.1秒是加速测试，不代表生产时序。报告写入被gitignore排除的`output/`，未脱敏，不直接公开。

## 3. 可选真实浏览器验收

这一步才需要额外开发依赖Playwright，不影响软件正常运行：

```powershell
python -m pip install playwright
python tools/gui_smoke.py --browser "C:\Program Files\Google\Chrome\Application\chrome.exe"
```

也可传入实际Edge路径。若机器没有已有兼容浏览器，按Playwright官方安装指引安装其Chromium后省略`--browser`。默认截图为`output/dashboard.png`；维护者有权分享且确认仅为合成数据时，可用`--screenshot docs/images/dashboard.png`更新README截图。

脚本会启动临时本地服务，验证自动收发、SOC→90、错误seq拒绝、丢包重传、停止、手动重启、390px窄屏无水平溢出和无JS运行异常，最后关闭浏览器及服务。不要求降低CSP或禁用证书校验；Playwright等待条件使用函数而非eval字符串。

## 4. C主机边界

```powershell
New-Item -ItemType Directory -Force output | Out-Null
gcc -std=c99 -Wall -Wextra -Werror -pedantic embedded/v2icp_boundary.c embedded/example_boundary.c -o output/boundary_test.exe
./output/boundary_test.exe
```

验证输入拒绝、权限/新鲜度、槽满、SNA和温度-1等接纳边界；不链接任何MCU、CAN或TLS驱动。主机通过不是硬件测试。Linux命令在embedded/README中。

## 5. 发布前检查

```powershell
python tools/release_check.py
```

未初始化Git时检查工作区候选文件，排除明确本机运行目录。有项目根Git仓库时检查Git已跟踪/已暂存清单，误加入的证书或output也会被抓出；正式审查时加`--require-git`防止误以为工作区扫描等于Git审查。

检查器验证必需交付文件、Markdown本地链接目标、常见敏感/二进制/标准PDF路径、基本私钥/token/个人路径文本模式，以及公开demo配置是否被改成私人值。它不是专业secret scanner，不审计历史，不证明许可证或法律权利，也不能理解图片里是否有敏感信息，仍需人工检查。

## 6. CI不是已完成的远端结果

`.github/workflows/test.yml`配置Windows/Linux与Python3.10/3.13单元和CLI检查，另有Linux C主机编译。每次提交的远端结果以仓库Actions记录为准；本机测试和远端结果分别记录。

CI使用只读仓库权限，不上传测试证书、原始日志或报告作为制品。不自动进行发布或打tag。依赖固定为官方checkout v4和setup-python v5的提交哈希，升级时应核验来源与兼容性。
