# 01 — 最新且可判定新鮮度的距離讀數

**What to build:** 一條正式距離管線，永遠以 process 內最新影格產生距離讀數，並讓呼叫端能在決策當下判斷讀數是否仍然新鮮。這張 ticket 完成後，M4 的 synthetic video 可以通過同一個 `latest_reading()` 介面量測正式管線，而不是只量 reference pipeline。

影格時間必須描述實際可觀察的事件：RTSP adapter 把影格交付給本 process 的時刻，而不是無法量測的相機曝光時刻。距離讀數另保留偵測完成時間；不可測的 sensor transport lag 繼續作為獨立、UNCALIBRATED 的假設。

Process 內緩衝採 latest-value 語意。慢 consumer 不逐張重播舊世界；尚未消費的舊影格可以被新影格取代，同時保留 dropped-frame 診斷。這個保證只涵蓋本 process，不延伸宣稱 OpenCV 或 RTSP 內部也有背壓。

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] 正式距離管線滿足既有 `latest_reading()` 介面，回傳距離、process ingress timestamp 與 detection completion timestamp
- [x] 既有容易誤解為相機曝光時間的名稱與說明，改成符合 process ingress 語意；所有呼叫端與測試同步遷移且保持綠燈
- [x] 最大讀數年齡以「決策當下 − process ingress timestamp」判定，不再使用處理完成時間冒充影格年齡
- [x] 有效距離樣本維持有界視窗；過期樣本不會出現在 `latest_reading()` 的聚合結果中
- [x] Process 內影格緩衝永遠有界，producer 快於 consumer 時，下一次讀取反映最新場景而非最舊排隊場景
- [x] 對外可觀察 buffer backlog 與累計 dropped-frame 數；測試不綁定特定 queue 類型或私有容器
- [x] Synthetic video adapter 與 RTSP adapter 具有相同 latest-value 語意，避免 harness 測到一條比 production 更理想的緩衝路徑
- [x] 正式管線取代 reference pipeline 接受既有 latency-bound 驗收：process 內讀數延遲 p95 不超過同次執行物理下限的兩倍
- [x] 測試清楚區分 process ingress、detection completion、decision time 與不可測的 sensor transport lag
- [x] 全套 pytest 使用專案 `.venv` 執行且零 skip；既有 simulation runner 保持綠燈

## Comments

完成於 2026-08-13。正式管線採單一 latest reading；ticket 02 所需的「至少兩筆移動後新樣本」留在 approach 決策層，不以感知端滑動 median 為每次 observation 增加固定延遲。九筆舊設定預設保留，避免在此 ticket 提前改變舊主腳本行為。

驗證：`.venv/bin/python -m pytest tests/ -q -rs` → **234 passed、零 skip**；`.venv/bin/python test_sim.py` → **24 passed**。兩軸 code review 最終結果：Standards 0 findings、Spec 0 findings。
