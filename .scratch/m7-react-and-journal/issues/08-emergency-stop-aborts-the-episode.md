# 08 — 緊急停止中止 Episode

**What to build:** 讓腳踩保險桿在任何一個 Turn 都能打斷互動，而且打斷之後機器人**確實停下來**。

這張票證明的是一個獨立的性質：**外力介入時，「保證回到閒置」還成不成立。** 那是 `PLAN.md` §4 說的系統最強性質，而它也是唯一一條會從外部打斷 Episode 的路徑 —— `CONTEXT.md` 把 Episode 定義成「保證有界終止」，不測這條就等於沒測那個保證。

緊急停止跑在**另一條執行緒**上。它記下的時間必須是**它發生的時間**，不是主迴圈回過頭來處理它的時間 —— 那個差距正是中斷延遲，是要量的東西（這也是 02 選擇「加鎖直接寫」而非「丟佇列」的理由）。

**Blocked by:** 02, 07

**Status:** ready-for-agent

- [ ] 從另一條執行緒觸發緊急停止會中止進行中的 Episode
- [ ] 中止成為一筆 Journal 紀錄，時間是它發生的時間
- [ ] **中止之後仍然回到閒置**：沒有留下未停止的動作
- [ ] 有測試證明中止發生在一個 Turn 的**中間**時也成立，不是只在 Turn 邊界
- [ ] 產出的 Journal 對得上 golden 4
- [ ] Turn 上限與終止保證在中止路徑上仍然成立
- [ ] 測試在專案 venv 下零 skip，不需硬體


## Notes（來自 #06 的 review）

- **`approach` Tool 沒有自己的 try/except，這是這張票的前提。** 有一條測試釘住它
  (`test_a_failure_from_outside_the_control_loop_is_not_turned_into_success`)：從
  `run_approach` **外面**來的失敗不會被吞成成功。`approach()` 自己會把機器人的例外接成
  `drive_error`，所以包在外面的 try/except 在正常情境下不會被觸發 —— 要一個從外面來的失敗
  才測得出來，而緊急停止正是那種。
- `tests/goldens/README.md` 記的決定：中止的 Episode 裡 `approach` 回報 `timeout`，**不是**
  `arrived`。上面那條測試就是保護這件事。
- 拒絕理由現在會被 `layering.mentions_control_parameter` 擋（§15.16），中止相關的訊息若含
  velocity / timeMs 字樣，`ToolRejected` 會拒絕被建出來。
