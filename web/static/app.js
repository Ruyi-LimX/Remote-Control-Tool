const loginView = document.querySelector("#loginView");
const remoteView = document.querySelector("#remoteView");
const passwordInput = document.querySelector("#passwordInput");
const connectButton = document.querySelector("#connectButton");
const disconnectButton = document.querySelector("#disconnectButton");
const loginStatus = document.querySelector("#loginStatus");
const connectionStatus = document.querySelector("#connectionStatus");
const screenPad = document.querySelector("#screenPad");
const screenImage = document.querySelector("#screenImage");
const directModeButton = document.querySelector("#directModeButton");
const touchpadModeButton = document.querySelector("#touchpadModeButton");
const rightClickButton = document.querySelector("#rightClickButton");
const backspaceButton = document.querySelector("#backspaceButton");
const spaceButton = document.querySelector("#spaceButton");
const imeSwitchButton = document.querySelector("#imeSwitchButton");
const escButton = document.querySelector("#escButton");
const enterButton = document.querySelector("#enterButton");
const textForm = document.querySelector("#textForm");
const textInput = document.querySelector("#textInput");

let token = localStorage.getItem("remoteToken") || "";
let mode = localStorage.getItem("remoteMode") || "direct";
let activePointers = new Map();
let downPoint = null;
let lastSinglePoint = null;
let dragStarted = false;
let longPressFired = false;
let longPressTimer = 0;
let lastMoveSentAt = 0;
let lastScrollY = null;
let screenRunning = false;
let nextFrameTimer = 0;

setMode(mode);
passwordInput.focus();

connectButton.addEventListener("click", connect);
passwordInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") connect();
});
disconnectButton.addEventListener("click", disconnect);
directModeButton.addEventListener("click", () => setMode("direct"));
touchpadModeButton.addEventListener("click", () => setMode("touchpad"));
rightClickButton.addEventListener("click", () => sendControl({ type: "right_click" }));
backspaceButton.addEventListener("click", () => sendControl({ type: "key", key: "backspace" }));
spaceButton.addEventListener("click", () => sendControl({ type: "key", key: "space" }));
imeSwitchButton.addEventListener("click", () => sendControl({ type: "hotkey", keys: ["ctrl", "space"] }));
escButton.addEventListener("click", () => sendControl({ type: "key", key: "esc" }));
enterButton.addEventListener("click", () => sendControl({ type: "key", key: "enter" }));
textForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const value = textInput.value;
  if (!value) return;
  sendControl({ type: "paste_text", value });
  textInput.value = "";
});

screenPad.addEventListener("pointerdown", onPointerDown);
screenPad.addEventListener("pointermove", onPointerMove);
screenPad.addEventListener("pointerup", onPointerUp);
screenPad.addEventListener("pointercancel", onPointerUp);
screenPad.addEventListener("wheel", onWheel, { passive: false });
screenPad.addEventListener("contextmenu", (event) => event.preventDefault());
if (token) {
  showRemote();
}

async function connect() {
  const password = passwordInput.value;
  loginStatus.textContent = "连接中...";
  connectButton.disabled = true;
  try {
    const response = await fetch("/api/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) {
      throw new Error(loginErrorMessage(data.error));
    }
    token = data.token;
    localStorage.setItem("remoteToken", token);
    loginStatus.textContent = "";
    showRemote();
  } catch (error) {
    loginStatus.textContent = error.message || "连接失败";
  } finally {
    connectButton.disabled = false;
  }
}

function loginErrorMessage(error) {
  if (error === "too_many_attempts") return "尝试太多，请稍后再试";
  if (error === "bad_password") return "密码错误";
  return "连接失败";
}

function disconnect() {
  token = "";
  localStorage.removeItem("remoteToken");
  stopScreen();
  screenImage.removeAttribute("src");
  remoteView.hidden = true;
  loginView.hidden = false;
  passwordInput.focus();
}

function showRemote() {
  loginView.hidden = true;
  remoteView.hidden = false;
  connectionStatus.textContent = "正在加载画面...";
  startScreen();
}

function startScreen() {
  stopScreen();
  screenRunning = true;
  screenImage.onload = () => {
    connectionStatus.textContent = "画面已连接";
    scheduleNextFrame(100);
  };
  screenImage.onerror = () => {
    connectionStatus.textContent = "画面连接失败";
    scheduleNextFrame(1000);
  };
  loadNextFrame();
}

function stopScreen() {
  screenRunning = false;
  window.clearTimeout(nextFrameTimer);
  nextFrameTimer = 0;
  screenImage.onload = null;
  screenImage.onerror = null;
}

function scheduleNextFrame(delay) {
  if (!screenRunning) return;
  window.clearTimeout(nextFrameTimer);
  nextFrameTimer = window.setTimeout(loadNextFrame, delay);
}

function loadNextFrame() {
  if (!screenRunning || !token) return;
  screenImage.src = `/frame.jpg?token=${encodeURIComponent(token)}&t=${Date.now()}`;
}

