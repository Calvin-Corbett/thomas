// Extracted from part-003.js
// From capped

function setAssistantSuggestions({ title = 'Suggestions', options = [], context = 'general', dismissible = true } = {}) {
    if (!assistantSuggestionRail || !assistantSuggestionBubbles) return;
    if (isGenerating) return;

    const validOptions = (Array.isArray(options) ? options : []).filter((option) => {
        return Boolean(safeString(option?.label) || safeString(option?.value));
    });
    if (validOptions.length === 0) {
        hideAssistantSuggestions({ force: true });
        return;
    }

    // Cap at 6 suggestions max
    const capped = validOptions.slice(0, 6);

    suggestionRailVersion += 1;
    const renderVersion = suggestionRailVersion;
    suggestionContext = safeString(context) || 'general';
    suggestionDismissible = Boolean(dismissible);
    const heading = safeString(title) || 'Try asking';

    assistantSuggestionRail.classList.remove('hidden');
    assistantSuggestionRail.dataset.context = suggestionContext;
    if (assistantSuggestionTitle) {
        assistantSuggestionTitle.textContent = heading;
    }
    if (assistantSuggestionDismissBtn) {
        assistantSuggestionDismissBtn.classList.toggle('hidden', !suggestionDismissible);
    }

    assistantSuggestionBubbles.innerHTML = '';

    // Build a marquee track that duplicates chips for seamless CSS looping
    const track = document.createElement('div');
    track.className = 'assistant-suggestion-track';

    function createChipButton(option) {
        const button = document.createElement('button');
        const isAction = safeString(option?.kind) === 'action';
        button.className = isAction
            ? 'onboarding-action-chip assistant-suggestion-chip'
            : 'onboarding-option-chip assistant-suggestion-chip';
        if (safeString(option?.tone) === 'primary') button.classList.add('primary');
        if (safeString(option?.tone) === 'danger') button.classList.add('danger');
        button.type = 'button';
        button.textContent = safeString(option?.label) || safeString(option?.value);

        button.addEventListener('click', async () => {
            if (!assistantSuggestionBubbles) return;
            const buttons = Array.from(assistantSuggestionBubbles.querySelectorAll('button'));
            buttons.forEach((b) => { b.disabled = true; });
            button.classList.add('selected');

            try {
                if (typeof option?.onChoose === 'function') {
                    await option.onChoose(option);
                } else {
                    const sendPrompt = safeString(option?.send_prompt || option?.sendPrompt);
                    const insertPrompt = safeString(option?.insert_prompt || option?.insertPrompt);
                    if (sendPrompt) {
                        composerTextarea.value = sendPrompt;
                        composerTextarea.dispatchEvent(new Event('input'));
                        await handleSend();
                    } else if (insertPrompt) {
                        composerTextarea.value = insertPrompt;
                        composerTextarea.dispatchEvent(new Event('input'));
                        composerTextarea.focus();
                    }
                }
            } catch (err) {
                console.error('Suggestion action failed', err);
            } finally {
                if (renderVersion !== suggestionRailVersion) return;
                if (Boolean(option?.keep_after_choose)) {
                    buttons.forEach((b) => { b.disabled = false; });
                    button.classList.remove('selected');
                } else {
                    hideAssistantSuggestions({ force: true });
                }
            }
        });
        return button;
    }

    // First set of chips (original)
    capped.forEach((option) => {
        track.appendChild(createChipButton(option));
    });
    // Duplicate set for seamless marquee loop
    capped.forEach((option) => {
        track.appendChild(createChipButton(option));
    });

    assistantSuggestionBubbles.appendChild(track);
}
