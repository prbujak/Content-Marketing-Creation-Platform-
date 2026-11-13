const state = {
  brand: null,
  selectedIdea: null,
  platforms: [],
  campaign: null,
  editing: null,
  ai: null,
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

function setStep(stepNumber) {
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
      "Sample mode active. Add OPENROUTER_API_KEY in Cursor Secrets to unlock multi-model copy + images.";
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
}

function renderCatalog(items = []) {
  catalogList.innerHTML = "";
  if (!items.length) {
    catalogList.innerHTML = "<p class='muted'>No catalog items yet.</p>";
    return;
  }
  items.forEach((item) => {
    const node = document.createElement("article");
    node.className = "catalog-item";
    node.innerHTML = `
      <strong>${escapeHtml(item.name || "Untitled")}</strong>
      <div class="muted">${escapeHtml(item.description || "")}</div>
    `;
    node.addEventListener("click", () => {
      document.getElementById("product-name").value = item.name || "";
      setStatus(`Using catalog item “${item.name}” for campaign ideas.`);
      setStep(2);
    });
    catalogList.appendChild(node);
  });
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
      setStatus(`Selected idea: ${idea.title}. Generate creatives when ready.`);
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
    <div class="channel-block">
      <h3>Email</h3>
      <p><strong>Subjects:</strong> ${(email.subject_variants || []).map(escapeHtml).join(" · ")}</p>
      <pre>${escapeHtml(email.body || "")}</pre>
    </div>
    <div class="channel-block">
      <h3>Blog</h3>
      <p><strong>${escapeHtml(blog.title || "")}</strong></p>
      <p>${escapeHtml(blog.intro || "")}</p>
    </div>
    <div class="channel-block">
      <h3>Ads + Landing</h3>
      <p><strong>Ad headline:</strong> ${escapeHtml(ads.headline || "")}</p>
      <p><strong>Landing hero:</strong> ${escapeHtml(landing.hero_headline || "")}</p>
      <p>${escapeHtml(landing.hero_subhead || "")}</p>
    </div>
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
  const results = payload.results || [];
  if (!results.length) {
    resultsContainer.innerHTML = "<p class='muted'>No creatives generated.</p>";
    return;
  }

  results.forEach((item) => {
    const card = document.createElement("article");
    card.className = "result-card";
    const errors =
      item.errors && item.errors.length
        ? `<p class="error">${item.errors.map((entry) => escapeHtml(entry)).join("<br/>")}</p>`
        : "";
    card.innerHTML = `
      <h3>${escapeHtml(item.platform_label)}</h3>
      <pre>${escapeHtml(item.copy || "")}</pre>
      ${item.image_url ? `<img class="asset" src="${item.image_url}" alt="${escapeHtml(item.platform_label)} creative" loading="lazy" />` : ""}
      ${item.video_url ? `<video class="asset" controls preload="metadata" src="${item.video_url}"></video>` : ""}
      <div class="links">
        <a href="${item.copy_url}" target="_blank" rel="noopener">Copy</a>
        ${item.image_url ? `<a href="${item.image_url}" target="_blank" rel="noopener">Image</a>` : ""}
        ${item.video_url ? `<a href="${item.video_url}" target="_blank" rel="noopener">Clip</a>` : ""}
        <button type="button" class="btn ghost edit-btn">Edit</button>
      </div>
      ${errors}
    `;
    card.querySelector(".edit-btn").addEventListener("click", () => openEditor(item));
    resultsContainer.appendChild(card);
  });
}

async function loadPlatforms() {
  const response = await fetch("/api/platforms");
  if (!response.ok) throw new Error("Failed to load platforms");
  const data = await response.json();
  renderPlatforms(data.platforms || []);
}

async function loadAiStatus() {
  const response = await fetch("/api/ai-status");
  if (!response.ok) return;
  renderAiStatus(await response.json());
}

async function loadCatalog(brandId) {
  if (!brandId) {
    renderCatalog([]);
    return;
  }
  const response = await fetch(`/api/catalog?brand_id=${encodeURIComponent(brandId)}`);
  if (!response.ok) return;
  const data = await response.json();
  renderCatalog(data.items || []);
}

async function loadExistingBrand() {
  const response = await fetch("/api/brands");
  if (!response.ok) return;
  const data = await response.json();
  const brands = data.brands || [];
  if (brands[0]) {
    renderBrand(brands[0]);
    setStatus(`Loaded Brand DNA for ${brands[0].name}. Continue to campaign ideas.`);
  }
}

async function buildBrandDNA(event) {
  event.preventDefault();
  dnaBtn.disabled = true;
  setStatus("Extracting Business DNA from website...");
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
    if (!response.ok) throw new Error(data.detail || "Brand DNA extraction failed");
    renderBrand(data);
    setStep(2);
    setStatus(`Brand DNA ready for ${data.name}. Generate campaign ideas next.`);
  } catch (error) {
    setStatus(`Brand DNA error: ${error.message}`, true);
  } finally {
    dnaBtn.disabled = false;
  }
}

