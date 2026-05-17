const state = {
  candidates: [],
  wordbook: [],
};

const el = {
  tabs: document.querySelectorAll(".tab-button"),
  views: {
    extract: document.querySelector("#extract-view"),
    vocabulary: document.querySelector("#vocabulary-view"),
    card: document.querySelector("#word-card-view"),
  },
  extractForm: document.querySelector("#extract-form"),
  uploadForm: document.querySelector("#upload-form"),
  inputPath: document.querySelector("#input-path"),
  limit: document.querySelector("#limit"),
  minScore: document.querySelector("#min-score"),
  persist: document.querySelector("#persist"),
  uploadFile: document.querySelector("#upload-file"),
  list: document.querySelector("#candidate-list"),
  template: document.querySelector("#candidate-template"),
  notice: document.querySelector("#notice"),
  candidateCount: document.querySelector("#candidate-count"),
  documentCount: document.querySelector("#document-count"),
  senseCount: document.querySelector("#sense-count"),
  learningCount: document.querySelector("#learning-count"),
  knownCount: document.querySelector("#known-count"),
  ignoredCount: document.querySelector("#ignored-count"),
  refreshSummary: document.querySelector("#refresh-summary"),
  clearDatabase: document.querySelector("#clear-database"),
  reloadVocabulary: document.querySelector("#reload-vocabulary"),
  wordbookList: document.querySelector("#wordbook-list"),
  backToVocabulary: document.querySelector("#back-to-vocabulary"),
  cardWord: document.querySelector("#card-word"),
  cardSub: document.querySelector("#card-sub"),
  cardStatus: document.querySelector("#card-status"),
  cardMeaning: document.querySelector("#card-meaning"),
  cardDefinition: document.querySelector("#card-definition"),
  cardSentence: document.querySelector("#card-sentence"),
  cardContext: document.querySelector("#card-context"),
  formList: document.querySelector("#form-list"),
};

for (const tab of el.tabs) {
  tab.addEventListener("click", async () => {
    const view = tab.dataset.view;
    if (view === "vocabulary") {
      await loadVocabulary();
    }
    showView(view);
  });
}

el.extractForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await extractCandidates();
});

el.uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await uploadFile();
});

el.refreshSummary.addEventListener("click", async () => {
  await refreshSummary();
});

el.clearDatabase.addEventListener("click", async () => {
  await clearDatabase();
});

el.reloadVocabulary.addEventListener("click", async () => {
  await loadVocabulary();
});

el.backToVocabulary.addEventListener("click", () => {
  showView("vocabulary");
});

refreshSummary();

function showView(viewName) {
  for (const [name, view] of Object.entries(el.views)) {
    view.hidden = name !== viewName;
  }
  for (const tab of el.tabs) {
    tab.classList.toggle("active", tab.dataset.view === viewName);
  }
}

async function extractCandidates() {
  setNotice("");
  setBusy(true);
  try {
    const response = await fetch("/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        input_path: el.inputPath.value,
        limit: Number(el.limit.value || 30),
        min_score: Number(el.minScore.value || 0),
        persist: el.persist.checked,
      }),
    });
    const data = await readJson(response);
    state.candidates = data.candidates || [];
    renderCandidates();
    await refreshSummary();
  } catch (error) {
    setNotice(error.message, true);
  } finally {
    setBusy(false);
  }
}

async function uploadFile() {
  setNotice("");
  const file = el.uploadFile.files[0];
  if (!file) {
    setNotice("请选择 .txt 文件。", true);
    return;
  }

  const body = new FormData();
  body.append("file", file);

  try {
    const response = await fetch("/upload", { method: "POST", body });
    const data = await readJson(response);
    renderFileOptions(data.files || [], data.input_path);
    el.uploadFile.value = "";
    setNotice(`已上传 ${data.filename}`);
  } catch (error) {
    setNotice(error.message, true);
  }
}

function renderFileOptions(files, selectedPath) {
  el.inputPath.replaceChildren();
  for (const file of files) {
    const option = document.createElement("option");
    option.value = file.path;
    option.textContent = file.name;
    option.selected = file.path === selectedPath;
    el.inputPath.append(option);
  }
}

function renderCandidates() {
  el.list.replaceChildren();
  el.candidateCount.textContent = state.candidates.length;

  for (const candidate of state.candidates) {
    const node = el.template.content.cloneNode(true);
    const article = node.querySelector(".candidate");
    article.dataset.senseId = candidate.sense_id ?? "";
    article.dataset.occurrenceId = candidate.occurrence_id ?? "";

    node.querySelector(".candidate-word").textContent = candidate.word || candidate.lemma;
    node.querySelector(".candidate-sub").textContent = `${candidate.lemma} / ${candidate.status || "new"}`;
    node.querySelector(".score").textContent = formatNumber(candidate.unknown_score);
    node.querySelector(".meaning").textContent = candidate.meaning_in_context || "";
    node.querySelector(".definition").textContent = candidate.definition_en || "";
    node.querySelector(".sentence").textContent = candidate.sample_sentence || "";
    node.querySelector(".context").textContent = candidate.context || "";
    node.querySelector(".frequency").textContent = candidate.frequency ?? "";
    node.querySelector(".sense-id").textContent = candidate.sense_id ?? "N/A";
    node.querySelector(".occurrence-id").textContent = candidate.occurrence_id ?? "N/A";
    node.querySelector(".method").textContent = candidate.selection_method || "";

    for (const button of node.querySelectorAll(".actions button")) {
      button.disabled = !candidate.sense_id;
      button.addEventListener("click", async () => {
        await updateSenseStatus(candidate, button.dataset.status, article);
      });
    }

    el.list.append(node);
  }
}

