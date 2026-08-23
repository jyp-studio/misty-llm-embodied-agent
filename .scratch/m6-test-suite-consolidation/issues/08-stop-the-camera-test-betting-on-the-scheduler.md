# 08 — 別讓相機測試賭排程器

**What to build:** 讓「未被讀取的相機只保留最新場景」這條測試，不再靠 wall-clock `sleep` 賭背景執行緒排得到 CPU。

`tests/test_synthetic_camera.py` 的 `test_an_unread_camera_keeps_only_the_latest_scene` 啟動一條真的 60fps producer thread，然後用兩個 `time.sleep(0.2)` 當作「這段時間內應該產出約 12 張影格」的替身，再斷言緩衝深度、丟棄數與最新影格的距離。單獨跑很穩（連續 20 次全過，8 個 busy-loop 壓著也全過），但在**完整套件**裡偶發失敗 —— 那時同一個 process 裡有其他測試留下的執行緒與 MediaPipe 的 Metal／TF 執行緒在競爭。

**這不是 M6 造成的**，是 M4 #04 就留下的。但它有後果：這個專案每張 ticket 的驗收都寫「全綠零 skip」，而這條測試讓那句話不是每次都成立 —— M6 #05 要據此產出發布用的報告。

**要保住的性質不變**：緩衝是 latest-value（深度有界）、被取代的影格數可觀察、讀到的是最新場景而不是最舊的。**要換掉的只是「用時間長度當作事件發生的替身」**。可觀察的替代品已經存在：`dropped_frames` 每當一張未讀影格被取代就 +1，所以「place() 之後 dropped 又增加了 N」就是「place() 之後至少又產出了 N 張影格」的直接證據，不需要猜排程。

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] 測試不再用固定 `sleep` 長度來代表「應該已經產出若干影格」
- [x] 改以有界輪詢等待可觀察的條件；逾時要有明確且足夠寬鬆的上限，逾時訊息說明等的是什麼
- [x] 仍然斷言：緩衝深度有界、被取代的影格數可觀察、讀到的是 `place()` 之後的場景
- [x] 仍然使用真實的 producer thread —— 這條測試的價值就在於它跑的是真的併發，不得改成同步假物
- [x] 在人為 CPU 負載下連續執行仍穩定
- [x] 其他同樣用 `sleep` 當替身的相機測試一併盤點，修掉或明確記錄為何不需要修
- [x] `pytest tests/ -q -rs` 全綠且零 skip

## Comments

完成於 2026-08-23。只動測試，`misty_agent/` 與 `harness/` 皆未修改。

**沒有重現出原始失敗，這一點要說清楚。** 單獨跑 20 次全過；8 個 busy-loop 壓著跑 10 次也
全過；把會起執行緒的四個測試檔湊在一起跑則超時，沒跑完。原始那一次是在完整套件裡出現的，
訊息指向 `pytest.approx` 那條 —— 也就是 `place(70.0)` 之後 0.2 秒內沒有任何新影格被產出，
讀到的仍是 120cm 的舊場景。

因此這次修的是**結構上的脆弱**而不是一個被重現的個案：測試拿 wall-clock 長度當作「這段
時間內應該產出約 12 張影格」的替身，而那是在賭排程器。不論當初紅的是三條斷言中的哪一條，
換掉這個賭注都同時消除全部三種可能。

**替代的觀察量本來就存在。** `FrameBuffer.dropped_frames` 只在「未讀影格被新影格取代」時
才 +1，所以「`place()` 之後 dropped 又增加了 N」就是「之後至少又產出了 N 張影格」的直接
證據。等 **2** 張而不是 1 張：`place()` 落地時正在合成的那一張可能還是舊場景，一次取代不算
證明；兩次之後，緩衝裡的那張必定是移動後合成的。

**順手盤點了同檔其他用 `sleep` 當替身的測試**（驗收條件最後第二條）。
`test_flush_discards_what_was_waiting` 也有一個 `sleep(0.3)`，但它不會 flaky ——
它斷言 `depth <= 1`，而**一台從未產出任何影格的相機也滿足它**。也就是說那個 sleep 撐著的
不是穩定性而是整條測試的意義。已改成先輪詢等到真的有影格在等，flush 才有東西可丟。

**要保住的性質全部保留**：真的 producer thread、latest-value 緩衝、可觀察的取代計數、讀到
的是移動後的場景。輪詢逾時設 10 秒 —— 刻意遠大於實際需要，它的作用是**失敗時能說出在等
什麼**，不是拿來表達速度期待。

順帶一提，改完之後這個檔案還變快了：原本無條件睡 0.7 秒，現在條件成立就往下走。

