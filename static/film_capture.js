const params = new URLSearchParams(window.location.search);
const robotId = params.get("robot_id") || "raspbot-a";
const $ = (id) => document.getElementById(id);

const state = {
  summary: null,
  lidar: null,
  commands: [],
  moveLogs: [],
};

function fmt(value, digits = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : "--";
}

function escapeLog(value) {
  return String(value ?? "-").replace(/\s+/g, " ").trim();
}

async function api(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`${response.status} ${path}`);
  return response.json();
}

function commandLabel(command) {
  if (command === "start_light_search") return "최적 조도 탐색";
  if (command === "stop") return "정지";
  if (command === "show_status") return "상태 확인";
  if (String(command || "").startsWith("remote-")) return "리모컨 입력";
  return command || "명령";
}

function phaseName(frame) {
  if (!frame) return "대기";
  if (frame.state === "EXPLORE") return "조도 탐색(1차)";
  if (frame.state === "RETURN_TO_BEST") return "최적 위치 복귀";
  if (frame.state === "SEEK_LIGHT") return "추가 탐색(2차)";
  if (frame.state === "AVOID") return "장애물 회피";
  if (frame.state === "BACKUP") return "후진 회피";
  if (frame.state === "ESCAPE") return "탈출 회전";
  if (frame.state === "IDLE") return "대기";
  return frame.state || "대기";
}

function obstacleState(frame) {
  if (!frame) return "clear";
  if (frame.emergency) return "emergency";
  if (frame.danger) return "danger";
  if (frame.front_blocked) return "front_blocked";
  return "clear";
}

function phaseRemaining(frame, config = {}) {
  if (!frame) return "--";
  if (frame.state === "EXPLORE") {
    const total = Number(config.explore_seconds ?? 50);
    return `${Math.max(0, Math.ceil(total - Number(frame.explore_elapsed || 0)))}초`;
  }
  if (frame.state === "SEEK_LIGHT") {
    return `${Math.max(0, Math.ceil(Number(frame.seek_seconds || 0) - Number(frame.seek_elapsed || 0)))}초`;
  }
  if (frame.state === "RETURN_TO_BEST") {
    const remaining = Math.max(0, Number(frame.return_total || 0) - Number(frame.return_index || 0));
    return frame.return_total ? `${remaining}단계` : "복귀 중";
  }
  return "--";
}

function drawLidar(canvas, frame) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const cx = width / 2;
  const robotY = height - 54;
  const scale = Math.min((width - 96) / 1200, (height - 108) / 1000);
  const points = frame?.points || [];

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fbfdfb";
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = "#dbe5dc";
  ctx.lineWidth = 1;
  ctx.font = "16px Arial";
  ctx.fillStyle = "#7a867e";
  for (let x = 100; x <= 1000; x += 100) {
    const sy = robotY - x * scale;
    ctx.beginPath();
    ctx.moveTo(38, sy);
    ctx.lineTo(width - 38, sy);
    ctx.stroke();
    if (x % 200 === 0) ctx.fillText(`${x}mm`, 46, sy - 6);
  }
  for (let y = -600; y <= 600; y += 100) {
    const sx = cx - y * scale;
    ctx.beginPath();
    ctx.moveTo(sx, 30);
    ctx.lineTo(sx, robotY + 26);
    ctx.stroke();
  }

  if (frame?.front_blocked || frame?.danger || frame?.emergency) {
    ctx.fillStyle = frame.emergency ? "rgba(189,71,71,.22)" : "rgba(242,164,0,.18)";
    ctx.fillRect(cx - 115 * scale, 34, 230 * scale, robotY - 34);
  }

  ctx.strokeStyle = "#197236";
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(cx, robotY - 48);
  ctx.lineTo(cx - 52, robotY + 28);
  ctx.lineTo(cx + 52, robotY + 28);
  ctx.closePath();
  ctx.stroke();
  ctx.fillStyle = "rgba(25,114,54,.10)";
  ctx.fill();
  ctx.fillStyle = "#197236";
  ctx.font = "bold 18px Arial";
  ctx.fillText("ROBOT", cx - 32, robotY + 48);

  for (const point of points) {
    const sx = cx - Number(point.y) * scale;
    const sy = robotY - Number(point.x) * scale;
    if (sx < 0 || sx > width || sy < 0 || sy > height) continue;
    ctx.beginPath();
    ctx.arc(sx, sy, point.ignored ? 2.5 : 4, 0, Math.PI * 2);
    ctx.fillStyle = point.ignored ? "rgba(105,115,109,.35)" : "#2d9cdb";
    ctx.fill();
  }
}

