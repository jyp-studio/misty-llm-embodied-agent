# 13 — 每條執行路徑都關閉 Episode，bumper 接線不可遺忘

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
- [x] 新增 `error` outcome 的第五份 golden，不削弱 spec 的完整覆蓋
- [x] M7 單檔測試綠；全套測試在可建立 MediaPipe context 的環境下零 skip

## Scope boundary

- Journal 自身若無法建立或寫入，不能靠同一個 Journal 記錄自己的失效；不宣稱處理這個悖論。
- `memory.close_episode()` 依 `PLAN.md` §15.5／§15.26 在 `episode_finished` 之後執行，是 post-Episode 衍生工作，不回頭改寫已完成 Episode 的 outcome。
- 不在本票建立 Docker、CI 或外層感知迴圈。

## Comments

以 `run_episode()`／`Session` 公開 seam 做逐條 red → green。M7 相關 14 個測試檔目前
`643 passed`；完整 suite 與兩軸 review 留到 commit 後的驗收階段。

兩軸 review 找到並修正：錯誤訊息以空白／連字號寫出 drive duration 時原本可繞過遮罩；兩個
Session 共用 EventStream 時固定訂閱名稱會讓第二個 callback 被拒絕；新增 `error` outcome 後應
新增第五份 golden，而不是從完整性斷言排除。錯誤收尾的五份重複程式也已收斂成單一 helper。
`Status: claimed` 是 wayfinder child 的狀態，這張一般 implementation issue 依既有 M7 慣例不冒用。

最終 M7 相關 14 個測試檔為 **663 passed**；`.venv` 完整 suite 為 **945 passed、13 failed、
38 errors、7 deselected、零 skip**。51 個失敗／錯誤都在需要 MediaPipe context 的測試，原因是
目前 headless 執行環境無法建立 macOS `NSOpenGLPixelFormat`／`kGpuService`；因此當時沒有冒稱
「全套全綠」，先保持最後一項未勾。這個專案沒有實機，bumper 與 halt 仍只由 contract/fake 驗證。

同日由使用者在一般 macOS Terminal、同一份專案 `.venv` 執行完整 suite：**996 passed、
7 deselected、零 skip，25.17s**。測試總數恰好等於 Codex headless 執行的 945 passed 加上
13 failed／38 errors，確認那 51 項是 Codex 執行環境無法建立 MediaPipe macOS OpenGL context，
不是程式或測試案例失敗。最後一項據此勾選；無實機邊界仍不變。