async function addCatalogItem(event) {
  event.preventDefault();
  if (!state.brand?.id) {
    setStatus("Build Brand DNA first before adding catalog items.", true);
    setStep(1);
    return;
  }
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
    if (!response.ok) throw new Error(data.detail || "Could not save catalog item");
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
  if (!state.brand?.id) {
    setStatus("Build Brand DNA first.", true);
    setStep(1);
    return;
  }
  ideasBtn.disabled = true;
  setStatus(
    state.ai?.enabled
      ? "Generating OpenRouter campaign ideas..."
      : "Generating sample campaign ideas (no OpenRouter key yet)..."
  );
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
    setStatus(`Generated ${(data.ideas || []).length} campaign ideas. Select one to continue.`);
  } catch (error) {
    setStatus(`Ideas error: ${error.message}`, true);
  } finally {
    ideasBtn.disabled = false;
  }
}

async function generateCampaign(event) {
  event.preventDefault();
  if (!state.brand?.id) {
    setStatus("Build Brand DNA first.", true);
    setStep(1);
    return;
  }

  const platforms = selectedPlatforms();
  if (!platforms.length) {
    setStatus("Select at least one channel.", true);
    return;
  }

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
  setStatus(
    state.ai?.enabled
      ? "Generating AI creatives via OpenRouter. This can take a minute..."
      : "Generating sample creatives (template mode). Add OPENROUTER_API_KEY for live AI..."
  );
  try {
    const response = await fetch("/api/campaigns/generate", {
      method: "POST",
      body: formData,
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Campaign generation failed");
    renderResults(payload);
    setStatus(
      `Campaign ${payload.campaign_id} ready · ${payload.platform_count} platform creatives · ${payload.clip_duration_seconds}s clips`
    );
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
  setStatus("Updating creative...");
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
    setStatus(`Updated ${data.result.platform_label} creative.`);
  } catch (error) {
    setStatus(`Editor error: ${error.message}`, true);
  } finally {
    saveBtn.disabled = false;
  }
}

document.querySelectorAll(".step").forEach((button) => {
  button.addEventListener("click", () => setStep(Number(button.dataset.step)));
});

clipDurationInput.addEventListener("input", () => {
  clipDurationValue.textContent = `${clipDurationInput.value}s`;
});

dnaForm.addEventListener("submit", buildBrandDNA);
ideasForm.addEventListener("submit", buildIdeas);
campaignForm.addEventListener("submit", generateCampaign);
catalogForm.addEventListener("submit", addCatalogItem);
document.getElementById("editor-close").addEventListener("click", closeEditor);
document.getElementById("editor-save").addEventListener("click", saveEditor);
editorModal.addEventListener("click", (event) => {
  if (event.target === editorModal) closeEditor();
});

(async function boot() {
  try {
    await Promise.all([loadPlatforms(), loadAiStatus()]);
    await loadExistingBrand();
  } catch (error) {
    setStatus(`Startup error: ${error.message}`, true);
  }
})();
