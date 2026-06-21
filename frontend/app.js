const { createApp } = Vue;
const { ElMessage, ElMessageBox } = ElementPlus;

const IS_ELECTRON = navigator.userAgent.includes("Electron");
// Electron 里 webkitSpeechRecognition 不可用（缺 Google 服务密钥），改走录音+转写 API
const SR = IS_ELECTRON ? null : window.SpeechRecognition || window.webkitSpeechRecognition;

const ZH_CN = window.ElementPlusLocaleZhCn || null;

// 五维定义来自 kb/SCORING-RUBRIC.md，用于把复盘正文解析成评分卡
const DIMS = {
  A: { name: "概念与架构", max: 15 },
  B: { name: "设计与决策", max: 25 },
  C: { name: "落地与工程化", max: 30 },
  D: { name: "代码基本功", max: 15 },
  E: { name: "行业视野与自省", max: 15 },
};

const app = createApp({