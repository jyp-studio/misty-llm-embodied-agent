# 03 — Episode 執行期間持續注意與管理 Cue

**What to build:** 讓 Attention Loop 在一個 Episode 執行期間仍持續消費輸入，但新的 Cue 只能被
去重、更新、排隊或淘汰，不能平行啟動第二個 Episode。

這張票先建立通用 cue scheduler，不處理完整人物 target tracking。它必須能用有時間的 scenario
展示：一個 Episode 忙碌時收到重複 cue、較高優先級 request 和最後已過期的 cue，且所有處置都可觀察。

**Blocked by:** 01

**Status:** resolved

- [x] Attention Loop 在 idle 與 active Episode 期間都持續處理 ScenarioInputAdapter 的 timed inputs
- [x] runtime 在任何時刻至多擁有一個能呼叫 model 或產生 robot effects 的 Episode
- [x] Cue queue 有明確 capacity、priority、deduplication、freshness 與 expiry 規則
- [x] Explicit Request 優先於非明確 cue，但不會在任意 physical effect 中途搶走控制權
- [x] Episode 完成後只會在安全的 Turn boundary 選取仍新鮮的下一個 cue
- [x] queue overflow、dedupe、replacement、expiry 與 dequeue 都留下 typed observable record
- [x] Demo 顯示 active cue、queued cues、優先級與被丟棄的原因
- [x] fake-clock tests 不使用真實 sleep，且包含會證明排程錯誤的 negative controls
- [x] runtime shutdown 會有界地結束 active work 並處理剩餘 queue，不留下背景 task

## Answer

以 cooperative Turn-boundary scheduler 完成：active Episode 每個 Tool 返回後收取已抵達 input，
但不平行開 Episode。queue policy、typed lifecycle records、shutdown 清理與同 seam Demo 已落地；
決策與限制記於 `PLAN.md` §16.52，現行結構記於 `docs/architecture.md`。
