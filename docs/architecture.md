# 软件架构与接口

## 1. 组件边界

| 模块 | 职责 | 不负责 |
|---|---|---|
| `protocol.py` | 信号模型、范围、JSON、全量/增量、序号和身份校验 | ISO 15118 EXI、PLC、CAN |
| `network.py` | 本机 IPv6 后台、字节中继、TLS 客户端、HTTP 长连接 | 生产 IPv6 路由、VAS 协商、长期恢复 |
| `lab.py` | 会话线程、参数变更、单步/周期、故障注入、快照、脱敏报告 | 整车执行器 |
| `web.py` | 回环 HTTP UI/API、Host/Origin/token 检查、固定资源白名单 | 公网认证、多租户、生产运维 |
| `static/` | 原生 HTML/CSS/JS、轮询、数据表、事件视图 | 服务端命令执行、第三方统计 |
| `run_demo.py` | 有限轮次 CLI 和原始本地报告 | 浏览器生命周期控制 |

浏览器每约 650ms 获取状态；发送周期与浏览器刷新周期不同。实验线程只允许一个请求在途。后台、字节中继分别持有本机 TCP 监听端口，均由系统分配。TLS 在 EVCC 与后台之间建立，中继不解密。浏览器 UI 自身是回环 HTTP，不要将它和实验内部 HTTPS 混淆。

## 2. 生命周期

```text
idle / stopped / error
  → starting（生成或加载本地证书，启动两个服务）
  → running（TLS连接，自动周期或等待单步）
  → stopping（唤醒等待，关闭socket，等待线程结束）
  → stopped（保留最近结果）

致命网络/超长响应/三次无响应 → error → 用户重启新会话
```

`RLock` 保护控制器状态，生命周期锁串行化启动/停止。变更车辆数据先完整验证再更新内存；后台计划在后台锁下原子更新。事件最多400条，后台原始请求/事件也保留最近400条，避免 UI 持续运行无限积累。

当前单步使用事件唤醒而不是任务队列；连续快速点击可能合并，故应等待一轮完成。参数更新不是磁盘持久化。关闭标签页不会停止 Python。

## 3. 本地 HTTP API

基础地址为 `http://127.0.0.1:8765`；端口可改，绑定地址不可通过命令参数改成公网。

| 方法 | 路径 | JSON 请求 | 响应 |
|---|---|---|---|
| GET | `/`、`/style.css`、`/app.js` | 无 | 固定 UI 资源；HTML嵌入会话 token |
| GET | `/api/schema` | 无 | 两方向信号的 minimum/maximum/resolution/sna |
| GET | `/api/state` | 无 | 当前会话、统计、配置白名单、最近消息与事件 |
| GET | `/api/report` | 无 | 脱敏JSON，Content-Disposition attachment |
| POST | `/api/start` | `{"interval":1,"timeout":2,"automatic":true}` | 启动后的快照，可能仍在 starting |
| POST | `/api/step` | 可带 interval/timeout；会话外强制手动 | 快照；实际收发异步进行 |
| POST | `/api/stop` | `{}` | 停止后的快照 |
| POST | `/api/vehicle` | `{"odo":5100}` | 验证并更新车辆信号 |
| POST | `/api/backend` | `{"values":{"target_soc":90},"departure_in_minutes":60}` | 更新计划；倒计时用分钟，不接受 raw driveoff |
| POST | `/api/fault` | `{"fault":"wrong_seq"}` | 为下一次请求设置故障 |

所有 POST 要求 JSON、明确 Content-Length（最多8192字节）、`X-Lab-Token` 为页面 token。Origin 如存在必须同本机来源；Host 只接受本机地址和当前端口。不提供 CORS，不支持反向代理、不允许任意文件或任意命令执行。安全措施用于减少本机误用，并不使标准库服务器变成生产 Web 服务。

故障名：`drop`、`wrong_seq`、`wrong_vin`、`http_503`、`oversize`。多次设置不同故障可能同时作用于一帧，教学建议一次只设置一个。

常见 HTTP 状态：400输入/协议错误，403 Host/Origin/token不匹配，404非白名单路径，409会话状态冲突，413请求过长，415类型错误，408本地读取超时。

## 4. 数据与网络约束

- V2ICP JSON 对象最大512字节；控制台API的8192字节上限是另一层限制。
- ASCII紧凑编码；重复键（含大小写归一后冲突）、NaN、非对象拒绝。
- 客户端当前限定 TLS1.2 与 `ECDHE-ECDSA-AES128-SHA256`，验证 CA 与 `localhost` 主机名。它是实验配置，不主张是所有版本的完整合规套件列表。
- 测试证书由 OpenSSL 新生成，30天；仅显式加载到 Python 连接，不导入系统信任库。不自动绕过过期或信任错误。
- HTTP Basic用户名为测试VIN；密码是公开示例凭据，不能复用到生产。UI不返回密码或Authorization。
- 中继固定转到一个本机目的端口，缓冲区有背压；不能代表任意目标IPv6路由、NDP、RA或防火墙策略。
- 超时重发保存的原始请求，最多三次尝试。部分HTTP响应超时、连接半关闭等完整生产恢复仍需增强。

## 5. 部署边界

不使用 Docker host networking、端口映射或隧道把此演示暴露到外部。需要生产后台时，应独立设计身份管理、凭据轮换、合规TLS、反向代理、资源限制、审计、持久化、幂等处理、长时重连和运营维护，不把当前模块直接部署为运营系统。
