function buildStarterSuggestionOptions() {
    if (!isOnboardingComplete()) {
        return [
            {
                label: 'Run Easy Setup',
                kind: 'action',
                tone: 'primary',
                onChoose: async () => {
                    ensureChatVisible();
                    await openEasySetup({ source: 'suggestion', force: false, restart: false });
                },
            },
            {
                label: withAgentName('Is {{agent}} safe?'),
                kind: 'option',
                send_prompt: withAgentName('Is {{agent}} safe to run? Explain approvals, downloads, and security controls in plain language.'),
            },
            {
                label: 'What does setup do?',
                kind: 'option',
                send_prompt: 'Explain Easy Setup in plain English and what each step unlocks.',
            },
            {
                label: 'Minimal setup',
                kind: 'action',
                onChoose: async () => {
                    ensureChatVisible();
                    await openEasySetup({ source: 'suggestion', force: false, restart: true });
                    handleEasySetupPathSelect('manual');
                },
            },
        ];
    }

    return [
        {
            label: 'Plan something',
            kind: 'action',
            tone: 'primary',
            send_prompt: 'Help me plan something important with milestones, priorities, and a practical first step.',
        },
        {
            label: 'Draft a message',
            kind: 'option',
            send_prompt: 'Help me draft a clear, effective message/email. Ask 2-3 clarifying questions first.',
        },
        {
            label: 'Research a topic',
            kind: 'option',
            send_prompt: 'Research this topic and compare the best options with tradeoffs and a recommendation.',
        },
        {
            label: 'Brainstorm ideas',
            kind: 'option',
            send_prompt: 'Brainstorm a wide range of ideas, then shortlist the strongest 3 with reasoning.',
        },
        {
            label: 'Organize tasks',
            kind: 'option',
            send_prompt: 'Turn my current priorities into a focused, realistic task plan.',
        },
        {
            label: 'Help me decide',
            kind: 'option',
            send_prompt: 'Help me decide between options with a clear recommendation and tradeoffs.',
        },
    ];
}
