# 07 — ReAct 迴圈

**What to build:** 一次完整的 Episode：餵一個觸發輸入進去，模型連續做幾個決定，做完之後回到閒置，過程留在 Journal 上。

這是 M7 的主菜，也是這個專案叫「agent」的理由 —— 在此之前，會呼叫控制層的只有測試與量測台。

**Turn 上限是硬上限。** `PLAN.md` §4 稱「每個 Episode 可證明回到閒置」是這個系統最強的性質，而 ReAct 化最容易弄丟它。上限值是初值，之後用 Journal 的資料修正。

**沒有獨立快路徑。** 模型在第一個 Turn 就能結束 Episode。自主終止本來就是 ReAct 的判準，硬編碼特例等於自廢武功。

**Observation = Tool 自己的結果 + Snapshot**，而 Snapshot 由迴圈附加，不由每個 Tool 各自組裝 —— 它對每個 Tool 都一樣，放進 Tool 就是複製九份。Snapshot 就三樣：主體距離、是否看得見、是否聽到新的話。序列化為 JSON 送給模型，**不並陳一份人話摘要**（同一個事實兩份拷貝會漂）。

模型呼叫走一個**窄介面**，測試注入腳本化的回應，不去 mock 第三方套件。

⚠️ **一個 M7 #03 期間發現的命名問題，在這裡最便宜地修掉：** `config.py` 的
`max_react_steps` **用 `steps` 指的是 Turn** —— 它自己的描述寫的是「Hard cap on LLM
**turns** per episode」。`CONTEXT.md` 的 `Step` 是控制層的一次驅動命令，而 `Turn` 才是
ReAct 的一輪。目前**沒有任何呼叫端**（grep 只有 `config.py` 自己），所以現在改名的成本是零；
等迴圈寫完就得連環境變數一起動。

**Blocked by:** 03, 05, 06

**Status:** ready-for-agent

- [ ] 單次 Episode 有公開入口，接受觸發輸入、回傳結構化結果
- [ ] Turn 上限是硬上限；耗盡時 Episode 仍然結束並回到閒置
- [ ] 模型可以在第一個 Turn 結束 Episode，沒有硬編碼的特例路徑
- [ ] Observation 由迴圈組裝：Tool 結果加上三樣 Snapshot
- [ ] Observation 序列化為 JSON，不並陳人話摘要
- [ ] 模型呼叫走窄介面；測試注入腳本化回應，不 mock 第三方套件
- [ ] **產出的 Journal 對得上 golden 1、2、3**
- [ ] 有測試證明模型收到的任何文字都不含 velocity 或 timeMs
- [ ] 測試在專案 venv 下零 skip，不呼叫真模型、不需網路
