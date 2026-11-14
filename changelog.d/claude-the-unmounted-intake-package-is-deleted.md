### Removed

- You no longer carry the `thomas/intake/` package: a clipboard-capture service built for a FastAPI server that Thomas does not run. Its own status page said "not integrated", nothing mounted its routes, and its three `intake_*` tool names were listed in the chat tool policy though no such tools were ever registered. Its only caller was its own test, which is gone with it.
- Two one-shot installers are gone too, `tools/apply_feature_14.py` and `tools/install_feature_15_conversation_search.py`. They patched a FastAPI app and the features they installed were already wired in.
- The feature list no longer shows "Clipboard Monitor" as done, and the stays-deleted test now keeps all of these paths from returning without a caller.
