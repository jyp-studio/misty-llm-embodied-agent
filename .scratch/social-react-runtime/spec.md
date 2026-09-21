# Social ReAct Runtime

Status: ready-for-agent

> 本規格綜合 2026-09-08 至 2026-09-09 的 `/grill-with-docs` 決策，並取代舊計畫中
> 「只執行外部觸發的單次 Episode」及「主動互動不在工程範圍」的方向。既有 bounded ReAct
> core、typed Journal、Tool validation、approach controller、simulated world 與 Demo
> Storyboard 是遷移基礎，不代表目前已具備本規格描述的完整 runtime。

---

## Problem Statement

這個專案目前有一個真正的 bounded ReAct core：模型可以在每個 Turn 選擇 Tool、接收
Observation，再依新資訊作下一個決定。但從使用者角度看，它仍不是一個自主社交機器人，而是一個
必須由命令列或 Demo 頁面手動餵入 trigger 才會跑一次的 Episode runner。

這與目標產品之間有幾個根本缺口：

- 沒有常駐的 Attention Loop，因此 AV streaming、語音與視覺感知不會自行產生 Episode。
- 沒有 wake-word gate；目前的音訊路徑會把音量超過門檻的 utterance 送往 hosted ASR，卻沒有
  runtime 消費者負責開啟 Episode。
- 視覺只提供便宜的 face presence、單眼距離與 gaze 線索；沒有可觀察的 Care Cue、Social
  Invitation、多人追蹤或短時間 Evidence。
- Trigger Evidence 沒有進入第一個 Turn。現在模型最初只看到 trigger 名稱與文字，因此視覺
  Episode 對模型實際上是盲的。
- 現有 model adapter 沒有忠實保存 native function-calling protocol；Tool call identity 會遺失，
  Observation 也不是以標準 Tool result 接回，而且多個 Tool calls 只取第一個。
- 現有 Tool Registry 可以驗證參數，但沒有 Skill Catalog，也沒有 Agent Skills 式的 progressive
  disclosure。
- 現有定位和 approach 只適用於人物已在正前方的簡化世界。頭轉向側面後，底盤仍可能直走；沒有
  Interaction Target lock、bearing alignment、多人物一致性或 hazard-aware approach。
- 現有 memory 會跨 Episode 保留 Exchange，與目前確定的 privacy-first、無個人長期記憶方向
  衝突。
- 現有 Demo 已能上傳輸入、重播 Episode Journal 並畫簡單 Misty，但內容仍是手動單次 Episode；
  它看不到 Attention Loop、Trigger Evidence、Skills、Interaction Target、cue queue 或底盤移動，
  內建 examples 也不是新的社交能力驗收情境。
- `PLAN.md`、`HANDOFF.md`、README、測試敘述與實作之間已出現多處漂移，讓維護者無法判斷哪一份
  才是目前架構真相。

使用者需要的是一個由 LLM 作社交判斷、由程式控制安全界線的 Misty social agent：它能在低成本
注意環境後自主開啟 bounded ReAct Episode，以 Skills 組合 Tools，根據每次 Observation 修正
行為，並能在沒有實體 Misty 的前提下透過同一套 runtime、模擬世界與 UI 完整展示。

## Solution

建立一個常駐的 SocialAgentRuntime，將連續的 Attention Loop 與既有 bounded ReAct Episode
組合成一個可替換輸入與 Robot Adapter 的深 Module。

SocialAgentRuntime 接受一個 InputSource：正式路徑由 LiveInputAdapter 將 RTSP AV streaming
與 Misty Events 轉成統一輸入；無硬體路徑由 ScenarioInputAdapter 將圖片、音訊、文字與內建
時間序列案例轉成相同輸入。兩條路徑進入完全相同的 Attention Loop、Episode orchestration、
Skill／Tool dispatch、Journal 與控制層。

Attention Loop 使用本地且低成本的 wake-word、人物與可觀察 cue gate。它只判斷是否值得建立
Trigger Evidence，不決定情緒是否為真，也不決定 Misty 要說什麼或是否移動。被選中的少量 Evidence
在第一個 ReAct Turn 交給 multimodal model；LLM 再根據不確定性、使用者語言、互動脈絡與可用
Skills／Tools 自主選擇回應。

同一時間只有一個 Episode 與一個 Interaction Target。Attention Loop 在 Episode 執行期間仍然
運作，但只能去重、更新、排隊或淘汰新的 cue。交接只在 Turn 邊界發生；只有 e-stop 及硬安全事件
可以立即中止執行中的行為。

Skills 與 Tools 分離：Skill 是符合 Agent Skills 慣例、逐步載入的指引；Tool 是唯一能讀取世界或
產生副作用的 typed bounded capability。Skill 不建立巢狀 agent、不執行任意 script，也不繞過
Tool validation、控制層或安全條件。

LLM 決定社交意圖與語意動作；deterministic controller 根據新鮮 Reading、Interaction Target、
對準狀態、hazard、設定與 deadline 計算短距離 movement Steps。LLM 不直接指定底盤 velocity、
angular velocity 或 motor duration。

