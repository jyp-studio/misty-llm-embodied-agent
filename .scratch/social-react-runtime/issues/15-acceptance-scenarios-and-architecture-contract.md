# 15 — 完成 15 個 Acceptance Scenarios 與架構收斂

**What to build:** 將規格中的 15 個社交情境整理成 Demo 與自動測試共用的 declarative scenario
set，補齊整體組合驗收，移除會繞過 SocialAgentRuntime 的舊產品入口，並讓架構文件只描述目前
真正存在且有證據的能力。

這是整合與 contract 階段，不是正式 benchmark：沒有 leaderboard、單一分數，也不宣稱與其他
robotics 或 social-agent benchmark 相容。

**Blocked by:** 04, 06, 07, 11, 12, 13, 14

**Status:** resolved

- [x] 共用 scenario set 包含空房間、無互動路人、wake 問候、揮手邀請、分享好消息
- [x] 共用 scenario set 包含疑似哭泣、要求獨處、邀請靠近、模糊求助、無需移動的問題
- [x] 共用 scenario set 包含協助冷靜、表情／言語衝突、A→B handoff、movement hazard、stale queued cue
- [x] 每個 scenario 定義 timed inputs、匿名 actors、可用 Skills/Tools、允許行為、禁止行為與 ending
- [x] 自動測試與 Demo picker 讀取同一份 scenario source of truth
- [x] 社交斷言允許多個合理回應與 Tool sequences，但明確拒絕不安全或違反界線的結果
- [x] Demo 能標示 specification fixture、scripted run、live-model run 與 `hardware-unverified` path
- [x] Demo 可播放、暫停、重播、拖曳全部 Moments，並顯示 Attention、Evidence、Target、Skill、Tool、Observation 與 ending
- [x] 所有產品入口都經過 SocialAgentRuntime；直接 Episode Interface 只保留給內部 invariant tests
- [x] current architecture、ADRs、glossary、未來計畫、handoff、圖示與 Demo 說明各自只承擔一種文件責任
- [x] 過期的 PPA、manual-only trigger、跨 Episode personal memory 與「主動互動不在範圍」敘述已修正
- [x] 預設 suite 在專案虛擬環境中不需網路、API key 或硬體，全部通過且零 skip
- [x] opt-in hosted-model results 分開報告，且任何未經真機驗證的能力都不包裝成 hardware evidence


## Answer

十五個情境寫成 `misty_agent/acceptance.py` 的 `ACCEPTANCE_CONTRACTS`，每條指名 card／fixture、
是否可開 Episode、Episode 數、cue 種類、必要 records、禁止與必要 Tools、底盤是否可動、是否必須
halt；不釘台詞與 Tool 順序，並對十五條一律套用 boundary audit。缺的三個情境（分享好消息、模糊
求助、不需移動的問題）已補上。

`run_fixture` 是執行內建 scenario 的唯一路徑，Demo 與 `tests/test_acceptance_scenarios.py` 共用，
因此頁面顯示的就是測試斷言過的那一次執行。每個契約維度都以 mutation 驗證會紅，其中 14 的契約
用 8 的 run 去跑會失敗——第一版不會，那是 review 抓到的空契約。

Demo 在 picker 標出規格情境編號與敘述，在結果標出三類 provenance 與 hardware-unverified，
`/acceptance` 提供完整契約，replay 可播放／暫停／從頭／拖曳整場所有 Moments。
所有產品入口都經過 `SocialAgentRuntime`，並有測試盯著（不再把 app.py 排除在外）。
`tests/test_documentation_contract.py` 讓文件責任與退場說法成為會紅的測試。

預設 suite 在 `.venv` 下不需網路、API key 或硬體，全過且零 skip；hosted-model 評估由 `llm_live`
marker 分開報告。這不是 benchmark：沒有分數、沒有 leaderboard，也不宣稱與其他 suite 可比。
