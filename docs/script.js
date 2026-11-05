/* NOC-01 · Campus Latency Copilot frontend
 * Two run modes:
 *   live   — talks to the FastAPI backend (/api/*), real DeepSeek or rule fallback
 *   static — GitHub Pages demo, replays traces saved in demo-data.json
 */
(function () {
  "use strict";

  var state = {
    mode: "probing",
    cases: [],
    network: null,
    demo: null,
    activeCase: null,
    busy: false,
    timer: null
  };

  var el = {
    caseSelect: document.getElementById("caseSelect"),
    caseHelp: document.getElementById("caseHelp"),
    scenarioSelect: document.getElementById("scenarioSelect"),
    promptInput: document.getElementById("promptInput"),
    apiKeyInput: document.getElementById("apiKeyInput"),
    toggleKeyBtn: document.getElementById("toggleKeyBtn"),
    skillToggle: document.getElementById("skillToggle"),
    roundRange: document.getElementById("roundRange"),
    roundValue: document.getElementById("roundValue"),
    runBtn: document.getElementById("runBtn"),
    runHint: document.getElementById("runHint"),
    linkList: document.getElementById("linkList"),
    healthCaption: document.getElementById("healthCaption"),
    linkLamp: document.getElementById("linkLamp"),
    modeLabel: document.getElementById("modeLabel"),
    footerMode: document.getElementById("footerMode"),
    readSource: document.getElementById("readSource"),
    readModel: document.getElementById("readModel"),
    readRounds: document.getElementById("readRounds"),
    readCalls: document.getElementById("readCalls"),
    readElapsed: document.getElementById("readElapsed"),
    banner: document.getElementById("banner"),
    reportEmpty: document.getElementById("reportEmpty"),
    reportBody: document.getElementById("reportBody"),
    traceList: document.getElementById("traceList"),
    evidenceBody: document.getElementById("evidenceBody")
  };

  // ---------------------------------------------------------------- helpers

  function esc(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function inline(text) {
    var out = esc(text);
    out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
    out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>');
    return out;
  }

  function num(value, digits) {
    if (value === null || value === undefined) return "null";
    if (typeof value !== "number") return String(value);
    return value.toFixed(digits === undefined ? 2 : digits);
  }

  function pct(value, digits) {
    if (value === null || value === undefined) return "null";
    return (value * 100).toFixed(digits === undefined ? 0 : digits) + "%";
  }

  // -------------------------------------------------------- markdown -> html

  function renderMarkdown(markdown) {
    var lines = String(markdown || "").replace(/\r\n/g, "\n").split("\n");
    var html = [];
    var i = 0;

    function isTableRow(line) { return line.indexOf("|") !== -1; }
    function isTableSep(line) { return /^\s*\|?[\s:\-|]+\|?\s*$/.test(line) && line.indexOf("-") !== -1; }

    while (i < lines.length) {
      var line = lines[i];

      if (!line.trim()) { i += 1; continue; }

      if (/^```/.test(line)) {
        var buf = [];
        i += 1;
        while (i < lines.length && !/^```/.test(lines[i])) { buf.push(lines[i]); i += 1; }
        i += 1;
        html.push("<pre><code>" + esc(buf.join("\n")) + "</code></pre>");
        continue;
      }

      var heading = /^(#{1,4})\s+(.*)$/.exec(line);
      if (heading) {
        var level = heading[1].length + 1;
        if (level > 4) level = 4;
        html.push("<h" + level + ">" + inline(heading[2].trim()) + "</h" + level + ">");
        i += 1;
        continue;
      }

      if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { html.push("<hr />"); i += 1; continue; }

      if (/^>\s?/.test(line)) {
        var quote = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) {
          quote.push(lines[i].replace(/^>\s?/, ""));
          i += 1;
        }
        html.push("<blockquote><p>" + inline(quote.join(" ")) + "</p></blockquote>");
        continue;
      }

      if (isTableRow(line) && i + 1 < lines.length && isTableSep(lines[i + 1])) {
        var headerCells = splitRow(line);
        i += 2;
        var rows = [];
        while (i < lines.length && isTableRow(lines[i])) {
          rows.push(splitRow(lines[i]));
          i += 1;
        }
        html.push("<table><thead><tr>" +
          headerCells.map(function (c) { return "<th>" + inline(c) + "</th>"; }).join("") +
          "</tr></thead><tbody>" +
          rows.map(function (row) {
            return "<tr>" + row.map(function (c) { return "<td>" + inline(c) + "</td>"; }).join("") + "</tr>";
          }).join("") +
          "</tbody></table>");
        continue;
      }

      if (/^\s*([-*+])\s+/.test(line)) {
        var items = [];
        while (i < lines.length && /^\s*([-*+])\s+/.test(lines[i])) {
          items.push(lines[i].replace(/^\s*([-*+])\s+/, ""));
          i += 1;
        }
        html.push("<ul>" + items.map(function (t) { return "<li>" + inline(t) + "</li>"; }).join("") + "</ul>");
        continue;
      }

      if (/^\s*\d+[.)]\s+/.test(line)) {
        var oitems = [];
        while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
          oitems.push(lines[i].replace(/^\s*\d+[.)]\s+/, ""));
          i += 1;
        }
        html.push("<ol>" + oitems.map(function (t) { return "<li>" + inline(t) + "</li>"; }).join("") + "</ol>");
        continue;
      }

      var para = [line.trim()];
      i += 1;
      while (i < lines.length && lines[i].trim() &&
             !/^(#{1,4})\s/.test(lines[i]) &&
             !/^\s*([-*+])\s+/.test(lines[i]) &&
             !/^\s*\d+[.)]\s+/.test(lines[i]) &&
             !/^>/.test(lines[i]) &&
             !/^```/.test(lines[i]) &&
             !isTableRow(lines[i])) {
        para.push(lines[i].trim());
        i += 1;
      }
      html.push("<p>" + inline(para.join(" ")) + "</p>");
    }

    return html.join("\n");
  }

  function splitRow(line) {
    var trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
    return trimmed.split("|").map(function (cell) { return cell.trim(); });
  }

  // ------------------------------------------------------------- rendering

  function showBanner(message, kind) {
    if (!message) { el.banner.hidden = true; return; }
    el.banner.textContent = message;
    el.banner.dataset.kind = kind || "info";
    el.banner.hidden = false;
  }

  function setReadout(result, elapsed) {
    var stats = result.stats || {};
    el.readSource.textContent = result.source || "—";
    el.readModel.textContent = (result.model || "—").replace("deepseek/", "");
    el.readRounds.textContent = stats.tool_rounds === undefined ? "—" : String(stats.tool_rounds);
    el.readCalls.textContent = stats.llm_calls === undefined ? (result.trace || []).filter(function (t) { return t.tool_call; }).length : String(stats.llm_calls);
    el.readElapsed.textContent = (elapsed / 1000).toFixed(1) + "s";
  }

  function renderReport(markdown) {
    el.reportEmpty.hidden = true;
    el.reportBody.hidden = false;
    el.reportBody.innerHTML = renderMarkdown(markdown);
  }

  function renderTrace(trace) {
    if (!trace || !trace.length) {
      el.traceList.innerHTML = '<li class="trace-placeholder">未记录到工具调用。</li>';
      return;
    }
    var html = trace.map(function (step) {
      if (step.tool_call) {
        var args = step.args && Object.keys(step.args).length ? JSON.stringify(step.args) : "{}";
        return '<li><div class="trace-call"><span>▸ ' + esc(step.tool_call) + "</span>" +
          '<span class="trace-args">' + esc(args) + "</span></div></li>";
      }
      var pretty = step.result;
      try { pretty = JSON.stringify(JSON.parse(step.result), null, 2); } catch (e) { /* keep raw */ }
      if (pretty && pretty.length > 2400) pretty = pretty.slice(0, 2400) + "\n… (truncated)";
      return '<li><div class="trace-call"><span>◂ ' + esc(step.tool) + "</span></div>" +
        '<pre class="trace-result">' + esc(pretty) + "</pre></li>";
    }).join("");
    el.traceList.innerHTML = html;
  }

  function renderEvidence(trace) {
    var latest = {};
    var order = [];
    var delay = null;

    (trace || []).forEach(function (step) {
      if (step.tool !== "get_link_metrics" || !step.result) return;
      var data;
      try { data = JSON.parse(step.result); } catch (e) { return; }
      if (!data || !data.link_id) return;
      if (!Object.prototype.hasOwnProperty.call(latest, data.link_id)) order.push(data.link_id);
      latest[data.link_id] = data;
      if (data._hint) delete data._hint;
    });

    (trace || []).forEach(function (step) {
      if (step.tool !== "analyze_delay_components" || !step.result) return;
      try { delay = JSON.parse(step.result); } catch (e) { delay = null; }
    });

    if (!order.length && !delay) {
      el.evidenceBody.innerHTML = '<p class="trace-placeholder">本次运行没有可展示的链路指标。</p>';
      return;
    }

    var html = ['<p class="evidence-note">证据均直接来自工具返回值，未做任何人工补全；null 表示监控缺失。</p>'];

    if (order.length) {
      html.push("<table><thead><tr><th>链路</th><th>利用率</th><th>RTT</th><th>丢包</th><th>队列</th><th>到达率</th></tr></thead><tbody>");
      order.forEach(function (id) {
        var m = latest[id];
        var util = m.utilization;
        var loss = m.packet_loss_percent;
        var bad = (util !== null && util >= 0.8) || (loss !== null && loss >= 1.0);
        var warn = !bad && ((util !== null && util >= 0.6) || (loss !== null && loss >= 0.1));
        html.push("<tr><td><code>" + esc(id) + "</code></td>" +
          "<td>" + (bad ? '<span class="metric-chip is-bad">' : warn ? '<span class="metric-chip is-warn">' : '<span class="metric-chip">') + pct(util) + "</span></td>" +
          "<td>" + esc(num(m.rtt_ms)) + "</td>" +
          "<td>" + esc(num(loss)) + "%</td>" +
          "<td>" + esc(num(m.avg_queue_depth, 0)) + "</td>" +
          "<td>" + esc(num(m.arrival_rate_pps, 0)) + " pps</td></tr>");
      });
      html.push("</tbody></table>");
    }

    if (delay && delay.delay_components) {
      var c = delay.delay_components;
      var cmp = delay.comparison || {};
      html.push('<h3 style="margin-top:22px;font-family:var(--font-display);font-size:14px;color:var(--text-soft)">延迟分解 · ' + esc(delay.link_id) + "</h3>");
      html.push('<p class="evidence-note">' +
        '传播 ' + esc(num(c.propagation_delay_ms, 3)) + " ms · " +
        '传输 ' + esc(num(c.transmission_delay_ms, 3)) + " ms · " +
        '排队 ' + esc(num(c.queue_delay_ms, 3)) + " ms · " +
        '处理 ' + esc(num(c.processing_delay_ms, 3)) + " ms · " +
        '合计 ' + esc(num(c.total_delay_ms, 3)) + " ms</p>");
      html.push('<p class="evidence-note">理论 RTT ' + esc(num(cmp.estimated_rtt_ms, 3)) +
        " ms ／ 实测 RTT " + esc(num(cmp.observed_rtt_ms, 3)) +
        " ms ／ 比值 " + esc(num(cmp.rtt_ratio_estimated_over_observed, 3)) + "</p>");
      html.push("<details class=\"raw\"><summary>查看工具原始 JSON</summary><pre>" +
        esc(JSON.stringify(delay, null, 2)) + "</pre></details>");
    }

    el.evidenceBody.innerHTML = html.join("");
  }

  function renderLinks() {
    if (!state.network) {
      el.linkList.innerHTML = '<li class="link-item placeholder">暂无拓扑数据。</li>';
      return;
    }
    var scenario = el.scenarioSelect.value;
    var scenarioData, metrics;
    if (Array.isArray(state.network.scenarios)) {
      // 实时后端：GET /api/network?scenario=x 返回单场景扁平结构
      scenarioData = { description: state.network.description };
      metrics = state.network.metrics || {};
    } else {
      // 静态演示：demo-data.json 按场景嵌套
      scenarioData = (state.network.scenarios || {})[scenario] || {};
      metrics = scenarioData.link_metrics || {};
    }
    var links = state.network.topology.links;

    el.healthCaption.textContent = scenarioData.description || "读取当前场景的实时指标";

    el.linkList.innerHTML = links.map(function (link) {
      var m = metrics[link.id] || {};
      var util = m.utilization;
      var rtt = m.rtt_ms;
      var cls = "";
      if (util !== null && util !== undefined && util >= 0.8) cls = "is-bad";
      else if (util !== null && util !== undefined && util >= 0.6) cls = "is-warn";
      var width = util === null || util === undefined ? 0 : Math.min(util * 100, 100);
      var rttCls = rtt !== null && rtt !== undefined && rtt >= 40 ? " is-bad" : "";
      return '<li class="link-item">' +
        '<div class="link-top"><span class="link-name">' + esc(link.id) + "</span>" +
        '<span class="link-rtt' + rttCls + '">' + esc(num(rtt)) + " ms</span></div>" +
        '<div class="link-bar ' + cls + '"><span style="width:' + width.toFixed(0) + '%"></span></div>' +
        "</li>";
    }).join("");
  }

  // ------------------------------------------------------------- data load

  function fetchJson(url, options) {
    return fetch(url, options).then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    });
  }

  function populateCases(cases) {
    state.cases = cases;
    el.caseSelect.innerHTML = '<option value="">自定义工单</option>' + cases.map(function (item) {
      return '<option value="' + esc(item.id) + '">' + esc(item.name) + " · " + esc(item.scenario) + "</option>";
    }).join("");
  }

  function applyCase(caseId) {
    var item = state.cases.filter(function (c) { return c.id === caseId; })[0];
    state.activeCase = item || null;
    if (!item) {
      el.caseHelp.textContent = "自定义工单：手动填写场景与描述";
      return;
    }
    el.scenarioSelect.value = item.scenario;
    el.promptInput.value = item.prompt;
    el.caseHelp.textContent = item.description;
    renderLinks();
  }

  function bootLive() {
    state.mode = "live";
    el.linkLamp.dataset.state = "live";
    el.modeLabel.textContent = "MODE · 实时后端";
    el.footerMode.textContent = "backend live";
    el.runHint.textContent = "后端在线：将调用 DeepSeek 与本地工具（无 Key 时自动降级）";

    return Promise.all([
      fetchJson("api/cases"),
      fetchJson("api/network?scenario=" + encodeURIComponent(el.scenarioSelect.value || "congestion"))
    ])
      .then(function (results) {
        populateCases(results[0].cases || []);
        state.network = results[1];
        renderLinks();
        showBanner("", null);
      });
  }

  function bootStatic(error) {
    state.mode = "static";
    el.linkLamp.dataset.state = "offline";
    el.modeLabel.textContent = "MODE · 静态演示";
    el.footerMode.textContent = "static demo · run4 replay";
    el.runHint.textContent = "未检测到后端：回放 results/repeat/run4 中保存的真实 trace";

    return fetchJson("demo-data.json").then(function (demo) {
      state.demo = demo;
      state.network = demo.network;
      populateCases(demo.cases || []);
      renderLinks();
      showBanner(
        "静态演示模式：本页没有连接后端，点击「开始调查」将回放课程实验中保存的真实 Agent trace。" +
        (error ? "（探测失败：" + error.message + "）" : ""),
        "info"
      );
    });
  }

  // ------------------------------------------------------------- run agent

  function setBusy(busy) {
    state.busy = busy;
    el.runBtn.disabled = busy;
    el.runBtn.querySelector(".btn-label").textContent = busy ? "调查中…" : "开始调查";
    if (busy) {
      var started = Date.now();
      el.readElapsed.textContent = "0.0s";
      state.timer = window.setInterval(function () {
        el.readElapsed.textContent = ((Date.now() - started) / 1000).toFixed(1) + "s";
      }, 100);
    } else if (state.timer) {
      window.clearInterval(state.timer);
      state.timer = null;
    }
  }

  function applyResult(result, elapsed) {
    setReadout(result, elapsed);
    if (result.warning) showBanner(result.warning, "info");
    else showBanner("", null);
    renderReport(result.output);
    renderTrace(result.trace);
    renderEvidence(result.trace);
    switchTab("report");
  }

  function runLive() {
    var body = {
      prompt: el.promptInput.value.trim(),
      scenario: el.scenarioSelect.value,
      use_skill: el.skillToggle.checked,
      max_tool_rounds: parseInt(el.roundRange.value, 10),
      api_key: el.apiKeyInput.value.trim() || null
    };
    var started = Date.now();
    return fetchJson("api/investigate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (result) {
      applyResult(result, Date.now() - started);
    });
  }

  function runStatic() {
    var demo = state.demo || { traces: {} };
    var caseId = state.activeCase ? state.activeCase.id : "case1_congestion";
    var record = demo.traces[caseId] || demo.traces.case1_congestion;
    if (!record) throw new Error("demo-data.json 中没有可回放的记录");

    var expected = 900 + Math.random() * 500;
    return new Promise(function (resolve) {
      window.setTimeout(function () {
        applyResult({
          output: record.output,
          trace: record.trace,
          stats: {
            tool_rounds: (record.trace || []).filter(function (t) { return t.tool_call; }).length,
            llm_calls: 0
          },
          model: record.model || "qwen3.5:0.8b",
          source: "demo-replay",
          warning: "静态演示：以下内容来自 " + (record.group || "C_Agent_Tools_Skill") +
            " 的真实运行记录（" + caseId + "），非本次实时生成。"
        }, expected);
        resolve();
      }, 650);
    });
  }

  function run() {
    if (state.busy) return;
    if (!el.promptInput.value.trim()) {
      showBanner("请先填写工程师描述，或选择一个预置案例。", "error");
      return;
    }
    setBusy(true);
    showBanner("", null);
    var task = state.mode === "live" ? runLive() : runStatic();
    task.catch(function (error) {
      showBanner("调查失败：" + error.message, "error");
    }).then(function () {
      setBusy(false);
    });
  }

  // ------------------------------------------------------------------- tabs

  function switchTab(name) {
    var tabs = document.querySelectorAll(".tab");
    tabs.forEach(function (tab) {
      var on = tab.dataset.tab === name;
      tab.classList.toggle("is-active", on);
      tab.setAttribute("aria-selected", on ? "true" : "false");
    });
    document.querySelectorAll(".view").forEach(function (view) {
      view.classList.toggle("is-active", view.id === "view-" + name);
    });
  }

  // ------------------------------------------------------------------ wiring

  el.caseSelect.addEventListener("change", function () { applyCase(el.caseSelect.value); });
  el.scenarioSelect.addEventListener("change", function () {
    if (state.mode === "live") {
      fetchJson("api/network?scenario=" + encodeURIComponent(el.scenarioSelect.value))
        .then(function (data) { state.network = data; renderLinks(); })
        .catch(function (error) { showBanner("网络指标加载失败：" + error.message, "error"); });
    } else {
      renderLinks();
    }
  });
  el.roundRange.addEventListener("input", function () { el.roundValue.textContent = el.roundRange.value; });
  el.runBtn.addEventListener("click", run);

  el.toggleKeyBtn.addEventListener("click", function () {
    var masked = el.apiKeyInput.type === "password";
    el.apiKeyInput.type = masked ? "text" : "password";
    el.toggleKeyBtn.textContent = masked ? "隐藏" : "显示";
    el.toggleKeyBtn.setAttribute("aria-pressed", masked ? "true" : "false");
  });

  document.querySelectorAll(".tab").forEach(function (tab) {
    tab.addEventListener("click", function () { switchTab(tab.dataset.tab); });
  });

  document.addEventListener("keydown", function (event) {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") run();
  });

  bootLive().catch(function (error) { return bootStatic(error); })
    .catch(function (error) {
      showBanner("前端初始化失败：" + error.message, "error");
      el.caseSelect.innerHTML = '<option value="">无法载入案例</option>';
    });
})();