Demo UI 會重構成 SocialAgentRuntime 的正式 client。它與自動測試共用 ScenarioInputAdapter 和
Acceptance Scenario 定義，能輸入文字或圖片、選取內建案例，並在一次 bounded run 完成後重播
Attention、Trigger Evidence、Episode Journal 與簡單 Misty 動畫。每個行為型垂直切片完成時都要
留下可由 UI 或內建案例觀察的成果，不等到整個專案最後才整合。

## User Stories

1. 身為周遭的人，我想在沒有任何人或互動線索時不被 Misty 打擾，這樣機器人不會為了展示功能而持續說話。
2. 身為路過的人，我想在沒有看向 Misty、沒有說話且沒有 Care Cue 時被忽略，這樣一般活動不會被誤判為求助。
3. 身為使用者，我想用 `Hey Misty` 或 `Hi Misty` 喚醒機器人，這樣我可以明確開始一次互動。
4. 身為使用者，我想讓 wake phrase 只開啟一次 bounded Episode，這樣背景聲音不會造成無止境錄音與模型呼叫。
5. 身為使用者，我想在 wake phrase 後說出完整 utterance，這樣 Misty 能以 VAD 和 ASR 取得我的需求。
6. 身為使用者，我想在看向 Misty 並揮手時被辨識為可能的 Social Invitation，這樣我可以用非語言方式開始低風險互動。
7. 身為可能需要關心的人，我想讓 Misty 把哭泣或異常表情視為不確定的 Care Cue，而不是診斷，這樣它不會武斷描述我的狀態。
8. 身為可能需要關心的人，我想由 LLM 決定是否先詢問、再觀察或保持距離，這樣 Care Cue 不會硬觸發固定安慰腳本。
9. 身為使用者，我想讓 Misty 在未經邀請時不要必然靠近，這樣社交關心不會侵犯我的空間。
10. 身為使用者，我想在說「請不要過來」時讓 Misty 尊重拒絕並停止接近，這樣我的界線優先於模型原先的計畫。
11. 身為使用者，我想在說「可以過來陪我嗎」時讓 Misty 安全對準並接近我，這樣語言與具身行為能一致。
12. 身為求助者，我想在只說「我需要幫忙」時先被詢問具體需求，這樣 Misty 不會自行編造問題或解法。
13. 身為詢問簡單問題的人，我想在不需要靠近時直接獲得回答，這樣 Misty 不會做多餘移動。
14. 身為分享好消息的人，我想得到與喜悅相符的語言、表情或手勢，這樣互動具有基本社交一致性。
15. 身為表情與言語不一致的人，我想讓 Misty 優先尊重我明確說出的感受並進一步澄清，這樣視覺分類不會凌駕自我陳述。
16. 身為焦慮並主動求助的人，我想得到有界、非醫療診斷式的支持性對話，這樣 Misty 能陪伴我而不冒充專業人員。
17. 身為使用者，我想在同一 Episode 的多個 Turn 中讓 Misty 記得我的名字與剛才說過的話，這樣對話具有連續性。
18. 身為使用者，我想在新 Episode 開始時預設不被套用上一個人的個人資訊，這樣匿名互動不會互相污染。
19. 身為 A，我想在與 Misty 對話時持續是該 Episode 的 Interaction Target，這樣旁邊出現另一張臉不會讓機器人偷偷換人。
20. 身為 B，我想在 A 的 Episode 期間呼叫 Misty 時被排入等待，而不是被完全忽略，這樣我的明確請求之後仍可獲得回應。
21. 身為 A，我想在 B 呼叫時讓 Misty先於安全的 Turn 邊界和我收尾，這樣對話不會被突兀切斷。
22. 身為 B，我想在 A 結束後得到新的獨立 Episode，這樣 A 的名字和對話不會被誤認為是我的。
23. 身為拒絕互動的人，我想讓相同的非明確 cue 在短時間內受到 Cue Suppression，這樣 Misty 不會立刻再次打擾我。
24. 身為先前拒絕但現在主動求助的人，我想讓新的 Explicit Request 解除 Cue Suppression，這樣真正的需求仍能立即被處理。
25. 身為使用者，我想在中文或英文中和 Misty 對話，並讓它跟隨目前使用的語言，這樣我不需要先設定語言模式。
26. 身為處於緊急情境的人，我想讓 Misty提供支持並鼓勵尋求附近可信任的人或當地緊急服務，這樣它不會冷漠忽略風險。
27. 身為處於緊急情境的人，我想讓 Misty 清楚說明它不能診斷、承諾救援、聯絡第三方或執行物理救援，這樣能力不會被誤解。
28. 身為使用者，我想讓原始圖片、錄音與可識別個人的逐字稿只存在於單次處理所需的記憶體中，這樣真實互動不會被持久保存。
29. 身為使用者，我接受經本地 gate 篩選的少量 Evidence、音訊或逐字稿傳往 hosted model，這樣系統可以使用外部 ASR、VLM 與 LLM。
30. 身為使用者，我想讓完成或離開後的 Evidence 過期，這樣延遲排隊的舊 cue 不會造成不合時宜的互動。
31. 身為 ReAct agent，我想在第一個 Turn 就收到 Trigger Evidence，這樣視覺 Episode 不會從盲目決策開始。
32. 身為 ReAct agent，我想在每個 Tool 後收到 Tool result 與新的 Snapshot，這樣下一個 Turn 能根據世界變化重新決策。
33. 身為 ReAct agent，我想主動呼叫便宜或昂貴程度不同的感知 Tools，這樣不必讓每個 Turn 都付出 VLM 成本。
34. 身為 ReAct agent，我想呼叫 `listen` 取得對方下一句話，這樣多輪對話不是靠外部硬塞新文字。
35. 身為 ReAct agent，我想每個 Turn 最多提出一個 Tool call，這樣動作順序、Observation 與資源所有權保持清楚。
36. 身為 ReAct agent，我想保留 native Tool call identity 並接收對應 Tool result，這樣模型協議不會被轉成數個模糊的 user messages。
37. 身為 ReAct agent，我想用簡短 Decision Note 表示下一個 Tool 的公開意圖，這樣 Journal 可讀而不暴露 chain-of-thought。
38. 身為 ReAct agent，我想在沒有更多事情要做時主動呼叫 `done`，這樣簡單互動不會被拖滿所有 Turns。
39. 身為 ReAct agent，我想在 Tool 失敗後收到可行動的原因，這樣我能改用詢問、重新觀察或安全結束。
40. 身為 ReAct agent，我想看到可用 Skills 的名稱與描述，再只載入當下需要的完整說明，這樣 context 不會塞滿所有操作手冊。
41. 身為 Skill 作者，我想用常見的 `SKILL.md` metadata 與內容格式描述工作流程，這樣新增社交能力不必修改 ReAct core。
42. 身為 Skill 作者，我想讓 Skill 只能引導既有 Tools，這樣 instruction content 不會取得未經驗證的硬體權限。
43. 身為 Tool 作者，我想用單一 typed declaration 同時產生 model schema 與 runtime validation，這樣宣告和檢查不會漂移。
44. 身為 Tool 作者，我想在新增能力時不修改 ReAct loop，這樣 Tool Registry 能獨立擴充。
45. 身為維護者，我想讓 Skill Catalog 與 Tool Registry 分開管理，這樣「操作指引」與「可執行能力」不會被混為同一概念。
46. 身為使用者，我想讓 LLM 決定是否移動、靠近誰和何時停止，這樣機器人的社交行為不是固定 PPA 腳本。
47. 身為附近的人，我想讓 deterministic controller 而不是 hosted LLM 計算底盤速度、角速度與時間，這樣移動能根據新感知快速修正。
48. 身為附近的人，我想讓每段底盤 movement Step 前後都檢查新鮮 target、方向與 hazard，這樣機器人不會依舊資料盲目前進。
49. 身為附近的人，我想在 Interaction Target 消失或 hazard 出現時讓 Misty 停止，這樣原先的 approach 意圖不會凌駕最新安全條件。
50. 身為開發者，我想讓 real 與 simulated Misty 符合相同 Robot Interface，這樣 Tools 與控制器不需要兩份實作。
51. 身為開發者，我想讓 SimulatedMistyAdapter 更新姿勢、位置與世界結果，而不只是記錄指令，這樣 closed-loop controller 能在無硬體環境收斂。
52. 身為開發者，我想讓真機 Adapter 明確標示 hardware-unverified，這樣任何 reader 都不會把官方 request shape 誤認為實機證據。
53. 身為開發者，我想透過一個 SocialAgentRuntime Interface 驗證從 input 到 Journal 和 robot effects 的完整路徑，這樣測試不會繞過 Attention Loop。
54. 身為開發者，我想用 ScenarioInputAdapter 控制事件、時間、人物與失敗，這樣測試可以快速、可重複且不需網路或硬體。
55. 身為 Demo 使用者，我想輸入文字或上傳圖片建立一次 scenario，這樣我可以親自觀察 agent 的決策。
56. 身為 Demo 使用者，我想選擇內建 Acceptance Scenario，這樣沒有準備素材或 API key 時仍能看到有意義的案例。
57. 身為 Demo 使用者，我想看到 Attention Cue、Trigger Evidence、Interaction Target、Skill activation、Tool calls、Observations 與結束原因，這樣我能理解整個 runtime 而非只有最後一句話。
58. 身為 Demo 使用者，我想看到簡單 Misty 圖形重播說話、表情、頭部、手臂、LED 與底盤位置，這樣 Journal 中的抽象動作具有視覺對應。
59. 身為 Demo 使用者，我想播放、暫停、重播和拖曳已完成的 run，這樣我不需要重新呼叫模型才能檢查每個 Moment。
60. 身為 Demo 使用者，我想知道目前顯示的是內建 scenario、模擬 run 還是 hardware-unverified 路徑，這樣我不會誤解證據來源。
61. 身為維護者，我想讓 Demo 與自動測試引用同一份 Acceptance Scenario 定義，這樣畫面範例不會與驗收內容各自漂移。
62. 身為維護者，我想讓每個行為型垂直切片都有可操作或可選擇的 Demo 成果，這樣整合問題不會累積到最後才出現。
63. 身為維護者，我想讓 UI 只繪製 Python 已產生且可測的 Storyboard，這樣畫面語意不會藏在無測試的 JavaScript 判斷裡。
64. 身為維護者，我想讓預設測試不呼叫 hosted model、不需網路、不需 Misty，這樣測試結果穩定且不產生成本。
65. 身為維護者，我想讓需要真 LLM 的情境獨立執行並評估可觀察性質，而不是精確字串，這樣模型改寫句子不會造成假失敗。
66. 身為維護者，我想讓文件將 glossary、目前架構、重大決策、未來計畫與當前進度分開，這樣歷史敘述不再冒充現在真相。
67. 身為作品讀者，我想清楚看到哪些能力只在 simulation 或 replay 中被驗證，這樣 portfolio 不會暗示不存在的真機成果。

