# 02 — 刪掉舊 simulation runner，連同它的所有指涉

**What to build:** 讓專案不再有兩套針對同一行為、結論可能分歧的測試。舊的 hardware-free simulation runner 整個刪除，不留殘骸、不遷移。

**不遷移它的 brain 與 memory scenario。** M7 改用 OpenAI function calling，由模型端保證結構，「消毒 malformed JSON」這個需求根本不會存在；把它搬進 pytest 等於把一個即將消失的需求正式化，M7 還得再刪一次。Memory 折疊與持久化的覆蓋因此隨之消失 —— 這是**有意識的缺口**，必須登記為 M7 搬出 memory 時的重建項目，不能靜默丟失。

刪除後全 repo 不得留下懸空指涉。用 `grep -rn` 找出全部提及處，逐一處理：執行說明與交接文件的驗收指令從三條變兩條；README 的檔案清單與執行段落；`PLAN.md` 裡那句「遷移到 pytest」現在與 §14.3 直接矛盾，必須改掉。歷史分析段落（描述舊 runner 為什麼抓不到缺陷 A）是**紀錄**，保留不動。

**Blocked by:** 01 — 盤點是刪除的依據，沒有它就是無憑據地砍測試。

**Status:** resolved

- [x] 舊 simulation runner 檔案不再存在
- [x] `grep -rn` 找不到任何指向它的**可執行指令或現況描述**；只剩歷史分析段落
- [x] 執行說明與交接文件的驗收指令更新為刪除後的實際狀態
- [x] README 的檔案清單與執行段落不再指向已刪除的檔案
- [x] `PLAN.md` 中與 §14.3 矛盾的「遷移到 pytest」敘述已改正
- [x] memory 折疊與持久化的覆蓋缺口登記在盤點與 `PLAN.md`，指名由 M7 重建
- [x] `pytest tests/ -q -rs` 全綠且零 skip
- [x] 沒有任何新測試在本 ticket 被加入 —— 這張票只做刪除與文件對齊

## Comments

完成於 2026-08-20。`git rm test_sim.py`，並逐一處理全部指涉。

**改掉的（可執行指令或現況描述）：** `AGENTS.md` 的執行區塊、`HANDOFF.md` §0 與 §3 的驗收
區塊與樹狀圖、`README.md` 的執行段落與檔案清單、`PLAN.md:254`「遷移到 pytest」那句（改成
劃線撤回並指向 §14.3）、`full_robot_v3.py:99` 註解裡的懸空檔名。

**保留不動的（紀錄）：** `PLAN.md` §5 與 §12 描述舊 runner 為什麼抓不到缺陷 A 的分析、
`.scratch/m4-*` 與 `.scratch/m5-*` 各 ticket 的驗證紀錄、M4 spec 把它列為反面教材的段落。
那些記的是當時為真的事，改掉等於竄改紀錄。

**M7 重建清單登記在 `PLAN.md` §14.6**，兩項：memory 折疊與持久化（舊 T9 五條）、工具參數
合法性檢查（舊 T8 倖存的那半）。寫成表格而不是只留在盤點裡，因為盤點是時點文件、清單是待辦。

**README 的其他陳舊指涉沒有一併修，這是刻意的。** 它的檔案清單仍列著 `AutoMisty.py`、
`Agents/`、`CUBS_Misty.py`、`RobotCommands.py`、`code/mistyPy/`、`Mistydemo/` —— 全部在
M1／M3 就刪了；「System 1 / System 2」那節也還在講 AutoMisty slow path。那是 **M9 README
重寫**的範圍（`PLAN.md` §7），不是這張票造成的懸空。本 ticket 只動它指向 `test_sim.py` 的
三處，外加把「28-case」與「measurement noise」兩個現在已知為假的說法改掉 —— 後者尤其不能
留：盤點剛證明**套件裡沒有任何噪音覆蓋**，而 README 兩處都在宣稱有。

驗證：`.venv/bin/python -m pytest tests/ -q -rs` → **272 passed、零 skip**（與刪除前相同，
舊 runner 本來就不被 pytest 收集）；`full_robot_v3.py` 仍可編譯。未新增任何測試。
