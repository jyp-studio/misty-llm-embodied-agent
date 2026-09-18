# 07 — 加入 Agent Skills progressive disclosure

**What to build:** 建立獨立於 Tool Registry 的 Skill Catalog。模型先看到可用 Skill 的名稱與描述，
再於需要時載入完整 `SKILL.md` 指引；Skill 只影響同一個 ReAct Episode 後續 Turns，所有感知與
副作用仍只能經過 typed Tools。

以「請協助我冷靜」做完整展示：模型載入支持性互動 Skill，組合說話、聆聽與肢體表達，最後主動
結束。第一版不執行 Skill scripts，也不建立巢狀 agent。

**Blocked by:** 02

**Status:** resolved

- [x] Skill Catalog 驗證必要 metadata，並只向 model 初始揭露名稱與描述
- [x] typed Skill activation capability 會載入指定 Skill instructions，未知或無效 Skill 會明確拒絕
- [x] active Skill instructions 只加入目前 Episode 的後續 model context，Episode 結束即丟棄
- [x] Skill 可以逐步讀取 references/assets，但第一版拒絕執行 scripts
- [x] Skill 無法直接呼叫 Robot Adapter、繞過 Tool validation 或啟動另一個 ReAct loop
- [x] 「協助冷靜」scenario 會載入合適 Skill，組合 speak、listen 與 expressive Tools
- [x] Demo 顯示 available Skills、activation、目前 active Skill 與由其引導的 Tool sequence
- [x] 新增一個合規 Skill 不需要修改 ReAct core 或 Tool Registry
- [x] tests 覆蓋 metadata、discovery、activation、缺失資源、script prohibition 與 context cleanup
