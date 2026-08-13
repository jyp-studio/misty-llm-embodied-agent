# M5 — ReAct 的可信 approach 後端

Status: ready-for-agent

> 上游脈絡：`PLAN.md` §5（缺陷 A、B、C、E）、§7（里程碑 M5）、§12（改成重寫），以及 M4 replay harness 的量測結果。

---

## Problem Statement

這個作品的核心是 ReAct robot：LLM 決定要不要接近使用者，確定性的控制層決定每一步走多遠，再把動作結果作為 observation 交回 ReAct。

目前缺的不是更多影像功能，而是一個可信的 `approach` 後端。舊控制迴圈可能在移動後繼續使用移動前的距離樣本，也可能依序處理已經過時的影格。這會讓機器人越過模擬安全底線後仍回報 `arrived`，使上層 ReAct 收到錯誤 observation。

現有控制律也只限制命令距離，沒有把未校準的實際移動誤差納入安全假設；樣本不足時則第一輪直接回報 `lost_user`。因此，即使 ReAct loop 本身設計正確，它依賴的 `approach` 工具仍不可靠。

M4 已經完成問題重現、延遲量測與 robustness sweep。M5 不再研究影像或最佳化 MediaPipe，而是把這些證據收斂成一個小而可靠、可供 ReAct 直接呼叫的後端。

## Solution

建立一條窄的感知至控制管線：永遠從 process 內最新的影格產生帶時間語意的距離讀數；每次移動後作廢舊讀數，等待移動後的新讀數；由確定性控制律規劃下一步；最後回傳結構化的 approach 結果。

主要測試 seam 是公開的 `approach()` 行為。測試以合成影格與記錄式 robot adapter 驅動整條流程，只觀察移動命令、讀數新鮮度所造成的行為，以及最後的結構化結果。queue、樣本容器、flush 次數與執行緒安排皆屬內部實作，不成為測試契約。

M4 已存在的 `latest_reading()` 保留為量測 seam，用同一把尺驗證正式管線的 process 內延遲上界。它不發展成第二套控制介面。

安全聲明必須維持誠實：M5 證明的是純軟體管線，以及在明示的傳輸延遲與驅動校準誤差假設內的模擬行為；它不證明真機安全，也不宣稱量到相機曝光至 process 的端到端延遲。

## User Stories

1. 身為 ReAct agent，我想呼叫一個單一的 `approach` 行為並收到結構化結果，這樣我能根據 observation 決定下一步。
2. 身為 ReAct agent，我想讓 `arrived` 只在新鮮讀數顯示機器人位於抵達帶內時出現，這樣我不會根據過時場景作決策。
3. 身為 ReAct agent，我想區分 `arrived`、`lost_user`、`timeout` 與 `drive_error`，這樣不同失敗可以導向不同的後續工具選擇。
4. 身為使用者，我想讓一次 approach 永遠在有限步數與有限等待時間內結束，這樣 robot 不會永久卡在一個工具呼叫裡。
5. 身為使用者，我想讓「請靠近」使用移動後的新距離重新閉環，這樣每一步都回應最新可得的世界狀態。
6. 身為使用者，我想讓短暫尚無樣本的情況先等待，而不是立即宣告看不到我，這樣啟動或移動後的正常感知延遲不會變成假失敗。
7. 身為使用者，我想讓長時間沒有有效人臉讀數的情況結束為 `lost_user`，這樣 robot 不會在失去目標後盲目移動。
8. 身為使用者，我想讓 robot 在驅動命令被拒絕或 adapter 發生錯誤時停止 approach，這樣失敗不會被偽裝成成功。
9. 身為開發者，我想讓 process 內的影格緩衝只保留最新值，這樣慢消費者不會逐張重播過去的世界。
10. 身為開發者，我想知道有多少影格因 latest-value 策略被取代，這樣我仍能診斷 producer 與 consumer 的速率差。
11. 身為開發者，我想讓距離讀數攜帶影格進入 process 與完成偵測的時間，這樣可以在決策當下判定 process 內年齡。
12. 身為開發者，我想讓時間欄位的名稱與實際量到的事件一致，這樣不會把「進入 process」誤稱為「相機曝光」。
13. 身為開發者，我想把不可測的 sensor transport lag 與可測的 process 內 age 分開，這樣報告不會暗示不存在的硬體證據。
14. 身為開發者，我想讓移動後的讀數必須晚於該次移動的失效 epoch，這樣中位數視窗不會被移動前樣本主導。
15. 身為開發者，我想在作廢後等待至少兩筆有效新樣本，這樣單一偵測雜訊不會直接驅動下一個移動命令。
16. 身為開發者，我想讓讀數等待期限可設定且有預設值，這樣測試可以快速推進，runtime 也有明確上界。
17. 身為開發者，我想讓讀數的最大允許年齡真正比較決策時間與 process ingress 時間，這樣設定名稱與行為一致。
18. 身為開發者，我想讓距離濾波、freshness 與樣本作廢藏在同一個深 module 後面，這樣呼叫端不需要重複維護時間規則。
19. 身為開發者，我想讓控制律同時處理前進與後退的步長上限，這樣降低 tolerance 或 gain 時不會喚醒反向超衝。
20. 身為開發者，我想把實際移動相對命令距離的最大假設明確建模，這樣 safety floor 的模擬保證有可讀的前提。
21. 身為開發者，我想直接掃描正式控制律而不是在測試中重寫公式，這樣實作與證明不會靜默分歧。
22. 身為開發者，我想把 M5 正式管線接回 M4 的 replay harness，這樣 before/after 使用同一個量測方法。
23. 身為開發者，我想維持 M4 已量得的 process 內延遲上界，這樣修正時間語意不會引入明顯效能退化。
24. 身為開發者，我想讓正式管線可注入既有的 synthetic video 與 recording robot adapters，這樣沒有硬體仍可驗證完整 approach 行為。
25. 身為 CI，我想讓所有 M5 測試免費、確定性且不呼叫 LLM，這樣它們可以在每個 push 執行。
26. 身為履歷讀者，我想看到 ReAct 的 approach observation 來自可重現的閉環驗證，這樣作品不只展示 prompt 與 function calling。
27. 身為履歷讀者，我想清楚看到「已模擬驗證」與「未實機驗證」的界線，這樣不會把參數掃描誤認為硬體測量。
28. 身為接手的 agent，我想讓 M5 嚴格停在可信 approach 後端，這樣完成後能立即轉向事件流與 ReAct 核心。

