
        const { useState, useReducer, useCallback, useEffect, useRef } = React;

        // Custom Hooks
        const useVoiceCapture = () => {
            const mediaRecorderRef = useRef(null);
            const audioContextRef = useRef(null);
            const analyserRef = useRef(null);
            const audioChunksRef = useRef([]);
            const streamRef = useRef(null);

            const startRecording = useCallback(async () => {
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    streamRef.current = stream;

                    audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)();
                    analyserRef.current = audioContextRef.current.createAnalyser();
                    const source = audioContextRef.current.createMediaStreamSource(stream);
                    source.connect(analyserRef.current);

                    audioChunksRef.current = [];
                    mediaRecorderRef.current = new MediaRecorder(stream);

                    mediaRecorderRef.current.ondataavailable = (event) => {
                        audioChunksRef.current.push(event.data);
                    };

                    mediaRecorderRef.current.start();
                    return { success: true };
                } catch (error) {
                    console.error("Microphone access error:", error);
                    return { success: false, error };
                }
            }, []);

            const stopRecording = useCallback(() => {
                return new Promise((resolve) => {
                    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
                        mediaRecorderRef.current.onstop = () => {
                            const audioBlob = new Blob(audioChunksRef.current, { type: "audio/webm;codecs=opus" });
                            if (streamRef.current) {
                                streamRef.current.getTracks().forEach(track => track.stop());
                            }
                            resolve(audioBlob);
                        };
                        mediaRecorderRef.current.stop();
                    } else {
                        resolve(null);
                    }
                });
            }, []);

            const getAudioLevel = useCallback(() => {
                if (!analyserRef.current) return 0;
                const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);
                analyserRef.current.getByteFrequencyData(dataArray);
                const average = dataArray.reduce((a, b) => a + b) / dataArray.length;
                return Math.min(100, (average / 255) * 100);
            }, []);

            return { startRecording, stopRecording, getAudioLevel };
        };

        const useSpeechRecognition = () => {
            const [isSupported] = useState(() => {
                const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                return !!SpeechRecognition;
            });

            const recognitionRef = useRef(null);

            const startListening = useCallback((language, onResult, onFinal) => {
                if (!isSupported) return false;

                const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                recognitionRef.current = new SpeechRecognition();
                recognitionRef.current.language = language;
                recognitionRef.current.continuous = false;
                recognitionRef.current.interimResults = true;

                recognitionRef.current.onresult = (event) => {
                    let interim = "";
                    let final = "";
                    for (let i = event.resultIndex; i < event.results.length; i++) {
                        const transcript = event.results[i][0].transcript;
                        if (event.results[i].isFinal) {
                            final += transcript;
                        } else {
                            interim += transcript;
                        }
                    }
                    if (interim) onResult(interim);
                    if (final) onFinal(final);
                };

                recognitionRef.current.start();
                return true;
            }, [isSupported]);

            const stopListening = useCallback(() => {
                if (recognitionRef.current) {
                    recognitionRef.current.stop();
                }
            }, []);

            return { startListening, stopListening, isSupported };
        };

        const useAudioPlayback = () => {
            const audioRef = useRef(new Audio());

            const play = useCallback((audioBlob) => {
                const url = URL.createObjectURL(audioBlob);
                audioRef.current.src = url;
                return audioRef.current.play().catch(err => console.error("Playback error:", err));
            }, []);

            const stop = useCallback(() => {
                audioRef.current.pause();
                audioRef.current.currentTime = 0;
            }, []);

            return { play, stop, audioElement: audioRef.current };
        };

        const useWaveform = () => {
            const [waveformData, setWaveformData] = useState([]);

            const generateWaveform = useCallback((audioBlob) => {
                const reader = new FileReader();
                reader.onload = (event) => {
                    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
                    audioContext.decodeAudioData(event.target.result, (buffer) => {
                        const rawData = buffer.getChannelData(0);
                        const samples = Math.floor(rawData.length / 64);
                        const waveform = [];
                        for (let i = 0; i < samples; i++) {
                            let sum = 0;
                            for (let j = 0; j < 64; j++) {
                                sum += Math.abs(rawData[i * 64 + j]);
                            }
                            waveform.push((sum / 64) * 100);
                        }
                        setWaveformData(waveform);
                    });
                };
                reader.readAsArrayBuffer(audioBlob);
            }, []);

            return { waveformData, generateWaveform };
        };

        // Chat State Reducer
        const chatReducer = (state, action) => {
            switch (action.type) {
                case "ADD_MESSAGE":
                    return {
                        ...state,
                        messages: [...state.messages, { ...action.payload, id: Date.now() }],
                    };
                case "SET_TYPING":
                    return { ...state, isTyping: action.payload };
                case "CLEAR_MESSAGES":
                    return { ...state, messages: [] };
                case "SET_STATUS":
                    return { ...state, status: action.payload };
                default:
                    return state;
            }
        };

        // Main App Component
        function VoiceChatApp() {
            const [chatState, dispatch] = useReducer(chatReducer, {
                messages: [],
                isTyping: false,
                status: "idle",
            });

            const [recordingState, setRecordingState] = useState("idle"); // idle, listening, processing, speaking
            const [settings, setSettings] = useState({
                voiceMode: "push-to-talk", // push-to-talk, hold-to-talk, continuous
                silenceTimeout: 2000,
                language: "en-US",
                ttsVoice: "google",
                ttsSpeed: 1,
                ttsPitch: 1,
                autoPlay: true,
                soundEffects: true,
                continuousMode: false,
            });
            const [showSettings, setShowSettings] = useState(false);
            const [transcription, setTranscription] = useState("");
            const [audioLevel, setAudioLevel] = useState(0);

            const voiceCapture = useVoiceCapture();
            const speechRecognition = useSpeechRecognition();
            const audioPlayback = useAudioPlayback();
            const waveform = useWaveform();
            const silenceTimeoutRef = useRef(null);
            const audioLevelIntervalRef = useRef(null);

            // Sound Effects
            const playSound = useCallback((type) => {
                if (!settings.soundEffects) return;
                const audioContext = new (window.AudioContext || window.webkitAudioContext)();
                const oscillator = audioContext.createOscillator();
                const gainNode = audioContext.createGain();

                oscillator.connect(gainNode);
                gainNode.connect(audioContext.destination);

                const now = audioContext.currentTime;

                switch (type) {
                    case "activate":
                        oscillator.frequency.value = 800;
                        gainNode.gain.setValueAtTime(0.1, now);
                        gainNode.gain.exponentialRampToValueAtTime(0.01, now + 0.1);
                        oscillator.start(now);
                        oscillator.stop(now + 0.1);
                        break;
                    case "stop":
                        oscillator.frequency.value = 400;
                        gainNode.gain.setValueAtTime(0.1, now);
                        gainNode.gain.exponentialRampToValueAtTime(0.01, now + 0.15);
                        oscillator.start(now);
                        oscillator.stop(now + 0.15);
                        break;
                    case "notification":
                        oscillator.frequency.value = 1000;
                        gainNode.gain.setValueAtTime(0.05, now);
                        gainNode.gain.exponentialRampToValueAtTime(0.01, now + 0.2);
                        oscillator.start(now);
                        oscillator.stop(now + 0.2);
                        break;
                }
            }, [settings.soundEffects]);

            const startRecording = useCallback(async () => {
                const result = await voiceCapture.startRecording();
                if (result.success) {
                    setRecordingState("listening");
                    playSound("activate");
                    dispatch({ type: "SET_STATUS", payload: "Listening..." });

                    // Start audio level monitoring
                    audioLevelIntervalRef.current = setInterval(() => {
                        const level = voiceCapture.getAudioLevel();
                        setAudioLevel(level);
                    }, 50);

                    // Speech recognition
                    speechRecognition.startListening(
                        settings.language,
                        (interim) => setTranscription(interim),
                        (final) => {
                            setTranscription(final);
                            stopRecording(final);
                        }
                    );

                    // Silence detection
                    clearTimeout(silenceTimeoutRef.current);
                    silenceTimeoutRef.current = setTimeout(() => {
                        stopRecording();
                    }, settings.silenceTimeout);
                }
            }, [voiceCapture, speechRecognition, settings.language, settings.silenceTimeout, playSound]);

            const stopRecording = useCallback(async (finalTranscript = null) => {
                clearInterval(audioLevelIntervalRef.current);
                clearTimeout(silenceTimeoutRef.current);
                speechRecognition.stopListening();

                const audioBlob = await voiceCapture.stopRecording();
                setRecordingState("processing");
                playSound("stop");
                dispatch({ type: "SET_STATUS", payload: "Processing..." });

                if (audioBlob) {
                    waveform.generateWaveform(audioBlob);
                    dispatch({
                        type: "ADD_MESSAGE",
                        payload: {
                            role: "user",
                            type: "voice",
                            content: finalTranscript || transcription,
                            timestamp: new Date(),
                            duration: 0,
                        },
                    });
                }

                // Simulate response
                setTimeout(() => {
                    dispatch({ type: "SET_TYPING", payload: true });
                    dispatch({ type: "SET_STATUS", payload: "Processing..." });

                    setTimeout(() => {
                        const responses = [
                            "That's an interesting question! Tell me more.",
                            "I understand. How can I help you further?",
                            "Great point! Let me think about that.",
                            "Absolutely! I can help with that.",
                        ];
                        const response = responses[Math.floor(Math.random() * responses.length)];

                        dispatch({ type: "SET_TYPING", payload: false });
                        dispatch({
                            type: "ADD_MESSAGE",
                            payload: {
                                role: "assistant",
                                type: "text",
                                content: response,
                                timestamp: new Date(),
                            },
                        });

                        setRecordingState("speaking");
                        dispatch({ type: "SET_STATUS", payload: "Thomas is speaking..." });
                        playSound("notification");

                        setTimeout(() => {
                            setRecordingState("idle");
                            dispatch({ type: "SET_STATUS", payload: "Ready to listen" });

                            if (settings.continuousMode || settings.voiceMode === "continuous") {
                                setTimeout(() => startRecording(), 500);
                            }
                        }, 2000);
                    }, 1000);
                }, 500);

                setTranscription("");
                setAudioLevel(0);
            }, [voiceCapture, speechRecognition, waveform, settings.language, settings.silenceTimeout, settings.continuousMode, settings.voiceMode, playSound, transcription, startRecording]);

            const handleMicClick = useCallback(() => {
                if (recordingState === "idle") {
                    startRecording();
                } else if (recordingState === "listening") {
                    stopRecording();
                }
            }, [recordingState, startRecording, stopRecording]);

            const handlePause = useCallback(() => {
                if (recordingState === "listening") {
                    speechRecognition.stopListening();
                    setRecordingState("idle");
                    dispatch({ type: "SET_STATUS", payload: "Paused" });
                }
            }, [recordingState, speechRecognition]);

            const handleCancel = useCallback(() => {
                speechRecognition.stopListening();
                setRecordingState("idle");
                setTranscription("");
                setAudioLevel(0);
                dispatch({ type: "SET_STATUS", payload: "Cancelled" });
                clearInterval(audioLevelIntervalRef.current);
                clearTimeout(silenceTimeoutRef.current);
            }, [speechRecognition]);

            return (
                <div className="voice-chat-app">
                    {/* Header */}
                    <div className="header">
                        <div className="header-content">
                            <h1>Thomas Voice Chat</h1>
                            <p>Speak naturally with your AI assistant</p>
                        </div>
                        <div className="header-controls">
                            {settings.continuousMode && (
                                <div className="continuous-indicator">
                                    <span>👂</span>
                                    <span>Always Listening</span>
                                </div>
                            )}
                            <button
                                className="settings-btn"
                                onClick={() => setShowSettings(!showSettings)}
                                aria-label="Settings"
                            >
                                ⚙️
                            </button>
                        </div>
                    </div>

                    {/* Conversation Area */}
                    <div className="conversation-area">
                        <div className="messages-container">
                            {chatState.messages.map((msg) => (
                                <div key={msg.id} className={`message ${msg.role}`}>
                                    <div>
                                        <div className="message-bubble">
                                            {msg.content}
                                            {msg.type === "voice" && (
                                                <div className="voice-message-waveform">
                                                    {waveform.waveformData.slice(0, 20).map((val, idx) => (
                                                        <div
                                                            key={idx}
                                                            className="waveform-bar"
                                                            style={{ height: `${val * 0.5}%` }}
                                                        />
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                        <div className="message-footer">
                                            <span>{msg.timestamp.toLocaleTimeString()}</span>
                                            {msg.duration && <span>{msg.duration}s</span>}
                                        </div>
                                    </div>
                                </div>
                            ))}
                            {chatState.isTyping && (
                                <div className="message assistant">
                                    <div className="message-bubble">
                                        <div className="typing-indicator">
                                            <div className="typing-dot"></div>
                                            <div className="typing-dot"></div>
                                            <div className="typing-dot"></div>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Voice Control Area */}
                    <div className="voice-control-area">
                        <div className="mic-control-wrapper">
                            <div className="mic-button-container">
                                <canvas className="circular-waveform" width="100" height="100" />
                                <button
                                    className={`mic-button ${recordingState}`}
                                    onClick={handleMicClick}
                                    aria-label={recordingState === "idle" ? "Start recording" : "Stop recording"}
                                >
                                    {recordingState === "speaking" ? "🔊" : "🎤"}
                                    {recordingState === "listening" && <div className="recording-dot" />}
                                </button>
                            </div>

                            <div className="control-buttons">
                                <button
                                    className="control-btn"
                                    onClick={handlePause}
                                    disabled={recordingState !== "listening"}
                                    aria-label="Pause recording"
                                    title="Pause"
                                >
                                    ⏸️
                                </button>
                                <button
                                    className="control-btn"
                                    onClick={handleCancel}
                                    disabled={recordingState === "idle"}
                                    aria-label="Cancel recording"
                                    title="Cancel"
                                >
                                    ✕
                                </button>
                            </div>

                            <div className="status-section">
                                <div className="status-text">{chatState.status}</div>
                                {transcription && (
                                    <div className="transcription-hint">{transcription}</div>
                                )}
                            </div>

                            {recordingState === "listening" && (
                                <div className="volume-indicator">
                                    <div
                                        className="volume-bar"
                                        style={{ width: `${audioLevel}%` }}
                                    />
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Settings Panel */}
                    <div className={`settings-overlay ${showSettings ? "open" : ""}`}
                         onClick={() => setShowSettings(false)} />
                    <div className={`settings-panel ${showSettings ? "open" : ""}`}>
                        <div className="settings-panel-header">
                            <h2>Settings</h2>
                            <button
                                className="close-settings-btn"
                                onClick={() => setShowSettings(false)}
                                aria-label="Close settings"
                            >
                                ✕
                            </button>
                        </div>
                        <div className="settings-content">
                            <div className="settings-group">
                                <label>Voice Mode</label>
                                <select
                                    value={settings.voiceMode}
                                    onChange={(e) => setSettings({ ...settings, voiceMode: e.target.value })}
                                >
                                    <option value="push-to-talk">Push-to-Talk</option>
                                    <option value="hold-to-talk">Hold-to-Talk</option>
                                    <option value="continuous">Continuous</option>
                                </select>
                            </div>

                            <div className="settings-group">
                                <label>Language</label>
                                <select
                                    value={settings.language}
                                    onChange={(e) => setSettings({ ...settings, language: e.target.value })}
                                >
                                    <option value="en-US">English (US)</option>
                                    <option value="es-ES">Spanish</option>
                                    <option value="fr-FR">French</option>
                                    <option value="de-DE">German</option>
                                </select>
                            </div>

                            <div className="settings-group">
                                <label>Silence Timeout (ms)</label>
                                <input
                                    type="number"
                                    min="1000"
                                    max="5000"
                                    step="100"
                                    value={settings.silenceTimeout}
                                    onChange={(e) => setSettings({ ...settings, silenceTimeout: parseInt(e.target.value) })}
                                />
                            </div>

                            <div className="settings-group">
                                <label>TTS Speed</label>
                                <input
                                    type="range"
                                    min="0.5"
                                    max="2"
                                    step="0.1"
                                    value={settings.ttsSpeed}
                                    onChange={(e) => setSettings({ ...settings, ttsSpeed: parseFloat(e.target.value) })}
                                    className="range-slider"
                                />
                                <div className="range-value">{settings.ttsSpeed.toFixed(1)}x</div>
                            </div>

                            <div className="settings-group">
                                <label>TTS Pitch</label>
                                <input
                                    type="range"
                                    min="0.5"
                                    max="2"
                                    step="0.1"
                                    value={settings.ttsPitch}
                                    onChange={(e) => setSettings({ ...settings, ttsPitch: parseFloat(e.target.value) })}
                                    className="range-slider"
                                />
                                <div className="range-value">{settings.ttsPitch.toFixed(1)}</div>
                            </div>

                            <div className="settings-divider" />

                            <div className="settings-group">
                                <div className="toggle-group">
                                    <label>Auto-Play Responses</label>
                                    <label className="toggle-switch">
                                        <input
                                            type="checkbox"
                                            checked={settings.autoPlay}
                                            onChange={(e) => setSettings({ ...settings, autoPlay: e.target.checked })}
                                        />
                                        <span className="toggle-slider" />
                                    </label>
                                </div>
                            </div>

                            <div className="settings-group">
                                <div className="toggle-group">
                                    <label>Sound Effects</label>
                                    <label className="toggle-switch">
                                        <input
                                            type="checkbox"
                                            checked={settings.soundEffects}
                                            onChange={(e) => setSettings({ ...settings, soundEffects: e.target.checked })}
                                        />
                                        <span className="toggle-slider" />
                                    </label>
                                </div>
                            </div>

                            <div className="settings-group">
                                <div className="toggle-group">
                                    <label>Continuous Listening</label>
                                    <label className="toggle-switch">
                                        <input
                                            type="checkbox"
                                            checked={settings.continuousMode}
                                            onChange={(e) => setSettings({ ...settings, continuousMode: e.target.checked })}
                                        />
                                        <span className="toggle-slider" />
                                    </label>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            );
        }

        // Render App
        ReactDOM.createRoot(document.getElementById("root")).render(<VoiceChatApp />);
    
