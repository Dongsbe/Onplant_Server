const viewRoutes = {
  dashboard: "/dashboard",
  live: "/live",
  history: "/sensors",
  move: "/logs",
  control: "/control",
  board: "/board",
  admin: "/admin",
  kiosk: "/kiosk",
};

const routeViews = Object.fromEntries(Object.entries(viewRoutes).map(([view, route]) => [route, view]));
const requestedView = routeViews[window.location.pathname] || sessionStorage.getItem("onplant_view") || "dashboard";

const state = {
  user: null,
  robotId: null,
  view: requestedView,
  kioskRoute: window.location.pathname === "/kiosk",
  latestSummary: null,
  latestLidar: null,
  latestCommands: [],
  latestMoveLogs: [],
  kioskLogClearedAt: Number(sessionStorage.getItem("onplant_kiosk_log_cleared_at") || 0),
  boardCategory: "전체",
  boardPosts: [],
  loginMode: "login",
  profileAvatarData: "",
  selectedPost: null,
};

const pageText = {
  dashboard: ["메인 대시보드", "식물의 현재 상태를 한눈에 확인합니다."],
  live: ["실시간 화면", "카메라와 LiDAR 실시간 맵을 확인합니다."],
  history: ["센서 기록", "센서 변화 추이를 확인합니다."],
  move: ["실행 로그", "입력 명령과 FSM 상태 변화를 시간순으로 확인합니다."],
  control: ["제어/설정", "로봇과 디스플레이 동작 설정을 저장합니다."],
  board: ["관리 게시판", "목차 목록에서 게시글을 읽어 확인합니다."],
  admin: ["계정/로봇 설정", "관리자 전용 계정 연동 화면입니다."],
  kiosk: ["키오스크", "실행 상태와 LiDAR 맵을 세로 화면에 표시합니다."],
};

const $ = (id) => document.getElementById(id);
const fmt = (value, digits = 1) => value === null || value === undefined ? "--" : Number(value).toFixed(digits);
const isAdmin = () => state.user?.role === "admin";
if (state.kioskRoute) document.body.classList.add("kiosk-route");

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 1600);
}