function setMode(nextMode) {
  mode = nextMode === "touchpad" ? "touchpad" : "direct";
  localStorage.setItem("remoteMode", mode);
  directModeButton.classList.toggle("selected", mode === "direct");
  touchpadModeButton.classList.toggle("selected", mode === "touchpad");
}

function onPointerDown(event) {
  event.preventDefault();
  screenPad.setPointerCapture(event.pointerId);
  activePointers.set(event.pointerId, pointFromEvent(event));

  if (activePointers.size >= 2) {
    clearLongPress();
    lastScrollY = averagePoint().y;
    return;
  }

  downPoint = pointFromEvent(event);
  lastSinglePoint = downPoint;
  dragStarted = false;
  longPressFired = false;

  clearLongPress();
  longPressTimer = window.setTimeout(() => {
    if (!downPoint || activePointers.size !== 1 || dragStarted) return;
    longPressFired = true;
    const coord = imageCoord(downPoint);
    if (!coord) return;
    sendControl({ type: "right_click", x: coord.x, y: coord.y });
    if (navigator.vibrate) navigator.vibrate(30);
  }, 600);
}

function onPointerMove(event) {
  event.preventDefault();
  if (!activePointers.has(event.pointerId)) return;
  activePointers.set(event.pointerId, pointFromEvent(event));

  if (activePointers.size >= 2) {
    const current = averagePoint();
    if (lastScrollY !== null) {
      const delta = current.y - lastScrollY;
      if (Math.abs(delta) > 10) {
        sendControl({ type: "scroll", clicks: Math.round(-delta / 18) });
        lastScrollY = current.y;
      }
    }
    return;
  }

  const current = pointFromEvent(event);
  if (!downPoint || !lastSinglePoint) return;

  const distance = Math.hypot(current.x - downPoint.x, current.y - downPoint.y);
  if (distance > 8) {
    clearLongPress();
  }

  if (mode === "direct") {
    const coord = imageCoord(current);
    if (!coord) return;
    if (distance > 8 && !dragStarted) {
      const startCoord = imageCoord(downPoint);
      if (!startCoord) return;
      sendControl({ type: "mouse_down", x: startCoord.x, y: startCoord.y, button: "left" });
      dragStarted = true;
    }
    if (dragStarted || shouldSendMove()) {
      sendControl({ type: "move_abs", x: coord.x, y: coord.y });
    }
  } else {
    const dx = Math.round((current.x - lastSinglePoint.x) * 1.35);
    const dy = Math.round((current.y - lastSinglePoint.y) * 1.35);
    if (dx || dy) {
      sendControl({ type: "move_rel", dx, dy });
    }
  }

  lastSinglePoint = current;
}

function onPointerUp(event) {
  event.preventDefault();
  if (activePointers.has(event.pointerId)) {
    activePointers.delete(event.pointerId);
  }
  clearLongPress();
  lastScrollY = activePointers.size >= 2 ? averagePoint().y : null;

  if (!downPoint) return;
  const upPoint = pointFromEvent(event);
  const distance = Math.hypot(upPoint.x - downPoint.x, upPoint.y - downPoint.y);

  if (dragStarted) {
    const coord = imageCoord(upPoint);
    if (!coord) return;
    sendControl({ type: "mouse_up", x: coord.x, y: coord.y, button: "left" });
  } else if (!longPressFired && distance < 10) {
    const coord = imageCoord(upPoint);
    if (!coord) return;
    sendControl({ type: "click", x: coord.x, y: coord.y, button: "left" });
  }

  if (activePointers.size === 0) {
    downPoint = null;
    lastSinglePoint = null;
    dragStarted = false;
    longPressFired = false;
  }
}

function onWheel(event) {
  event.preventDefault();
  sendControl({ type: "scroll", clicks: Math.round(-event.deltaY / 80) });
}

function pointFromEvent(event) {
  return { x: event.clientX, y: event.clientY };
}

function averagePoint() {
  let x = 0;
  let y = 0;
  for (const point of activePointers.values()) {
    x += point.x;
    y += point.y;
  }
  const count = Math.max(1, activePointers.size);
  return { x: x / count, y: y / count };
}

function imageCoord(point) {
  const rect = screenImage.getBoundingClientRect();
  if (rect.width <= 1 || rect.height <= 1) {
    connectionStatus.textContent = "等待画面";
    return null;
  }
  const x = clamp((point.x - rect.left) / rect.width, 0, 1);
  const y = clamp((point.y - rect.top) / rect.height, 0, 1);
  if (!Number.isFinite(x) || !Number.isFinite(y)) {
    connectionStatus.textContent = "等待画面";
    return null;
  }
  return { x, y };
}

function shouldSendMove() {
  const now = performance.now();
  if (now - lastMoveSentAt < 28) return false;
  lastMoveSentAt = now;
  return true;
}

async function sendControl(payload) {
  if (!token) return false;
  try {
    const response = await fetch("/api/control", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      connectionStatus.textContent = data.error || `控制失败 ${response.status}`;
      return false;
    }
    return true;
  } catch {
    connectionStatus.textContent = "控制连接异常";
    return false;
  }
}

function clearLongPress() {
  if (longPressTimer) {
    window.clearTimeout(longPressTimer);
    longPressTimer = 0;
  }
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}