function latestInput() {
  const visible = state.commands.filter((item) => item.command !== "speak");
  const latest = visible[visible.length - 1];
  return latest ? `${commandLabel(latest.command)}${latest.value ? ` / ${latest.value}` : ""}` : "대기 중";
}

function renderStatus() {
  if (!$("filmStatus")) return;
  const frame = state.lidar;
  const summary = state.summary;
  const config = summary?.config || {};
  const profile = summary?.plant_profile || {};
  const currentLux = frame?.current_lux !== undefined && frame?.current_lux !== null
    ? `${fmt(frame.current_lux, 0)} lx`
    : summary?.latest ? `${fmt(summary.latest.lux, 0)} lx` : "--";
  const targetLux = profile.lux_range || `${config.search_lux_min ?? 800}~${config.search_lux_max ?? 900} lux`;
  const pose = frame?.pose_x !== undefined && frame?.pose_x !== null && frame?.pose_y !== undefined && frame?.pose_y !== null
    ? `(${fmt(frame.pose_x, 0)}, ${fmt(frame.pose_y, 0)})`
    : "--";
  const bestCoord = frame?.best_x !== undefined && frame?.best_x !== null && frame?.best_y !== undefined && frame?.best_y !== null
    ? `(${fmt(frame.best_x, 0)}, ${fmt(frame.best_y, 0)})`
    : "--";
  const lines = [
    `현재 상태: ${frame?.state || "IDLE"}`,
    `최근 입력: ${latestInput()}`,
    `현재 동작: ${frame?.action || "STOP"}`,
    `현재 조도: ${currentLux}`,
    `목표 조도: ${targetLux}`,
    `최고 조도: ${frame?.best_lux !== undefined && frame?.best_lux !== null ? `${fmt(frame.best_lux, 0)} lx` : "--"}`,
    `현재 좌표: ${pose}`,
    `목표 좌표: ${bestCoord}`,
    `실행 상태: ${phaseName(frame)}`,
    `남은 시간: ${phaseRemaining(frame, config)}`,
    `장애물 상태: ${obstacleState(frame)}`,
  ];
  $("filmStatus").textContent = lines.join("\n");
}

function buildEvents(limit = 80) {
  const commands = state.commands.filter((item) => item.command !== "speak").map((item) => ({
    title: `INPUT: ${commandLabel(item.command)}`,
    body: item.value || item.command || "-",
    meta: new Date(item.created_at).toLocaleString(),
    time: new Date(item.created_at).getTime(),
  }));
  const logs = state.moveLogs.map((item) => ({
    title: `FSM: ${item.state || "IDLE"} / ${item.action || "STOP"}`,
    body: item.message || "-",
    meta: `목표 ${fmt(item.target_lux, 0)} lux / 현재 ${fmt(item.current_lux, 0)} lux / ${new Date(item.created_at).toLocaleString()}`,
    time: new Date(item.created_at).getTime(),
  }));
  return [...commands, ...logs].sort((a, b) => b.time - a.time).slice(0, limit);
}

function renderLogs() {
  if (!$("filmLogRows")) return;
  const rows = buildEvents(120).map((item) => {
    const time = Number.isFinite(item.time) ? new Date(item.time).toLocaleTimeString() : "--";
    return `[${time}] ${item.title} | ${escapeLog(item.body)} | ${escapeLog(item.meta)}`;
  });
  $("filmLogRows").textContent = rows.join("\n") || "입력 대기 상태입니다.";
}

function renderHeader() {
  const clock = $("filmClock");
  if (clock) clock.textContent = new Date().toLocaleTimeString();
  const obstacle = $("filmObstacle");
  if (obstacle) {
    const points = state.lidar?.points?.length ?? 0;
    obstacle.textContent = `${obstacleState(state.lidar)} / ${points} pts`;
  }
}

async function refresh() {
  try {
    const [summary, lidar, logs, commands] = await Promise.all([
      api(`/api/robots/${encodeURIComponent(robotId)}/summary`),
      api(`/api/robots/${encodeURIComponent(robotId)}/lidar`),
      api(`/api/robots/${encodeURIComponent(robotId)}/move-logs?limit=120`),
      api(`/api/robots/${encodeURIComponent(robotId)}/commands?limit=100`),
    ]);
    state.summary = summary;
    state.lidar = lidar;
    state.moveLogs = Array.isArray(logs) ? logs : [];
    state.commands = Array.isArray(commands) ? commands : [];
  } catch (error) {
    state.lidar = null;
  }

  renderHeader();
  if ($("filmLidarCanvas")) drawLidar($("filmLidarCanvas"), state.lidar);
  if ($("filmStatus")) renderStatus();
  if ($("filmLogRows")) renderLogs();
}

refresh();
setInterval(refresh, 500);
setInterval(renderHeader, 1000);
