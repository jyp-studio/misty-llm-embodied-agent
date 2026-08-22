# 02 — 刪掉舊 simulation runner，連同它的所有指涉

**What to build:** 讓專案不再有兩套針對同一行為、結論可能分歧的測試。舊的 hardware-free simulation runner 整個刪除，不留殘骸、不遷移。

**不遷移它的 brain 與 memory scenario。** M7 改用 OpenAI function calling，由模型端保證結構，「消毒 malformed JSON」這個需求根本不會存在；把它搬進 pytest 等於把一個即將消失的需求正式化，M7 還得再刪一次。Memory 折疊與持久化的覆蓋因此隨之消失 —— 這是**有意識的缺口**，必須登記為 M7 搬出 memory 時的重建項目，不能靜默丟失。

刪除後全 repo 不得留下懸空指涉。用 `grep -rn` 找出全部提及處，逐一處理：執行說明與交接文件的驗收指令從三條變兩條；README 的檔案清單與執行段落；`PLAN.md` 裡那句「遷移到 pytest」現在與 §14.3 直接矛盾，必須改掉。歷史分析段落（描述舊 runner 為什麼抓不到缺陷 A）是**紀錄**，保留不動。

**Blocked by:** 01 — 盤點是刪除的依據，沒有它就是無憑據地砍測試。

**Status:** ready-for-agent

- [ ] 舊 simulation runner 檔案不再存在
- [ ] `grep -rn` 找不到任何指向它的**可執行指令或現況描述**；只剩歷史分析段落
- [ ] 執行說明與交接文件的驗收指令更新為刪除後的實際狀態
- [ ] README 的檔案清單與執行段落不再指向已刪除的檔案
- [ ] `PLAN.md` 中與 §14.3 矛盾的「遷移到 pytest」敘述已改正
- [ ] memory 折疊與持久化的覆蓋缺口登記在盤點與 `PLAN.md`，指名由 M7 重建
- [ ] `pytest tests/ -q -rs` 全綠且零 skip
- [ ] 沒有任何新測試在本 ticket 被加入 —— 這張票只做刪除與文件對齊
