# 05 — 入口：真驅動路徑

**What to build:** 讓真的 driver 被組起來 —— 即使沒有人能執行它。

M7 的教訓寫在 `PLAN.md` §15.34：`EmergencyStop` 與 `ToolContext.ears` 造好、測到 mutation
全紅、**完全沒接線**，直到 #12 才發現。一個忘記接線的 session 會通過專案裡其他每一條測試，
同時讓機器人停不下來、而且對自己的聲音充耳不聞。

`load_api_key` 現在是同一個狀態：搬進來了、測過了、**沒有任何呼叫端** —— 所以 README 與
`.env.example` 承諾的 `OAI_CONFIG_LIST.json` 這條路實際上不通。

**Blocked by:** 04

**Status:** ready-for-agent

- [ ] 真的 driver（機器人指令、AV 串流、影像與距離管線、音訊、事件串流）在一條明確的路徑上
      被組起來
- [ ] 腳踩保險桿接到緊急停止；麥克風接到 TTS 抑制窗
- [ ] 所有協作者共用同一個時鐘
- [ ] `load_api_key` 有生產呼叫端
- [ ] 這條路徑**明確標註「從未在真機執行過」**（`PLAN.md` §8），不得暗示它被驗證過
- [ ] 有測試在協作者邊界上用假物件涵蓋這條組裝路徑
- [ ] 預設仍然是模擬路徑
- [ ] 全套測試綠且零 skip
