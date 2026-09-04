const { app, BrowserWindow, session, shell, dialog, Menu, Tray, ipcMain, nativeImage } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const http = require("http");
const net = require("net");
const fs = require("fs");

let PORT = 0; // 启动时动态挑选空闲端口，杜绝「端口被占 → 后端 exit code 3」
let backendProc = null;
let win = null;
let tray = null;
let logStream = null;
const recentLog = []; // 后端最近输出，崩溃弹窗里直接给出，不用翻日志

const isDev = !app.isPackaged;

function resDir() {
  // 打包后 kb/frontend/.env.example 在 resources/app-res；开发时用仓库根目录
  return isDev ? path.join(__dirname, "..") : path.join(process.resourcesPath, "app-res");
}
function dataDir() {
  return isDev ? path.join(__dirname, "..") : app.getPath("userData");
}
function logPath() {
  return path.join(dataDir(), "backend.log");
}

function appendLog(chunk) {
  const line = String(chunk).trim();
  if (!line) return;
  recentLog.push(line);
  while (recentLog.length > 20) recentLog.shift();
  try { logStream?.write(line + "\n"); } catch {}
}

// 找一个系统分配的空闲端口
function pickFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.once("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
  });
}

function startBackend() {
  if (!isDev) {
    // 清掉升级/崩溃后残留的旧后端进程
    try {
      require("child_process").execSync("taskkill /IM interview-coach-backend.exe /F", {
        stdio: "ignore",
      });
    } catch {}
  }
  try {
    logStream = fs.createWriteStream(logPath(), { flags: "w" });
  } catch {}
  const env = {
    ...process.env,
    IC_PORT: String(PORT),
    IC_RES_DIR: resDir(),
    IC_DATA_DIR: dataDir(),
  };
  if (isDev) {
    backendProc = spawn("python", ["run_backend.py"], { cwd: path.join(__dirname, ".."), env });
  } else {
    const exe = path.join(process.resourcesPath, "app-res", "interview-coach-backend.exe");
    backendProc = spawn(exe, [], { env, windowsHide: true });
  }
  backendProc.stdout?.on("data", appendLog);
  backendProc.stderr?.on("data", appendLog);
  backendProc.on("exit", (code) => {
    if (code && !app.isQuitting) {
      dialog.showErrorBox(
        "后端异常退出",
        `exit code ${code}\n\n最近输出：\n${recentLog.slice(-6).join("\n") || "（无）"}\n\n完整日志：${logPath()}`
      );
    }
  });
}

function waitForBackend(retries = 60) {
  return new Promise((resolve, reject) => {
    const tick = (left) => {
      if (backendProc && backendProc.exitCode !== null) {
        return reject(new Error(`后端启动即退出（exit code ${backendProc.exitCode}），日志：${logPath()}`));
      }
      const req = http.get(`http://127.0.0.1:${PORT}/api/qa/conversations`, (res) => {
        res.resume();
        if (res.statusCode === 404) {
          return reject(new Error("当前后端版本不支持问答多会话，请退出托盘中的旧版后重新安装最新版。"));
        }
        if (res.statusCode < 200 || res.statusCode >= 300) {
          return reject(new Error(`后端健康检查失败（HTTP ${res.statusCode}），日志：${logPath()}`));
        }
        resolve();
      });
      req.on("error", () => {
        if (left <= 0) return reject(new Error(`后端启动超时，日志：${logPath()}`));
        setTimeout(() => tick(left - 1), 500);
      });
      req.setTimeout(1000, () => req.destroy());
    };
    tick(retries);
  });
}

function createTray() {
  const icon = nativeImage.createFromPath(path.join(__dirname, "icon.ico"));
  tray = new Tray(icon);
  tray.setToolTip("Interview Coach · 模拟面试");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "显示主界面", click: () => showWin() },
      { type: "separator" },
      { label: "打开配置文件 (.env)", click: () => shell.openPath(path.join(dataDir(), ".env")) },
      { label: "打开面试记录文件夹", click: () => shell.openPath(path.join(dataDir(), "sessions")) },
      { label: "打开知识库文件夹", click: () => shell.openPath(path.join(dataDir(), "kb")) },
      { type: "separator" },
      {
        label: "退出",
        click: () => {
          app.isQuitting = true;
          app.quit();
        },
      },
    ])
  );
  tray.on("click", () => showWin());
}

function showWin() {
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

function createWindow() {
  win = new BrowserWindow({
    width: 980,
    height: 760,
    title: "Interview Coach",
    icon: path.join(__dirname, "icon.ico"),
    webPreferences: {
      contextIsolation: true,
      preload: path.join(__dirname, "preload.js"),
    },
  });

  // 原生菜单栏在应用里既丑又多余：入口都在应用内（设置弹窗 / 托盘菜单）
  Menu.setApplicationMenu(null);

  // 没有菜单后保留必要快捷键：F12 开发者工具，F5 / Ctrl+R 刷新
  win.webContents.on("before-input-event", (e, input) => {
    if (input.type !== "keyDown") return;
    if (input.key === "F12") {
      win.webContents.toggleDevTools();
      e.preventDefault();
    } else if (input.key === "F5" || (input.control && input.key.toLowerCase() === "r")) {
      win.webContents.reload();
      e.preventDefault();
    }
  });

  // 自动允许麦克风（本地应用，无需弹窗）
  session.defaultSession.setPermissionRequestHandler((wc, permission, cb) => {
    cb(["media", "audioCapture", "speaker-selection"].includes(permission));
  });

  // 关窗 = 收进托盘继续挂着；真正退出走托盘菜单
  let trayTipShown = false;
  win.on("close", (e) => {
    if (app.isQuitting) return;
    e.preventDefault();
    win.hide();
    if (!trayTipShown && tray) {
      trayTipShown = true;
      tray.displayBalloon({
        title: "Interview Coach 还在托盘里",
        content: "点托盘图标回来继续面试，右键「退出」才是真的退出。",
        iconType: "info",
      });
    }
  });

  win.loadURL(`http://127.0.0.1:${PORT}/`);
}

// 应用内「打开文件夹/文件」入口（settings 弹窗里的链接走这里）
ipcMain.handle("ic:open", (e, what) => {
  const map = {
    env: path.join(dataDir(), ".env"),
    sessions: path.join(dataDir(), "sessions"),
    kb: path.join(dataDir(), "kb"),
    log: logPath(),
  };
  const target = map[what];
  if (target) shell.openPath(target);
});

// 单实例：托盘挂着时再点桌面图标，唤起已有窗口而不是再开一个
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => showWin());

  app.whenReady().then(async () => {
    try {
      PORT = await pickFreePort();
    } catch {
      PORT = 47821; // 挑端口本身失败的概率极低，兜底回冷门默认端口（8321 已被用户的常驻应用占用）
    }
    startBackend();
    createTray();
    try {
      await waitForBackend();
    } catch (e) {
      dialog.showErrorBox("启动失败", String(e.message || e));
    }
    createWindow();
  });
}

app.on("before-quit", () => {
  app.isQuitting = true;
  if (backendProc) {
    try { backendProc.kill(); } catch {}
  }
});

app.on("window-all-closed", () => app.quit());