## Implementation Decisions

- M5 的唯一產品目標是供 ReAct 使用的可信 `approach` 後端。它不是新的影像研究里程碑。
- 公開的 approach module 提供一個小介面：執行一次有界的 approach，回傳結構化結果。結果至少包含狀態與已執行步數；狀態固定為 `arrived`、`lost_user`、`timeout` 或 `drive_error`。
- `arrived` 只代表有效且新鮮的距離位於抵達帶內；不得用它代表 safety-floor 異常或無讀數。
- Approach module 隱藏讀數輪詢、樣本 epoch、控制律、驅動時間換算、settle 與錯誤轉譯。ReAct 與其他呼叫端不接觸這些細節。
- 正式距離管線滿足 M4 已使用的 `latest_reading()` 介面，以便沿用相同量測。回傳值包含距離、影格進入 process 的 monotonic timestamp，以及偵測完成的 monotonic timestamp。
- 現有影格 timestamp 的語意明確定義為「影格由 RTSP adapter 交付給本 process 的時刻」，不是相機曝光時間。實作應採用符合此語意的名稱，並同步更新呼叫端與文件。
- Sensor transport lag 仍是獨立、UNCALIBRATED 的假設。任何 process 內 freshness 判斷都不得宣稱涵蓋它。
- Process 內影格緩衝採 latest-value 語意：最多保留一張尚未消費的影格，新影格取代舊影格。對外保留 backlog 與累計 dropped-frame 診斷，但不承諾控制 OpenCV 或 RTSP 自身的內部緩衝。
- 距離管線維護一個有界的有效樣本視窗，並只聚合仍在最大允許年齡內的樣本。年齡以決策當下減去 process ingress timestamp 計算。
- `distance_max_age_s` 保留為 freshness 上限；M5 修正它的時間語意，不在沒有新量測證據時任意重調既有預設值。
- 每次會改變 robot 視點的位置動作都建立新的失效 epoch。下一次控制決策只能使用 process ingress timestamp 晚於該 epoch 的樣本；移動前樣本不得留在聚合結果中。
- 失效後至少取得兩筆有效的新距離樣本，才允許作下一個控制決策。這延續 `PLAN.md` 已定的抗單筆雜訊要求，而不是把整個九筆視窗填滿後才反應。
- 等待新樣本有獨立、可設定的 timeout，預設為兩秒。Timeout 內持續輪詢；到期仍無足夠有效樣本時回傳 `lost_user`。等待受每步上限與整次 approach 上限共同約束。
- `post_step_settle_s` 仍表示移動完成後允許場景穩定的時間；它不能取代 freshness 判斷，也不能靠 sleep 本身證明讀數已更新。
- 控制律維持「輸入距離、輸出一步意圖」的單一實作。Runtime、reachability 分析、robustness sweep 與測試都呼叫同一實作，不重寫其公式。
- 前進與後退都必須有對稱的有界步長語意。`min_step_cm` 不得強迫任一方向跨過抵達帶或造成可預見的來回震盪。
- 新增一個明示為 UNCALIBRATED 的最大驅動距離倍率假設，表示實際移動距離相對命令距離的上界。控制律以這個倍率預留 safety headroom；預設情境至少覆蓋 M4 已重現的 `2.0×` 校準誤差。
- Safety claim 是條件式的：只有在實際移動倍率不超過上述假設、且 sensor lag 落在明示 sweep 範圍時，模擬才證明不越過 safety floor。超出假設的真機行為未知。
- 驅動 adapter 拒絕命令、回傳非成功結果或拋出例外時，approach 立即停止並回傳 `drive_error`；不得繼續推測 robot 已移動。
- `max_approach_steps` 繼續作為硬上限。耗盡步數仍未抵達時回傳 `timeout`，保留「每次工具呼叫都會終止」的不變量。
- M5 完成後，舊主腳本只作唯讀行為參考；新的 ReAct 工作不得重新依賴它的感知或 approach 實作。
- M5 不建立事件匯流排，也不決定 ReAct observation 的最終 JSON schema。結構化結果只需讓後續里程碑無須解析字串或重建失敗語意。

