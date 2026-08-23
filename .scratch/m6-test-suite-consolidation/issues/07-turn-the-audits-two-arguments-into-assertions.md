# 07 — 把盤點裡用推論撐著的兩條換成直接斷言

**What to build:** 讓覆蓋盤點裡「我論證得出來」的兩條，變成「我指得出來」。

盤點（`docs/measurements/m6-coverage-audit.md`）誠實標明了兩處是推論而非指認。誠實不等於足夠 —— 論證會隨著程式碼變動而悄悄失效，斷言不會。

**第一條：1× 行走倍率下的 safety floor。** 套件只在 2× 直接斷言底線。論證是「2× 是嚴格更壞的情況，1× 落在其內」。這個論證成立，但完美校準這個情境本身就有一個現成的測試在跑，它只斷言了抵達與步數，沒有斷言最近距離 —— 補一行就好。

**第二條：起始距離的涵蓋範圍。** 舊 runner 的校準誤差情境從 **150cm** 起步，而現有的多起點 2× 測試只涵蓋 90–130cm。code review 期間實際掃過更遠的起點，發現**最近距離對起始距離不是單調的**（2× 之下 150cm→52.1、160cm→48.1、200cm→60.1），所以「近距離沒事、遠距離自然沒事」的外推**不成立**。這個點碰巧安全，但那是碰巧。起點範圍要涵蓋舊 runner 實際用過的距離。

**這張票不是 02 的前置。** 盤點已經把這兩處標成推論，刪除的正當性不依賴它們被消除；先刪再補與先補再刪都成立，排在 02 之後只是為了與 03、04、06 共用同一條「新測試在刪除之後」的規矩。

**Blocked by:** 02（可與 03、04、06 平行）

**Status:** resolved

- [x] 完美校準（1× 行走倍率）的情境直接斷言最近距離不低於 safety floor
- [x] 多起點的 2× 測試涵蓋舊 runner 實際使用過的起始距離，不只 90–130cm
- [x] 起始距離的涵蓋範圍在測試中寫明理由，避免將來被當成任意數字縮回去
- [x] 若加大範圍後出現越線，那是**結果**：照實記錄並回報，不得為了讓測試變綠而縮小範圍
- [x] 盤點文件中這兩條的「推論」註記更新為指向新斷言，且文件不再宣稱只有一處是推論
- [x] `pytest tests/ -q -rs` 全綠且零 skip

## Comments

完成於 2026-08-23。只動測試，`misty_agent/` 未修改。

**兩處推論都換成斷言：**

1. `test_with_no_lag_and_perfect_calibration_the_robot_arrives` 直接斷言 `closest_cm` 對
   safety floor，並從四個起始距離（130／150／200／300cm）跑。原本靠的是「2× 是嚴格更壞的
   情況，1× 落在其內」——論證成立，但論證會在程式碼變動時無聲失效。
2. `test_the_two_x_bound_is_not_luck_at_one_starting_distance` 改寫成
   `test_the_two_x_floor_bound_holds_across_every_start_distance`，掃 **75–320cm、1cm 步進**
   （246 點、0.18 秒），涵蓋舊 runner 用過的每一個前進起點（150／160／200／300）。

**結果：底線一次都沒被越過。** 最糟的 closest 是 48.00cm @ start=92cm —— 那是**抵達帶的
近端**（48.0），不是 45cm 的底線。這與 `PLAN.md` §5 記的一致：合法 config 下抵達帶 cap 比
safety floor 更嚴格。測試因此同時斷言這件事，將來若鬆掉會先在那裡看到。

**但把網格從 10cm 改成 1cm 之後，跑出 10cm 看不到的東西 —— 驗收條件第四點正是為此而寫。**

start = 142／212／282cm（間隔 70cm ＝ 2 × `max_step_cm`）回報 `arrived` 而 truth audit 判
`overshoot`。**不是安全問題，方向恰好相反**：機器人停在 72.04／72.08／72.12cm，抵達帶是
`[48.0, 72.0]`，也就是**比帶子更遠**。成因是讀數截成整數公分——真值 72.04 時控制器讀到 72，
落在帶內就宣告抵達。誤差被「一公分量化能藏多少」界定，每步約累積 0.04cm。

**沒有為了讓測試變綠而縮小範圍。** 範圍保持 75–320cm，假象由
`test_the_arrival_band_edge_is_missed_by_less_than_the_reading_quantises_to` 釘住並斷言
超出量小於一公分。完整記錄在 `PLAN.md` §14.9，並已寫進 ticket 05 的注意事項：**報告不得把
這幾列列為安全失敗，也不得藏起來** —— public status 與模擬真值在**零 transport lag** 下就
已經分家，沒有過期讀數可以怪。

**這是 M4 #08 的教訓第二次應驗。** 當時是 0.5 秒的粗網格跳過超衝帶，把後面的碰撞誤報成第一個
失敗；這次是 10cm 的粗網格整段跨過三個不收斂的起點。掃描步長在測試裡寫明了理由，避免將來
被當成任意數字縮回去。

**Mutation testing：** 把控制律的 `max_actual_motion_multiplier` headroom 拿掉 →
`test_the_two_x_floor_bound_holds_across_every_start_distance` 變紅；把讀數的整數截斷拿掉 →
`test_the_arrival_band_edge_is_missed_by_less_than_the_reading_quantises_to` 變紅。兩條新斷言
都有牙齒。

驗證：`.venv/bin/python -m pytest tests/ -q -rs` → **298 passed、零 skip**（297 → 298）。
