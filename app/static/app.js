const state = {
  videoId: null,
  videoTimer: null,
  publishTimer: null,
  objectUrl: null,
};

const elements = {
  uploadForm: document.querySelector("#uploadForm"),
  videoFile: document.querySelector("#videoFile"),
  dropZone: document.querySelector("#dropZone"),
  fileSummary: document.querySelector("#fileSummary"),
  fileName: document.querySelector("#fileName"),
  fileMeta: document.querySelector("#fileMeta"),
  clearFile: document.querySelector("#clearFile"),
  uploadButton: document.querySelector("#uploadButton"),
  uploadProgress: document.querySelector("#uploadProgress"),
  uploadProgressBar: document.querySelector("#uploadProgressBar"),
  editCard: document.querySelector("#editCard"),
  publishCard: document.querySelector("#publishCard"),
  videoPreview: document.querySelector("#videoPreview"),
  videoStatus: document.querySelector("#videoStatus"),
  editForm: document.querySelector("#editForm"),
  startTime: document.querySelector("#startTime"),
  endTime: document.querySelector("#endTime"),
  captionText: document.querySelector("#captionText"),
  captionCount: document.querySelector("#captionCount"),
  verticalCrop: document.querySelector("#verticalCrop"),
  renderButton: document.querySelector("#renderButton"),
  renderState: document.querySelector("#renderState"),
  downloadLink: document.querySelector("#downloadLink"),
  publishForm: document.querySelector("#publishForm"),
  publishButton: document.querySelector("#publishButton"),
  publishResults: document.querySelector("#publishResults"),
  appAlert: document.querySelector("#appAlert"),
};

function formatBytes(bytes) {
  if (!bytes) return "0 MB";
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function showAlert(message, type = "danger") {
  elements.appAlert.textContent = message;
  elements.appAlert.className = `alert app-alert alert-${type}`;
  elements.appAlert.classList.remove("d-none");
}

function clearAlert() {
  elements.appAlert.classList.add("d-none");
}

function errorMessage(payload, fallback) {
  if (!payload) return fallback;
  if (typeof payload.detail === "string") return payload.detail;
  if (Array.isArray(payload.detail)) return payload.detail.map((item) => item.msg).join("; ");
  return fallback;
}

function setWorkflow(step) {
  document.querySelectorAll(".workflow-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.workflow === step);
  });
}

function selectFile(file) {
  clearAlert();
  if (!file) {
    elements.fileSummary.classList.add("d-none");
    elements.uploadButton.disabled = true;
    return;
  }
  if (file.size > window.APP_CONFIG.maxFileSize) {
    elements.videoFile.value = "";
    showAlert(`The selected file exceeds ${window.APP_CONFIG.maxFileSize / 1024 / 1024} MB.`);
    return;
  }
  elements.fileName.textContent = file.name;
  elements.fileMeta.textContent = formatBytes(file.size);
  elements.fileSummary.classList.remove("d-none");
  elements.uploadButton.disabled = false;

  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  state.objectUrl = URL.createObjectURL(file);
  elements.videoPreview.src = state.objectUrl;
  elements.videoPreview.onloadedmetadata = () => {
    if (Number.isFinite(elements.videoPreview.duration)) {
      elements.endTime.value = elements.videoPreview.duration.toFixed(1);
    }
  };
}

elements.videoFile.addEventListener("change", () => selectFile(elements.videoFile.files[0]));
elements.clearFile.addEventListener("click", () => {
  elements.videoFile.value = "";
  selectFile(null);
});

["dragenter", "dragover"].forEach((eventName) => {
  elements.dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    elements.dropZone.classList.add("dragging");
  });
});
["dragleave", "drop"].forEach((eventName) => {
  elements.dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    elements.dropZone.classList.remove("dragging");
  });
});
elements.dropZone.addEventListener("drop", (event) => {
  const file = event.dataTransfer.files[0];
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  elements.videoFile.files = transfer.files;
  selectFile(file);
});

elements.uploadForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const file = elements.videoFile.files[0];
  if (!file) return;

  clearAlert();
  const body = new FormData();
  body.append("file", file);
  const request = new XMLHttpRequest();
  request.open("POST", "/upload");
  elements.uploadButton.disabled = true;
  elements.publishCard.classList.add("d-none");
  elements.uploadProgress.classList.remove("d-none");
  request.upload.addEventListener("progress", (progressEvent) => {
    if (!progressEvent.lengthComputable) return;
    const percentage = Math.round((progressEvent.loaded / progressEvent.total) * 100);
    elements.uploadProgressBar.style.width = `${percentage}%`;
  });
  request.addEventListener("load", () => {
    let payload = {};
    try { payload = JSON.parse(request.responseText); } catch (_) { payload = {}; }
    if (request.status < 200 || request.status >= 300) {
      elements.uploadButton.disabled = false;
      showAlert(errorMessage(payload, "Upload failed."));
      return;
    }
    state.videoId = payload.video_id;
    elements.editCard.classList.remove("d-none");
    setWorkflow("edit");
    updateVideoStatus("queued");
    elements.editCard.scrollIntoView({ behavior: "smooth", block: "start" });
    pollVideoStatus();
  });
  request.addEventListener("error", () => {
    elements.uploadButton.disabled = false;
    showAlert("The server could not be reached.");
  });
  request.send(body);
});

