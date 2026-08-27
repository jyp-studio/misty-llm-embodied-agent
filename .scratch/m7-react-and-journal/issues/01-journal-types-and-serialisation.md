# 01 — Journal 的型別與序列化

**What to build:** 讓一份 Journal 可以被建立、寫成文字、再讀回來，而且來回之後一模一樣。

**每種事件一個 frozen 型別。** 共同欄位只有三個：時間、事件種類、Episode 識別。**`turn` 不是共同欄位** —— Episode 開始那一筆沒有 Turn，硬塞會逼出一個 Optional，然後每個讀者都要處理它。

**時間是 Episode 相對秒，來自單調時鐘，而時鐘可以注入。** 沿用控制層已經在用的 Clock protocol 與假時鐘。這不是為了優雅：golden files 要逐字元比對，絕對時間就不可能。Episode 開始那一筆額外帶**一個**絕對 wall-clock 戳記給人對時 —— 只有一個，所以不影響其餘的可比對性。

**契約是那些型別，JSONL 只是序列化格式。** 版本欄位只放在 Episode 開始那一筆（一個 Journal 對應一個 Episode，檔案是整份讀的）。M10 之前 schema 不保證穩定，而且要在文件裡明講這件事。

序列化必須是純函式：不碰檔案、不碰時鐘、毫秒級可測。M6 的報告層是既有先例。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] 每種值得記錄的事件各有一個 frozen 型別；共同欄位只有時間、種類、Episode 識別
- [ ] `turn` 只出現在真的有 Turn 的事件上，不是共同欄位
- [ ] 時間是 Episode 相對秒，來自單調時鐘，時鐘可注入
- [ ] Episode 開始那筆額外帶一個絕對 wall-clock 戳記與 schema 版本
- [ ] 型別 → JSONL → 解析回型別，來回結果與原本相同
- [ ] 序列化是純函式，不做 IO，不讀真實時鐘
- [ ] 沒有任何欄位或型別洩漏 velocity 或 timeMs
- [ ] 文件明寫 M10 之前 schema 不保證穩定
- [ ] 測試在專案 venv 下零 skip，不呼叫模型、不需網路
