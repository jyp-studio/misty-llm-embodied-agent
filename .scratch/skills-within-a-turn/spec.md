# Skills within a Turn: reading guidance without spending a Turn

Status: needs-triage

> 2026-09-29 與使用者討論後記錄，尚未 grill，也還沒拆 ticket。開始前先跑一次 `/grill-with-docs`
> 把「待決問題」定下來。架構圖 `assets/architecture.svg`（README 使用中）已經照本檔的目標行為畫
> （一個 Turn 內 policy 讀 Skill、選動作、觀察），**比程式超前**；在本檔實作前，對外圖說必須註明，
> 或改回現行行為。

---

## Problem Statement

現在讀 Skill 會用掉一整個 Turn。模型在第一個 Turn 就看得到每個 Skill 的 name 與 description
（目錄），但要讀完整指引必須呼叫 `activate_skill`（`misty_agent/agent/tools.py`），它和 `speak`、
`listen` 一樣是 Tool；再讀 references 要另一次 `read_skill_resource`。ReAct 一個 Turn 只呼叫一個
Tool，所以：

- 「請幫我冷靜下來」的錄音（`misty_agent/demo/recordings/calming-support.json`）第 1 個 Turn 只做了
  `activate_skill`，第 2 個 Turn 才開口。對方多等了一次 model call（約 1–3 秒）才聽到回應。
- 讀 Skill 在 Journal 與 demo 上是一個獨立的動作，和使用者直覺的「看到輸入 → 想到要參考哪份指引 →
  選動作 → 執行 → 觀察」不一致。架構圖畫成一個 Turn 時，demo 的三格畫面就會橫跨三個 Turn。
- Turn 上限 12 裡，讀 Skill 與讀 reference 最多可能先吃掉兩個。

使用者期待的行為：**讀 Skill 是 policy 在同一個 Turn 內參考的資料，不是一個對外的動作。**
一個 Turn 仍然是 π → a_t → o_t，只是 π 在選 a_t 之前可以先讀需要的 Skill。

## 現行設計與它的理由（改之前要先回答）

見 `PLAN.md` §16.56 與 `docs/adr/0002-separate-skills-from-tools.md`：

- 讀 Skill 走同一條 typed Tool schema／validation／dispatch，內容放在 Tool result，所以會進
  Journal，可追查模型讀了什麼、何時讀。
- 目錄在第一個 Turn 就給，完整指引按需載入（progressive disclosure），不讓每個 Episode 都付全部
  Skill 的 token。
- Skill 不能繞過 Tool 與控制層影響機器人；它只是文字指引。

改動不能丟掉這三點：可追查、按需、沒有第二條影響機器人的路徑。

## 可能的方向（待 grill 選定）

1. **同一個 Turn 內允許「讀 Skill」後再選一個動作。** 讀 Skill 仍是 typed call、仍記進 Journal，
   但不算 Turn，也不附 Snapshot；模型拿到指引後，同一個 Turn 再做一次 model call 選出唯一的動作
   Tool。代價：一個 Turn 可能有兩次 model call，延遲與 token 要重新量；「一個 Turn 一個 Tool」
   要改寫成「一個 Turn 一個**有外部效果的** Tool」。
2. **Runtime 在 Turn 開始前預先載入。** 依 Trigger Evidence 或模型前一 Turn 的宣告預先把 Skill
   指引放進 working context。代價：由 runtime 而不是模型決定載入哪份，等於在 runtime 裡做語意判斷，
   和「Attention Loop 不選擇回應」的原則相衝，需要非常窄的規則。
3. **目錄直接附完整指引。** 最簡單，但放棄按需載入，Skill 一多 prompt 就膨脹；只適合 Skill 很少時。

## 會受影響的東西

- `misty_agent/agent/react.py`：Turn 的定義、Turn 上限的計算、`Dispatched` 與 Observation 的組成。
- Journal 型別：讀 Skill 的紀錄若不再是 `tool_called` + `observation`，需要新型別或新欄位；
  goldens 與 `tests/goldens/README.md` 的讓步規則照走。
- `tests/episode_invariants.py`、live 測試的不變量（一個 Turn 一個 Tool）。
- Demo 的 plain telling：讀 Skill 目前是一個獨立的步驟與 Skill 卡片。
- 既有 15 份錄音都是舊行為；改完要重錄才會反映在 demo。
- 和 `.scratch/body-language/spec.md` 的關係：兩者都在放寬「一個 Turn 一個 Tool」。應該一起 grill，
  避免各自定義一套 Turn 內的附加呼叫。

## 待決問題

1. 一個 Turn 內最多讀幾份 Skill／reference？超過時是拒絕還是算下一個 Turn？
2. 讀 Skill 的 model call 算不算進延遲與 token 的量測？Journal 怎麼區分「讀指引」和「選動作」兩次呼叫？
3. Turn 上限 12 是否需要重算？現行 12 的依據見 §16.48。
4. `read_skill_resource` 是否一併移進 Turn 內，還是維持為一般 Tool？
5. 失敗處理：Skill 不存在或無效時，同一個 Turn 是繼續選動作，還是以 refusal 結束這個 Turn？
