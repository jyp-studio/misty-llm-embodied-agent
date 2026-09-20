# 14 — 加入中英雙語與緊急情境界線

**What to build:** 讓 Misty 在中文或英文 Episode 中跟隨目前使用者語言，並在自傷、醫療危險或
物理救援要求中提供支持性但有界的回應。它可以鼓勵尋找附近可信任的人或當地緊急服務並保持對話，
但不得診斷、承諾救援、主動聯絡第三方或聲稱能執行物理救援。

使用 system behavior policy 與適當 Skill 指引模型，不建立關鍵字對應固定台詞的旁路。

**Blocked by:** 07

**Status:** resolved

- [x] 中文 utterance 得到自然中文回應，英文 utterance 得到自然英文回應
- [x] 同一 Episode 的使用者改變語言時，模型可以跟隨目前語言而不遺失對話脈絡
- [x] wake phrase 仍只接受既定英文 `Hey Misty` 與 `Hi Misty`
- [x] 高風險 scenario 使用支持性語言並建議尋求附近可信任的人或當地緊急服務
- [x] 回應不作心理／醫療診斷，不保證安全結果，也不宣稱已聯絡任何第三方
- [x] 要求 Misty 執行物理救援時，清楚表達能力限制並提供安全的替代建議
- [x] behavior policy 與 Skill 只引導 model；所有 effects 仍經過正常 ReAct／Tool 路徑
- [x] Demo 提供至少一個中文支持案例與一個英文 emergency-boundary 案例
- [x] scripted-model tests 以允許／禁止行為性質斷言，不比對固定句子
- [x] 真模型評估是 opt-in，結果與 deterministic suite 分開報告


## Answer

語言與緊急界線都寫在 persona policy 與 `emergency-boundaries` Skill，runtime 不做關鍵字對應。
兩條界線是結構性的：沒有任何 Tool 能離開機器人（「已聯絡第三方」不可能為真），`speak` 只收 text。
其餘是指引，可能被改寫繞過，文件與測試都這樣說。

`tests/boundary_audit.py` 把說出口的話讀成性質，`tests/test_boundary_audit.py` 證明每個 pattern
都會觸發、也不會誤判守住界線的句子。`tests/test_bilingual_emergency.py` 以性質而非固定句子斷言
scripted Episodes。真模型評估沿用 `llm_live` marker，預設 deselect，只報告不 gate。

Demo 關心卡新增中文求助與英文救援界線兩個案例，各自示範載入 Skill、說明能力限制並指向真正的
求助管道。
