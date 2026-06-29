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
      meterBars: [0.16, 0.16, 0.16, 0.16, 0.16],
      meterLive: false, // true = 真实电平（有音频流时），false = 呼吸动画
      _rec: null,
      _media: null,
      _chunks: [],
      _timer: null,
      _voice: null,
      _raf: null,
      _actx: null,
    };
  },

  computed: {
    kbStale() {
      const today = new Date().toISOString().slice(0, 10);
      return !(this.kb.latest_update || "").includes(today);
    },
    questionCount() {
      return this.messages.filter((m) => m.role === "assistant").length;
    },
    /* ---- 复盘档案：首页最近 3 场 + 抽屉全量筛选 ---- */
    recentHistory() {
      return this.history.slice(0, 3);
    },
    filteredHistory() {
      const q = this.archFilter.trim();
      if (!q) return this.history;
      return this.history.filter((h) =>
        `${h.round} ${h.style} ${h.level} ${h.started_at} ${h.score}`.includes(q)
      );
    },
    bestScore() {
      const scored = this.history.filter((h) => h.score).map((h) => Number(h.score));
      return scored.length ? Math.max(...scored) : "";
    },
    kbChars() {
      const n = (this.kb.files || []).reduce((s, f) => s + (f.chars || 0), 0);
      return n >= 10000 ? (n / 10000).toFixed(1) + " 万" : String(n);
    },
    avgScore() {
      const scored = this.history.filter((h) => h.score).slice(0, 5);
      if (!scored.length) return "";
      return Math.round(scored.reduce((s, h) => s + Number(h.score), 0) / scored.length);
    },

    sttHint() {
      return this.isElectron
        ? "exe 版需要在「设置 → 语音转写」里填一个 whisper 兼容接口的 key，填完保存即可生效。"
        : "浏览器内置语音识别只在 Edge / Chrome 里可用，换个浏览器就行。也可以直接打字回答。";
    },

    /* ---- 复盘评分卡：从正文里解析真实分数 ---- */
    parsed() {
      const md = this.report || "";
      const dims = [];
      const re = /^\|\s*([A-E])[\s、.．·]*([^|]*?)\s*\|\s*([^|]*?)\s*\|/gm;
      let m;
      while ((m = re.exec(md))) {
        const key = m[1];
        const meta = DIMS[key];
        if (!meta) continue;
        const cell = m[3];
        const pair = cell.match(/(\d+(?:\.\d+)?)\s*\/\s*(\d+)/);
        const lone = cell.match(/(\d+(?:\.\d+)?)/);
        if (!pair && !lone) continue;
        const score = parseFloat(pair ? pair[1] : lone[1]);
        const max = pair ? parseInt(pair[2], 10) || meta.max : meta.max;
        if (!isFinite(score)) continue;
        dims.push({
          key,
          name: (m[2] || meta.name).trim() || meta.name,
          score,
          max,
          pct: Math.max(0, Math.min(100, Math.round((score / max) * 100))),
        });
      }
      const totalM = md.match(/总分[^\d\n]{0,10}(\d{1,3})/);
      const total = totalM
        ? parseInt(totalM[1], 10)
        : dims.length
        ? Math.round(dims.reduce((s, d) => s + d.score, 0))
        : 0;
      // 先认「→」——模板里等级就跟在箭头后面；退化路径要去掉前面的分数片段
      let g = "";
      const arrowM = md.match(/总分[^\n]*?(?:→|->|=>)\s*([^\n]+)/);
      if (arrowM) {
        g = arrowM[1];
      } else {
        const colonM = md.match(/总分[^\n]*?[:：]\s*([^\n]+)/);
        if (colonM) g = colonM[1].replace(/^\s*\d{1,3}\s*\/\s*\d{1,3}\s*/, "");
      }
      g = g.replace(/[*`#]/g, "").trim();
      // 「SP —— 工程化思维成型，需带教」拆开：等级才是该放大的那半，判词是注解
      const parts = g.split(/\s*(?:——|—|--|–)\s*/);
      return {
        dims,
        total: Math.max(0, Math.min(100, total)),
        grade: (parts[0] || "").trim(),
        gradeNote: parts.slice(1).join(" ").trim(),
      };
    },
    scores() {
      return this.parsed.dims.length >= 3 ? this.parsed.dims : [];
    },
    totalScore() {
      return this.parsed.total;
    },
    totalPct() {
      return this.parsed.total;
    },
    grade() {
      return this.parsed.grade;
    },
    gradeNote() {
      return this.parsed.gradeNote;
    },
    // 阈值直接照抄评分细则的等级线，所以配色不会和判词打架
    gradeColor() {
      const t = this.totalScore;
      if (t >= 85) return "#4FB37C";
      if (t >= 70) return "#24B5C4";
      if (t >= 55) return "#DBA24B";
      return "#DF6663";
    },
    reportHtml() {
      if (!this.report) return "";
      // 评分卡已经把总分和五维表提到上面了，正文里就不再重复一遍
      const md = this.scores.length ? this.stripScoreBlock(this.report) : this.report;
      return marked.parse(md);
    },
  },

  async mounted() {
    try {
      this.cfg = await (await fetch("/api/config")).json();
    } catch {
      this.cfg = { ready: false, detail: "后端未启动" };
    }
    // STT 可用性：浏览器有 Web Speech API 即可；Electron 需配置转写 API key
    this.sttAvailable = SR ? true : !!(this.cfg.stt_api_ready && navigator.mediaDevices);
    if (this.cfg.resume) this.resume = this.cfg.resume;
    if (this.cfg.kb) this.kb = this.cfg.kb;
    if (!this.cfg.ready) this.openSettings();
    this.loadHistory();
    this.loadIntelLatest();
    // hash 路由：前进后退/刷新都能落回原页面
    if (!location.hash) history.replaceState(null, "", "#/" + this.page);
    window.addEventListener("hashchange", () => {
      const m = location.hash.match(/^#\/([a-z]+)/);
      const p = m && m[1];
      if (["prep", "interview", "intel", "records", "report"].includes(p)) this.page = p;
    });
    // 选中文语音（voices 异步加载）
    const pick = () => {
      const vs = speechSynthesis.getVoices();
      // 面试官是冷面男声：男声优先（云希/云扬/云健/康康），再退任意中文音
      this._voice =
        vs.find((v) => v.lang === "zh-CN" && /Yunxi|Yunyang|Yunjian|Kangkang/i.test(v.name)) ||
        vs.find((v) => v.lang === "zh-CN" && !/Xiaoxiao|Xiaoyi|Huihui|Yaoyao/i.test(v.name)) ||
        vs.find((v) => v.lang === "zh-CN") ||
        null;
    };
    pick();
    speechSynthesis.onvoiceschanged = pick;
  },
