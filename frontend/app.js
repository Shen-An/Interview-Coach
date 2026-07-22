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

  methods: {
    /* ---------- 页面导航 ---------- */
    nav(p) {
      this.page = p;
      const h = "#/" + p;
      if (location.hash !== h) location.hash = h;
    },

    /* ---------- 主题 / 本机文件 ---------- */
    toggleTheme() {
      this.theme = this.theme === "dark" ? "light" : "dark";
      document.documentElement.className = this.theme;
      try { localStorage.setItem("ic-theme", this.theme); } catch {}
    },
    icOpen(what) {
      if (window.ic && window.ic.open) window.ic.open(what);
    },

    /* ---------- 简历 ---------- */
    onResumePick(uploadFile) {
      const f = uploadFile && uploadFile.raw;
      if (f) this.uploadResume(f);
    },
    async uploadResume(f) {
      if (!f) return;
      this.uploading = true;
      try {
        const fd = new FormData();
        fd.append("file", f, f.name);
        const r = await fetch("/api/resume", { method: "POST", body: fd });
        if (!r.ok) throw new Error((await r.json()).detail);
        this.resume = await r.json();
        ElMessage.success(`已读入《${this.resume.filename}》，面试官会照着它问`);
      } catch (e) {
        ElMessage.error("简历解析失败：" + e.message);
      } finally {
        this.uploading = false;
      }
    },
    async deleteResume() {
      try {
        await ElMessageBox.confirm("移除后面试官会改成让你口头介绍项目。", "移除简历？", {
          confirmButtonText: "移除",
          cancelButtonText: "留着",
          type: "warning",
        });
      } catch {
        return;
      }
      try {
        await fetch("/api/resume", { method: "DELETE" });
        this.resume = { loaded: false };
        ElMessage.success("已移除");
      } catch (e) {
        ElMessage.error("移除失败：" + e.message);
      }
    },

    /* ---------- 设置 ---------- */
    async openSettings() {
      try {
        this.st = await (await fetch("/api/settings")).json();
      } catch {
        this.st = { LLM_PROVIDER: "anthropic" };
      }
      if (!this.st.LLM_PROVIDER) this.st.LLM_PROVIDER = "anthropic";
      if (!this.st.STT_REWRITE) this.st.STT_REWRITE = "on";   // .env 里没写过就是默认开
      this.saveMsg = "";
      this.micTest.msg = "";
      this.showSettings = true;
      this.loadMics();          // 设备列表要授权后才有标签，进设置时拉一次
    },
    async saveSettings() {
      this.savingSettings = true;
      this.saveMsg = "";
      try {
        const r = await fetch("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ values: this.st }),
        });
        if (!r.ok) throw new Error((await r.json()).detail);
        const d = await r.json();
        this.cfg = await (await fetch("/api/config")).json();
        this.sttAvailable = SR ? true : !!(d.stt_api_ready && navigator.mediaDevices);
        this.saveOk = !!d.ready;
        this.saveMsg = d.ready ? "已生效" : d.detail;
        this._cloudTtsDead = false; // 配置变了，云端 TTS 重新给机会
        if (d.ready) {
          ElMessage.success("模型已就绪：" + (this.cfg.model || this.cfg.provider));
          setTimeout(() => (this.showSettings = false), 500);
        }
      } catch (e) {
        this.saveOk = false;
        this.saveMsg = "保存失败：" + e.message;
      } finally {
        this.savingSettings = false;
      }
    },

    /* ---------- 复盘档案 ---------- */
    async loadHistory() {
      try {
        this.history = (await (await fetch("/api/history")).json()).items || [];
      } catch {
        this.history = [];
      }
    },
    async openHistory(h) {
      try {
        const d = await (await fetch(`/api/history/${encodeURIComponent(h.id)}`)).json();
        this.historyTitle = `${h.round} · ${h.style}风格 · ${(h.started_at || "").replace("T", " ")}`;
        this.historyHtml = marked.parse(d.md || "");
        this.showHistory = true;
      } catch (e) {
        ElMessage.error("读取记录失败：" + e.message);
      }
    },
    async deleteHistory(h) {
      try {
        await ElMessageBox.confirm("删除后这场的复盘和对话记录就没了。", "删除这条记录？", {
          confirmButtonText: "删除",
          cancelButtonText: "留着",
          type: "warning",
        });
      } catch {
        return;
      }
      await fetch(`/api/history/${encodeURIComponent(h.id)}`, { method: "DELETE" });
      this.loadHistory();
    },

    /* ---------- 配置自检：保存并测试 ---------- */
    async saveQuiet() {
      // 静默保存：测试按钮先落盘当前表单再测，不关弹窗不弹提示
      const r = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values: this.st }),
      });
      if (!r.ok) throw new Error((await r.json()).detail);
      this.cfg = await (await fetch("/api/config")).json();
      this._cloudTtsDead = false;
      const SR_OK = window.SpeechRecognition || window.webkitSpeechRecognition;
      this.sttAvailable = !IS_ELECTRON && SR_OK ? true : !!(this.cfg.stt_api_ready && navigator.mediaDevices);
      return this.cfg;
    },
    async testLlm() {
      this.testing.llm = true;
      this.testMsg.llm = "";
      try {
        await this.saveQuiet();
        const d = await (await fetch("/api/test/llm", { method: "POST" })).json();
        this.testOk.llm = d.ok;
        this.testMsg.llm = d.ok
          ? `通了 · ${(d.ms / 1000).toFixed(1)}s · 她说：「${d.reply}」`
          : "失败：" + d.error;
      } catch (e) {
        this.testOk.llm = false;
        this.testMsg.llm = "失败：" + e.message;
      } finally {
        this.testing.llm = false;
      }
    },
    async testStt() {
      this.testing.stt = true;
      this.testMsg.stt = "";
      try {
        await this.saveQuiet();
        const d = await (await fetch("/api/test/stt", { method: "POST" })).json();
        this.testOk.stt = d.ok;
        this.testMsg.stt = d.ok
          ? `通了 · ${(d.ms / 1000).toFixed(1)}s · 识别出：「${d.heard}」`
          : "失败：" + d.error;
      } catch (e) {
        this.testOk.stt = false;
        this.testMsg.stt = "失败：" + e.message;
      } finally {
        this.testing.stt = false;
      }
    },
    async testTts() {
      this.testing.tts = true;
      this.testMsg.tts = "";
      try {
        await this.saveQuiet();
        await this.speakCloud("你好，这一段是音色试听，接下来的面试就是这个声音。");
        this.testOk.tts = true;
        this.testMsg.tts = "正在播放试听…不满意换个音色再点";
      } catch (e) {
        this.testOk.tts = false;
        this.testMsg.tts = "失败：" + (e.message || e);
      } finally {
        this.testing.tts = false;
      }
    },

    /* ---------- 情报库 ---------- */
    async refreshKb() {
      if (!this.cfg.ready) {
        ElMessage.warning("先配置对话模型，联网检索要用它");
        return this.openSettings();
      }
      this.kbBusy = true;
      try {
        const r = await fetch("/api/kb/refresh", { method: "POST" });
        if (!r.ok) throw new Error((await r.json()).detail);
        const d = await r.json();
        this.kb = d.kb;
        this.showIntelSummary(d);
        if (d.no_news) ElMessage.info("今日无新增面经，行业无重大变化");
        else ElMessage.success("情报库已更新：" + d.section);
      } catch (e) {
        // 搜索通路不可用时后端会给一段多行的排查说明，弹窗比 toast 读得清
        const msg = String(e.message || e);
        if (msg.includes("\n")) {
          ElMessageBox.alert(msg.replace(/\n/g, "<br>"), "联网搜索用不了", {
            dangerouslyUseHTMLString: true, confirmButtonText: "知道了",
          });
        } else ElMessage.error("更新失败：" + msg);
      } finally {
        this.kbBusy = false;
      }
    },
    showIntelSummary(d) {
      this.intelTitle = d.section || "增量情报";
      this.intelHtml = marked.parse(d.summary || "（这次没有产出新内容）");
      this.intelSites = d.sites || [];
      this.intelSources = d.sources || [];
    },
    async loadIntelLatest() {
      // 静默加载最新一节情报，情报库页面直接展示；没有内容就留空态
      try {
        const r = await fetch("/api/kb/latest");
        if (!r.ok) return;
        const d = await r.json();
        if (d.summary) this.showIntelSummary(d);
      } catch {}
    },
    onKbPick(uploadFile) {
      const f = uploadFile && uploadFile.raw;
      if (f) this.importKb(f);
    },
    async importKb(f) {
      if (!f) return;
      this.kbBusy = true;
      try {
        const fd = new FormData();
        fd.append("file", f, f.name);
        const r = await fetch("/api/kb/import", { method: "POST", body: fd });
        if (!r.ok) throw new Error((await r.json()).detail);
        const d = await r.json();
        this.kb = d.kb;
        this.showIntelSummary(d);
        ElMessage.success("已蒸馏进情报库：" + d.section);
      } catch (e) {
        ElMessage.error("导入失败：" + e.message);
      } finally {
        this.kbBusy = false;
      }
    },

    /* ---------- 面试主流程 ---------- */
    async startInterview() {
      this.busy = true;
      try {
        const r = await fetch("/api/session/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ round: this.round, style: this.style, level: this.level }),
        });
        if (!r.ok) throw new Error((await r.json()).detail);
        const d = await r.json();
        this.sessionId = d.session_id;
        this.messages = [{ role: "assistant", content: d.message }];
        this.startedAt = Date.now();
        this._timer = setInterval(() => {
          const s = Math.floor((Date.now() - this.startedAt) / 1000);
          this.elapsed = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
        }, 1000);
        this.nav("interview");
        this.speak(d.message);
      } catch (e) {
        ElMessage.error("开始失败：" + e.message);
      } finally {
        this.busy = false;
      }
    },

    async sendDraft() {
      const text = this.draft.trim();
      if (!text || this.busy) return;
      this.stopTTS();
      this.stopMic(false);
      this.draft = "";
      this.messages.push({ role: "user", content: text });
      this.scrollDown();
      this.busy = true;
      try {
        const r = await fetch(`/api/session/${this.sessionId}/turn`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        if (!r.ok) throw new Error((await r.json()).detail);
        const d = await r.json();
        this.messages.push({ role: "assistant", content: d.message });
        this.scrollDown();
        this.speak(d.message);
      } catch (e) {
        this.messages.push({ role: "assistant", content: "（系统错误：" + e.message + "）" });
        this.scrollDown();
      } finally {
        this.busy = false;
      }
    },

    async endInterview() {
      try {
        await ElMessageBox.confirm(
          `已经聊了 ${this.questionCount} 问、${this.elapsed}。结束后会生成五维评分和扣分点回放。`,
          "结束面试并复盘？",
          { confirmButtonText: "结束并复盘", cancelButtonText: "再聊几句", type: "warning" }
        );
      } catch {
        return;
      }
      this.stopTTS();
      this.stopMic(false);
      this.busy = true;
      // 复盘是长生成：给用户一个进度感，也给请求一个硬超时兜底（后端有轮换，前端别无限等）
      const tip = ElMessage({ message: "复盘生成中：五维评分 + 扣分回放，通常 1~3 分钟…", type: "info", duration: 0 });
      const ctl = new AbortController();
      const killer = setTimeout(() => ctl.abort(), 360000);
      try {
        const r = await fetch(`/api/session/${this.sessionId}/end`, { method: "POST", signal: ctl.signal });
        if (!r.ok) throw new Error((await r.json()).detail);
        const d = await r.json();
        this.report = d.report;
        this.savedTo = d.saved_to;
        this.sessionId = null;
        clearInterval(this._timer);
        this.loadHistory();
        this.nav("report");
      } catch (e) {
        ElMessage.error(
          e.name === "AbortError"
            ? "复盘超时：6 分钟没等到模型回话。多半是中转站断了——去设置点「保存并测试对话」确认，修好后再点一次结束（对话还在，不会丢）。"
            : "复盘失败：" + e.message
        );
      } finally {
        clearTimeout(killer);
        tip.close();
        this.busy = false;
      }
    },

    askHint() {
      this.draft = "这里我卡住了，能给点提示吗？";
      this.sendDraft();
    },
    skipQuestion() {
      this.draft = "这题我确实不太会，先跳过吧。";
      this.sendDraft();
    },
    reset() {
      this.report = null;
      this.messages = [];
      this.elapsed = "00:00";
      this.savedTo = "";
      this.nav("prep");
    },

    /* ---------- 复盘辅助 ---------- */
    stripScoreBlock(md) {
      const lines = md.split("\n");
      const out = [];
      let i = 0;
      while (i < lines.length) {
        if (/^#{1,4}\s*总分/.test(lines[i])) {
          i++;
          while (i < lines.length && (lines[i].trim() === "" || lines[i].trim().startsWith("|"))) i++;
          continue;
        }
        out.push(lines[i]);
        i++;
      }
      return out.join("\n");
    },
    barColor(pct) {
      if (pct >= 80) return "#4FB37C";
      if (pct >= 60) return "#24B5C4";
      if (pct >= 40) return "#DBA24B";
      return "#DF6663";
    },
    async copy(text, okMsg) {
      try {
        await navigator.clipboard.writeText(text);
        ElMessage.success(okMsg);
      } catch {
        ElMessage.warning("这个环境不让直接写剪贴板，手动选中复制吧");
      }
    },
    copyReport() {
      this.copy(this.report || "", "复盘 Markdown 已复制");
    },
    copyPath() {
      this.copy(this.savedTo || "", "存档路径已复制");
    },

    /* ---------- TTS：面试官朗读 ----------
       三级：配了 key 走付费云端（onyx + 语气指令）→ 没配走 Edge 免费云音（云希男声 + 风格韵律，
       后端 /api/tts 内部选路）→ 网络挂了才退系统本地音。失败一次后本场跳过云端，不反复等超时 */
    async speak(text) {
      if (!this.ttsOn) return;
      const clean = text.replace(/[#*`>\-]/g, "");
      if (!this._cloudTtsDead) {
        try {
          await this.speakCloud(clean);
          return;
        } catch (e) {
          this._cloudTtsDead = true;
          console.warn("云端 TTS 失败，降级本地语音：", e);
        }
      }
      this.speakLocal(clean);
    },

    async speakCloud(text) {
      this.stopTTS();
      const r = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, style: this.style }),
      });
      if (!r.ok) throw new Error((await r.json()).detail);
      const url = URL.createObjectURL(await r.blob());
      const audio = new Audio(url);
      this._audio = audio;
      audio.onplay = () => (this.speaking = true);
      audio.onended = audio.onerror = () => {
        this.speaking = false;
        URL.revokeObjectURL(url);
        if (this._audio === audio) this._audio = null;
      };
      await audio.play();
    },

    speakLocal(text) {
      if (!("speechSynthesis" in window)) return;
      speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "zh-CN";
      if (this._voice) u.voice = this._voice;
      // 按厂风格调韵律：压力面快而低，慢厂稳而平
      const prosody = {
        "字节": { rate: 1.14, pitch: 0.9 },
        "美团": { rate: 1.06, pitch: 0.94 },
        "阿里/蚂蚁": { rate: 1.0, pitch: 0.92 },
        "腾讯": { rate: 1.0, pitch: 1.0 },
        "京东": { rate: 0.96, pitch: 0.98 },
      }[this.style] || { rate: 1.05, pitch: 0.95 };
      u.rate = prosody.rate;
      u.pitch = prosody.pitch;
      u.onstart = () => (this.speaking = true);
      u.onend = u.onerror = () => (this.speaking = false);
      speechSynthesis.speak(u);
    },

    stopTTS() {
      if ("speechSynthesis" in window) speechSynthesis.cancel();
      if (this._audio) {
        try { this._audio.pause(); } catch {}
        this._audio = null;
      }
      this.speaking = false;
    },

    /* ---------- STT：候选人语音作答（按下说话 → 停止并发送）----------
       双路：浏览器走 Web Speech API（免费实时）；Electron 走 MediaRecorder + 转写 API */
    toggleMic() {
      this.recording ? this.stopMic(true) : this.startMic();
    },
    startMic() {
      if (!SR) return this.startRecorder();
      this.stopTTS(); // 打断面试官朗读，像真实抢话
      const rec = new SR();
      rec.lang = "zh-CN";
      rec.continuous = true;
      rec.interimResults = true;
      let finalText = this.draft ? this.draft + " " : "";
      rec.onresult = (ev) => {
        let interim = "";
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const t = ev.results[i][0].transcript;
          if (ev.results[i].isFinal) finalText += t;
          else interim += t;
        }
        this.interim = interim;
        this.draft = finalText + interim;
      };
      rec.onerror = (ev) => {
        if (ev.error !== "no-speech" && ev.error !== "aborted")
          ElMessage.error("语音识别出错：" + ev.error + "，检查一下麦克风权限");
        this.recording = false;
        this.stopMeter();
      };
      rec.onend = () => {
        // continuous 模式下浏览器可能自动断开：仍在录音状态就重启
        if (this.recording) {
          try {
            rec.start();
          } catch {
            this.recording = false;
          }
        }
      };
      this._rec = rec;
      this.recording = true;
      // 这条通路有实时听写文字兜底，不再额外占一路麦克风，音量表走呼吸动画
      this.meterLive = false;
      rec.start();
    },