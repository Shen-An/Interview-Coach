const { contextBridge, ipcRenderer } = require("electron");

// 前端用 window.ic.open("env" | "sessions" | "kb" | "log") 打开本机文件/文件夹
contextBridge.exposeInMainWorld("ic", {
  open: (what) => ipcRenderer.invoke("ic:open", what),
});
