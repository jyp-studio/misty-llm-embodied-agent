# 02 — 使用移動後新讀數完成一次有界 approach

**What to build:** 一個供後續 ReAct 工具直接呼叫的公開 `approach()` 行為。它從正式距離管線取得讀數、用唯一的控制律規劃一步、透過 robot adapter 移動，再等待移動後的新讀數繼續閉環，最後回傳結構化結果。

這張 ticket 的驗收從 synthetic video 一路跨到 recording robot adapter，只觀察移動命令與公開結果。讀數輪詢、樣本視窗、失效 epoch、settle、驅動時間換算與錯誤轉譯都藏在 approach module 裡，不成為 ReAct 呼叫端必須理解的細節。

每次改變 robot 視點的移動都作廢先前樣本。下一次控制決策必須等待至少兩筆 ingress timestamp 晚於該次失效 epoch 的有效距離樣本；短暫沒有資料會等待，超過可設定期限仍不足才回傳 `lost_user`。

**Blocked by:** 01 — 最新且可判定新鮮度的距離讀數

**Status:** ready-for-agent

- [ ] 公開 approach module 只需一個小介面便能執行完整閉環，回傳至少包含狀態與已執行步數的結構化結果
- [ ] 公開狀態固定為 `arrived`、`lost_user`、`timeout` 與 `drive_error`，後續 ReAct 不需要解析自由文字
- [ ] `arrived` 只在有效且新鮮的聚合距離位於抵達帶內時回傳；剛好位於抵達帶的 stale reading 不得造成成功
- [ ] 啟動時樣本暫時不足會在有界期限內輪詢；期限內湊足至少兩筆有效樣本便繼續，而非第一輪立即 `lost_user`
- [ ] 每次移動建立失效 epoch；下一步只使用 ingress timestamp 晚於 epoch 的至少兩筆樣本，移動前樣本不能主導聚合結果
- [ ] 固定 settle 只能作為場景穩定等待，不能取代 timestamp freshness 判斷
- [ ] 在正常合成場景中，approach 發出可觀察的移動命令並以移動後讀數抵達，回傳 `arrived`
- [ ] 持續沒有足夠有效人臉讀數時，在期限內停止並回傳 `lost_user`，且不盲目發出新的移動命令
- [ ] 耗盡最大步數仍未抵達時回傳 `timeout`，證明一次工具呼叫必然終止
- [ ] Robot adapter 拒絕命令、回傳失敗或拋出例外時立即停止並回傳 `drive_error`；不得假設 robot 已移動
- [ ] 驗收測試跨公開 `approach()` seam，不斷言 queue、deque、flush 次數、thread 數量或私有方法
- [ ] 測試可注入 monotonic fake clock 快速驗證 timeout 與 epoch，同時不取代 M4 真實時間 replay 對 MediaPipe 成本的量測
- [ ] 新實作不依賴或修改舊主腳本；舊檔只作唯讀行為參考
- [ ] 全套 pytest 使用專案 `.venv` 執行且零 skip；既有 simulation runner 保持綠燈