## Implementation Decisions

### Runtime 與主要 seam

- 建立 SocialAgentRuntime 作為常駐 agent 的深 Module。其 Interface 負責生命週期、輸入消費、
  Attention orchestration、單一 active Episode、cue handoff、硬中止與可觀察結果；內部 Module 不因
  測試方便而全部暴露。
- SocialAgentRuntime 是 Acceptance Scenarios 的最高且主要測試 seam。測試與 Demo 不得直接
  手動呼叫 Episode 來宣稱已驗證自主注意流程。
- 現有單次 Episode Interface 保留為 SocialAgentRuntime 內部依賴與較窄的 ReAct invariant seam，
  不再是產品最外層入口。
- 同一時間只有一個 Episode 擁有模型工作脈絡和 Robot effects。Episode 執行期間的新 cue 只會
  排隊、合併、更新優先順序或過期。
- 一般交接只能發生在 Turn 邊界。e-stop、bumper、hazard stop 與 runtime shutdown 可以立即打斷
  physical effect，並以結構化 ending 呈現。
- SocialAgentRuntime 有 Turn 上限、Episode wall-clock deadline、每個 Tool timeout 和 bounded
  input queues。預設 Turn 上限沿用目前的 12 作起始值；其餘數值由設定持有並透過 replay 結果調整，
  不宣稱是真機量測值。

