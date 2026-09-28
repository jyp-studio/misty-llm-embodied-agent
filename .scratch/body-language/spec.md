# Body Language: reflexes, co-speech gestures, and deliberate actions

Status: needs-triage

> 延後到 M10（開新 repo、乾淨歷史匯入、公開）之後才開始。本檔記錄 2026-09-28 與使用者討論
> 後的方向，尚未 grill，也還沒拆 ticket。開始前先跑一次 `/grill-with-docs` 把「待決問題」定下來。

---

## Problem Statement

使用者希望 Misty 有豐富的肢體語言：思考時歪頭沉思、說話時舉手等等。§16.67 已在 persona 加上
「Your body」一節，重錄後 15 份錄音的肢體 Tool 呼叫從 4 次增加到 10 次，但 9 份仍一次都沒用，
而且即使用了，也只能是「說完 → 停頓 → 舉手 → 停頓 → 再說」。

原因不在 prompt，而在架構：

- **ReAct 每個 Turn 只呼叫一個 Tool。** `speak` 與 `move_arms` 是兩個 Turn，只能先後發生，
  「邊說話邊舉手」在時間上做不到。
- **模型「在想」的時候，機器人什麼都不能做。** 思考就是在等 model call 回來，那段時間沒有任何
  Tool 在執行，所以「思考時歪頭」不可能由模型決定。
- **每個手勢都多花一個 Turn。** 一個 Turn 是一次 model call（約 1–3 秒、約 2.5k input
  tokens），模型自然傾向省略手勢；Turn 上限 12 也讓組合付不起。

## 方向（使用者已同意，細節待 grill）

依「做完需不需要看結果」分三層。ReAct 的價值是做完後觀察結果再決定；結果不確定、且會影響下一步
的動作（移動、觀察、聆聽）才值得一個 Turn。手勢是開環、幾乎必定成功的動作，每個都重新觀察只是
浪費 Turn。

| 層 | 誰決定 | 例子 | 怎麼執行 |
|---|---|---|---|
| 1. 反射層 | runtime 自動，不是模型 | model call 進行中頭微歪、燈慢閃；`listen` 時頭朝向對方；待機時的微小動作 | runtime 依狀態播放，不佔 Turn |
| 2. 伴隨說話的手勢 | 模型選語意 | 說「恭喜！」時雙手舉起；問問題時歪頭；打招呼時揮手 | `speak` 加可選 `gesture`，封閉小集合；runtime 在說話開始時同步播放、說完歸位；一個 Turn |
| 3. 刻意的多步驟行為 | 模型，照現在的 ReAct | 跳舞、靠近、後退、計時、觀察 | 一個 Turn 一個 Tool，每步有 Observation |

第 2 層比照 `approach(keep=...)`：模型給語意，角度與時機由 runtime 決定（§4「模型說要不要、
控制層說怎麼做」）。

## 考慮過但不推薦

- **一個 Turn 多個 Tool call**（OpenAI 支援 parallel function calls）：說話與手勢可同 Turn 送出，
  但要改 `react.py` 一 Turn 一 Tool 的核心不變式、golden 與 Journal 語意，而且模型仍要自己拼角度，
  不如第 2 層乾淨。
- **`express(emotion)` 預設組合**：一次做完臉、手、燈、音效，等於把 §4 移除的 AutoMisty 手勢
  整包搬回來，且不和說話同步。
- **只改 prompt**：§16.67 已經做了，效果見上方數字。

## 要與既有決策對帳

- **PLAN §4「AutoMisty 移除後的表現力由組合取代」**：第 2 層的封閉手勢集合與它衝突，需在 PLAN
  記錄理由——組合適合刻意的表演（第 3 層保留），不適合伴隨說話的手勢，因為一 Turn 一動作在時間
  上無法同步。
- **§16.67 當時沒選反射層**（理由：不是模型的決定，畫面上會混淆）。這次的理由是「思考時的動作只有
  runtime 能做」；混淆的問題靠 Journal 與舞台明確標示「反射」解決。
- **§15.2 / Tool 數量**：第 2 層不新增 Tool，只給 `speak` 加參數；golden 裡 `speak` 的 args
  會多一個欄位，依 goldens README 的規則記錄。

## 待決問題（grill 時處理）

1. 手勢集合的內容與大小：例如 `none / raise_arms / wave / tilt_head / nod / open_arms`？
   每個對應的角度序列、時長，以及說話比手勢短或長時怎麼辦。
2. 反射層的觸發條件與內容：model call 期間、`listen` 期間、待機；燈的顏色是否與模型用
   `change_led` 設的顏色衝突，誰優先。
3. 反射層在 Journal 裡怎麼記：新的 record type（例如 `reflex_played`），還是不記？若不記，
   舞台如何知道要畫——從 runtime 狀態推導還是從紀錄？
4. 安全：反射與伴隨手勢不能在移動中或 stop 之後發生；`respect_boundary` 之後是否全部停止。
5. 手勢在真實機器人上是 REST 命令序列，與 TTS 是否能對齊（PLAN §15.4：Misty 的 TTS 不回報時長，
   只能用估計值）。
6. 舞台：同時畫說話泡泡與手勢；反射的視覺標示方式；重播時手勢的時間軸。
7. 評估：重錄後怎麼判斷「肢體語言變豐富」——例如每份錄音的手勢次數、伴隨說話手勢的比例。

## Out of Scope

- 真實硬體驗證（PLAN §8：沒有機器人）。
- 情緒辨識或依對方情緒自動選手勢；Care Cue 仍只是可觀察的幾何，不是情緒診斷。
- 以手勢取代任何安全界線上的語言回應。

## 參考

- `PLAN.md` §4、§15.2、§15.4、§15.15、§15.19、§16.67
- `misty_agent/agent/persona.py` 的「Your body」
- 2026-09-28 重錄統計：display_image 4、move_arms 2、change_led 2、move_head 2，9/15 份為零
