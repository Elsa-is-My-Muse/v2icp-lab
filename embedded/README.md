# 固件侧 C 接口参考

这不是可刷写固件，也不是C版完整V2ICP栈。它仅示范：**协议校验后的后台目标如何进入单个待处理槽，而不直接操作CAN或功率级。** 不依赖私人固件或厂商库。

## 主机验证

在项目根目录，有GCC时：

```powershell
New-Item -ItemType Directory -Force output | Out-Null
gcc -std=c99 -Wall -Wextra -Werror -pedantic embedded/v2icp_boundary.c embedded/example_boundary.c -o output/boundary_test.exe
./output/boundary_test.exe
```

Linux可将输出名换为 `output/boundary_test`，先 `mkdir -p output`。示例中断言必须启用，别加 `-DNDEBUG`。

## 约定

- 调用者先完成TLS/HTTP/JSON/身份/序号/范围/时效校验，再传入 `v2icp_admission`；这些布尔值不能硬编码为true来绕过检查。示例中的true仅是单元场景。
- `local_policy_allows` 来自本地整车策略，不是后台自报的安全许可；接收方仍要在实际使用目标前重新检查状态和时效。
- `driveoff_minutes` 已经是转换后的分钟；**不是**协议raw，raw=12应在解析层转换为60。其他未核实单位继续保留raw命名。
- SNA保留为-1，温度SNA为-51；`known_mask`表示可用目标，未知字段不得当作零、默认启用或“安全正常”。
- 槽满返回BUSY，不悄悄覆盖未处理目标。`take`仅代表上层读出目标，**不代表车辆已执行**。
- 此槽不是线程安全队列；必须从同一任务调用，或由你的RTOS消息队列/互斥锁封装。真实项目还需序列关联、过期处理、执行反馈和优先级。
- 没有TCP、TLS、JSON解析、CAN驱动和RTOS适配；不要因为能在GCC编译就宣称已适配Keil、GD32、STM32或整车。

## 推荐真实数据路径

```text
独立V2ICP socket/TLS → 有界HTTP/JSON解析 → 身份/序号/单位/新鲜度校验
  → 本地整车策略 → RTOS目标队列 → 使用前再检查 → 授权VCU接口
```

原ISO15118连接保持独立；此C边界不读取或修改它。移植位置、资源和验收见 `../docs/hardware-integration.md`。