### InputSource 與 Attention Loop

- InputSource 是統一的輸入 Interface，有兩個 Adapter：LiveInputAdapter 與
  ScenarioInputAdapter。Demo UI 不是第三個 Adapter；它是 ScenarioInputAdapter 的 caller。
- LiveInputAdapter 組合 RTSP AV streaming、外部 wake detector、VAD、ASR、本地視覺 gate 與
  Misty Events。這些可以是內部可替換實作，但不擴張 SocialAgentRuntime 的 Interface。
- ScenarioInputAdapter 接受有時間的圖片、音訊、transcript、人物狀態、hazard、bumper、模型回應
  與世界變化。內建 Acceptance Scenarios、自動測試及 Demo UI 使用同一套 declarative scenario。
- Attention Loop 是連續且低成本的注意機制。idle 時它可開啟 Episode；active Episode 期間它仍
  處理新輸入，但只能排隊或更新 cue，不能平行啟動第二個 Episode。
- 音訊 gate 在外部裝置上辨識可設定的 `Hey Misty` 與 `Hi Misty`。wake 成功後才開始 bounded
  utterance capture、VAD 與 hosted ASR；idle ambient speech 不持續送往 ASR。
- 第一版不使用 Misty 內建 wake recognition 或 source direction。兩者因 vendor microphone mode
  與 AV streaming 互斥而保留為 hardware-unverified 的未來替代方向。
- 第一版假設明確對 Misty 說出的 utterance 來自目前對話者。這是 simulation/product assumption，
  不是聲源定位能力宣稱。
- 視覺 gate 使用本地快速感知，只處理可觀察 signal：人物存在、朝向、揮手／姿勢、表情變化與
  時間連續性。它產生候選 Interaction Cue，不診斷情緒，也不硬編「哭泣就靠近」。
- Attention Loop 維持短且有界的 temporal evidence buffer。只有通過 gate 的少量 selected frames
  或 crops、可觀察 facts、時間與 transcript 形成 Trigger Evidence；不週期性上傳所有含人的畫面。
- 選擇安靜且沒有明顯可觀察 cue 的哭泣可能漏掉，優先避免持續上傳所有路人的影像。此限制要在
 文件與 Demo 中清楚呈現。
- Cue 分為 Explicit Request、Care Cue 與 Social Invitation。各 cue 帶匿名 track reference、
  timestamp、confidence、Evidence reference 與 freshness；不得把 classifier label 當成已證實情緒。
