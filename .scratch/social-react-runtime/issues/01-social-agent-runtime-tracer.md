# 01 — 建立 SocialAgentRuntime 最小垂直路徑

**What to build:** 讓一個有時間資訊的文字 scenario，從統一輸入進入 Attention Loop，開啟一次
bounded ReAct Episode，影響 simulated Misty，留下 Journal，最後能在 Demo 重播。這是新架構的
tracer bullet，也是後續所有自動觸發能力的主要 seam。

先以最簡單的 Explicit Request 打通完整路徑，不在這張票加入 wake detection、視覺分類、Skills、
多人交接或移動控制。既有單次 Episode runner 留作 runtime 內部依賴，不再由 Demo 直接呼叫。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] SocialAgentRuntime 提供清楚且有界的啟動、消費輸入、完成 Episode 與停止生命週期
- [ ] ScenarioInputAdapter 能以 fake clock 餵入一個文字 Explicit Request
- [ ] Attention Loop 將該 request 轉成 cue，並且只開啟一個 active Episode
- [ ] Episode 使用既有 bounded ReAct core、Tool dispatch 與 simulated effects，正常回到 idle
- [ ] runtime 結果同時包含 Attention/Cue 可觀察資料與既有 typed Episode Journal
- [ ] Demo 的一個內建文字案例走完整 runtime seam，完成後可重播而不是直接呼叫 Episode
- [ ] 主要測試從 SocialAgentRuntime 公開 Interface 斷言輸入、Journal、effect 與 ending
- [ ] Turn cap、runtime shutdown 與錯誤結束仍可證明為 bounded
- [ ] 預設測試不呼叫 hosted model、不需網路、不需硬體，且零 skip

## Comments

### 2026-09-09 — Demo 驗收 follow-up

三張情境卡的第一版讓 scripted future scenarios 看起來像已完成能力，也把 `Episode`、record count
與 `input_exhausted` 當成主要結果。Ticket 01 的 Demo acceptance 改為：

- greeting 是唯一可 Run 的案例；結果必須從這次 runtime records 與 Journal 衍生。
- 主畫面直接顯示輸入、Explicit Request、Tool choice、模擬說話內容與正常完成。
- scripted model 與 simulated robot 必須直接標示；它不是歷史錄影或自主 LLM 結果。
- 哭泣與 A→B 只作為 ticket 06／08 preview，在對應能力實作前拒絕 Run。
- raw runtime ending 與 Journal 保留在工程細節，不以「Misty 思考」描述不存在的 Decision Note。

完整決策與後續展示契約記於 `PLAN.md` §16.50。
