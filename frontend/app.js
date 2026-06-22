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
  data() {
    return {
      locale: ZH_CN,
      cfg: { ready: false, detail: "检查中…" },
      isElectron: IS_ELECTRON,
      theme: (() => {
        try { return localStorage.getItem("ic-theme") === "dark" ? "dark" : "light"; } catch { return "light"; }
      })(),
      page: (() => {
        const m = location.hash.match(/^#\/([a-z]+)/);
        const p = m && m[1];
        return ["prep", "interview", "intel", "records", "report"].includes(p) ? p : "prep";
      })(),
      showSettings: false,
      savingSettings: false,
      saveMsg: "",
      saveOk: false,
      st: {},
      testing: { llm: false, stt: false, tts: false },
      testMsg: { llm: "", stt: "", tts: "" },
      testOk: { llm: false, stt: false, tts: false },
      resume: { loaded: false },
      uploading: false,
      kb: { files: [], latest_update: "" },
      kbBusy: false,
      history: [],
      showHistory: false,
      historyTitle: "",
      historyHtml: "",
      intelTitle: "",
      intelHtml: "",
      intelSites: [],
      intelSources: [],
      archFilter: "",
      round: "二面",
      level: "应届校招",
      style: "字节",
      levels: ["在校实习", "应届校招", "社招1-3年", "社招3年+"],
      rounds: ["一面", "二面"],
      styles: ["字节", "美团", "阿里/蚂蚁", "腾讯", "京东"],
      providerOpts: [
        { label: "Anthropic", value: "anthropic" },
        { label: "OpenAI / 兼容", value: "openai" },
      ],
      ttsOn: true,
      sttAvailable: !!SR,
      sessionId: null,
      messages: [],
      draft: "",
      interim: "",
      busy: false,
      recording: false,
      transcribing: false,
      polishing: false,
      speaking: false,
      report: null,
      savedTo: "",
      startedAt: null,
      elapsed: "00:00",
      mics: [],                       // 可选的音频输入设备
      micId: localStorage.getItem("ic_mic") || "",
      micTest: { on: false, peak: 0, msg: "" },