- Cue queue 有 bounded capacity、deduplication、freshness expiry 和 priority。Explicit Request
  優先於非明確 cue，但不能繞過當前 physical Tool 的安全停止程序。
- Episode 拒絕或正常完成後，對同一匿名 track 的非明確 cue 啟用可設定的短期 Cue Suppression；
  新 Explicit Request 永遠可以繞過 suppression。這不形成跨 Episode 個人身分或記憶。

### Trigger Evidence、perception 與 Target

- Trigger Evidence 在 Episode 建立時即存在，並在第一個 Turn 交給 model。它和每個 Tool 後附加的
  Snapshot 是不同概念。
- multimodal model 在第一個 Turn 進行語意判斷，並可選擇不互動、先詢問、呼叫主動感知 Tool、
  保持距離或結束。Attention Loop 不另行建立第二個固定 response planner。
- Snapshot 保持便宜且可在每個 Observation 取得；需要等待、重新取景、選擇性 VLM inspection 或
  更豐富 target facts 時，model 必須呼叫感知 Tool。
- 提供 bounded `listen`、便宜的 target observation 及較昂貴的 scene inspection 能力。所有感知
  Tool 都要回傳 typed result、freshness 與不確定性，不回傳未標來源的自由文字事實。
- 一個 Episode 只有一個 Interaction Target。Target 是匿名、短期且與 Evidence 對應的 track；
  可以 lost/reacquired，但不得因另一張更近或更清楚的臉而靜默替換。
- 新 Episode 不繼承上一個 Interaction Target。跨 Episode 的 cue deduplication 只使用短期匿名
  tracking token，不升格為人物身分。
- 多人物感知可以同時維持多個候選 track，但只有 active Interaction Target 能被當前 Episode 的
  movement Tool 使用。

### ReAct 與 model protocol

- 保留真正的 iterative ReAct：每個 Turn 是 model decision、至多一個 Tool call、Tool result 加
  Snapshot 的 Observation，再進入下一個 Turn。不得攤平成固定 perception-plan-action pipeline。
- Model Interface 保持 provider-neutral；正式 OpenAI Adapter 使用能忠實保存 native function
  call identity 與 Tool result 關係的 protocol。不得把 assistant/tool records 改寫成數個 user
  messages。
- 每次 model request 禁用 parallel Tool calls，且 adapter 若收到不符合「每 Turn 至多一個」的
  response 必須明確拒絕或正規化為錯誤，不可默默丟棄其餘 calls。
- Trigger Evidence、working context、active Skill instructions、Tool schemas 與最近 Observations 是
  model 可見內容。model 看不到 raw motor parameters、private chain-of-thought 或跨 Episode 個人
  transcript。
- 每個 decision 可帶一段簡短、非敏感的 Decision Note，描述下一個 Tool 的公開目的。它不是
  chain-of-thought，也不要求模型揭露隱藏推理。
- `done` 仍是 model 可在任何 Turn 選擇的 Tool。沒有因 trigger 類型而硬編的固定第一動作或
  response fast path。
- 同一 Episode 的 working context 保留名字、utterances、Tool calls 與 Observations；Episode
  結束即丟棄。第一版不做跨 Episode summary、facts extraction、RAG 或 personal memory。

### Skills 與 Tools

- Skill 採 Agent Skills 慣例：一個 Skill directory 至少含有帶 `name` 與 `description` metadata 的
  `SKILL.md`，並可帶 references 或 assets。第一版不執行 Skill scripts。
- Skill Catalog 先只向 model 揭露可用 Skill 的名稱與描述。model 透過 typed activation capability
  載入一個 Skill 的完整 instructions；需要時才讀 references/assets。
- Skill activation 只修改同一 Episode 後續 Turns 的 instruction context，不建立另一個 agent
  loop、不直接執行 effect，也不跳過 Tool Registry。
- Skill Catalog 與 Tool Registry 是不同 Module。前者管理 guidance 與 progressive disclosure；
  後者管理 capability schema、validation、dispatch 與 effects。
- Tool 仍由單一 typed definition 產生 model schema 與 runtime validation。未知參數、越界值與
  未註冊 Tool 必須在到達 Robot Interface 前拒絕，並回到 model 成為可行動 Observation。
- 初始 Tool surface 保留必要的說話、表情、LED、音訊與肢體表達能力，並加入本規格要求的 Skill
  activation、listen、主動 target observation、scene inspection、target-aware approach、stop 與
  done。既有重疊或幾何不完整的 Tool 必須在 ticket 設計時合併或遷移，不同名稱不得提供同一能力。
- 新增 Skill 不修改 ReAct core；新增 Tool 不修改 ReAct core。兩者新增方式都要有 validation、
  discoverability 與 Acceptance Scenario 或 focused contract coverage。

### Controller 與 Robot seam

- Robot Interface 有兩個 Adapter：RealMistyAdapter 與 SimulatedMistyAdapter。沒有第三個
  RecordingRobot，也不新增 RecordingTransport 作為本規格的一部分。
