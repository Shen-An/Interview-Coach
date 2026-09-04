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
        return ["prep", "qa", "interview", "intel", "records", "report"].includes(p) ? p : "prep";
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
      qaMessages: [],
      qaDraft: "",
      qaConversations: [],
      qaConversationId: null,
      qaLoadingConversations: false,
      qaSwitching: false,
      qaBusy: false,
      qaStage: "idle", // idle / waiting / streaming / done / error
      qaTiming: null,
      qaSuggested: [
        "如何解决工具调用失败和兜底？",
        "如何降低模型幻觉？",
        "Agent 如何设计重试和幂等？",
        "RAG 召回不到内容怎么办？",
        "如何设计 Agent 评测体系？",
      ],
      interim: "",
      busy: false,
      recording: false,
      transcribing: false,
      speaking: false,
      streaming: false, // SSE 增量已开始渲染（思考点让位给正在生长的气泡）
      _ttsQueue: [],
      _ttsBusy: false,
      _sentBuf: "",
      _firstChunk: true, // 本轮 TTS 还没开过口：首块允许在逗号处提前切出
      _audioDone: null,
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
      _chatScrollTimer: null,
      _qaScrollTimer: null,
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
    this.loadQaConversations();
    this.loadIntelLatest();
    // hash 路由：前进后退/刷新都能落回原页面
    if (!location.hash) history.replaceState(null, "", "#/" + this.page);
    window.addEventListener("hashchange", () => {
      const m = location.hash.match(/^#\/([a-z]+)/);
      const p = m && m[1];
      if (["prep", "qa", "interview", "intel", "records", "report"].includes(p)) this.page = p;
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

    /* ---------- 独立面试问答 ---------- */
    qaHtml(text) {
      return marked.parse(text || "");
    },
    timingLabel(timing) {
      if (!timing || typeof timing.total_ms !== "number") return "";
      const seconds = timing.total_ms / 1000;
      return seconds < 10 ? `${seconds.toFixed(1)}s` : `${Math.round(seconds)}s`;
    },
    qaConversationTime(value) {
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return "";
      const now = new Date();
      const sameDay = date.toDateString() === now.toDateString();
      return sameDay
        ? date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })
        : date.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
    },
    async qaApiError(response, fallback) {
      let detail = "";
      try {
        const data = await response.json();
        detail = data.detail || data.message || "";
      } catch {
        // 旧后端可能只返回纯文本，下面统一使用状态码提示。
      }
      if (response.status === 404) {
        return "当前后端版本不支持多会话，请完全退出托盘中的旧版 Interview Coach 后安装最新版。";
      }
      return detail || `${fallback}（HTTP ${response.status}）`;
    },
    async loadQaConversations(preferredId = null) {
      this.qaLoadingConversations = true;
      try {
        const r = await fetch("/api/qa/conversations");
        if (!r.ok) throw new Error(await this.qaApiError(r, "会话列表加载失败"));
        const data = await r.json();
        this.qaConversations = data.items || [];
        const target = preferredId || this.qaConversationId;
        const found = target && this.qaConversations.some((item) => item.id === target);
        if (found) {
          if (this.qaConversationId !== target || !this.qaMessages.length) await this.loadQaConversation(target);
        } else if (this.qaConversations.length) {
          await this.loadQaConversation(this.qaConversations[0].id);
        } else {
          this.qaConversationId = null;
          this.qaMessages = [];
          this.qaStage = "idle";
          this.qaTiming = null;
        }
      } catch (e) {
        this.qaConversations = [];
        if (!this.qaMessages.length) ElMessage.error("问答会话加载失败：" + e.message);
      } finally {
        this.qaLoadingConversations = false;
      }
    },
    async refreshQaConversationList() {
      try {
        const r = await fetch("/api/qa/conversations");
        if (r.ok) this.qaConversations = (await r.json()).items || [];
      } catch {
        // 问答已经完成时，列表刷新失败不应覆盖当前回答。
      }
    },
    async loadQaConversation(id) {
      if (!id || this.qaBusy || this.qaSwitching) return;
      this.qaSwitching = true;
      try {
        const r = await fetch(`/api/qa/conversations/${encodeURIComponent(id)}`);
        if (!r.ok) throw new Error(await this.qaApiError(r, "会话读取失败"));
        const conversation = await r.json();
        this.qaConversationId = conversation.id;
        this.qaMessages = (conversation.messages || []).map((message) => ({
          role: message.role,
          content: message.content || "",
          sources: message.sources || [],
        }));
        this.qaDraft = "";
        this.qaStage = this.qaMessages.length ? "done" : "idle";
        this.qaTiming = null;
        this.$nextTick(() => this.scrollQaDown());
      } catch (e) {
        ElMessage.error("问答会话读取失败：" + e.message);
      } finally {
        this.qaSwitching = false;
      }
    },
    async createQaConversation() {
      if (this.qaBusy || this.qaSwitching) return false;
      try {
        const r = await fetch("/api/qa/conversations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        if (!r.ok) throw new Error(await this.qaApiError(r, "新建会话失败"));
        const conversation = await r.json();
        this.qaConversations = [conversation, ...this.qaConversations.filter((item) => item.id !== conversation.id)];
        this.qaConversationId = conversation.id;
        this.qaMessages = [];
        this.qaDraft = "";
        this.qaStage = "idle";
        this.qaTiming = null;
        return true;
      } catch (e) {
        ElMessage.error("新建问答会话失败：" + e.message);
        return false;
      }
    },
    async deleteQaConversation() {
      if (!this.qaConversationId || this.qaBusy || this.qaSwitching) return;
      try {
        await ElMessageBox.confirm("删除后，这个主题的问答记录将无法恢复。", "删除问答会话？", {
          confirmButtonText: "删除",
          cancelButtonText: "保留",
          type: "warning",
        });
      } catch {
        return;
      }
      const deletedId = this.qaConversationId;
      try {
        const r = await fetch(`/api/qa/conversations/${encodeURIComponent(deletedId)}`, { method: "DELETE" });
        if (!r.ok) throw new Error(await this.qaApiError(r, "删除失败"));
        this.qaConversations = this.qaConversations.filter((item) => item.id !== deletedId);
        this.qaConversationId = null;
        this.qaMessages = [];
        this.qaStage = "idle";
        this.qaTiming = null;
        if (this.qaConversations.length) await this.loadQaConversation(this.qaConversations[0].id);
        ElMessage.success("问答会话已删除");
      } catch (e) {
        ElMessage.error("删除问答会话失败：" + e.message);
      }
    },
    async askQuestion(preset) {
      const text = (typeof preset === "string" ? preset : this.qaDraft).trim();
      if (!text || this.qaBusy || this.qaSwitching) return;
      if (!this.cfg.ready) {
        ElMessage.warning("请先在设置里配置对话模型");
        return;
      }
      if (!this.qaConversationId && !(await this.createQaConversation())) return;
      const conversationId = this.qaConversationId;
      // 有会话 id 时后端从磁盘读取上下文；history 只为旧客户端/旧服务保留。
      const history = this.qaMessages.map((m) => ({
        role: m.role,
        content: m.content || "",
      })).filter((m) => m.content.trim());
      this.qaMessages.push({ role: "user", content: text });
      const holder = { role: "assistant", content: "", sources: [] };
      this.qaMessages.push(holder);
      this.qaDraft = "";
      this.qaBusy = true;
      this.qaStage = "waiting";
      this.qaTiming = null;
      this.scrollQaDown();

      const append = (piece) => {
        holder._pending = (holder._pending || "") + piece;
        if (this.qaStage === "waiting") this.qaStage = "streaming";
        this.scheduleStreamRender(holder, "qaBox");
      };
      try {
        const r = await fetch("/api/qa/ask/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: text, conversation_id: conversationId, history }),
        });
        if (!r.ok) throw new Error((await r.json()).detail || "请求失败");
        if (!r.body) throw new Error("这个环境不支持流式读取");
        const reader = r.body.getReader();
        const dec = new TextDecoder();
        let buf = "", finalText = null, errMsg = null;
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let i;
          while ((i = buf.indexOf("\n\n")) >= 0) {
            const frame = buf.slice(0, i);
            buf = buf.slice(i + 2);
            for (const line of frame.split("\n")) {
              if (!line.startsWith("data: ")) continue;
              const ev = JSON.parse(line.slice(6));
              if (ev.conversation_id && ev.conversation_id !== this.qaConversationId) {
                this.qaConversationId = ev.conversation_id;
              }
              if (ev.d) append(ev.d);
              else if (ev.err) { errMsg = ev.err; this.qaTiming = ev.timing || null; }
              else if (ev.done) {
                finalText = ev.text;
                holder.sources = ev.sources || [];
                this.qaTiming = ev.timing || null;
              }
            }
          }
        }
        if (errMsg) throw new Error(errMsg);
        if (finalText === null) throw new Error("回答流意外结束，请重试一次");
        this.flushStreamRender(holder, "qaBox");
        holder.content = finalText;
        this.qaStage = "done";
        this.scrollQaDown();
      } catch (e) {
        this.flushStreamRender(holder, "qaBox");
        if (holder.content) holder.content += "\n\n> 系统提示：" + e.message;
        else holder.content = "（系统错误：" + e.message + "）";
        this.qaStage = "error";
        ElMessage.error("问答失败：" + e.message);
      } finally {
        this.qaBusy = false;
        await this.refreshQaConversationList();
        this.flushStreamRender(holder, "qaBox");
        this.scrollQaDown();
      }
    },
    async newQaConversation() {
      await this.createQaConversation();
    },
    copyQaAnswer(text) {
      this.copy(text, "回答已复制");
    },
    scheduleStreamRender(holder, ref) {
      if (!holder || holder._renderTimer) return;
      holder._renderTimer = setTimeout(() => {
        holder._renderTimer = null;
        if (holder._pending) {
          holder.content += holder._pending;
          holder._pending = "";
        }
        ref === "qaBox" ? this.scrollQaDown() : this.scrollDown();
      }, 32);
    },
    flushStreamRender(holder, ref) {
      if (!holder) return;
      if (holder._renderTimer) {
        clearTimeout(holder._renderTimer);
        holder._renderTimer = null;
      }
      if (holder._pending) {
        holder.content += holder._pending;
        holder._pending = "";
      }
      ref === "qaBox" ? this.scrollQaDown() : this.scrollDown();
    },
    scrollQaDown() {
      if (this._qaScrollTimer) return;
      this._qaScrollTimer = setTimeout(() => {
        this._qaScrollTimer = null;
        this.$nextTick(() => {
          const el = this.$refs.qaBox;
          if (el) el.scrollTop = el.scrollHeight;
        });
      }, 0);
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
      this.streaming = false;
      this._sentBuf = "";
      let holder = null; // 首个增量到达时才建气泡，之前显示思考点
      const append = (d) => {
        if (!holder) {
          holder = { role: "assistant", content: "" };
          this.messages.push(holder);
          this.streaming = true;
        }
        holder._pending = (holder._pending || "") + d;
        this.queueSentences(d); // 攒满一句立刻开始念
        this.scheduleStreamRender(holder, "chatBox");
      };
      try {
        const r = await fetch(`/api/session/${this.sessionId}/turn/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        if (!r.ok) throw new Error((await r.json()).detail);
        if (!r.body) throw new Error("这个环境不支持流式读取");
        const reader = r.body.getReader();
        const dec = new TextDecoder();
        let buf = "", finalText = null, errMsg = null;
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let i;
          while ((i = buf.indexOf("\n\n")) >= 0) {
            const frame = buf.slice(0, i);
            buf = buf.slice(i + 2);
            for (const line of frame.split("\n")) {
              if (!line.startsWith("data: ")) continue;
              const ev = JSON.parse(line.slice(6));
              if (ev.d) append(ev.d);
              else if (ev.err) errMsg = ev.err;
              else if (ev.done) finalText = ev.text;
            }
          }
        }
        if (errMsg) throw new Error(errMsg);
        // 后端清洗可能截掉了泄漏的尾巴，用最终版覆盖气泡
        if (holder) this.flushStreamRender(holder, "chatBox");
        if (finalText !== null && holder && holder.content !== finalText) holder.content = finalText;
        this.flushSentences(); // 末尾不带句号的半句也念出来
        this.scrollDown();
      } catch (e) {
        this.stopTTS();
        if (holder) this.flushStreamRender(holder, "chatBox");
        if (holder && holder.content) {
          holder.content += "（——已中断：" + e.message + "）";
        } else {
          if (holder) this.messages.pop();
          this.messages.push({ role: "assistant", content: "（系统错误：" + e.message + "）" });
        }
        this.scrollDown();
      } finally {
        this.busy = false;
        this.streaming = false;
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

    /* ---------- TTS：面试官朗读（分句流水线） ----------
       文本按句进播放队列：SSE 边吐字边攒句，攒满一句立刻入队——第一句到齐就开口，不等全文。
       队列顺序播放；云端音频在入队时就预取，播上一句的同时下一句已在合成。
       三级选路不变：付费云端 → Edge 免费云音（后端 /api/tts 内部选）→ 系统本地音。
       云端失败一次后本场跳过云端，不反复等超时 */
    speak(text) {
      // 整段文本入口（开场白等）：同样走分句队列，首句最快开播
      if (!this.ttsOn) return;
      this.stopTTS();
      this.queueSentences(text);
      this.flushSentences();
    },

    queueSentences(delta) {
      if (!this.ttsOn) return;
      this._sentBuf += delta;
      let m;
      while ((m = this._sentBuf.match(/[\s\S]*?[。！？!?；;\n]+/))) {
        this._sentBuf = this._sentBuf.slice(m[0].length);
        this.enqueueSpeak(m[0]);
        this._firstChunk = false;
      }
      // 首块提前开口：整句还没成形时先把第一个逗号前的半句送去合成，
      // 面试官第一声能早出零点几秒到一秒多；之后恢复整句粒度，语调才自然。
      if (this._firstChunk && (m = this._sentBuf.match(/[\s\S]+?[，、,]/))) {
        this._sentBuf = this._sentBuf.slice(m[0].length);
        this.enqueueSpeak(m[0]);
        this._firstChunk = false;
      }
    },
    flushSentences() {
      const rest = this._sentBuf;
      this._sentBuf = "";
      if (rest.trim()) this.enqueueSpeak(rest);
    },

    enqueueSpeak(text) {
      const clean = text.replace(/[#*`>\-]/g, "").trim();
      if (!clean) return;
      const item = { text: clean };
      if (!this._cloudTtsDead) {
        item.blob = this.fetchTTS(clean).catch(() => null); // 预取：播上一句时这句已在合成
      }
      this._ttsQueue.push(item);
      this.pumpTTS();
    },

    async pumpTTS() {
      if (this._ttsBusy) return;
      this._ttsBusy = true;
      try {
        while (this._ttsQueue.length) {
          const item = this._ttsQueue.shift();
          await this.speakOne(item);
        }
      } finally {
        this._ttsBusy = false;
        this.speaking = false;
      }
    },

    async speakOne(item) {
      if (item.blob) {
        const blob = await item.blob;
        if (blob) {
          await this.playBlob(blob);
          return;
        }
        this._cloudTtsDead = true; // 预取失败：本场剩余句子直接走本地音
        console.warn("云端 TTS 失败，降级本地语音");
      }
      await this.speakLocalOne(item.text);
    },

    async fetchTTS(text) {
      const r = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, style: this.style }),
      });
      if (!r.ok) throw new Error((await r.json()).detail);
      return await r.blob();
    },

    playBlob(blob) {
      return new Promise((resolve) => {
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        this._audio = audio;
        let done = false;
        const fin = () => {
          if (done) return;
          done = true;
          URL.revokeObjectURL(url);
          if (this._audio === audio) this._audio = null;
          if (this._audioDone === fin) this._audioDone = null;
          resolve();
        };
        this._audioDone = fin; // stopTTS 靠它解开队列的 await，否则暂停后队列会卡死
        audio.onplay = () => (this.speaking = true);
        audio.onended = audio.onerror = fin;
        audio.play().catch(fin);
      });
    },

    speakLocalOne(text) {
      return new Promise((resolve) => {
        if (!("speechSynthesis" in window)) return resolve();
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
        u.onend = u.onerror = () => resolve();
        speechSynthesis.speak(u);
      });
    },

    // 音色试听（设置里的按钮）保留整段直出
    async speakCloud(text) {
      this.stopTTS();
      const blob = await this.fetchTTS(text);
      await this.playBlob(blob);
    },

    stopTTS() {
      this._ttsQueue = [];
      this._sentBuf = "";
      this._firstChunk = true;
      if ("speechSynthesis" in window) speechSynthesis.cancel();
      if (this._audio) {
        try { this._audio.pause(); } catch {}
        this._audio = null;
      }
      if (this._audioDone) this._audioDone(); // 解开 playBlob 的 await，队列才能退出
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
    stopMic(send) {
      if (this._media) return this.stopRecorder(send);
      if (this._rec) {
        this.recording = false;
        try {
          this._rec.stop();
        } catch {}
        this._rec = null;
      } else {
        this.recording = false;
      }
      this.interim = "";
      this.stopMeter();
      // 等最后一段 final 结果落地就直接发送。转写错字不再单独过一遍模型修正——
      // 那是每轮多一次完整 LLM 往返；面试官提示词里有转写容错，原文照发它自己会懂。
      if (send) setTimeout(() => this.sendDraft(), 250);
    },

    /* ---------- 麦克风设备 ---------- */
    async openMicStream() {
      // 指定设备失败（拔了/关了）就退回系统默认，别让面试卡在这
      if (this.micId) {
        try {
          return await navigator.mediaDevices.getUserMedia({
            audio: { deviceId: { exact: this.micId } },
          });
        } catch {
          this.micId = "";
          localStorage.removeItem("ic_mic");
          ElMessage.warning("之前选的麦克风不在了，已退回系统默认");
        }
      }
      // 没手动选过，就跟 Windows 的「默认通信设备」走——微信打电话用的就是这个，
      // 蓝牙耳机会被自动切到免提模式，麦克风才通；默认设备常年落在空插孔或虚拟声卡上
      try {
        return await navigator.mediaDevices.getUserMedia({
          audio: { deviceId: { exact: "communications" } },
        });
      } catch {
        return navigator.mediaDevices.getUserMedia({ audio: true });
      }
    },
    async loadMics() {
      try {
        // 先拿一次授权，否则 enumerateDevices 只给空标签，列表全是「麦克风 1/2/3」
        const probe = await navigator.mediaDevices.getUserMedia({ audio: true });
        probe.getTracks().forEach((t) => t.stop());
        const all = await navigator.mediaDevices.enumerateDevices();
        this.mics = all
          .filter((d) => d.kind === "audioinput" && d.deviceId !== "communications")
          .map((d) => ({ id: d.deviceId, label: d.label || "未命名输入设备" }));
        if (this.micId && !this.mics.some((m) => m.id === this.micId)) this.micId = "";
      } catch (e) {
        this.mics = [];
        this.micTest.msg = "拿不到设备列表：" + (e.message || e);
      }
    },
    onMicPick(id) {
      this.micId = id || "";
      if (this.micId) localStorage.setItem("ic_mic", this.micId);
      else localStorage.removeItem("ic_mic");
      this.micTest.msg = "";
      this.micTest.peak = 0;
    },
    async testMic() {
      if (this.micTest.on) return;
      this.micTest.on = true;
      this.micTest.peak = 0;
      this.micTest.msg = "对着麦克风说句话…";
      let stream;
      try {
        stream = await this.openMicStream();
        const Ctx = window.AudioContext || window.webkitAudioContext;
        const ctx = new Ctx();
        const an = ctx.createAnalyser();
        an.fftSize = 512;
        ctx.createMediaStreamSource(stream).connect(an);
        const buf = new Uint8Array(an.frequencyBinCount);
        const t0 = Date.now();
        await new Promise((done) => {
          const tick = () => {
            an.getByteFrequencyData(buf);
            let all = 0;
            for (let j = 0; j < buf.length; j++) all += buf[j];
            this.micTest.peak = Math.max(this.micTest.peak, all / buf.length / 255);
            if (Date.now() - t0 > 4000) return done();
            requestAnimationFrame(tick);
          };
          tick();
        });
        ctx.close();
        const pct = Math.round(this.micTest.peak * 100);
        this.micTest.msg =
          this.micTest.peak >= 0.02
            ? `听到了，峰值 ${pct}%——这个麦克风能用`
            : `全程没有声音（峰值 ${pct}%），换一个设备再试`;
      } catch (e) {
        this.micTest.msg = "打不开麦克风：" + (e.message || e);
      } finally {
        if (stream) stream.getTracks().forEach((t) => t.stop());
        this.micTest.on = false;
      }
    },
    warnSilentMic(peak) {
      const cur = this.mics.find((m) => m.id === this.micId);
      ElMessageBox.alert(
        `这段录音全程没有声音（峰值 ${Math.round(peak * 100)}%），不是没识别出来，是根本没采到。<br><br>` +
        `当前设备：<b>${cur ? cur.label : "系统默认"}</b><br><br>` +
        "常见原因：<br>" +
        "• <b>蓝牙耳机</b>：麦克风只在「免提/Hands-Free」端点上，选带 Hands-Free 字样的那个<br>" +
        "• 系统默认输入是空插孔或虚拟声卡（如虚拟音频设备），录出来就是静音<br>" +
        "• 麦克风被系统静音，或 Windows 隐私设置里没放开麦克风权限<br><br>" +
        "去「设置 → 语音转写 → 麦克风」挑一个，用旁边的测试按钮确认能看到电平。",
        "没采到声音",
        { dangerouslyUseHTMLString: true, confirmButtonText: "去设置" }
      ).then(() => this.openSettings()).catch(() => {});
    },

    /* ---------- MediaRecorder 通路（Electron / 无 Web Speech API 的浏览器）---------- */
    async startRecorder() {
      this.stopTTS();
      try {
        const stream = await this.openMicStream();
        const mr = new MediaRecorder(stream, { mimeType: "audio/webm" });
        this._chunks = [];
        this._peak = 0;               // 这一段录音的最大电平，用来分辨「没说话」和「选错麦克风」
        mr.ondataavailable = (e) => e.data.size && this._chunks.push(e.data);
        this._media = mr;
        this.recording = true;
        mr.start();
        // 这条通路没有实时文字，音量表是唯一的「她听到我了」反馈，所以用真实电平
        this.startMeter(stream);
      } catch (e) {
        ElMessage.error("无法访问麦克风：" + e.message);
      }
    },
    stopRecorder(send) {
      const mr = this._media;
      if (!mr) return;
      this._media = null;
      this.recording = false;
      this.stopMeter();
      mr.onstop = async () => {
        mr.stream.getTracks().forEach((t) => t.stop());
        if (!send) return;
        const blob = new Blob(this._chunks, { type: "audio/webm" });
        this._chunks = [];
        const peak = this._peak || 0;
        // 全程没有电平 = 麦克风选错了或被静音，跟「说了但没识别出来」是两回事
        if (peak < 0.02 || blob.size < 1000) return this.warnSilentMic(peak);
        this.transcribing = true;
        try {
          const fd = new FormData();
          fd.append("file", blob, "answer.webm");
          const r = await fetch("/api/stt", { method: "POST", body: fd });
          if (!r.ok) throw new Error((await r.json()).detail);
          const d = await r.json();
          if (d.text) {
            this.draft = (this.draft ? this.draft + " " : "") + d.text;
            this.sendDraft();
          } else {
            ElMessage.warning("没识别到内容，再说一次或者直接打字");
          }
        } catch (e) {
          ElMessage.error("转写失败：" + e.message + "，可以改用打字回答");
        } finally {
          this.transcribing = false;
        }
      };
      mr.stop();
    },

    /* ---------- 音量表（只在拿到音频流时用真实电平） ---------- */
    startMeter(stream) {
      try {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx || !stream) return;
        const ctx = new Ctx();
        const an = ctx.createAnalyser();
        an.fftSize = 512;
        an.smoothingTimeConstant = 0.72;
        ctx.createMediaStreamSource(stream).connect(an);
        const buf = new Uint8Array(an.frequencyBinCount);
        const edges = [0, 0.08, 0.18, 0.34, 0.58, 1];
        this._actx = ctx;
        this.meterLive = true;
        const tick = () => {
          if (!this.recording) return;
          an.getByteFrequencyData(buf);
          const n = buf.length;
          let all = 0;
          for (let j = 0; j < n; j++) all += buf[j];
          this._peak = Math.max(this._peak || 0, all / n / 255);
          this.meterBars = edges.slice(0, 5).map((_, i) => {
            const a = Math.floor(edges[i] * n);
            const b = Math.max(a + 1, Math.floor(edges[i + 1] * n));
            let sum = 0;
            for (let j = a; j < b; j++) sum += buf[j];
            return Math.max(0.16, Math.min(1, sum / (b - a) / 105));
          });
          this._raf = requestAnimationFrame(tick);
        };
        tick();
      } catch {
        this.meterLive = false; // 表坏了不影响录音
      }
    },
    stopMeter() {
      if (this._raf) cancelAnimationFrame(this._raf);
      this._raf = null;
      this.meterBars = [0.16, 0.16, 0.16, 0.16, 0.16];
      this.meterLive = false;
      if (this._actx) {
        try {
          this._actx.close();
        } catch {}
        this._actx = null;
      }
    },

    scrollDown() {
      if (this._chatScrollTimer) return;
      this._chatScrollTimer = setTimeout(() => {
        this._chatScrollTimer = null;
        this.$nextTick(() => {
          const el = this.$refs.chatBox;
          if (el) el.scrollTop = el.scrollHeight;
        });
      }, 0);
    },
  },
});

app.use(ElementPlus, ZH_CN ? { locale: ZH_CN } : {});
// 图标统一加 Icon 前缀：在 DOM 内模板里 <icon-setting> 不会和真实标签名撞车
if (window.ElementPlusIconsVue) {
  for (const [name, comp] of Object.entries(window.ElementPlusIconsVue)) {
    app.component("Icon" + name, comp);
  }
}
app.mount("#app");
