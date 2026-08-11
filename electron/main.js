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