- RealMistyAdapter 將 Robot Interface 操作轉成 Misty HTTP/WebSocket 行為。由於專案沒有實體
  Misty，其 request shapes 可依 vendor 文件檢查，但行為、latency、calibration 與可靠度一律標為
  hardware-unverified。
- SimulatedMistyAdapter 不只記錄指令；它更新模擬的 pose、位置與世界結果，使後續 perception
  能看見 movement、target loss、hazard 或 failure，並讓 closed-loop controller 真正收斂或失敗。
- Journal 在 ReAct／Tool dispatch 層記錄 model intent、validation、Tool result、Observation 與
  ending，是 agent behavior 的唯一紀錄來源。Robot Adapter 不建立第二份競爭的行為紀錄。
- LLM 只選擇語意 movement intent，例如接近、朝向、停止或保持距離。velocity、angular velocity、
  motor duration、Step size、settling 與 retry 由 deterministic controller 持有。
- target-aware approach 每次只執行一個 bounded Step，然後等待 movement 後的新鮮 Reading。它在
  每步重新計算距離誤差，並受最大單步、arrival band、安全距離、總 Steps 與 deadline 限制。
- approach 前必須取得 active target bearing 並使底盤而非只有頭部對準 target。head yaw 不得被
  當成 chassis alignment。
- movement 前、中斷點與重新量測時都檢查 target freshness 與 hazard。失去 target、reading
  stale、hazard unavailable、bumper、deadline 或 Robot error 都產生明確結果並停止盲目前進。
- 真機模式若必要安全訊號無法取得，movement Tool fail closed；模擬模式可由 scenario 明確提供
  safety state。
- 所有 physical constants 與 movement assumptions 留在 configuration/controller 層，並標示
  simulated、measured 或 hardware-unverified。不得因公式可測就宣稱真機安全。

### Observability、privacy 與 Demo UI

- 保留 Episode Journal 的 typed invariants，並增加可表示 Attention decision、cue lifecycle、queue、
  suppression、handoff 與 runtime ending 的上層可觀察資料。不得為了 runtime records 把每個
  Episode record 的 `turn` 或 `episode_id` 強迫改成含糊的 Optional。
- Storyboard 由可觀察資料純函式推導。它負責把每個 record 轉成 Moment、fold robot state 並產生
  UI 所需結構；JavaScript 只負責控制播放與繪圖。
- 真實使用者的原始影音與可識別逐字稿只在單次處理必要期間存在記憶體，不寫入磁碟、不形成跨
  Episode memory，run 結束後釋放。合成／授權的 Acceptance Scenario assets 與預先產生的
  synthetic Journals 可以進入版本控制。
- hosted ASR、VLM 與 LLM 可接收完成當次判斷所需的 bounded selected Evidence；第一版不要求
  完全離線處理。UI 與文件要誠實說明外部傳輸與不持久保存是兩個不同概念。
- Demo UI 進行結構性重構，而不是將目前不完整頁面視為完成。保留有價值的純 HTTP handler、
  Storyboard projection、播放控制與 SVG pose rendering 思路，移除只適用舊 one-shot trigger 的
  假設。
- UI 至少支援文字與圖片輸入；音訊上傳可在相應行為切片加入。輸入會建立一次 bounded scenario，
  不直接繞過 SocialAgentRuntime 開 Episode。
- UI 提供內建 Acceptance Scenario picker。picker 與自動測試引用同一個 scenario source of truth，
  並標示它是 specification fixture、scripted run 或 live-model run。
- UI 顯示 Attention state、cue 類型、Trigger Evidence 摘要、Interaction Target、queued cues、
  Cue Suppression、active Skill、Decision Note、Tool calls、Observations、tokens/latency 與 ending。
- SVG Misty 至少呈現 expression、LED、head、arms、speaking state 與 simulated chassis position／
  target distance。UI 不暗示動畫等同真機動作。
- 初期採 run 完成後的 Journal/Storyboard replay，不新增即時 streaming seam。可播放、暫停、重播、
  拖曳 Moment 並展開 typed fields。
- 每個行為型 ticket 的 acceptance criteria 必須包含一條 UI 或內建 example 的可見路徑。純機械
  prefactor 或底層 safety ticket 可以只交付測試，但不得破壞既有 Demo 路徑。

### Social policy、語言與緊急情境

- persona 使用友善、簡潔、不武斷的社交語氣。視覺 cue 是 Evidence，不是對情緒或意圖的確診。
- LLM 自主決定是否介入與是否移動；system instructions/Skills 可以定義尊重界線、先詢問、承認
  不確定性等行為準則，但不得把 Care Cue 映射成固定動作。
- 支援中文與英文，預設跟隨目前 utterance 的語言；同一 Episode 語言改變時可以跟隨。wake phrase
  接受英文 `Hey Misty` 與 `Hi Misty`，不加入中文 wake phrase。
- 在自傷、醫療危險或物理救援要求中，Misty 可以提供支持性語言、鼓勵尋找附近可信任的人或當地
  緊急服務並保持對話，但不得診斷、承諾救援、主動聯絡第三方或執行物理救援。

