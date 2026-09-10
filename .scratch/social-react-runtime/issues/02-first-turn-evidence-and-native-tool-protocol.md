# 02 — 讓 Trigger Evidence 進入第一個 Turn

**What to build:** 讓一次由圖片或文字啟動的 Episode，在模型第一次決策前就收到 Trigger Evidence，
並以忠實的 native function-calling protocol 完成至少一次 Tool call、Tool result 與下一個 Turn。

這張票同時修正目前會遺失 Tool call identity、把 Tool result 改寫成 user message，以及默默忽略
多餘 Tool calls 的 protocol drift。視覺 cue 如何產生留給後續票；這裡用受控 scenario evidence
驗證 model boundary。

**Blocked by:** 01

**Status:** ready-for-agent

- [x] Trigger Evidence 是 Episode 建立時的 typed input，與每個 Tool 後取得的 Snapshot 明確分開
- [x] 第一個 model Turn 能收到文字 facts、selected image evidence、來源、時間與不確定性
- [x] provider-neutral Model Interface 可由 scripted model deterministic 測試，也能承載 multimodal input
- [x] hosted-model Adapter 保存 assistant Tool call identity，並以相符的 Tool result 接回下一個 Turn
- [x] 每 Turn 最多接受一個 Tool call；parallel 或多重 calls 會明確拒絕，不會默默丟棄
- [x] Tool result 後仍附加新的 Snapshot，使下一個 Turn 能依世界變化決策
- [x] 簡短 Decision Note 可記入 Journal，但不要求或保存 private chain-of-thought
- [x] Demo 能顯示 Trigger Evidence 摘要、Decision Note、Tool call 與對應 Observation
- [x] scripted provider tests 能抓到 evidence 消失、call identity 錯配、錯誤 role 及多 call 漂移
- [x] 預設測試不需 API key；真 multimodal model 只在明確 opt-in suite 執行

## Comments

### 2026-09-10 — Implementation

- Trigger Evidence 成為 Runtime → Session → bounded Episode 的 typed input；圖片只在記憶體中傳入第一個 Turn，Demo payload 不回傳 raw base64。
- provider-neutral context 保留 assistant Tool call 與 matching `tool_call_id`；OpenAI adapter 明確送出 `parallel_tool_calls=False` 並拒絕多 calls。
- Decision Note 是 240 字內的公開 Journal record，Storyboard 與 Demo 可重播；persona 明確不要求 private reasoning。
- 預設驗收使用 scripted provider、fake clock 與 simulated Misty，不需 API key、網路或硬體；本專案仍未曾連接 Misty II。