## Testing Decisions

- 好測試只斷言通過 module 介面可觀察的行為，不斷言 queue 類型、deque 內容、flush 呼叫次數、thread 數量或私有方法。
- 主要驗收測試跨越公開 `approach()` seam，以 synthetic video adapter 提供場景、以 recording robot adapter 記錄動作，最後斷言命令序列與結構化結果。
- 測試必須證明移動後的下一個決策不會使用移動前樣本。場景應讓舊樣本與新樣本導致不同決策，避免只測 timestamp 欄位。
- 測試必須證明啟動時暫時沒有足夠樣本會等待，樣本在期限內到達便能繼續；期限內始終不足則回傳 `lost_user`。
- 測試必須證明 stale reading 不會被視為有效 reading，即使其距離數值剛好位於抵達帶內。
- 測試必須覆蓋四個公開結果：正常抵達、失去使用者、步數耗盡、驅動失敗。
- 測試必須覆蓋前進與後退，包括會喚醒既有 `min_step_cm` 缺陷的非預設組合。
- Safety 測試沿用 M4 的真實控制律 sweep；至少要求 `2.0×` 移動倍率的既有反例不再越過 45cm 模擬底線。測試與報告必須同時寫出這是條件式模擬，不是真機保證。
- 正式距離管線取代 M4 的 reference pipeline 接受同一個 latency-bound 測試；門檻維持「process 內讀數延遲 p95 不超過同次執行物理下限的兩倍」。
- Backpressure 測試從外部觀察：在 producer 快於 consumer 時，讀到的是最新場景、buffer 維持有界，且 dropped-frame 診斷增加。它不檢查使用哪一種 queue。
- Timestamp 測試必須區分 process ingress、detection completion 與 decision time，並證明不可測的 sensor transport lag 沒有被混入已測數字。
- 使用 monotonic fake clock 的純控制測試可以快速驗證 timeout 與 epoch；保留真實時間的 M4 replay 測試，用來量 MediaPipe 的真實成本。兩者證明的事情必須分開描述。
- Prior art 包括 M4 replay harness 的 synthetic video、latency bound、diagnostics 與 robustness sweep，以及驅動契約測試使用的 recording adapter。
- 不把舊 `FakePerception` 的瞬時真值測試當成感知至控制整合證據；它可以保留作快速控制案例，但必須清楚標示其證據範圍。
- 全部 M5 測試使用專案 `.venv` 執行，不呼叫 LLM、不需要網路、不需要硬體，且不得 skip 感知案例。

## Out of Scope

- ReAct loop、function calling、工具註冊表、step cap 的 LLM orchestration，以及最終 observation schema。
- EventBus、JSONL 事件紀錄與舊 simulation runner 遷移到 pytest。
- Audio、VAD、ASR backlog、TTS suppression window 與插話處理；這些另立工作，最遲在語音工具整合前完成。
- 新增或更換臉部偵測模型、調整 MediaPipe 參數、遷移到 Tasks API，或提升視覺辨識品質。
- 量測相機曝光、Misty 編碼、Wi-Fi 或 RTSP 到 process 的真實延遲。
- 真機校準、真機安全認證、馬達 deadband 測量，或宣稱 `approach` 已在 Misty II 上執行。
- 重寫 memory、prompt、人格、表情、手臂、頭部、燈光、音訊與其他 ReAct 工具。
- Docker、CI workflow 與 README 改寫；M5 只提供後續會引用的可重現證據與誠實邊界。
- 繼續維護舊主腳本。只有尚未搬出的 prompt 與 memory 邏輯可以在後續里程碑把它當唯讀參考。

## Further Notes

- M4 已量得 reference pipeline 的 process 內讀數延遲 p95 約 43ms，當次物理下限約 38ms；正式管線必須接受同一把尺，而不是另造較寬鬆的指標。
- M4 顯示這台機器的 MediaPipe consumer 通常遠快於 30fps producer，但故意放慢 consumer 仍能重現無界 backlog。Latest-value 是正確性語意，不是針對目前機器的效能最佳化。
- M4 的 transport-lag sweep 是參數掃描，不是量測。既有結果約在 1.55s 後失去收斂、1.75s 起越過 safety floor；M5 應重跑同一分析並報告新結果，不把舊數字當驗收目標。
- `approach_user()` 從未在真機執行。任何測試名稱、報告與未來 README 都必須保持這句事實可見。
- 工作樹目前已有不屬於本 spec 的未提交修改。後續 tickets 必須保留它們，提交前檢查整個 staged diff，且不要順手提交既有的架構圖修改。
- 本 spec 完成後應立即用 `/to-tickets` 拆成少量 tracer-bullet tickets；M5 收尾後直接進事件流與 ReAct，不新增影像研究支線。