### 文件與遷移

- 先建立一份簡潔的 current architecture 文件，再依 vertical tickets 修改程式。舊文件不得繼續
  把一次性 manual Episode、跨 Episode personal memory 或「主動互動不在範圍」說成目前方向。
- glossary 只定義 ubiquitous language，不放實作細節。Attention Loop 的定義要涵蓋 active
  Episode 期間持續觀察與排隊，修正目前只寫 idle watch 的過窄描述。
- 架構文件保存目前架構真相；ADR 保存難逆轉且有取捨的決策；未來計畫文件只保存未來工作；
  handoff 文件只保存目前進度；舊長篇時間順序決策移入 history。
- 專案概覽、architecture diagram、設定說明、測試註解與 Demo 文案要在對應行為落地時同步更新，
  不留到最後以一次性大掃除修補。
- 所有保留的 real-driver 路徑、文件與 UI 都清楚標示：本專案沒有 Misty II，任何硬體行為從未驗證。

## Testing Decisions

好的測試斷言穿過公開 Interface 可觀察到的行為，而不是 class 數量、私有 queue、prompt 拼接順序
或內部 state machine。重構內部 Module 時，只要相同 scenario 產生相同可接受結果，主要測試就
不應修改。

### 主要 seam

- 主要 acceptance seam 是 SocialAgentRuntime。每個 scenario 透過 ScenarioInputAdapter 餵入
  timed inputs，透過 SimulatedMistyAdapter 產生 physical consequences，最後斷言 runtime
  observability、Episode Journals、robot state/effects、queue/handoff 與 ending。
- 這個 seam 必須涵蓋 Attention Loop 到 Episode 的完整路徑。直接呼叫單次 Episode 的測試只證明
  ReAct invariants，不算完成任何「自主觸發」Acceptance Scenario。
- Demo UI 使用同一 seam 與 scenario definitions。測試 Storyboard/view data，不依賴瀏覽器 pixel
  screenshot；頁面只繪製已測的資料。

### 15 個 Acceptance Scenarios

1. 空房間、無語音：不產生 Episode。
2. 有路人但未看向 Misty、沒有 cue：不打擾、不產生 Episode。
3. `Hey/Hi Misty` 加一般問候：開啟 Episode、合理回應並主動完成。
4. 人物看向 Misty 並揮手：形成 Social Invitation，可低風險回應但不強制靠近。
5. 使用者分享成功消息：語言與表達協調，不做無關 movement。
6. 人物疑似哭泣但未說話：承認不確定性；可詢問、觀察或不介入，不把 approach 當固定答案。
7. 可能悲傷的人明確說想獨處：尊重拒絕、停止追問與 movement，完成 Episode 並啟用 suppression。
8. 使用者明確邀請 Misty 過來陪伴：保持 target、對準、安全 approach，再進行互動。
9. 使用者只說需要幫忙：不猜需求，先確認對話者並詢問需要什麼協助。
10. 使用者提出不需要移動的問題：回答或澄清，不為展示功能而 approach。
11. 使用者主動要求協助冷靜：載入適當 Skill，組合 speak/listen/expressive Tools，不作醫療診斷。
12. 視覺看似微笑但使用者明確說難過：尊重自我陳述並澄清，不讓 classifier label 覆蓋語言。
13. A 的 Episode 期間 B 明確呼叫：保持 A target，排隊 B，在 Turn 邊界收尾後為 B 開獨立 Episode。
14. approach 期間 target lost 或 hazard 出現：立即停止盲目前進，回報失敗並由 model 改採重新觀察、
    遠距對話或結束。
15. queued Care Cue 在輪到處理前已恢復、離開或過期：依新 Evidence 丟棄，不依舊資料強行互動。

每個 scenario 定義輸入時間線、actors/anonymous tracks、可用 Skills/Tools、可接受行為集合、禁止
行為、必要 ending 與可觀察 assertions。社交情境不要求唯一台詞或唯一 Tool sequence。

### Focused coverage

- wake detector 使用音訊 fixtures 驗證兩個 wake phrases、false trigger、bounded capture、VAD、
  ASR 只在 wake 後執行及 queue backpressure。
- visual gate 使用短 temporal fixtures 驗證無人、路人、gaze/wave、candidate Care Cue、多人 track、
  confidence/freshness 與 negative controls。單張 still-image test 不得宣稱已驗證 temporal gesture。
- model adapter 以 scripted provider responses 驗證 native call identity、Tool result role、單 Tool
  policy、multimodal first Turn、error/timeout 與 token/latency accounting。
- Skill Catalog 驗證 metadata、progressive disclosure、缺失／無效 Skill、references/assets 與第一版
  script prohibition。Tool Registry 延續 typed schema/validation/refusal invariants。
- target-aware controller 以 simulated world 驗證 bearing alignment、fresh readings、bounded Steps、
  arrival、overshoot assumptions、target loss、hazard、bumper、timeout 及 Robot error。公式可測不等於
  hardware-safe。
