const state = {
  brand: null,
  selectedIdea: null,
  platforms: [],
  campaign: null,
  editing: null,
  ai: null,
  apps: [],
};

const statusBox = document.getElementById("status-box");
const dnaForm = document.getElementById("dna-form");
const ideasForm = document.getElementById("ideas-form");
const campaignForm = document.getElementById("campaign-form");
const catalogForm = document.getElementById("catalog-form");
const dnaBtn = document.getElementById("dna-btn");
const ideasBtn = document.getElementById("ideas-btn");
const generateBtn = document.getElementById("generate-btn");
const brandPanel = document.getElementById("brand-panel");
const ideasGrid = document.getElementById("ideas-grid");
const resultsContainer = document.getElementById("results-container");
const channelPack = document.getElementById("channel-pack");
const platformsContainer = document.getElementById("platforms-container");
const clipDurationInput = document.getElementById("clip-duration");
const clipDurationValue = document.getElementById("clip-duration-value");
const aiStatusBox = document.getElementById("ai-status");
const catalogList = document.getElementById("catalog-list");
const editorModal = document.getElementById("editor-modal");
const agentChat = document.getElementById("agent-chat");
const magicOutput = document.getElementById("magic-output");
const libraryList = document.getElementById("library-list");

function setStatus(message, isError = false) {
  statusBox.textContent = message;
  statusBox.classList.toggle("error", isError);
}