async function api(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function showApp(user) {
  state.user = user;
  state.robotId = user.robot_id;
  sessionStorage.setItem("onplant_user", JSON.stringify(user));
  $("currentUser").textContent = `${user.display_name} (${user.username})`;
  $("loginScreen").classList.add("hidden");
  $("appRoot").classList.remove("hidden");
  document.querySelectorAll(".admin-only").forEach((node) => node.classList.toggle("hidden", !isAdmin()));
  document.querySelectorAll("#mainNav .nav-item:not(.admin-only)").forEach((node) => node.classList.toggle("hidden", isAdmin()));
  const requested = routeViews[window.location.pathname] || state.view;
  const nextView = isAdmin()
    ? (["admin", "kiosk"].includes(requested) ? requested : "admin")
    : (["admin", "kiosk"].includes(requested) ? "dashboard" : requested);
  setView(nextView, { replace: true });
}

function showLogin() {
  sessionStorage.removeItem("onplant_user");
  sessionStorage.removeItem("onplant_view");
  state.user = null;
  state.robotId = null;
  state.view = "dashboard";
  document.body.classList.remove("kiosk-fullscreen");
  document.querySelectorAll(".view").forEach((section) => section.classList.remove("active"));
  $("view-dashboard")?.classList.add("active");
  $("appRoot").classList.add("hidden");
  $("loginScreen").classList.remove("hidden");
  window.history.replaceState({}, "", "/");
}

function setLoginMode(mode) {
  state.loginMode = mode;
  $("loginTab").classList.toggle("active", mode === "login");
  $("registerTab").classList.toggle("active", mode === "register");
  document.querySelectorAll(".register-only").forEach((node) => node.classList.toggle("hidden", mode !== "register"));
  $("loginSubmit").textContent = mode === "login" ? "로그인" : "회원가입";
}

async function submitLogin() {
  const username = $("loginUsername").value.trim();
  const password = $("loginPassword").value;
  if (!username || !password) return showToast("아이디와 비밀번호를 입력하세요.");
  const endpoint = state.loginMode === "login" ? "/api/auth/login" : "/api/auth/register";
  const payload = state.loginMode === "login"
    ? { username, password }
    : {
        username,
        password,
        display_name: $("displayName").value.trim() || "사용자",
        plant_name: $("registerPlantName").value.trim() || "토로예",
      };
  try {
    const user = await api(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    showApp(user);
    await refreshAll();
  } catch {
    showToast(state.loginMode === "login" ? "로그인 정보를 확인하세요." : "이미 있는 아이디일 수 있습니다.");
  }
}

function setView(view, options = {}) {
  if (view === "kiosk" && !isAdmin()) view = "dashboard";
  if (isAdmin() && !["admin", "kiosk"].includes(view)) view = "admin";
  state.view = view;
  const route = viewRoutes[view] || "/dashboard";
  if (options.updateUrl !== false && window.location.pathname !== route) {
    window.history[options.replace ? "replaceState" : "pushState"]({}, "", route);
  }
  state.kioskRoute = route === "/kiosk";
  document.body.classList.toggle("kiosk-route", state.kioskRoute);
  if (view !== "kiosk") document.body.classList.remove("kiosk-fullscreen");
  syncFullscreenLayout();
  sessionStorage.setItem("onplant_view", view);
  document.querySelectorAll(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  document.querySelectorAll(".view").forEach((section) => section.classList.toggle("active", section.id === `view-${view}`));
  $("pageTitle").textContent = pageText[view]?.[0] || "OnPlant";
  $("pageSub").textContent = pageText[view]?.[1] || "";
  refreshAll();
}

function setConnectionState(online, lastSeen = null) {
  const pill = $("connectionPill");
  if (!pill) return;
  pill.textContent = online ? "온라인" : "오프라인";
  pill.className = `connection-pill ${online ? "online" : "offline"}`;
  pill.title = lastSeen ? `마지막 수신: ${new Date(lastSeen).toLocaleString()}` : "수신 기록 없음";
}

async function refreshSummary() {
  if (!state.robotId) return;
  let summary;
  try {
    summary = await api(`/api/robots/${encodeURIComponent(state.robotId)}/summary`);
  } catch (error) {
    setConnectionState(false);
    throw error;
  }
  state.latestSummary = summary;
  const { latest, status, config, robot } = summary;
  const online = Boolean(summary.connection?.online);
  setConnectionState(online, summary.connection?.last_seen || robot.last_seen);
  $("plantName").textContent = robot.plant_name;
  $("robotName").textContent = `${robot.name} / ${robot.link_code || "연동 코드 없음"}`;
  renderPlantAvatar(robot.plant_avatar);
  $("statusPill").textContent = online ? status.level : "오프라인";
  $("statusPill").className = `status-pill ${online ? status.tone : "offline"}`;
  $("statusPill").classList.remove("hidden");
  $("statusEmoji").textContent = status.emoji;
  $("statusLevel").textContent = online ? status.level : "오프라인";
  $("statusMessage").textContent = online ? status.message : "라즈봇에서 최근 센서 데이터가 들어오지 않았습니다.";
  $("recommendation").textContent = online ? status.recommendation : "라즈봇 전원과 네트워크 연결 상태를 확인하세요.";
  $("temperature").textContent = latest ? fmt(latest.temperature) : "--";
  $("humidity").textContent = latest ? fmt(latest.humidity) : "--";
  $("lux").textContent = latest ? fmt(latest.lux, 0) : "--";
  $("soil").textContent = latest ? fmt(latest.soil_moisture) : "--";

  const profile = summary.plant_profile || {};
  $("plantSpecies").textContent = profile.species || "하월시아";
  $("dailyLuxRange").textContent = profile.daily_lux_range || `${config.daily_lux_min ?? 300}~${config.daily_lux_max ?? 800} lux`;
  $("luxTarget").textContent = profile.lux_range || `${config.search_lux_min ?? 800}~${config.search_lux_max ?? 900} lux`;
  $("tempRange").textContent = profile.temperature_range || "18~28°C";
  $("humidityRange").textContent = profile.humidity_range || "35~60%";
  $("soilRange").textContent = profile.soil_moisture_range || "20~45%";
  $("plantNote").textContent = profile.note || "";
  $("plantNote").classList.toggle("hidden", !profile.note);

  $("speakerVolume").value = config.speaker_volume;
  $("speakerVolumeValue").textContent = `${config.speaker_volume}%`;
  $("displayBrightness").value = config.display_brightness;
  $("displayBrightnessValue").textContent = `${config.display_brightness}%`;
  $("defaultRegion").value = config.default_region || "진주";
  $("adminExploreSeconds").value = config.explore_seconds;
  $("adminDailyLuxMin").value = config.daily_lux_min ?? 300;
  $("adminDailyLuxMax").value = config.daily_lux_max ?? 800;
  $("adminSearchLuxMin").value = config.search_lux_min ?? 800;
  $("adminSearchLuxMax").value = config.search_lux_max ?? 900;
  $("adminExcessLux").value = config.excess_lux ?? 1100;
  renderCamera(summary.display?.camera_visible);
  renderKiosk();
}

function renderPlantAvatar(avatar) {
  [$("plantAvatar"), $("profilePreview")].forEach((node) => {
    if (!node) return;
    if (avatar) {
      node.style.backgroundImage = `url("${avatar}")`;
      node.classList.add("has-image");
    } else {
      node.style.backgroundImage = "";
      node.classList.remove("has-image");
    }
  });
}

function renderCamera(visible) {
  $("cameraState").textContent = visible ? "카메라 표시 중" : "카메라 대기";
  $("videoBox").classList.toggle("camera-on", Boolean(visible));
  $("cameraText").textContent = visible
    ? "카메라 화면 표시 상태입니다. 실제 스트림은 로봇 연동 시 자동 연결됩니다."
    : "카메라 스트리밍은 로봇 카메라 연결 후 표시됩니다.";
}

async function refreshHistory() {
  if (state.view !== "history") return;
  const rows = await api(`/api/robots/${encodeURIComponent(state.robotId)}/history?limit=80`);
  drawChart(rows);
  $("historyRows").innerHTML = rows.slice().reverse().map((item, index) => (
    `<tr><td>${rows.length - index}</td><td>${new Date(item.received_at).toLocaleString()}</td><td>${fmt(item.lux)}</td><td>${fmt(item.temperature)}</td><td>${fmt(item.humidity)}</td><td>${fmt(item.soil_moisture)}</td></tr>`
  )).join("");
}

function drawChart(rows) {
  const canvas = $("historyChart");
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const pad = 32;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#dbe5dc";
  ctx.lineWidth = 1;
  for (let i = 0; i < 4; i += 1) {
    const y = pad + ((height - pad * 2) * i / 3);
    ctx.beginPath();
    ctx.moveTo(pad, y);
    ctx.lineTo(width - pad, y);
    ctx.stroke();
  }
  const points = rows.filter((row) => row.lux !== null && row.lux !== undefined);
  if (points.length < 2) return;
  const values = points.map((row) => Number(row.lux));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(1, max - min);
  ctx.strokeStyle = "#197236";
  ctx.lineWidth = 3;
  ctx.beginPath();
  points.forEach((row, index) => {
    const x = pad + ((width - pad * 2) * index / Math.max(1, points.length - 1));
    const y = height - pad - ((Number(row.lux) - min) / range) * (height - pad * 2);
    if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function drawLidarOnCanvas(canvas, frame) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const cx = width / 2;
  const robotY = height - 44;
  const scale = Math.min((width - 80) / 1200, (height - 86) / 900);
  const points = frame?.points || [];
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fbfdfb";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#dbe5dc";
  ctx.lineWidth = 1;
  ctx.font = "12px Arial";
  ctx.fillStyle = "#69736d";
  for (let x = 100; x <= 900; x += 100) {
    const sy = robotY - x * scale;
    ctx.beginPath();
    ctx.moveTo(32, sy);
    ctx.lineTo(width - 32, sy);
    ctx.stroke();
    if (x % 200 === 0) ctx.fillText(`${x}mm`, 38, sy - 4);
  }
  for (let y = -500; y <= 500; y += 100) {
    const sx = cx - y * scale;
    ctx.beginPath();
    ctx.moveTo(sx, 24);
    ctx.lineTo(sx, robotY + 20);
    ctx.stroke();
  }
  if (frame?.front_blocked || frame?.danger || frame?.emergency) {
    ctx.fillStyle = frame.emergency ? "rgba(189,71,71,.20)" : "rgba(242,164,0,.16)";
    ctx.fillRect(cx - 105 * scale, 28, 210 * scale, robotY - 28);
  }
  ctx.strokeStyle = "#197236";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(cx, robotY - 42);
  ctx.lineTo(cx - 42, robotY + 22);
  ctx.lineTo(cx + 42, robotY + 22);
  ctx.closePath();
  ctx.stroke();
  ctx.fillStyle = "rgba(25,114,54,.10)";
  ctx.fill();
  ctx.fillStyle = "#197236";
  ctx.fillText("ROBOT", cx - 22, robotY + 38);
  for (const point of points) {
    const sx = cx - Number(point.y) * scale;
    const sy = robotY - Number(point.x) * scale;
    if (sx < 0 || sx > width || sy < 0 || sy > height) continue;
    ctx.beginPath();
    ctx.arc(sx, sy, point.ignored ? 2 : 3, 0, Math.PI * 2);
    ctx.fillStyle = point.ignored ? "rgba(105,115,109,.35)" : "#2d9cdb";
    ctx.fill();
  }
}

function drawLidar(frame) {
  drawLidarOnCanvas($("lidarCanvas"), frame);
}

function drawKioskLidar(frame) {
  drawLidarOnCanvas($("kioskLidarCanvas"), frame);
}

function phaseName(frame) {
  if (!frame) return "WAIT";
  if (frame.state === "EXPLORE") return "조도 탐색(1차)";
  if (frame.state === "RETURN_TO_BEST") return "복귀 이동";
  if (frame.state === "SEEK_LIGHT") return "추가 탐색(2차)";
  if (frame.state === "AVOID") return "장애물 회피";
  if (frame.state === "BACKUP") return "후진 탈출";
  if (frame.state === "IDLE") return "대기";
  return frame.state || "WAIT";
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

function renderLidarPhase(frame) {
  const phaseLabel = $("phaseLabel");
  if (!phaseLabel) return;
  if (!frame) {
    phaseLabel.textContent = "WAIT";
    $("phaseBest").textContent = "--";
    $("phaseLux").textContent = "--";
    $("phaseReturn").textContent = "--";
    $("phaseSeek").textContent = "--";
    return;
  }
  const bestLux = frame.best_lux ?? null;
  const currentLux = frame.current_lux ?? null;
  const err = frame.lux_error ?? null;
  phaseLabel.textContent = `${phaseName(frame)} / ${frame.action || "STOP"}`;
  $("phaseBest").textContent = bestLux === null ? "--" : `best ${fmt(bestLux, 0)} lx @ ${fmt(frame.best_time, 1)}s`;
  $("phaseLux").textContent = currentLux === null ? "--" : `now ${fmt(currentLux, 0)} lx / err ${fmt(err, 0)} lx`;
  $("phaseReturn").textContent = frame.state === "RETURN_TO_BEST"
    ? `${frame.return_index || 0}/${frame.return_total || 0} / ${fmt(frame.return_elapsed, 1)}s / avoid ${frame.return_avoid_count || 0} / pos(${fmt(frame.pose_x, 1)},${fmt(frame.pose_y, 1)}) -> best(${fmt(frame.best_x, 1)},${fmt(frame.best_y, 1)}) ${frame.heading || ""} blocked ${frame.blocked_count || 0}`
    : "--";
  $("phaseSeek").textContent = frame.state === "SEEK_LIGHT" ? `${fmt(frame.seek_elapsed, 1)}/${fmt(frame.seek_seconds, 1)}s` : "--";
}

async function refreshLidar() {
  if (!state.robotId || !["live", "kiosk"].includes(state.view)) return;
  try {
    const frame = await api(`/api/robots/${encodeURIComponent(state.robotId)}/lidar`);
    state.latestLidar = frame;
    if (!frame) {
      if ($("lidarState")) $("lidarState").textContent = "WAIT";
      if ($("lidarUpdated")) $("lidarUpdated").textContent = "--";
      renderLidarPhase(null);
      drawLidar(null);
      drawKioskLidar(null);
      renderKiosk();
      return;
    }
    const flags = frame.emergency ? "EMERGENCY" : frame.danger ? "DANGER" : frame.front_blocked ? "BLOCKED" : "CLEAR";
    if ($("lidarState")) $("lidarState").textContent = `${frame.state} / ${frame.action} / ${flags} / ${frame.points.length}pts`;
    if ($("lidarUpdated")) $("lidarUpdated").textContent = new Date(frame.received_at).toLocaleTimeString();
    renderLidarPhase(frame);
    drawLidar(frame);
    drawKioskLidar(frame);
    renderKiosk();
  } catch {
    if ($("lidarState")) $("lidarState").textContent = "OFFLINE";
    if ($("lidarUpdated")) $("lidarUpdated").textContent = "--";
    renderLidarPhase(null);
  }
}

function commandLabel(command) {
  if (command === "start_light_search") return "최적 조도 탐색";
  if (command === "stop") return "정지";
  if (command === "speak") return "음성 응답";
  if (String(command || "").startsWith("remote-")) return "리모컨 입력";
  return command || "명령";
}

function buildExecutionEvents(limit = 80) {
  const commands = (state.latestCommands || []).filter((item) => item.command !== "speak").map((item) => ({
    kind: "input",
    title: `INPUT: ${commandLabel(item.command)}`,
    body: item.value || item.command || "-",
    meta: new Date(item.created_at).toLocaleString(),
    time: new Date(item.created_at).getTime(),
  }));
  const logs = (state.latestMoveLogs || []).map((item) => ({
    kind: "fsm",
    title: `FSM: ${item.state || "IDLE"} / ${item.action || "STOP"}`,
    body: item.message || "-",
    meta: `목표 ${fmt(item.target_lux, 0)} lux / 현재 ${fmt(item.current_lux, 0)} lux / ${new Date(item.created_at).toLocaleString()}`,
    time: new Date(item.created_at).getTime(),
  }));
  return [...commands, ...logs].sort((a, b) => b.time - a.time).slice(0, limit);
}

async function refreshMoveLogs() {
  if (!["move", "kiosk"].includes(state.view)) return;
  const [logs, commands] = await Promise.all([
    api(`/api/robots/${encodeURIComponent(state.robotId)}/move-logs?limit=100`),
    api(`/api/robots/${encodeURIComponent(state.robotId)}/commands?limit=80`),
  ]);
  state.latestMoveLogs = logs;
  state.latestCommands = commands;
  const events = buildExecutionEvents(100);
  if ($("moveRows")) {
    $("moveRows").innerHTML = events.map((item) => (
      `<div class="log-item ${item.kind}"><strong>${escapeHtml(item.title)}</strong><div>${escapeHtml(item.body)}</div><div class="meta">${escapeHtml(item.meta)}</div></div>`
    )).join("") || `<div class="muted">실행 로그가 없습니다.</div>`;
  }
  renderKiosk();
}

async function refreshCommands() {
  if (!["admin", "kiosk"].includes(state.view)) return;
  const commands = await api(`/api/robots/${encodeURIComponent(state.robotId)}/commands?limit=30`);
  state.latestCommands = commands;
  if (state.view === "kiosk") {
    renderKiosk();
    return;
  }
  $("commandRows").innerHTML = commands.filter((item) => item.command !== "speak").slice().reverse().map((item) => (
    `<div class="log-item"><strong>${escapeHtml(item.command)}</strong><div>값: ${escapeHtml(item.value ?? "-")}</div><div class="meta">${new Date(item.created_at).toLocaleString()}</div></div>`
  )).join("") || `<div class="muted">등록된 명령이 없습니다.</div>`;
}

function renderKiosk() {
  if (!$("kioskLogRows") || !$("kioskStatusRows")) return;
  const frame = state.latestLidar;
  const summary = state.latestSummary;
  const visibleCommands = (state.latestCommands || []).filter((item) => {
    const time = new Date(item.created_at).getTime();
    return Number.isFinite(time) && time >= state.kioskLogClearedAt && item.command !== "speak";
  });
  const latestCommand = visibleCommands[visibleCommands.length - 1];
  const obstacleState = frame?.emergency ? "emergency" : frame?.danger ? "danger" : frame?.front_blocked ? "front_blocked" : "clear";
  const currentLux = frame?.current_lux !== undefined && frame?.current_lux !== null
    ? `${fmt(frame.current_lux, 0)} lx`
    : summary?.latest ? `${fmt(summary.latest.lux, 0)} lx` : "--";
  const config = summary?.config || {};
  const profile = summary?.plant_profile || {};
  const targetLux = profile.lux_range || `${config.search_lux_min ?? 800}~${config.search_lux_max ?? 900} lux`;
  const bestLux = frame?.best_lux !== undefined && frame?.best_lux !== null ? `${fmt(frame.best_lux, 0)} lx` : "--";
  const pose = frame?.pose_x !== undefined && frame?.pose_x !== null && frame?.pose_y !== undefined && frame?.pose_y !== null
    ? `(${fmt(frame.pose_x, 0)}, ${fmt(frame.pose_y, 0)})`
    : "--";
  const bestCoord = frame?.best_x !== undefined && frame?.best_x !== null && frame?.best_y !== undefined && frame?.best_y !== null
    ? `(${fmt(frame.best_x, 0)}, ${fmt(frame.best_y, 0)})`
    : "--";
  const recentInput = latestCommand ? `${commandLabel(latestCommand.command)}${latestCommand.value ? ` / ${latestCommand.value}` : ""}` : "대기 중";
  $("kioskObstacle").textContent = `${obstacleState}${frame?.points ? ` / ${frame.points.length} pts` : ""}`;
  $("kioskUpdated").textContent = frame?.received_at ? new Date(frame.received_at).toLocaleTimeString() : "대기";
  const headerLines = [
    `현재 상태: ${frame?.state || "IDLE"}`,
    `최근 입력: ${recentInput}`,
    `현재 동작: ${frame?.action || "STOP"}`,
    `현재 조도: ${currentLux}`,
    `목표 조도: ${targetLux}`,
    `최고 조도: ${bestLux}`,
    `현재 좌표: ${pose}`,
    `목표 좌표: ${bestCoord}`,
    `실행 상태: ${phaseName(frame)}`,
    `남은 시간: ${phaseRemaining(frame, config)}`,
    `장애물 상태: ${obstacleState}`,
  ];
  const events = buildExecutionEvents(120).filter((item) => {
    return Number.isFinite(item.time) && item.time >= state.kioskLogClearedAt;
  }).map((item) => {
    const time = Number.isFinite(item.time) ? new Date(item.time).toLocaleTimeString() : "--";
    return `[${time}] ${item.title} | ${item.body} | ${item.meta}`;
  });
  $("kioskStatusRows").textContent = headerLines.join("\n");
  $("kioskLogRows").textContent = events.join("\n") || "입력 대기 상태입니다.";
}

async function refreshBoard() {
  if (state.view !== "board") return;
  const url = state.boardCategory === "전체" ? "/api/board" : `/api/board?category=${encodeURIComponent(state.boardCategory)}`;
  const posts = await api(url);
  state.boardPosts = posts;
  $("posts").innerHTML = posts.map((post) => (
    `<article class="post post-card compact" data-post-id="${post.id}" tabindex="0"><div class="post-title">${escapeHtml(post.title)}</div><div class="meta">${escapeHtml(post.category)} / ${escapeHtml(post.author)} / ${new Date(post.created_at).toLocaleDateString()}</div></article>`
  )).join("") || `<div class="muted">게시글이 없습니다.</div>`;
  document.querySelectorAll(".post-card").forEach((card) => {
    card.addEventListener("click", () => openPostDetail(Number(card.dataset.postId)));
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openPostDetail(Number(card.dataset.postId));
      }
    });
  });
}

function canEdit(post) {
  return isAdmin() || post.author_username === state.user?.username || post.author === state.user?.display_name;
}

function openPostEditor(post = null) {
  $("postEditor").classList.remove("hidden");
  $("postDetail").classList.add("hidden");
  $("boardList").classList.add("hidden");
  $("postEditorTitle").textContent = post ? "게시글 수정" : "글쓰기";
  $("editingPostId").value = post?.id || "";
  $("postCategory").value = post?.category || (state.boardCategory === "자유게시판" ? "자유게시판" : "공지");
  $("postTitle").value = post?.title || "";
  $("postBody").value = post?.body || "";
}

function closePostEditor() {
  $("postEditor").classList.add("hidden");
  $("boardList").classList.remove("hidden");
}

function closePostDetail() {
  $("postDetail").classList.add("hidden");
  $("boardList").classList.remove("hidden");
}

function openPostDetail(postId) {
  const post = state.boardPosts.find((item) => item.id === postId);
  if (!post) return;
  state.selectedPost = post;
  $("boardList").classList.add("hidden");
  $("postEditor").classList.add("hidden");
  $("postDetail").classList.remove("hidden");
  $("postDetailTitle").textContent = post.title;
  $("postDetailMeta").textContent = `${post.category} · ${post.author} · ${new Date(post.created_at).toLocaleString()}${post.updated_at ? " · 수정됨" : ""}`;
  $("postDetailBody").textContent = post.body;
  $("postEditButton").classList.toggle("hidden", !canEdit(post));
  $("postDeleteButton").classList.toggle("hidden", !(isAdmin() || canEdit(post)));
}

async function savePost() {
  const id = $("editingPostId").value;
  const title = $("postTitle").value.trim();
  const body = $("postBody").value.trim();
  const category = $("postCategory").value;
  if (!title || !body) return showToast("제목과 내용을 입력하세요.");
  const payload = { category, title, body, author: state.user?.display_name || "관리자", author_username: state.user?.username || "admin" };
  const url = id ? `/api/board/${id}` : "/api/board";
  await api(url, { method: id ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  showToast(id ? "게시글을 수정했습니다." : "게시글을 등록했습니다.");
  closePostEditor();
  await refreshBoard();
}

async function deletePost() {
  if (!state.selectedPost) return;
  await api(`/api/board/${state.selectedPost.id}`, { method: "DELETE" });
  showToast("게시글을 삭제했습니다.");
  closePostDetail();
  await refreshBoard();
}

async function saveConfig() {
  const previous = state.latestSummary?.config || {};
  const payload = {
    speaker_volume: Number($("speakerVolume").value),
    display_brightness: Number($("displayBrightness").value),
    display_text: previous.display_text || "OnPlant",
    drive_enabled: previous.drive_enabled ?? false,
    explore_seconds: previous.explore_seconds ?? 50,
    lidar_speed: previous.lidar_speed ?? 45,
    default_region: $("defaultRegion").value.trim() || "진주",
    daily_lux_min: previous.daily_lux_min ?? 300,
    daily_lux_max: previous.daily_lux_max ?? 800,
    search_lux_min: previous.search_lux_min ?? 800,
    search_lux_max: previous.search_lux_max ?? 900,
    excess_lux: previous.excess_lux ?? 1100,
    camera_enabled: true,
    camera_url: previous.camera_url || "",
  };
  await api(`/api/robots/${encodeURIComponent(state.robotId)}/config`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  showToast("설정을 저장했습니다.");
  await refreshAll();
}

async function saveAdminConfig() {
  if (!isAdmin()) return showToast("관리자만 탐색 설정을 변경할 수 있습니다.");
  const previous = state.latestSummary?.config || {};
  const dailyMin = Number($("adminDailyLuxMin").value);
  const dailyMax = Number($("adminDailyLuxMax").value);
  const searchMin = Number($("adminSearchLuxMin").value);
  const searchMax = Number($("adminSearchLuxMax").value);
  const excessLux = Number($("adminExcessLux").value);
  if (dailyMin > dailyMax || searchMin > searchMax || excessLux < searchMax) {
    return showToast("조도 최소·최대·과다 기준의 순서를 확인하세요.");
  }
  const payload = {
    ...previous,
    explore_seconds: Number($("adminExploreSeconds").value),
    daily_lux_min: dailyMin,
    daily_lux_max: dailyMax,
    search_lux_min: searchMin,
    search_lux_max: searchMax,
    excess_lux: excessLux,
  };
  await api(`/api/robots/${encodeURIComponent(state.robotId)}/config`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  showToast("탐색 설정을 저장했습니다.");
  await refreshAll();
}

async function sendRemote(key) {
  const display = await api(`/api/robots/${encodeURIComponent(state.robotId)}/remote`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key }),
  });
  renderCamera(display.camera_visible);
  showToast(key === "3" ? "상태 리포트를 표시합니다." : "카메라 표시 상태를 변경했습니다.");
  await refreshCommands();
}

async function sendRobotCommand(command, value) {
  if (!state.robotId) return showToast("연동된 로봇이 없습니다.");
  if (!isAdmin()) return showToast("관리자만 웹에서 주행 명령을 보낼 수 있습니다.");
  await api(`/api/robots/${encodeURIComponent(state.robotId)}/commands`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, value, username: state.user?.username || "demo" }),
  });
  showToast(command === "stop" ? "정지 명령을 보냈습니다." : "최적 조도 탐색 명령을 보냈습니다.");
  await refreshCommands();
}

async function sendChatCommand() {
  if (!isAdmin()) return showToast("관리자만 웹에서 명령과 대화를 전송할 수 있습니다.");
  const input = $("chatCommandInput");
  const message = input.value.trim();
  if (!message) return showToast("명령이나 질문을 입력하세요.");
  const replyBox = $("chatReply");
  replyBox.classList.remove("hidden");
  replyBox.textContent = "전송 중...";
  try {
    const result = await api(`/api/robots/${encodeURIComponent(state.robotId)}/llm/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ message, username: state.user?.username || "demo", speak: true }),
    });
    replyBox.textContent = result.reply ? "로봇 스피커로 응답을 보냈습니다." : "명령을 처리했습니다.";
    input.value = "";
    await refreshCommands();
    await refreshSummary();
  } catch (error) {
    replyBox.textContent = "응답을 가져오지 못했습니다.";
    showToast("텍스트 명령 전송 실패");
    console.error(error);
  }
}

document.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  if (target.id === "startLightSearch") {
    event.preventDefault();
    try {
      await sendRobotCommand("start_light_search", "web-start");
    } catch (error) {
      showToast("탐색 명령 전송 실패");
      console.error(error);
    }
  }
  if (target.id === "stopRobot") {
    event.preventDefault();
    try {
      await sendRobotCommand("stop", "web-stop");
    } catch (error) {
      showToast("정지 명령 전송 실패");
      console.error(error);
    }
  }
});

function openProfileModal() {
  const robot = state.latestSummary?.robot;
  state.profileAvatarData = robot?.plant_avatar || "";
  $("profilePlantName").value = robot?.plant_name || "";
  $("profileImage").value = "";
  renderPlantAvatar(state.profileAvatarData);
  $("profileModal").classList.remove("hidden");
}

function closeProfileModal() {
  $("profileModal").classList.add("hidden");
}

async function enterFullscreen() {
  const root = document.documentElement;
  try {
    if (document.fullscreenElement) {
      await document.exitFullscreen();
      syncFullscreenLayout();
      return;
    }
    if (!root.requestFullscreen) {
      showToast("이 브라우저는 전체화면 전환을 지원하지 않습니다.");
      return;
    }
    await root.requestFullscreen();
    syncFullscreenLayout();
  } catch (error) {
    showToast("전체화면 전환은 버튼을 직접 눌렀을 때만 가능합니다.");
    console.error(error);
  }
}

function syncFullscreenLayout() {
  const active = Boolean(document.fullscreenElement && state.view === "kiosk");
  document.body.classList.toggle("kiosk-fullscreen", active);
  const button = $("enterFullscreen");
  if (button) button.textContent = document.fullscreenElement ? "전체화면 해제" : "전체화면";
}

async function clearKioskLog() {
  if (!state.robotId) return;
  try {
    await api(`/api/robots/${encodeURIComponent(state.robotId)}/activity`, { method: "DELETE" });
    state.latestCommands = [];
    state.latestMoveLogs = [];
    state.kioskLogClearedAt = Date.now();
    sessionStorage.setItem("onplant_kiosk_log_cleared_at", String(state.kioskLogClearedAt));
    renderKiosk();
    showToast("실행 로그를 초기화했습니다.");
  } catch (error) {
    showToast("실행 로그 초기화에 실패했습니다.");
    console.error(error);
  }
}

function openKioskMode() {
  window.location.href = "/kiosk";
}

async function saveProfile() {
  const next = $("profilePlantName").value.trim();
  if (!next) return showToast("식물 이름을 입력하세요.");
  try {
    await api(`/api/robots/${encodeURIComponent(state.robotId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plant_name: next, plant_avatar: state.profileAvatarData }),
    });
    closeProfileModal();
    showToast("프로필을 저장했습니다.");
    await refreshAll();
  } catch (error) {
    showToast(error.message || "프로필 저장에 실패했습니다.");
  }
}