async function updateSenseStatus(candidate, status, article) {
  setNotice("");
  try {
    const response = await fetch("/sense-status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sense_id: candidate.sense_id,
        occurrence_id: candidate.occurrence_id,
        status,
      }),
    });
    const data = await readJson(response);
    state.candidates = state.candidates.filter((item) => item !== candidate);
    article.remove();
    el.candidateCount.textContent = state.candidates.length;
    setNotice(`${data.lemma} / ${data.meaning_zh} -> ${data.status}`);
    await refreshSummary();
  } catch (error) {
    setNotice(error.message, true);
  }
}

async function clearDatabase() {
  setNotice("");
  const confirmed = window.confirm("确认清空当前数据库？这会删除所有文档、义项、出现记录和用户状态。");
  if (!confirmed) {
    return;
  }

  setBusy(true);
  el.clearDatabase.disabled = true;
  try {
    const response = await fetch("/database/clear", { method: "POST" });
    await readJson(response);
    state.candidates = [];
    state.wordbook = [];
    renderCandidates();
    renderVocabulary();
    showView("extract");
    await refreshSummary();
    setNotice("数据库已清空。");
  } catch (error) {
    setNotice(error.message, true);
  } finally {
    setBusy(false);
    el.clearDatabase.disabled = false;
  }
}

async function loadVocabulary() {
  setNotice("");
  try {
    const response = await fetch("/vocabulary");
    const data = await readJson(response);
    state.wordbook = data.items || [];
    renderVocabulary();
  } catch (error) {
    setNotice(error.message, true);
  }
}

function renderVocabulary() {
  el.wordbookList.replaceChildren();

  if (state.wordbook.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "当前生词本为空。";
    el.wordbookList.append(empty);
    return;
  }

  for (const item of state.wordbook) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "wordbook-item";
    button.addEventListener("click", async () => {
      await openWordCard(item.sense_id);
    });

    const main = document.createElement("span");
    main.className = "wordbook-main";
    const word = document.createElement("strong");
    word.textContent = item.word || item.lemma;
    const meaning = document.createElement("span");
    meaning.textContent = `${item.pos ? `${item.pos}. ` : ""}${item.meaning_zh || ""}`;
    main.append(word, meaning);

    const meta = document.createElement("span");
    meta.className = "wordbook-meta";
    meta.textContent = `${item.lemma || ""}${item.added_at ? ` / ${item.added_at}` : ""}`;

    button.append(main, meta);
    el.wordbookList.append(button);
  }
}

async function openWordCard(senseId) {
  setNotice("");
  try {
    const response = await fetch(`/vocabulary/${senseId}`);
    const card = await readJson(response);
    renderWordCard(card);
    showView("card");
  } catch (error) {
    setNotice(error.message, true);
  }
}

function renderWordCard(card) {
  el.cardWord.textContent = card.word || card.lemma;
  el.cardSub.textContent = `lemma: ${card.lemma || ""}${card.frequency_rank ? ` / freq ${card.frequency_rank}` : ""}`;
  el.cardStatus.textContent = card.status || "";
  el.cardDefinition.textContent = card.definition_en || "";
  el.cardSentence.textContent = card.sentence || "";
  el.cardContext.textContent = card.context || "";

  el.cardMeaning.replaceChildren();
  if (card.pos) {
    const pos = document.createElement("span");
    pos.className = "pos-label";
    pos.textContent = `${card.pos}.`;
    el.cardMeaning.append(pos);
  }
  const meaning = document.createElement("strong");
  meaning.textContent = card.meaning_zh || "";
  el.cardMeaning.append(meaning);

  renderForms(card.forms || []);
}

function renderForms(forms) {
  el.formList.replaceChildren();
  if (forms.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "当前 ECDICT 未找到相关形式。";
    el.formList.append(empty);
    return;
  }

  for (const form of forms) {
    const row = document.createElement("article");
    row.className = "form-row";

    const head = document.createElement("div");
    head.className = "form-head";
    const word = document.createElement("strong");
    word.textContent = form.word;
    const pos = document.createElement("span");
    pos.textContent = form.pos || "";
    head.append(word, pos);

    const meanings = document.createElement("div");
    meanings.className = "form-meanings";
    for (const meaning of form.meanings || []) {
      const item = document.createElement("span");
      const text = `${meaning.pos ? `${meaning.pos}. ` : ""}${meaning.text}`;
      if (meaning.selected) {
        const selected = document.createElement("strong");
        selected.textContent = text;
        item.append(selected);
      } else {
        item.textContent = text;
      }
      meanings.append(item);
    }

    row.append(head, meanings);
    el.formList.append(row);
  }
}

async function refreshSummary() {
  try {
    const response = await fetch("/database/summary");
    const data = await readJson(response);
    const tables = data.tables || {};
    const statuses = data.user_sense_statuses || {};
    el.documentCount.textContent = tables.documents || 0;
    el.senseCount.textContent = tables.word_senses || 0;
    el.learningCount.textContent = statuses.learning || 0;
    el.knownCount.textContent = statuses.known || 0;
    el.ignoredCount.textContent = statuses.ignored || 0;
  } catch (error) {
    setNotice(error.message, true);
  }
}

async function readJson(response) {
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Request failed.");
  }
  return data;
}

function setBusy(busy) {
  document.querySelector("#extract-button").disabled = busy;
}

function setNotice(message, isError = false) {
  el.notice.hidden = !message;
  el.notice.textContent = message;
  el.notice.classList.toggle("error", isError);
}

function formatNumber(value) {
  const number = Number(value);
  if (Number.isNaN(number)) {
    return "";
  }
  return number.toFixed(2);
}
