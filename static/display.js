const robotId = new URLSearchParams(location.search).get("robot_id") || "raspbot-a";
const screens = new Set(["idle", "sulk", "angry", "sleep", "happy", "listening", "analyzing", "report"]);
let currentScreen = "idle";

function show(screen) {
  const next = screens.has(screen) ? screen : "idle";
  currentScreen = next;
  document.querySelectorAll(".screen").forEach((node) => {
    node.classList.toggle("active", node.dataset.screen === next);
  });
}

async function sendRemote(key) {
  await fetch(`/api/robots/${robotId}/remote`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key }),
  });
  await refresh();
}

function setMetric(id, value, suffix, digits = 0) {
  const node = document.getElementById(id);
  if (!node) return;
  node.textContent = value == null ? `--${suffix}` : `${Number(value).toFixed(digits)}${suffix}`;
}

async function refresh() {
  try {
    const [state, summary] = await Promise.all([
      fetch(`/api/robots/${robotId}/display`).then((response) => response.json()),
      fetch(`/api/robots/${robotId}/summary`).then((response) => response.json()),
    ]);
    show(state.screen || "idle");
    const latest = summary.latest || {};
    const status = summary.status || {};
    setMetric("dTemp", latest.temperature, "°C", 1);
    setMetric("dHum", latest.humidity, "%");
    setMetric("dLux", latest.lux, " lux");
    setMetric("dSoil", latest.soil_moisture, "%");
    document.getElementById("reportTitle").textContent = status.level || "현재 상태";
    document.getElementById("reportMessage").textContent = status.message || "최신 센서 데이터를 확인하고 있습니다.";
    document.getElementById("reportRecommend").textContent = status.recommendation || "현재 환경을 유지하고 주기적으로 확인하세요.";
  } catch {
    show("idle");
  }
}

window.addEventListener("keydown", (event) => {
  if (event.key === "3") sendRemote("3");
});

function blinkActiveFace() {
  if (currentScreen === "sleep" || currentScreen === "report") return;
  const eyes = document.querySelector(".screen.active .eyes");
  if (!eyes) return;
  eyes.classList.remove("blink-now");
  void eyes.offsetWidth;
  eyes.classList.add("blink-now");
  window.setTimeout(() => eyes.classList.remove("blink-now"), 220);
}

refresh();
setInterval(refresh, 1000);
setInterval(blinkActiveFace, 1800);
window.setTimeout(blinkActiveFace, 600);