function readProfileImage(file) {
  if (!file) return;
  if (!file.type.startsWith("image/")) return showToast("이미지 파일을 선택하세요.");
  const reader = new FileReader();
  reader.onerror = () => showToast("이미지를 읽지 못했습니다.");
  reader.onload = () => {
    const image = new Image();
    image.onerror = () => showToast("이미지를 불러오지 못했습니다.");
    image.onload = () => {
      const maxSize = 360;
      const ratio = Math.min(1, maxSize / Math.max(image.width, image.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(image.width * ratio));
      canvas.height = Math.max(1, Math.round(image.height * ratio));
      const context = canvas.getContext("2d");
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      state.profileAvatarData = canvas.toDataURL("image/jpeg", 0.82);
      renderPlantAvatar(state.profileAvatarData);
      showToast("사진을 첨부했습니다.");
    };
    image.src = String(reader.result);
  };
  reader.readAsDataURL(file);
}

async function clearHistory() {
  await api(`/api/robots/${encodeURIComponent(state.robotId)}/history`, { method: "DELETE" });
  showToast("센서 기록을 삭제했습니다.");
  await refreshAll();
}

async function refreshAdmin() {
  if (!isAdmin() || state.view !== "admin") return;
  const users = await api("/api/admin/users");
  $("adminUsers").innerHTML = users.map((user) => (
    `<div class="log-item"><strong>${escapeHtml(user.username)} / ${escapeHtml(user.role)}</strong><div>${escapeHtml(user.display_name)} / ${escapeHtml(user.robot_id)}</div></div>`
  )).join("");
}

async function linkRobot() {
  const payload = { username: $("linkUsername").value.trim(), link_code: $("linkCode").value.trim(), robot_id: $("linkRobotId").value.trim() };
  await api("/api/admin/link-robot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  showToast("로봇 연동을 변경했습니다.");
  await refreshAdmin();
}

async function refreshAll() {
  await refreshSummary();
  await refreshLidar();
  await refreshHistory();
  await refreshMoveLogs();
  await refreshCommands();
  await refreshBoard();
  await refreshAdmin();
}

function bindEvents() {
  $("loginTab").addEventListener("click", () => setLoginMode("login"));
  $("registerTab").addEventListener("click", () => setLoginMode("register"));
  $("loginSubmit").addEventListener("click", submitLogin);
  $("logoutButton").addEventListener("click", showLogin);
  document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
  document.querySelectorAll(".category").forEach((button) => button.addEventListener("click", async () => {
    state.boardCategory = button.dataset.category;
    document.querySelectorAll(".category").forEach((item) => item.classList.toggle("active", item === button));
    closePostDetail();
    closePostEditor();
    await refreshBoard();
  }));
  $("saveConfig").addEventListener("click", saveConfig);
  $("saveAdminConfig").addEventListener("click", saveAdminConfig);
  $("sendChatCommand").addEventListener("click", sendChatCommand);
  $("chatCommandInput").addEventListener("keydown", (event) => { if (event.key === "Enter") sendChatCommand(); });
  document.querySelectorAll("[data-remote]").forEach((button) => button.addEventListener("click", () => sendRemote(button.dataset.remote)));
  $("editPlantName").addEventListener("click", openProfileModal);
  $("profileCancel").addEventListener("click", closeProfileModal);
  $("profileSave").addEventListener("click", saveProfile);
  $("profileImage").addEventListener("change", (event) => readProfileImage(event.target.files?.[0]));
  $("profileImageClear").addEventListener("click", () => {
    state.profileAvatarData = "";
    $("profileImage").value = "";
    renderPlantAvatar("");
  });
  $("newPostButton").addEventListener("click", () => openPostEditor());
  $("postSubmit").addEventListener("click", savePost);
  $("postCancel").addEventListener("click", closePostEditor);
  $("postDetailClose").addEventListener("click", closePostDetail);
  $("postEditButton").addEventListener("click", () => openPostEditor(state.selectedPost));
  $("postDeleteButton").addEventListener("click", deletePost);
  $("clearHistory").addEventListener("click", clearHistory);
  $("linkRobotButton").addEventListener("click", linkRobot);
  $("openKioskMode")?.addEventListener("click", openKioskMode);
  $("enterFullscreen")?.addEventListener("click", enterFullscreen);
  $("clearKioskLog")?.addEventListener("click", clearKioskLog);
  $("speakerVolume").addEventListener("input", (event) => { $("speakerVolumeValue").textContent = `${event.target.value}%`; });
  $("displayBrightness").addEventListener("input", (event) => { $("displayBrightnessValue").textContent = `${event.target.value}%`; });
  document.addEventListener("fullscreenchange", syncFullscreenLayout);
  window.addEventListener("popstate", () => {
    const view = routeViews[window.location.pathname] || "dashboard";
    setView(view, { updateUrl: false });
  });
}

bindEvents();
const savedUser = sessionStorage.getItem("onplant_user");
if (savedUser) {
  showApp(JSON.parse(savedUser));
  refreshAll();
}
setInterval(() => refreshSummary().catch(() => {}), 3000);
setInterval(() => refreshLidar().catch(() => {}), 700);
setInterval(() => refreshMoveLogs().catch(() => {}), 1000);
setInterval(() => refreshCommands().catch(() => {}), 1500);
