# 02 — 把臉部偵測抽進 perception 套件

**What to build:** 拿到一張影像就能問出「有沒有人 / 距離多遠 / 是不是正在看鏡頭」,
而且不需要 OpenAI API key、不需要 import 主腳本、不需要 stub 任何 LLM 程式碼。

現在做不到:臉部偵測住在主腳本裡,而該模組在 import 時就會建構 OpenAI client。
任何想用它的東西都得重演 `test_sim.py` 的 stub 大戰。harness 是下一個想用它的東西。

新家是 `misty_agent.perception.face`,對應 `PLAN.md` §2 目標結構裡的 `perception/face.py`
(該檔在 §7 沒有被指派給任何里程碑,現歸入 M4)。

介面只知道影像,不知道緩衝、不知道執行緒、不知道時間——時間語意是 03 的事。

**Blocked by:** 01(需要一個真的裝得起來的臉部偵測堆疊)

**Status:** ready-for-agent

- [ ] 臉部偵測與由臉寬推距離的邏輯移入 `misty_agent.perception.face`
- [ ] 介面接受一張影像,回傳有沒有人 / 距離 / 是否正在看;**不接受也不回傳時間戳**
- [ ] 校正常數(焦距、假設臉寬)仍從 config 取得,維持 M2 建立的單一來源
- [ ] 主腳本改為委派,自己不再持有這段邏輯
- [ ] 純搬移:相同輸入得到相同輸出,**沒有順手改善偵測參數或估算方式**
- [ ] 新增針對此模組的測試:給定一張已知臉寬的影像,回報距離符合預期
- [ ] 重相依(MediaPipe、OpenCV)的 import 不在模組頂層,裸環境下模組仍 import 得起來
- [ ] `pytest` 與 `test_sim.py` 兩套仍全綠