function updateVideoStatus(status, error = null) {
  const labels = {
    queued: "Queued",
    uploaded: "Uploaded",
    processing: "Processing",
    ready: "Ready",
    error: "Error",
  };
  elements.videoStatus.className = `status-pill ${status}`;
  elements.videoStatus.querySelector("span").textContent = labels[status] || status;
  const busy = status === "queued" || status === "processing";
  elements.renderState.classList.toggle("d-none", !busy);
  elements.renderButton.disabled = busy || status === "error";
  if (error) showAlert(error);
}

async function pollVideoStatus() {
  window.clearTimeout(state.videoTimer);
  if (!state.videoId) return;
  try {
    const response = await fetch(`/video/${state.videoId}/status`, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(errorMessage(payload, "Could not read video status."));
    updateVideoStatus(payload.status, payload.error);
    if (payload.duration && !elements.endTime.dataset.touched) {
      elements.endTime.value = Number(payload.duration).toFixed(1);
    }
    if (payload.status === "ready") {
      elements.publishCard.classList.remove("d-none");
      elements.downloadLink.href = payload.download_url;
      setWorkflow("publish");
      pollPublishStatus();
      return;
    }
    if (payload.status === "error" || payload.status === "uploaded") return;
    state.videoTimer = window.setTimeout(pollVideoStatus, 1600);
  } catch (error) {
    showAlert(error.message);
    state.videoTimer = window.setTimeout(pollVideoStatus, 3000);
  }
}

elements.endTime.addEventListener("input", () => { elements.endTime.dataset.touched = "true"; });
elements.captionText.addEventListener("input", () => {
  elements.captionCount.textContent = elements.captionText.value.length;
});

elements.editForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.videoId) return;
  clearAlert();
  const body = {
    start_time: Number(elements.startTime.value),
    end_time: Number(elements.endTime.value),
    is_vertical: elements.verticalCrop.checked,
    subtitle_text: elements.captionText.value,
  };
  try {
    const response = await fetch(`/video/${state.videoId}/edit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(errorMessage(payload, "Rendering could not start."));
    elements.publishCard.classList.add("d-none");
    updateVideoStatus("processing");
    pollVideoStatus();
  } catch (error) {
    showAlert(error.message);
  }
});

elements.publishForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.videoId) return;
  const platforms = [...document.querySelectorAll('input[name="platform"]:checked')].map((input) => input.value);
  if (!platforms.length) {
    showAlert("Select at least one publishing destination.");
    return;
  }
  clearAlert();
  elements.publishButton.disabled = true;
  try {
    const response = await fetch(`/video/${state.videoId}/publish`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        platforms,
        title: document.querySelector("#postTitle").value,
        description: document.querySelector("#postDescription").value,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(errorMessage(payload, "Publishing could not start."));
    showAlert(payload.mock ? "Demo publication started. No external post will be created." : "Publication started.", "success");
    pollPublishStatus(true);
  } catch (error) {
    showAlert(error.message);
  } finally {
    elements.publishButton.disabled = false;
  }
});

async function pollPublishStatus(force = false) {
  window.clearTimeout(state.publishTimer);
  if (!state.videoId || (elements.publishCard.classList.contains("d-none") && !force)) return;
  try {
    const response = await fetch(`/video/${state.videoId}/publish-status`, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error("Could not read publishing status.");
    if (payload.posts.length) {
      elements.publishResults.classList.remove("d-none");
      elements.publishResults.replaceChildren(...payload.posts.map((post) => {
        const row = document.createElement("div");
        row.className = "post-result";
        const name = document.createElement("strong");
        name.textContent = post.platform;
        const status = document.createElement("span");
        status.className = post.status;
        status.textContent = post.error || post.status;
        row.append(name, status);
        return row;
      }));
      const unfinished = payload.posts.some((post) => ["queued", "publishing", "pending"].includes(post.status));
      if (unfinished) state.publishTimer = window.setTimeout(pollPublishStatus, 3000);
    }
  } catch (error) {
    showAlert(error.message);
  }
}