- memory/privacy coverage 驗證 Episode working context 會保留、下一 Episode 不含前一人的資訊、
  Cue Suppression 不是 personal memory、real-user payload 不落地，以及 run 結束後釋放 ephemeral media。
- cue queue coverage 驗證 bounded capacity、dedupe、priority、expiry、active target stability、
  Turn-boundary handoff 與 Explicit Request bypass。
- Storyboard coverage 驗證每個 runtime/Episode record 都有 Moment、只有成功 effects 改變 robot
  state、底盤位置可重播、內建 scenario provenance 清楚且 UI payload 不含原始媒體。

### Test execution policy

- 預設 suite 在專案 `.venv` 執行，不呼叫 hosted model、不需網路、不需硬體，而且不得因錯誤
  interpreter 導致 perception tests skip。
- 真 LLM/VLM/ASR scenarios 使用明確 marker、由使用者主動執行並分開報告。它們評估終止、Tool
  合法性、target consistency、禁止行為與結果性質，不比對精確台詞，也不成為 deterministic CI gate。
- 合成 scenario、scripted model、fake clock、simulated world、typed Journal、Episode invariant tests、
  perception fixtures 與純 Storyboard projection 是既有 prior art，應優先深化而不是另建平行 harness。
- 所有時間、queue 與 concurrency tests 要有能證明測試會抓到錯誤的 negative control；不得用真實
  sleep 或 scheduler 運氣作 correctness oracle。
- 每個行為 ticket 先以最高 seam 寫 failing Acceptance Scenario，再補必要 focused tests。若最高
  seam 已完整覆蓋行為，避免保留與它重複且綁定內部實作的舊 unit tests。

## Out of Scope

- 真機校準、真機 safety certification，或宣稱任何功能曾在 Misty II 上驗證。
- Misty 內建 wake recognition、`Hey Snapdragon`、source-direction events 或多人 speaker
  attribution。
- SLAM、map-based navigation、房間級路徑規劃、occupancy grid、depth camera 或 2D/3D world pose。
- 從任意距離或場地導航到人物；第一版 movement 只處理相機可觀察、相對座標、可鎖定 target 的
  bounded alignment 與 approach。
- 將表情或姿勢分類當作情緒診斷、心理健康診斷或求助意願的確定事實。
- 由 cue 硬編固定 response，包括「偵測哭泣即靠近」。
- 讓 LLM 直接控制 velocity、angular velocity、motor duration 或無界 movement。
- 同時執行多個 Episodes、同時有多個模型控制 robot effects，或在 Skill 內建立巢狀 agent loop。
- 第一版執行任意 Skill scripts、從網路自動安裝 Skill，或讓 Skill 繞過 Tool validation。
- 跨 Episode personal memory、face recognition identity、RAG、vector database 或 consent-based 長期
  profile；這些需要未來獨立隱私設計。
- 自動聯絡家人、醫療人員或緊急服務，以及任何物理救援能力。
- 完全離線的 ASR、VLM 與 LLM；本規格允許 bounded selected Evidence 傳往 hosted providers。
- 即時 streaming Demo UI、遠端公開部署、使用者帳號、多人登入或長期保存真實 run。
- 正式 benchmark、leaderboard、單一綜合分數或宣稱與 AutoMisty、SOTOPIA 等 benchmark 相容。
- 為了 UI 引入大型前端 framework；若未來確有需求，另行提出依賴與維護成本。

## Further Notes

- PPA 不是目前主要問題：既有 inner loop 已是 iterative ReAct。這個 effort 的核心是補上 autonomous
  runtime shell、first-Turn Evidence、Skills、target-aware control、privacy boundary 與可驗收 UI。
- Real driver 與 vendor capability 只能依官方文件組裝。所有聲源角度、AV mode 切換、motor
  calibration、hazard payload、camera latency 與 multi-person performance 都必須維持
  `hardware-unverified` 標示。
- `Hey Misty` 與 `Hi Misty` 都可作外部 wake phrase；不是產品差異。使用 Misty 內建 recognition
  會改變 AV architecture，因此不在本規格中偷偷切換。
- 「不保存」是 persistent-storage policy，不是禁止單次記憶體處理。Demo 可在 browser/session 中
  顯示當次 Journal，但重新整理或 run 結束後不把真實 payload 留在專案檔案中。
- Visual gating 優先減少旁觀者影像外傳，因此會接受部分低可觀察 Care Cue 的 false negatives。
  LLM 對入選 Evidence 的判斷仍必須承認不確定性。
- 現有 UI、Storyboards、goldens 與大量 unit/contract tests 是有價值的 prior art，但不得因數量
  很多就宣稱 15 個 SocialAgentRuntime scenarios 已完成。新的 scenarios 必須穿過新的主要 seam。
- 本 spec 發布只表示已具備拆票條件，不會自動修改產品程式碼。下一步是 `/to-tickets` 先提出
  tracer-bullet vertical slices、blocking edges 與每張票的可見 Demo 成果，經使用者批准後才發布。
