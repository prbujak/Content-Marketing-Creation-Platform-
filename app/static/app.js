const platformsContainer = document.getElementById("platforms-container");
const form = document.getElementById("campaign-form");
const generateBtn = document.getElementById("generate-btn");
const analyzeLinksBtn = document.getElementById("analyze-links-btn");
const statusBox = document.getElementById("status-box");
const insightsContainer = document.getElementById("insights-container");
const resultsContainer = document.getElementById("results-container");
const clipDurationInput = document.getElementById("clip-duration");
const clipDurationValue = document.getElementById("clip-duration-value");
const websiteLinksInput = document.getElementById("website-links");

function setStatus(message, isError = false) {
  statusBox.textContent = message;
  statusBox.classList.toggle("error", isError);
}

function escapeHtml(raw) {
  return raw
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderPlatforms(platforms) {
  platformsContainer.innerHTML = "";
  for (const platform of platforms) {
    const wrapper = document.createElement("label");
    wrapper.className = "platform-option";
    wrapper.innerHTML = `
      <input type="checkbox" data-platform="${platform.key}" checked />
      <span>
        <strong>${escapeHtml(platform.label)}</strong>
        <small>${escapeHtml(platform.tone)}</small>
      </span>
    `;
    platformsContainer.appendChild(wrapper);
  }
}

function selectedPlatforms() {
  const selected = [];
  for (const node of platformsContainer.querySelectorAll("input[type='checkbox']")) {
    if (node.checked) {
      selected.push(node.dataset.platform);
    }
  }
  return selected;
}

function renderInsights(insights = []) {
  insightsContainer.innerHTML = "";
  if (!insights.length) {
    insightsContainer.innerHTML = "<p>No website metadata available yet.</p>";
    return;
  }

  for (const insight of insights) {
    const card = document.createElement("article");
    card.className = "card";
    const errorText = insight.error ? `<p class="error">${escapeHtml(insight.error)}</p>` : "";
    const title = insight.title || "No title discovered";
    const description = insight.description || "No description metadata found.";
    card.innerHTML = `
      <h3>${escapeHtml(insight.url || "Unknown URL")}</h3>
      <p><strong>Title:</strong> ${escapeHtml(title)}</p>
      <p><strong>Description:</strong> ${escapeHtml(description)}</p>
      ${errorText}
    `;
    insightsContainer.appendChild(card);
  }
}

function renderResults(payload) {
  const { results = [], website_sources: websiteSources = [] } = payload || {};
  renderInsights(websiteSources);

  resultsContainer.innerHTML = "";
  if (!results.length) {
    resultsContainer.innerHTML = "<p>No assets were generated.</p>";
    return;
  }

  for (const item of results) {
    const card = document.createElement("article");
    card.className = "card";
    const errors =
      item.errors && item.errors.length
        ? `<p class="error">${item.errors.map((e) => escapeHtml(e)).join("<br/>")}</p>`
        : "";

    const imageMarkup = item.image_url
      ? `<img class="asset" src="${item.image_url}" alt="${escapeHtml(item.platform_label)} image asset" loading="lazy" />`
      : "";
    const videoMarkup = item.video_url
      ? `<video class="asset" controls preload="metadata" src="${item.video_url}"></video>`
      : "";
    const links = `
      <div class="links">
        <a href="${item.copy_url}" target="_blank" rel="noopener noreferrer">Download Copy</a>
        ${item.image_url ? `<a href="${item.image_url}" target="_blank" rel="noopener noreferrer">Download Image</a>` : ""}
        ${item.video_url ? `<a href="${item.video_url}" target="_blank" rel="noopener noreferrer">Download Video</a>` : ""}
      </div>
    `;

    card.innerHTML = `
      <h3>${escapeHtml(item.platform_label)}</h3>
      <pre>${escapeHtml(item.copy || "")}</pre>
      ${imageMarkup}
      ${videoMarkup}
      ${links}
      ${errors}
    `;
    resultsContainer.appendChild(card);
  }
}

async function loadPlatforms() {
  setStatus("Loading platform presets...");
  try {
    const response = await fetch("/api/platforms");
    if (!response.ok) {
      throw new Error(`Failed to load platforms (${response.status})`);
    }
    const data = await response.json();
    renderPlatforms(data.platforms || []);
    setStatus("Ready.");
  } catch (error) {
    setStatus(`Error loading platforms: ${error.message}`, true);
  }
}

async function analyzeLinks() {
  const links = websiteLinksInput.value.trim();
  if (!links) {
    setStatus("Add at least one website link before analyzing.", true);
    return;
  }

  analyzeLinksBtn.disabled = true;
  setStatus("Analyzing website links...");
  try {
    const response = await fetch("/api/website-insights", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ links }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Failed to analyze links.");
    }
    renderInsights(data.insights || []);
    setStatus("Website links analyzed.");
  } catch (error) {
    setStatus(`Website analysis error: ${error.message}`, true);
  } finally {
    analyzeLinksBtn.disabled = false;
  }
}

async function generateCampaign(event) {
  event.preventDefault();
  const selected = selectedPlatforms();
  if (!selected.length) {
    setStatus("Select at least one platform.", true);
    return;
  }

  const formData = new FormData(form);
  for (const platform of selected) {
    formData.append("platforms", platform);
  }

  generateBtn.disabled = true;
  analyzeLinksBtn.disabled = true;
  setStatus("Generating marketing assets. This can take 30-90 seconds...");

  try {
    const response = await fetch("/api/generate", {
      method: "POST",
      body: formData,
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Generation request failed.");
    }
    renderResults(payload);
    setStatus(
      `Campaign ${payload.campaign_id} finished. Generated ${payload.platform_count} platform packs (${payload.clip_duration_seconds}s clips).`
    );
  } catch (error) {
    setStatus(`Generation failed: ${error.message}`, true);
  } finally {
    generateBtn.disabled = false;
    analyzeLinksBtn.disabled = false;
  }
}

clipDurationInput.addEventListener("input", () => {
  clipDurationValue.textContent = `${clipDurationInput.value}s`;
});

analyzeLinksBtn.addEventListener("click", analyzeLinks);
form.addEventListener("submit", generateCampaign);
loadPlatforms();
