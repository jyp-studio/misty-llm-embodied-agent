# 02 — 使用移動後新讀數完成一次有界 approach

**What to build:** 一個供後續 ReAct 工具直接呼叫的公開 `approach()` 行為。它從正式距離管線取得讀數、用唯一的控制律規劃一步、透過 robot adapter 移動，再等待移動後的新讀數繼續閉環，最後回傳結構化結果。

這張 ticket 的驗收從 synthetic video 一路跨到 recording robot adapter，只觀察移動命令與公開結果。讀數輪詢、樣本視窗、失效 epoch、settle、驅動時間換算與錯誤轉譯都藏在 approach module 裡，不成為 ReAct 呼叫端必須理解的細節。

每次改變 robot 視點的移動都作廢先前樣本。下一次控制決策必須等待至少兩筆 ingress timestamp 晚於該次失效 epoch 的有效距離樣本；短暫沒有資料會等待，超過可設定期限仍不足才回傳 `lost_user`。

**Blocked by:** 01 — 最新且可判定新鮮度的距離讀數

**Status:** resolved

- [x] 公開 approach module 只需一個小介面便能執行完整閉環，回傳至少包含狀態與已執行步數的結構化結果
- [x] 公開狀態固定為 `arrived`、`lost_user`、`timeout` 與 `drive_error`，後續 ReAct 不需要解析自由文字
- [x] `arrived` 只在有效且新鮮的聚合距離位於抵達帶內時回傳；剛好位於抵達帶的 stale reading 不得造成成功
- [x] 啟動時樣本暫時不足會在有界期限內輪詢；期限內湊足至少兩筆有效樣本便繼續，而非第一輪立即 `lost_user`
- [x] 每次移動建立失效 epoch；下一步只使用 ingress timestamp 晚於 epoch 的至少兩筆樣本，移動前樣本不能主導聚合結果
- [x] 固定 settle 只能作為場景穩定等待，不能取代 timestamp freshness 判斷
- [x] 在正常合成場景中，approach 發出可觀察的移動命令並以移動後讀數抵達，回傳 `arrived`
- [x] 持續沒有足夠有效人臉讀數時，在期限內停止並回傳 `lost_user`，且不盲目發出新的移動命令
- [x] 耗盡最大步數仍未抵達時回傳 `timeout`，證明一次工具呼叫必然終止
- [x] Robot adapter 拒絕命令、回傳失敗或拋出例外時立即停止並回傳 `drive_error`；不得假設 robot 已移動
- [x] 驗收測試跨公開 `approach()` seam，不斷言 queue、deque、flush 次數、thread 數量或私有方法
- [x] 測試可注入 monotonic fake clock 快速驗證 timeout 與 epoch，同時不取代 M4 真實時間 replay 對 MediaPipe 成本的量測
- [x] 新實作不依賴或修改舊主腳本；舊檔只作唯讀行為參考
- [x] 全套 pytest 使用專案 `.venv` 執行且零 skip；既有 simulation runner 保持綠燈

## Answer

完成於 2026-08-13。新增 `misty_agent.control.approach.approach()`，以至少兩筆同時有效、且 ingress timestamp 晚於最近移動失效 epoch 的樣本取中位數，再呼叫唯一的 `plan_step()`。移動完成時建立 epoch；settle 期間仍蒐集新樣本，但直到 settle 結束才允許決策。

公開結果固定為 `arrived`、`lost_user`、`timeout`、`drive_error` 並攜帶已完成步數。獨立讀數 timeout、最大步數與整次呼叫 deadline 共同保證有界；adapter 例外、非 2xx 回應或超過 deadline 都立即轉譯為 `drive_error`，不計入已完成步數。

驗證：`.venv/bin/python -m pytest tests/ -q -rs` → **250 passed、零 skip**；`.venv/bin/python test_sim.py` → **24 passed**。Synthetic video + 真 MediaPipe + recording robot adapter 已跨公開 seam 驗證一步移動後以新讀數抵達。以上全是模擬／process 內驗證；`approach()` 仍從未在 Misty II 實機執行。
