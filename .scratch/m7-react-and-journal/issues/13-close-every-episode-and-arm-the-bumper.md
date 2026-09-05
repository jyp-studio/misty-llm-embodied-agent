# 13 — 每條執行路徑都關閉 Episode，bumper 接線不可遺忘

Status: claimed

**What to build:** 讓模型、Tool 或 Snapshot 在一次 Episode 中失敗時，公開入口仍回傳結構化結果、Journal 仍恰好以一筆 `episode_finished` 結束，並在離開前要求機器人停止；有 event stream 的 Session 則從建構完成起就已訂閱 foot bumper，不靠呼叫端記得補做。

這是 M7 的 closure，不擴大成新的外層語音迴圈。測試 seam 沿用 M7 spec：一次 `run_episode()`／`Session.episode()` 的公開結果與 Journal；bumper 只從 Session 的公開建構與 event subscription 觀察。

**Blocked by:** 12

- [x] `EpisodeFinished` 接受明確的 `error` outcome，錯誤另有 `execution_failed` typed Journal record，含失敗階段與例外型別
- [x] 模型決策拋例外時，公開呼叫不把半截 Episode 丟給呼叫端
- [x] 直接 Tool 的 robot adapter 拋例外時，Journal 恰好以一筆 `episode_finished` 結束
- [x] Tool 成功後 Snapshot 拋例外時，同樣以 `error` 結束
- [x] 上述錯誤在結束前都會嘗試 `halt()`；halt 自己失敗也不得破壞終止保證
- [x] 錯誤訊息不能把 velocity／drive duration 洩漏進 Journal
- [x] 有 event stream 的 `Session` 建構後就已訂閱 bumper；重複呼叫 wiring 方法不會重複訂閱
- [x] 沒有 event stream 的 Session 行為不變
- [x] 既有四份 golden Journal 不變
- [ ] M7 單檔測試綠；全套測試在可建立 MediaPipe context 的環境下零 skip

## Scope boundary

- Journal 自身若無法建立或寫入，不能靠同一個 Journal 記錄自己的失效；不宣稱處理這個悖論。
- `memory.close_episode()` 依 `PLAN.md` §15.5／§15.26 在 `episode_finished` 之後執行，是 post-Episode 衍生工作，不回頭改寫已完成 Episode 的 outcome。
- 不在本票建立 Docker、CI 或外層感知迴圈。

## Comments

以 `run_episode()`／`Session` 公開 seam 做逐條 red → green。M7 相關 14 個測試檔目前
`643 passed`；完整 suite 與兩軸 review 留到 commit 後的驗收階段。