function escapeHtml(raw = "") {
  return String(raw)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function requireBrand() {
  if (!state.brand?.id) {
    setStatus("Build Brand DNA first.", true);
    showPanel("studio");
    setStep(1);
    return false;
  }
  return true;
}

function showPanel(name) {
  document.querySelectorAll(".panel-section").forEach((node) => {
    node.classList.toggle("active-panel", node.dataset.panelSection === name);
  });
}

function setStep(stepNumber) {
  showPanel("studio");
  document.querySelectorAll(".step").forEach((node) => {
    const active = Number(node.dataset.step) === stepNumber;
    node.classList.toggle("active", active);
    node.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".stage").forEach((node) => {
    node.classList.toggle("active", Number(node.dataset.stage) === stepNumber);
  });
}

function renderAiStatus(status) {
  state.ai = status;
  if (!aiStatusBox) return;
  aiStatusBox.classList.remove("live", "sample");
  if (status?.enabled) {
    aiStatusBox.classList.add("live");
    aiStatusBox.textContent = `OpenRouter live · text ${status.text_model} · image ${status.image_model}`;
  } else {
    aiStatusBox.classList.add("sample");
    aiStatusBox.textContent =
      "Sample mode active. Add OPENROUTER_API_KEY in Cursor Secrets for live multi-model AI.";
  }
}

function renderPlatforms(platforms) {
  state.platforms = platforms;
  platformsContainer.innerHTML = "";
  platforms.forEach((platform, index) => {
    const label = document.createElement("label");
    label.className = "platform-option";
    label.innerHTML = `
      <input type="checkbox" data-platform="${escapeHtml(platform.key)}" ${index < 3 ? "checked" : ""} />
      <span>
        <strong>${escapeHtml(platform.label)}</strong>
        <small>${escapeHtml(platform.tone)}</small>
      </span>
    `;
    platformsContainer.appendChild(label);
  });
}

function selectedPlatforms() {
  return [...platformsContainer.querySelectorAll("input[type='checkbox']")]
    .filter((node) => node.checked)
    .map((node) => node.dataset.platform);
}

function renderBrand(brand) {
  state.brand = brand;
  brandPanel.classList.remove("hidden");
  document.getElementById("brand-title").textContent = brand.name || "Untitled brand";
  document.getElementById("brand-tagline").textContent = brand.tagline || "";
  document.getElementById("brand-description").textContent = brand.description || "";

  const swatches = document.getElementById("palette-swatches");
  swatches.innerHTML = "";
  (brand.palette?.all || []).forEach((color) => {
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.title = color;
    swatch.style.background = color;
    swatches.appendChild(swatch);
  });

  const voice = brand.voice || {};
  document.getElementById("voice-summary").textContent =
    `${voice.primary_tone || "professional"} · ${voice.secondary_tone || "friendly"}${voice.ai_enriched ? " · AI enriched" : ""}`;
  const rules = document.getElementById("voice-rules");
  rules.innerHTML = "";
  (voice.style_rules || []).slice(0, 4).forEach((rule) => {
    const item = document.createElement("li");
    item.textContent = rule;
    rules.appendChild(item);
  });

  document.getElementById("font-summary").textContent =
    `Display: ${brand.fonts?.display || "Syne"} · Body: ${brand.fonts?.body || "Sora"}`;

  const images = document.getElementById("brand-images");
  images.innerHTML = "";
  (brand.images || []).slice(0, 5).forEach((image) => {
    if (!image.public_url) return;
    const img = document.createElement("img");
    img.src = image.public_url;
    img.alt = `${brand.name} source`;
    images.appendChild(img);
  });

  loadCatalog(brand.id);
  loadAudiences(brand.id);
  loadKnowledge(brand.id);
  loadLibrary(brand.id);
}

function renderSimpleList(container, items, emptyText, onClick) {
  container.innerHTML = "";
  if (!items.length) {
    container.innerHTML = `<p class='muted'>${escapeHtml(emptyText)}</p>`;
    return;
  }
  items.forEach((item) => {
    const node = document.createElement("article");
    node.className = "catalog-item";
    node.innerHTML = `
      <strong>${escapeHtml(item.name || item.title || "Untitled")}</strong>
      <div class="muted">${escapeHtml(item.description || item.summary || item.body || "").slice(0, 180)}</div>
      <div class="muted">${escapeHtml(item.id || "")}</div>
    `;
    if (onClick) node.addEventListener("click", () => onClick(item));
    container.appendChild(node);
  });
}

function renderCatalog(items = []) {
  renderSimpleList(document.getElementById("catalog-list"), items, "No catalog items yet.", (item) => {
    document.getElementById("product-name").value = item.name || "";
    document.getElementById("magic-product").value = item.name || "";
    setStatus(`Using catalog item “${item.name}”.`);
    setStep(2);
  });
}

function renderAudiences(items = []) {
  renderSimpleList(document.getElementById("audience-list"), items, "No audiences yet.", (item) => {
    document.getElementById("magic-audience").value = item.id || "";
    setStatus(`Audience selected: ${item.name}`);
    showPanel("magic");
  });
}

function renderKnowledge(items = []) {
  renderSimpleList(document.getElementById("knowledge-list"), items, "No knowledge docs yet.");
}

function appendChat(role, text) {
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${role}`;
  bubble.textContent = text;
  agentChat.appendChild(bubble);
  agentChat.scrollTop = agentChat.scrollHeight;
}

function renderIdeas(ideas = []) {
  ideasGrid.innerHTML = "";
  if (!ideas.length) {
    ideasGrid.innerHTML = "<p class='muted'>No ideas yet.</p>";
    return;
  }
  ideas.forEach((idea, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "idea-card";
    button.innerHTML = `
      <h3>${escapeHtml(idea.title)}</h3>
      <p>${escapeHtml(idea.angle)}</p>
      <p><strong>Objective:</strong> ${escapeHtml(idea.objective)}</p>
      <p><strong>Channels:</strong> ${escapeHtml(idea.channels)}</p>
    `;
    button.addEventListener("click", () => {
      state.selectedIdea = idea;
      document.querySelectorAll(".idea-card").forEach((node) => node.classList.remove("selected"));
      button.classList.add("selected");
      document.getElementById("campaign-title").value = idea.title;
      document.getElementById("campaign-brief").value = idea.angle;
      setStep(3);
      setStatus(`Selected idea: ${idea.title}.`);
    });
    if (index === 0) button.classList.add("selected");
    ideasGrid.appendChild(button);
  });
  state.selectedIdea = ideas[0];
  document.getElementById("campaign-title").value = ideas[0].title;
  document.getElementById("campaign-brief").value = ideas[0].angle;
}

function renderChannelPack(channels = {}) {
  const content = channels.content || {};
  if (!content || !Object.keys(content).length) {
    channelPack.classList.add("hidden");
    channelPack.innerHTML = "";
    return;
  }
  channelPack.classList.remove("hidden");
  const email = content.email || {};
  const blog = content.blog || {};
  const ads = content.ads || {};
  const landing = content.landing || {};
  const aiBadge = content.ai_generated ? " · AI generated" : " · template fallback";
  channelPack.innerHTML = `
    <div class="channel-block">
      <h3>Jasper Channel Pack${aiBadge}</h3>
      <p>${escapeHtml(content.voice || "")}</p>
      <div class="links">
        <a href="${channels.email_url}" target="_blank" rel="noopener">Email</a>
        <a href="${channels.blog_url}" target="_blank" rel="noopener">Blog</a>
        <a href="${channels.ads_url}" target="_blank" rel="noopener">Ads</a>
        <a href="${channels.landing_url}" target="_blank" rel="noopener">Landing</a>
      </div>
    </div>
    <div class="channel-block"><h3>Email</h3><pre>${escapeHtml(email.body || "")}</pre></div>
    <div class="channel-block"><h3>Blog</h3><p><strong>${escapeHtml(blog.title || "")}</strong></p><p>${escapeHtml(blog.intro || "")}</p></div>
    <div class="channel-block"><h3>Ads + Landing</h3><p>${escapeHtml(ads.headline || "")}</p><p>${escapeHtml(landing.hero_subhead || "")}</p></div>
  `;
}

function openEditor(item) {
  state.editing = item;
  const lines = (item.copy || "").split("\n").filter(Boolean);
  document.getElementById("editor-title").textContent = `Edit ${item.platform_label}`;
  document.getElementById("editor-headline").value = lines[0] || "";
  document.getElementById("editor-body").value = lines.slice(1, -1).join(" ").trim() || lines[1] || "";
  document.getElementById("editor-cta").value = lines[lines.length - 1] || "Learn more";
  editorModal.classList.remove("hidden");
}

function closeEditor() {
  state.editing = null;
  editorModal.classList.add("hidden");
}

function renderResults(payload) {
  state.campaign = payload;
  renderChannelPack(payload.channels || {});
  if (payload.ai) renderAiStatus(payload.ai);
  resultsContainer.innerHTML = "";
  (payload.results || []).forEach((item) => {
    const card = document.createElement("article");
    card.className = "result-card";
    card.innerHTML = `
      <h3>${escapeHtml(item.platform_label)}</h3>
      <pre>${escapeHtml(item.copy || "")}</pre>
      ${item.image_url ? `<img class="asset" src="${item.image_url}" alt="${escapeHtml(item.platform_label)}" />` : ""}
      ${item.video_url ? `<video class="asset" controls src="${item.video_url}"></video>` : ""}
      <div class="links">
        <a href="${item.copy_url}" target="_blank" rel="noopener">Copy</a>
        ${item.image_url ? `<a href="${item.image_url}" target="_blank" rel="noopener">Image</a>` : ""}
        ${item.video_url ? `<a href="${item.video_url}" target="_blank" rel="noopener">Clip</a>` : ""}
        <button type="button" class="btn ghost edit-btn">Edit</button>
      </div>
    `;
    card.querySelector(".edit-btn").addEventListener("click", () => openEditor(item));
    resultsContainer.appendChild(card);
  });
}

function renderMagicItem(item) {
  const extras = item.extras || {};
  const images = (extras.images || []).map((url) => `<img class="asset" src="${url}" alt="shot" />`).join("");
  magicOutput.innerHTML = `
    <div class="channel-block">
      <h3>${escapeHtml(item.app_label || item.title || "Asset")}</h3>
      <p class="muted">${escapeHtml(item.summary || "")}</p>
      <pre>${escapeHtml(item.body || "")}</pre>
      ${images}
      ${extras.video_url ? `<video class="asset" controls src="${extras.video_url}"></video>` : ""}
      <div class="links">
        ${extras.html_url ? `<a href="${extras.html_url}" target="_blank" rel="noopener">Open HTML</a>` : ""}
        ${extras.md_url ? `<a href="${extras.md_url}" target="_blank" rel="noopener">Open Markdown</a>` : ""}
        ${extras.site_url ? `<a href="${extras.site_url}" target="_blank" rel="noopener">Open Website</a>` : ""}
      </div>
    </div>
  `;
}

function renderLibrary(items = []) {
  libraryList.innerHTML = "";
  if (!items.length) {
    libraryList.innerHTML = "<p class='muted'>Library is empty.</p>";
    return;
  }
  items.forEach((item) => {
    const card = document.createElement("article");
    card.className = "result-card";
    const extras = item.extras || {};
    card.innerHTML = `
      <h3>${escapeHtml(item.app_label || "Asset")}</h3>
      <p><strong>${escapeHtml(item.title || "")}</strong></p>
      <p class="muted">${escapeHtml(item.summary || "")}</p>
      <pre>${escapeHtml((item.body || "").slice(0, 500))}</pre>
      <div class="links">
        ${extras.html_url ? `<a href="${extras.html_url}" target="_blank" rel="noopener">HTML</a>` : ""}
        ${extras.site_url ? `<a href="${extras.site_url}" target="_blank" rel="noopener">Website</a>` : ""}
        ${extras.video_url ? `<a href="${extras.video_url}" target="_blank" rel="noopener">Video</a>` : ""}
      </div>
    `;
    libraryList.appendChild(card);
  });
}

async function loadPlatforms() {
  const response = await fetch("/api/platforms");
  const data = await response.json();
  renderPlatforms(data.platforms || []);
}

async function loadAiStatus() {
  const response = await fetch("/api/ai-status");
  if (response.ok) renderAiStatus(await response.json());
}

async function loadApps() {
  const response = await fetch("/api/content-apps");
  if (!response.ok) return;
  const data = await response.json();
  state.apps = data.apps || [];
  const select = document.getElementById("magic-app");
  select.innerHTML = state.apps
    .map((app) => `<option value="${escapeHtml(app.key)}">${escapeHtml(app.label)}</option>`)
    .join("");
}

async function loadCatalog(brandId) {
  if (!brandId) return renderCatalog([]);
  const response = await fetch(`/api/catalog?brand_id=${encodeURIComponent(brandId)}`);
  if (response.ok) renderCatalog((await response.json()).items || []);
}

async function loadAudiences(brandId) {
  if (!brandId) return renderAudiences([]);
  const response = await fetch(`/api/audiences?brand_id=${encodeURIComponent(brandId)}`);
  if (response.ok) renderAudiences((await response.json()).audiences || []);
}

async function loadKnowledge(brandId) {
  if (!brandId) return renderKnowledge([]);
  const response = await fetch(`/api/knowledge?brand_id=${encodeURIComponent(brandId)}`);
  if (response.ok) renderKnowledge((await response.json()).items || []);
}

async function loadLibrary(brandId) {
  if (!brandId) return renderLibrary([]);
  const response = await fetch(`/api/content-library?brand_id=${encodeURIComponent(brandId)}`);
  if (response.ok) renderLibrary((await response.json()).items || []);
}

async function loadExistingBrand() {
  const response = await fetch("/api/brands");
  if (!response.ok) return;
  const brands = (await response.json()).brands || [];
  if (brands[0]) {
    renderBrand(brands[0]);
    setStatus(`Loaded Brand DNA for ${brands[0].name}.`);
  }
}

async function buildBrandDNA(event) {
  event.preventDefault();
  dnaBtn.disabled = true;
  setStatus("Extracting Business DNA...");
  try {
    const response = await fetch("/api/brand-dna", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        website_url: document.getElementById("website-url").value.trim(),
        brand_name: document.getElementById("brand-name").value.trim(),
        extra_notes: document.getElementById("extra-notes").value.trim(),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Brand DNA failed");
    renderBrand(data);
    setStep(2);
    setStatus(`Brand DNA ready for ${data.name}.`);
  } catch (error) {
    setStatus(`Brand DNA error: ${error.message}`, true);
  } finally {
    dnaBtn.disabled = false;
  }
}

async function addCatalogItem(event) {
  event.preventDefault();
  if (!requireBrand()) return;
  const button = document.getElementById("catalog-btn");
  button.disabled = true;
  try {
    const response = await fetch("/api/catalog", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        brand_id: state.brand.id,
        name: document.getElementById("catalog-name").value.trim(),
        description: document.getElementById("catalog-description").value.trim(),
        source_url: document.getElementById("catalog-url").value.trim(),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Catalog save failed");
    catalogForm.reset();
    await loadCatalog(state.brand.id);
    setStatus(`Added catalog item “${data.name}”.`);
  } catch (error) {
    setStatus(`Catalog error: ${error.message}`, true);
  } finally {
    button.disabled = false;
  }
}

async function buildIdeas(event) {
  event.preventDefault();
  if (!requireBrand()) return;
  ideasBtn.disabled = true;
  setStatus("Generating campaign ideas...");
  try {
    const response = await fetch("/api/campaign-ideas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        brand_id: state.brand.id,
        product_name: document.getElementById("product-name").value.trim(),
        custom_prompt: document.getElementById("custom-prompt").value.trim(),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Idea generation failed");
    renderIdeas(data.ideas || []);
    setStatus(`Generated ${(data.ideas || []).length} ideas.`);
  } catch (error) {
    setStatus(`Ideas error: ${error.message}`, true);
  } finally {
    ideasBtn.disabled = false;
  }
}

async function generateCampaign(event) {
  event.preventDefault();
  if (!requireBrand()) return;
  const platforms = selectedPlatforms();
  if (!platforms.length) return setStatus("Select at least one channel.", true);
  const formData = new FormData(campaignForm);
  formData.set("brand_id", state.brand.id);
  platforms.forEach((platform) => formData.append("platforms", platform));
  if (state.selectedIdea) {
    formData.set("idea_title", state.selectedIdea.title || "");
    formData.set("idea_angle", state.selectedIdea.angle || "");
    formData.set("idea_objective", state.selectedIdea.objective || "");
    formData.set("idea_channels", state.selectedIdea.channels || "");
  }
  generateBtn.disabled = true;
  setStatus("Generating campaign pack...");
  try {
    const response = await fetch("/api/campaigns/generate", { method: "POST", body: formData });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Campaign generation failed");
    renderResults(payload);
    setStatus(`Campaign ${payload.campaign_id} ready.`);
  } catch (error) {
    setStatus(`Generation failed: ${error.message}`, true);
  } finally {
    generateBtn.disabled = false;
  }
}

async function saveEditor() {
  if (!state.editing || !state.campaign?.campaign_id) return;
  const saveBtn = document.getElementById("editor-save");
  saveBtn.disabled = true;
  try {
    const response = await fetch("/api/creatives/edit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        campaign_id: state.campaign.campaign_id,
        platform_key: state.editing.platform_key,
        headline: document.getElementById("editor-headline").value.trim(),
        body: document.getElementById("editor-body").value.trim(),
        cta: document.getElementById("editor-cta").value.trim(),
        regenerate_ai_image: document.getElementById("editor-regen-image").checked,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Edit failed");
    renderResults(data.campaign);
    closeEditor();
    setStatus(`Updated ${data.result.platform_label}.`);
  } catch (error) {
    setStatus(`Editor error: ${error.message}`, true);
  } finally {
    saveBtn.disabled = false;
  }
}

async function sendBrandAgent(event) {
  event.preventDefault();
  if (!requireBrand()) return;
  const message = document.getElementById("agent-message").value.trim();
  appendChat("user", message);
  document.getElementById("agent-message").value = "";
  setStatus("Brand Agent thinking...");
  try {
    const response = await fetch("/api/brand-agent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ brand_id: state.brand.id, message }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Brand Agent failed");
    appendChat("agent", data.reply || "Updated.");
    if (data.brand) renderBrand(data.brand);
    setStatus(`Brand Agent updated: ${(data.changed_fields || []).join(", ") || "no fields"}`);
  } catch (error) {
    appendChat("agent", `Error: ${error.message}`);
    setStatus(`Brand Agent error: ${error.message}`, true);
  }
}

async function saveKnowledge(event) {
  event.preventDefault();
  if (!requireBrand()) return;
  try {
    const response = await fetch("/api/knowledge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        brand_id: state.brand.id,
        title: document.getElementById("knowledge-title").value.trim(),
        body: document.getElementById("knowledge-body").value.trim(),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Knowledge save failed");
    document.getElementById("knowledge-form").reset();
    await loadKnowledge(state.brand.id);
    setStatus(`Saved knowledge “${data.title}”.`);
  } catch (error) {
    setStatus(`Knowledge error: ${error.message}`, true);
  }
}

async function saveAudience(event) {
  event.preventDefault();
  if (!requireBrand()) return;
  try {
    const response = await fetch("/api/audiences", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        brand_id: state.brand.id,
        name: document.getElementById("audience-name").value.trim(),
        description: document.getElementById("audience-description").value.trim(),
        pains: document.getElementById("audience-pains").value.trim(),
        desires: document.getElementById("audience-desires").value.trim(),
        channels: document.getElementById("audience-channels").value.trim(),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Audience save failed");
    document.getElementById("audience-form").reset();
    await loadAudiences(state.brand.id);
    setStatus(`Saved audience “${data.name}”.`);
  } catch (error) {
    setStatus(`Audience error: ${error.message}`, true);
  }
}

async function runInstantMagic(event) {
  event.preventDefault();
  if (!requireBrand()) return;
  setStatus("Running Instant Magic...");
  try {
    const response = await fetch("/api/instant-magic", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        brand_id: state.brand.id,
        app_key: document.getElementById("magic-app").value,
        brief: document.getElementById("magic-brief").value.trim(),
        audience_id: document.getElementById("magic-audience").value.trim(),
        product_name: document.getElementById("magic-product").value.trim(),
        language: document.getElementById("magic-language").value.trim() || "English",
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Instant Magic failed");
    renderMagicItem(data);
    await loadLibrary(state.brand.id);
    setStatus(`Created ${data.app_label}: ${data.title}`);
  } catch (error) {
    setStatus(`Instant Magic error: ${error.message}`, true);
  }
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Request failed");
  return data;
}

document.querySelectorAll(".step").forEach((button) => {
  button.addEventListener("click", () => setStep(Number(button.dataset.step)));
});
document.querySelectorAll("[data-panel]").forEach((node) => {
  node.addEventListener("click", (event) => {
    const panel = node.getAttribute("data-panel");
    if (panel) {
      event.preventDefault();
      showPanel(panel);
    }
  });
});

clipDurationInput.addEventListener("input", () => {
  clipDurationValue.textContent = `${clipDurationInput.value}s`;
});

dnaForm.addEventListener("submit", buildBrandDNA);
ideasForm.addEventListener("submit", buildIdeas);
campaignForm.addEventListener("submit", generateCampaign);
catalogForm.addEventListener("submit", addCatalogItem);
document.getElementById("agent-form").addEventListener("submit", sendBrandAgent);
document.getElementById("knowledge-form").addEventListener("submit", saveKnowledge);
document.getElementById("audience-form").addEventListener("submit", saveAudience);
document.getElementById("magic-form").addEventListener("submit", runInstantMagic);
document.getElementById("editor-close").addEventListener("click", closeEditor);
document.getElementById("editor-save").addEventListener("click", saveEditor);
document.getElementById("refresh-library").addEventListener("click", () => {
  if (requireBrand()) loadLibrary(state.brand.id);
});
editorModal.addEventListener("click", (event) => {
  if (event.target === editorModal) closeEditor();
});

document.getElementById("calendar-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!requireBrand()) return;
  try {
    const item = await postJson("/api/social-calendar", {
      brand_id: state.brand.id,
      campaign_title: document.getElementById("calendar-title").value.trim() || "Weekly Pulse",
      brief: document.getElementById("calendar-brief").value.trim(),
      days: Number(document.getElementById("calendar-days").value || 7),
    });
    renderMagicItem(item);
    await loadLibrary(state.brand.id);
    setStatus("Social calendar ready.");
  } catch (error) {
    setStatus(`Calendar error: ${error.message}`, true);
  }
});

document.getElementById("photoshoot-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!requireBrand()) return;
  setStatus("Generating photoshoot...");
  try {
    const item = await postJson("/api/photoshoot", {
      brand_id: state.brand.id,
      product_name: document.getElementById("shoot-product").value.trim(),
      product_description: document.getElementById("shoot-desc").value.trim(),
      style: document.getElementById("shoot-style").value.trim() || "clean product studio",
      count: 3,
    });
    renderMagicItem(item);
    await loadLibrary(state.brand.id);
    setStatus("Photoshoot ready.");
  } catch (error) {
    setStatus(`Photoshoot error: ${error.message}`, true);
  }
});

document.getElementById("book-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!requireBrand()) return;
  try {
    const item = await postJson("/api/brand-book", { brand_id: state.brand.id });
    renderMagicItem(item);
    await loadLibrary(state.brand.id);
    setStatus("Brand book ready.");
  } catch (error) {
    setStatus(`Brand book error: ${error.message}`, true);
  }
});

document.getElementById("website-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!requireBrand()) return;
  try {
    const item = await postJson("/api/website", { brand_id: state.brand.id });
    renderMagicItem(item);
    await loadLibrary(state.brand.id);
    setStatus("Website ready.");
  } catch (error) {
    setStatus(`Website error: ${error.message}`, true);
  }
});

document.getElementById("localize-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!requireBrand()) return;
  try {
    const data = await postJson("/api/localize", {
      brand_id: state.brand.id,
      text: document.getElementById("localize-text").value.trim(),
      language: document.getElementById("localize-language").value.trim() || "Spanish",
    });
    renderMagicItem(data.item);
    await loadLibrary(state.brand.id);
    setStatus("Localization ready.");
  } catch (error) {
    setStatus(`Localize error: ${error.message}`, true);
  }
});

(async function boot() {
  try {
    await Promise.all([loadPlatforms(), loadAiStatus(), loadApps()]);
    await loadExistingBrand();
    showPanel("studio");
  } catch (error) {
    setStatus(`Startup error: ${error.message}`, true);
  }
})();
