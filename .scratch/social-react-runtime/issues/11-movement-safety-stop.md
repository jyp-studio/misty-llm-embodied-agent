# 11 — 在移動期間安全停止

**What to build:** 在 target-aware movement 的每個安全中斷點檢查 target freshness、hazard、bumper、
deadline 與 Robot error。任何必要安全條件失效時，立即停止盲目前進，產生結構化 Observation，讓
LLM 決定重新觀察、改用遠距對話或結束。

這張票把「LLM 決定是否移動」和「controller 決定能否安全繼續」的責任邊界做成可證明的行為。

**Blocked by:** 10

**Status:** resolved

- [x] movement 開始前、每個 Step 後及重新量測前都檢查 target 與 safety state
- [x] target lost、stale reading、hazard、bumper、deadline 與 Robot error 都停止後續 drive commands
- [x] bumper、hazard stop 與 e-stop 可以立即中止 physical effect，不受 Turn-boundary handoff 限制
- [x] 真機模式缺少必要 hazard signal 時 movement fail closed；模擬模式由 scenario 明確提供狀態
- [x] Tool result 清楚區分 arrived、target lost、blocked、aborted、timeout 與 robot failure
- [x] model 收到停止原因後可以合法選擇重新觀察、說話或完成 Episode
- [x] Demo 提供 target lost 與 hazard 兩種內建案例，動畫在正確 Moment 停止底盤
- [x] Journal 保留 movement intent、已完成 Steps、停止原因與最終 Snapshot
- [x] mutation/negative-control tests 能抓到少一次 safety check 或停止後仍發命令的錯誤
- [x] 測試證明公式與模擬行為通過時，文件仍不把結果描述成真機 safety certification

