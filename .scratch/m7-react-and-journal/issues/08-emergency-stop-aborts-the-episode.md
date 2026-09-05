# 08 — 緊急停止中止 Episode

**What to build:** 讓腳踩保險桿在任何一個 Turn 都能打斷互動，而且打斷之後機器人**確實停下來**。

這張票證明的是一個獨立的性質：**外力介入時，「保證回到閒置」還成不成立。** 那是 `PLAN.md` §4 說的系統最強性質，而它也是唯一一條會從外部打斷 Episode 的路徑 —— `CONTEXT.md` 把 Episode 定義成「保證有界終止」，不測這條就等於沒測那個保證。

緊急停止跑在**另一條執行緒**上。它記下的時間必須是**它發生的時間**，不是主迴圈回過頭來處理它的時間 —— 那個差距正是中斷延遲，是要量的東西（這也是 02 選擇「加鎖直接寫」而非「丟佇列」的理由）。

**Blocked by:** 02, 07

**Status:** done

- [x] 從另一條執行緒觸發緊急停止會中止進行中的 Episode
- [x] 中止成為一筆 Journal 紀錄，時間是它發生的時間
- [x] **中止之後仍然回到閒置**：沒有留下未停止的動作
- [x] 有測試證明中止發生在一個 Turn 的**中間**時也成立，不是只在 Turn 邊界
- [x] 產出的 Journal 對得上 golden 4
- [x] Turn 上限與終止保證在中止路徑上仍然成立
- [x] 測試在專案 venv 下零 skip，不需硬體


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


## Notes（來自 #07）

- **`run_episode` 目前沒有中止的入口。** outcome 只會是 `done` 或 `turn_limit`，在迴圈裡本地
  算出來。這張票要加一個 seam（例如一個帶 `requested()` 的 stop 物件），在 dispatch 之後檢查
  並把 outcome 設成 `aborted`。形狀容得下，但簽名要動。
- **`episode_is_aborted.jsonl` 還在舊的時間慣例上。** §15.21 換了規則（時間只在真的有等待時
  前進），但那個 golden 有 `stop_requested`、只有這張票產得出來，所以刻意沒動它。**這張票要
  把它帶到新規則上**，`tests/goldens/README.md` 已註明。
- `approach` Tool 沒有自己的 try/except，測試釘死了（見 #06 的 Notes）。


## Comments

完成於 2026-09-03。`misty_agent/agent/stop.py`（`EmergencyStop` 與 `NeverStops` 空物件）、
`react.py` 加一個 `stop` 參數與兩個檢查點、`tests/test_stop.py` 10 條、`test_react.py` 加
13 條。全套 **799 passed、零 skip**（776 → 799）。

**golden 4 對上了，而且它與原始檔案的差異只有 `t`** —— 七筆紀錄、種類、順序、
`outcome=aborted`、`steps=1`、`turns=1`、`result={timeout, 1}`、`source=foot_bumper`
全部本來就相符。逐欄位盤點過（只有 6 筆的 `t` 變），ticket 03 的六十條內容斷言 60/60 通過。
這正是 §15.21 預測的，也是 #07 的 Notes 交代這張票要做的事：把它帶到新的時間規則上。
四個 golden 現在都在同一條規則上。

**三個決定記在 §15.24：** 先記錄後 halt（時間戳要是腳踩下去的時間，halt 是 HTTP 往返）；
用 `halt` 不用 `drive/stop`（後者會留一隻手臂在半空）；halt 失敗要吞例外 —— 它跑在感測器
執行緒上沒人接，而**一個沒停下來、Episode 還繼續跑的 halt 比只是沒停下來更糟**。

**迴圈檢查兩次，是兩件不同的事：** dispatch 之前那次拒絕開始新的物理動作，Observation 之後
那次在已經在跑的動作回傳之後結束 Episode。golden 4 走第二條。

---

## Review

**兩軸沒有跑。** #07 連吃四次 529 之後我就沒有再嘗試，直接照 §15.23 的做法自己補做 ——
**「仍然跑不起來」是我當時的推測，不是查證過的事實**（2026-09-05 補跑時一次就成功了）。

**自己跑十五個 mutation，存活一個 —— 而那一個很有意思：把 `request()` 的鎖整個拿掉，
「多執行緒同時踩只能產生一個 stop」那條測試照樣綠。**

八條執行緒卡在 barrier 一起衝抓不到；`sys.setswitchinterval(1e-9)` 也抓不到。視窗在 GIL 下
太窄。改用 `threading.settrace` 掛「每行 `time.sleep(0)`」的 hook 之後，無鎖版本會出現兩個
贏家、兩筆 `stop_requested`，有鎖版本永遠一個 —— **兩邊都實測過才寫進測試**。15/15 全紅。

這是 M7 #02 那個教訓的第二次出現（當時「時間戳在鎖之前取」也是名義上測並行、實際把鎖拿掉
還是綠）。寫進 §15.25：**併發的測試要先證明它抓得到那個 bug，再相信它。**

**⚠️ 還沒接線的部分（不在這張票的驗收條件裡，但要說清楚）：** `EmergencyStop.request` 目前
沒有任何生產程式碼呼叫它 —— 舊腳本用 `_thread.interrupt_main()`，而把 `BumpSensor` 事件接到
這個物件上是 **ticket 12**（刪舊主腳本、接上新入口）的事。這張票交付的是機制與它的證明。
