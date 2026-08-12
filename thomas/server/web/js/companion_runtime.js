export function attachCompanionRuntime(runtime) {
  const {
    state,
    refs,
    asText,
    appendMessage,
    updateMessage,
    render,
    renderComposer,
    renderModelButton,
    setActivePanel,
    buildAuthHeaders,
    loadAppStore,
    pushModuleToDevice,
    persistModelState,
    persistDeviceState,
    refreshModelSelector,
    registerCurrentDevice,
    loadProfiles,
    applyRuntimeModel,
    openModelModal,
    closeModelModal,
    appendSystemNotice,
    captureTokenFromQuery,
    hydrateChatState,
    hydrateModelState,
    hydrateDeviceState,
  } = runtime;

  async function streamChatReply(text, assistantId) {
    const response = await fetch("/api/v2/chat", {
      method: "POST",
      headers: buildAuthHeaders({
        "Accept": "application/x-ndjson, application/json",
        "Content-Type": "application/json",
      }),
      body: JSON.stringify({
        session_id: state.chat.sessionId,
        message: text,
        profile: state.model.profile,
        model_id: state.model.modelId || undefined,
        channel: "companion",
        source: "infinite_companion_phone",
        client: "thomas_infinite_companion",
        surface: "phone_app",
        mode: "auto",
      }),
    });

    if (!response.ok) {
      const detail = asText(await response.text(), `${response.status} ${response.statusText}`);
      throw new Error(detail);
    }

    const contentType = String(response.headers.get("content-type") || "").toLowerCase();
    if (contentType.includes("application/json")) {
      const payload = await response.json().catch(() => ({}));
      const queued = Boolean(payload && payload.queued);
      updateMessage(assistantId, () => ({
        text: queued ? "Message queued for active run." : asText(payload && payload.detail, "Request completed."),
        error: false,
      }));
      render();
      return;
    }

    if (!response.body) {
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let seenText = false;
    let failed = false;

    const appendDelta = (delta) => {
      const textDelta = String(delta || "");
      if (!textDelta) {
        return;
      }
      seenText = true;
      updateMessage(assistantId, (message) => ({ text: `${message.text || ""}${textDelta}` }));
      render();
    };

    const handlePacket = (packet) => {
      const type = asText(packet && packet.type, "");
      if (type === "text" || type === "assistant_delta" || type === "delta" || type === "message_delta") {
        appendDelta(packet && (packet.text || packet.delta || packet.content));
        return;
      }
      if (type === "agent_text") {
        const agentId = asText(packet && (packet.agent_id || packet.agent), "").toLowerCase();
        const taskId = asText(packet && packet.task_id, "").toLowerCase();
        if (agentId === "reviewer" || taskId === "__review__") {
          appendDelta(packet && packet.text);
        }
        return;
      }
      if (type === "done") {
        const finalText = asText(packet && (packet.final || packet.text || packet.output_text), "");
        if (finalText) {
          appendDelta(finalText);
        }
        return;
      }
      if (type === "error") {
        failed = true;
        updateMessage(assistantId, () => ({
          text: `Error: ${asText(packet && packet.error, "unknown error")}`,
          error: true,
        }));
        render();
        return;
      }
      if (type === "model_runtime") {
        applyRuntimeModel(packet && packet.runtime);
      }
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      let next = buffer.indexOf("\n");
      while (next >= 0) {
        const line = buffer.slice(0, next).trim();
        buffer = buffer.slice(next + 1);
        if (line) {
          try {
            handlePacket(JSON.parse(line));
          } catch (_error) {
            // Ignore malformed line.
          }
        }
        next = buffer.indexOf("\n");
      }
    }

    if (buffer.trim()) {
      try {
        handlePacket(JSON.parse(buffer.trim()));
      } catch (_error) {
        // Ignore malformed tail line.
      }
    }

    if (!seenText && !failed) {
      updateMessage(assistantId, (message) => ({
        text: asText(message.text, "Completed with no text output."),
        error: Boolean(message.error),
      }));
      render();
    }
  }

  async function sendChatMessage(text) {
    const trimmed = asText(text, "");
    if (!trimmed || state.chat.sending) {
      return;
    }

    state.chat.sending = true;
    appendMessage("user", trimmed);
    const assistantId = appendMessage("assistant", "");
    render();

    try {
      await streamChatReply(trimmed, assistantId);
    } catch (error) {
      updateMessage(assistantId, () => ({
        text: `Request failed: ${asText(error && error.message, "unknown error")}`,
        error: true,
      }));
      render();
    } finally {
      state.chat.sending = false;
      renderComposer();
    }
  }

  async function onChatSubmit(event) {
    event.preventDefault();
    if (!refs.chatInput) {
      return;
    }
    const text = refs.chatInput.value;
    refs.chatInput.value = "";
    render();
    await sendChatMessage(text);
  }

  function wireUi() {
    if (refs.chatForm) {
      refs.chatForm.addEventListener("submit", onChatSubmit);
    }

    if (refs.chatInput) {
      refs.chatInput.addEventListener("input", render);
      refs.chatInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          if (refs.chatForm) {
            refs.chatForm.requestSubmit();
          }
        }
      });
    }

    if (refs.modelSetupBtn) {
      refs.modelSetupBtn.addEventListener("click", async () => {
        openModelModal();
        await refreshModelSelector(state.model.profile, state.model.modelId);
      });
    }

    if (refs.closeModelSetupBtn) {
      refs.closeModelSetupBtn.addEventListener("click", closeModelModal);
    }
    if (refs.cancelModelSetupBtn) {
      refs.cancelModelSetupBtn.addEventListener("click", closeModelModal);
    }
    if (refs.modelSetupBackdrop) {
      refs.modelSetupBackdrop.addEventListener("click", closeModelModal);
    }

    if (refs.setupProfileSelector) {
      refs.setupProfileSelector.addEventListener("change", async () => {
        await refreshModelSelector(refs.setupProfileSelector.value, "");
      });
    }

    if (refs.applyModelSetupBtn && refs.setupProfileSelector && refs.setupModelSelector) {
      refs.applyModelSetupBtn.addEventListener("click", () => {
        state.model.profile = asText(refs.setupProfileSelector.value, state.model.profile);
        state.model.modelId = asText(refs.setupModelSelector.value, state.model.modelId);
        persistModelState();
        renderModelButton();
        closeModelModal();
      });
    }

    if (refs.tabChat) {
      refs.tabChat.addEventListener("click", () => setActivePanel("chat"));
    }
    if (refs.tabApps) {
      refs.tabApps.addEventListener("click", () => setActivePanel("apps"));
    }
    if (refs.tabAdd) {
      refs.tabAdd.addEventListener("click", () => setActivePanel("add"));
    }

    if (refs.appsRefreshBtn) {
      refs.appsRefreshBtn.addEventListener("click", () => {
        void loadAppStore();
      });
    }

    if (refs.appsList) {
      refs.appsList.addEventListener("click", (event) => {
        const target = event.target instanceof Element ? event.target.closest("[data-app-push]") : null;
        if (!target) {
          return;
        }
        const moduleId = asText(target.getAttribute("data-app-push"), "");
        if (!moduleId) {
          return;
        }
        void pushModuleToDevice(moduleId).catch((error) => {
          appendSystemNotice(`Push failed: ${asText(error && error.message, "unknown error")}`, { error: true });
        });
      });
    }

    if (refs.deviceSetupForm) {
      refs.deviceSetupForm.addEventListener("submit", (event) => {
        event.preventDefault();
        void registerCurrentDevice().then(() => loadAppStore()).catch((error) => {
          appendSystemNotice(`Device setup failed: ${asText(error && error.message, "unknown error")}`, { error: true });
        });
      });
    }
  }

  async function bootstrap() {
    captureTokenFromQuery();
    hydrateChatState();
    hydrateModelState();
    hydrateDeviceState();
    wireUi();

    try {
      await loadProfiles();
      await refreshModelSelector(state.model.profile, state.model.modelId);
    } catch (_error) {
      // Keep local model label if discovery fails.
    }

    persistModelState();
    persistDeviceState();
    setActivePanel(asText(state.panel, "chat"));
    render();
  }

  return { bootstrap };
}
