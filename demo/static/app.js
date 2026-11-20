"use strict";

const byId = (identifier) => document.getElementById(identifier);
const token = document.querySelector('meta[name="lab-token"]').content;
const labels = {
  odo: "里程 odo", bat_reqtime: "电池需求时长 bat_reqtime",
  bat_eamount: "电池需求能量 bat_eamount", prec_eamount: "预调节能量 prec_eamount",
  prec_reqtime: "预调节时长 prec_reqtime", chrg_stat: "充电状态 chrg_stat",
  h2_stat: "氢系统状态 h2_stat", bat_stat: "电池状态 bat_stat",
  prec_dsrd: "预调节请求 prec_dsrd", prec_hvac: "空调模式 prec_hvac",
  ambienttemp: "环境温度 ambienttemp", target_dist: "目标里程 target_dist",
  target_soc: "目标 SOC target_soc"
};
let schema;
let lastEventId = -1;
let initialized = false;
let working = false;
let disconnected = false;

function notify(message, error = false) {
  byId("notice").textContent = message;
  byId("notice").className = error ? "error" : "";
}

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {cache: "no-store"} : {
    method: "POST", headers: {"Content-Type": "application/json", "X-Lab-Token": token},
    body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function buildFields(group, values) {
  const container = byId(`${group}-fields`);
  for (const [name, signal] of Object.entries(schema[group])) {
    if (name === "driveoff") continue;
    const label = document.createElement("label");
    const title = document.createElement("span");
    title.textContent = labels[name] || name;
    const input = document.createElement("input");
    input.id = `${group}-${name}`;
    input.name = name;
    input.type = "number";
    input.step = "1";
    input.required = true;
    input.min = Math.min(signal.minimum, signal.sna);
    input.max = signal.maximum;
    input.value = values[name] ?? signal.sna;
    const hint = document.createElement("small");
    hint.textContent = `raw ${signal.minimum}…${signal.maximum} · SNA ${signal.sna}`;
    label.append(title, input, hint);
    container.append(label);
  }
}

function render(state) {
  if (!initialized) {
    buildFields("vehicle", state.config.vehicle);
    buildFields("backend", state.config.backend);
    byId("departure").value = state.config.departure_in_minutes ?? "";
    byId("vehicle-id").textContent = state.config.vin;
    initialized = true;
  }
  const active = ["starting", "running", "stopping"].includes(state.status);
  const running = state.status === "running";
  const states = {idle: "尚未启动", starting: "正在连接", running: "运行中", stopping: "正在停止", stopped: "已停止", error: "会话异常"};
  byId("status-label").textContent = states[state.status] || state.status;
  byId("status-dot").className = `status-dot ${state.status}`;
  byId("start").disabled = active || working;
  byId("step").disabled = working || (active && (state.automatic || !running));
  byId("stop").disabled = !active || working;
  byId("inject").disabled = !running || working;
  for (const identifier of ["interval", "timeout", "preset"]) byId(identifier).disabled = active;
  byId("tx-count").textContent = state.tx_count;
  byId("rx-count").textContent = state.rx_count;
  byId("sequence").textContent = state.sequence;
  byId("latency").textContent = state.latency_ms ?? "—";
  byId("anomalies").textContent = `${state.retries} / ${state.rejected}`;
  byId("bytes").textContent = (state.relay_bytes.to_backend + state.relay_bytes.to_vehicle).toLocaleString();
  if (state.topology.relay_port) {
    byId("relay-address").textContent = `[::1]:${state.topology.relay_port}`;
    byId("backend-address").textContent = `[::1]:${state.topology.backend_port}`;
  }
  byId("tls-label").textContent = state.tls ? `${active ? "●" : "○"} ${state.tls.version} · ${state.tls.cipher} · ${active ? "已校验证书" : "上次会话"}` : "○ 等待建立 TLS";
  byId("tx-json").textContent = state.last_tx ? JSON.stringify(state.last_tx, null, 2) : "等待发送…";
  byId("rx-json").textContent = state.last_rx ? JSON.stringify(state.last_rx, null, 2) : "等待响应…";
  if (Object.keys(state.physical).length) {
    const rows = Object.entries(state.physical).map(([name, value]) => {
      const row = document.createElement("tr");
      const raw = value === null ? schema.backend[name].sna : value / schema.backend[name].resolution;
      for (const content of [name, raw, value === null ? "不可用 / SNA" : `${value}${name === "driveoff" ? " 分钟" : name === "ambienttemp" ? " °C" : name === "target_soc" ? " %" : ""}`]) {
        const cell = document.createElement("td"); cell.textContent = content; row.append(cell);
      }
      return row;
    });
    byId("physical-values").replaceChildren(...rows);
  } else {
    const row = document.createElement("tr");
    const cell = document.createElement("td"); cell.colSpan = 3; cell.textContent = "尚无有效响应";
    row.append(cell); byId("physical-values").replaceChildren(row);
  }
  const newest = state.events.at(-1)?.id ?? -1;
  if (newest !== lastEventId) {
    lastEventId = newest;
    const rows = [...state.events].reverse().map((entry) => {
      const {id, time, event, ...detail} = entry;
      const row = document.createElement("div");
      row.className = `event-row ${/ERROR|REJECT|TIMEOUT|FAULT/.test(event) ? "warning" : ""}`;
      const timestamp = document.createElement("time"); timestamp.textContent = time;
      const title = document.createElement("strong"); title.textContent = event;
      const description = document.createElement("span"); description.textContent = JSON.stringify(detail);
      row.append(timestamp, title, description); return row;
    });
    byId("events").replaceChildren(...rows);
  }
  if (state.error) notify(`会话已停止：${state.error}。修正问题后可重新启动。`, true);
}

function options() {
  return {interval: Number(byId("interval").value), timeout: Number(byId("timeout").value)};
}

async function action(path, body, success) {
  working = true;
  try {
    render(await api(path, body));
    notify(success);
  } catch (error) {
    notify(error.message, true);
  } finally {
    working = false;
    await refresh();
  }
}

async function refresh() {
  try {
    render(await api("/api/state"));
    if (disconnected) notify("已重新连接本地控制台。");
    disconnected = false;
  } catch (error) {
    disconnected = true;
    notify(`无法连接本地控制台：${error.message}。请确认 Python 服务仍在运行。`, true);
  }
}

byId("preset").addEventListener("change", () => {
  const reference = byId("preset").value === "reference";
  if (byId("preset").value !== "custom") {
    byId("interval").value = reference ? 10 : 1;
    byId("timeout").value = reference ? 15 : 2;
  }
});
for (const identifier of ["interval", "timeout"]) byId(identifier).addEventListener("input", () => {byId("preset").value = "custom";});
byId("start").addEventListener("click", () => action("/api/start", {...options(), automatic: true}, "自动实验已启动。快速演示时序不代表规范完整实现。"));
byId("step").addEventListener("click", () => action("/api/step", options(), "已请求单步收发；再次点击可发送下一帧。"));
byId("stop").addEventListener("click", () => action("/api/stop", {}, "实验已停止，结果保留。"));
byId("inject").addEventListener("click", () => action("/api/fault", {fault: byId("fault").value}, "故障已设置：下一次请求生效。单步模式请再点击“单步收发”。"));
for (const group of ["vehicle", "backend"]) {
  byId(`${group}-form`).addEventListener("submit", (event) => {
    event.preventDefault();
    const values = {};
    for (const input of byId(`${group}-fields`).querySelectorAll("input")) values[input.name] = Number(input.value);
    const departure = byId("departure").value;
    const body = group === "vehicle" ? values : {values, departure_in_minutes: departure === "" ? null : Number(departure)};
    action(`/api/${group}`, body, "参数已应用到内存；下一次收发可观察变化。原配置文件未修改。");
  });
}

async function initialize() {
  try {
    schema = await api("/api/schema");
    await refresh();
    const poll = async () => {await refresh(); window.setTimeout(poll, 650);};
    window.setTimeout(poll, 650);
  } catch (error) {notify(`初始化失败：${error.message}。请刷新页面。`, true);}
}
initialize();
