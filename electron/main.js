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
      const req = http.get(`http://127.0.0.1:${PORT}/api/config`, (res) => {
        res.resume();
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
