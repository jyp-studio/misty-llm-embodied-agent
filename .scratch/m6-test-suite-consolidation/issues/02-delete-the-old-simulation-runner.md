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
區塊、§2 的樹狀圖、§4 的 `requests` 那條、`README.md` 的執行段落與檔案清單、`PLAN.md:254`「遷移到 pytest」那句（改成
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

---

**Review 後的更正（2026-08-20，同日）。** 兩軸 `/code-review` 找出 Standards 4 項、
Spec 5 項，兩軸的頭號發現是同一條，而且是本 ticket **改出來的**：

1. **README 的「no dependencies beyond the stdlib」變成假的。** 那句話對舊 runner 是真的
   （它只 import stdlib），但我把它底下的指令換成 `pytest tests/` 之後就不成立了 ——
   那需要 mediapipe、opencv、numpy、pydantic。這與本 ticket 修掉的「28-case」「measurement
   noise」是**同一類錯誤**，出現在修它們的同一次提交裡。已改寫整段。
2. **`# Result: 272 passed` 是把會過期的數字釘進 README。** 而本 ticket 存在的理由之一，
   正是盤點花了一整節去解決「28 passed」這個釘死的數字。03、04、06、07 都會加測試，這個
   數字在 M6 結束前就會錯。已移除，改成一句「suite 自己才是它大小的真相來源」。
3. **README 引入了 `.venv` 卻沒說怎麼來。** Quick start 只講 `pip install -r requirements.txt`。
   已補一句指向 `AGENTS.md`，並帶出「挑錯直譯器會一片綠」那個坑。
4. **§14.6 登記了但不好找。** §14.3 只說「登記為 M7 的重建項目」沒給指標，§7 的 M7 列也沒提。
   兩處都補了指向 §14.6。
5. **本段原本把 HANDOFF 的樹狀圖寫成 §3、`requests` 那條寫成 §3**，實際是 §2 與 §4。已更正。
   `3a2ea09` 的 commit message 帶著同樣的口誤，不改寫歷史，在此註記。

**兩項判定為不修，理由記在這裡以免被當成漏掉：**

- **`.scratch/m4-replay-harness/spec.md:212`**（「harness 上線後應在該檔註明其侷限」）與
  **`.scratch/m5-approach-backend/spec.md:106`**（把「舊 runner 遷移到 pytest」列為 out of
  scope）。review 認為前者是活的待辦而非紀錄。判定：**不改**。`PLAN.md` 是**活的**決策
  紀錄，必須與現況一致，所以 `:254` 那句要劃線撤回；而 `.scratch/m*/spec.md` 是**已完成
  里程碑的產物**，必須忠於當時寫了什麼。編輯它等於竄改考卷。何況那條指令指向一個不存在的
  檔案，本身已經自我取消。
- **`.claude/settings.local.json`** 仍授權 `Bash(python3 test_sim.py)`。該檔被全域
  gitignore、不在版控、是使用者的機器本機設定，不由 agent 代改。