驗證：10 個 busy-loop 壓著跑 `tests/test_synthetic_camera.py` **25 次全過**；
`.venv/bin/python -m pytest tests/ -q` **連續四次 299 passed**、零 skip。

**這條 flaky 不是 M6 造成的**（M4 #04 就留下的），但它有後果：每張 ticket 的驗收都寫
「全綠零 skip」，而 M6 #05 要據此產出發布用的報告。

---

**Review 後的更正（2026-08-23，同日）。** 兩軸序列跑、各自隔離 worktree。Spec 軸找到一個
**比我修掉的那條更嚴重**的東西，另有四項。

**(1) 我的盤點只掃了同一個檔案，而漏掉的那條會靜默假通過。**
`tests/test_distance_pipeline.py` 的 `test_a_stale_frame_cannot_contribute_to_the_latest_distance`
用 `time.sleep(0.15)` 當作「偵測已完成」，然後斷言 `latest_reading() is None`。reviewer 在
隔離 worktree 證明：把新鮮度過濾拿掉，**正常情況下這條會紅**；但只要讓 `_consume_loop` 慢
0.4 秒（就是本票在講的那種負載），同一個 mutant **就通過了** —— 因為 worker 還沒算完，
`_latest` 本來就是 None。

**這比 flaky 更糟：flaky 會吵，假通過不會。** 已改成讓 `ManualVideoSource` 數出被取走幾張
影格，並等到**第二張**被取走 —— worker 的迴圈是 read → detect → store，所以第二次讀取
證明第一張已經整段走完。重測：新鮮度壞掉、偵測慢 0.4 秒、以及兩者並存的那個組合，現在
**三種都紅**。

**(2) `test_flush_discards_what_was_waiting` 仍然是空洞的，兩軸都確認。** 我以為「先等到有
影格」就修好了，但 `depth <= 1` 是 `maxsize=1` 佇列的**恆真式** —— 把 `flush` 整個換成
`pass` 照樣過，換成無界佇列也照樣過。等待只補上了「從未產出」那個洞。已改成**先停掉
producer 再 flush**，然後斷言 `backlog == 0`；這樣才是一句只關於 `flush` 的主張。重測：
`flush` 改 `pass` 現在會紅。

**(3) 我在 docstring 裡把自己的證據講成兩倍。** 寫的是「twenty more under eight busy loops」，
實際只跑了 **10** 次（另外 25 次是在 10 個 busy-loop 下）。已更正為 10。

**(4) docstring 把未經證實的歸因寫成事實。** 「occasionally does not when the whole suite
shares the process with MediaPipe's Metal and TensorFlow threads」——那次失敗從未重現，
所以原因是**推測不是發現**。誠實的說明本來只存在於 `.scratch`，而讀者看到的是程式碼。
已在 docstring 明寫「那次失敗從未重現，成因是推測」。

**(5) `replaced_before` 的快照順序是承重的但沒註記** —— 若在 `place()` 之前取值，一次發生
在 120cm 時的取代就會被算進那兩次裡。已補註解。

**另外：修的過程中我自己引入了一個新的同類問題。** 為了讓兩張過期影格不互相取代，我加了
`time.sleep(0.02)` —— 那正是本票在消滅的東西，而且負載一高第二張會蓋掉第一張，輪詢要等
滿 10 秒才紅。已改成等第一張被取走再發第二張，`sleep` 完全消失。

**全套件盤點（原本只做了單檔）：** 其餘 `time.sleep` 全部合格 ——
`test_replay.py:211`、`test_distance_pipeline.py:85` 與兩個 `_wait_until` 內的都是**輪詢間隔**；
`test_diagnostics.py:211` 的 sleep **就是被模擬的消費者成本本身**；`test_approach.py` 的兩個是
`FakeClock` 不是 wall clock。
`test_the_replay_takes_about_as_long_as_the_script_says` 的 `elapsed < duration + 0.5` 看似
同類但不是：**它的主題本身就是耗時**，wall-clock 斷言在那裡是正確的工具。實測裕度只用掉
0.003–0.030 秒（上限 0.5），16 倍餘裕，不動它。

**(6) 驗收條件「在人為 CPU 負載下連續執行仍穩定」其實不具鑑別力**，reviewer 指出得對：
ticket 內文自己就記著**未修版本**在 8 個 busy-loop 下也全過。它勾起來不代表修好了；真正
的證據是上面那些 mutation 從綠變紅。這一點記在這裡，不改驗收條件原文。

驗證：8 個 busy-loop 壓著跑兩個檔 **20 次全過**；`pytest tests/ -q -rs` → **299 passed、零 skip**。
`misty_agent/` 與 `harness/` 未修改。
