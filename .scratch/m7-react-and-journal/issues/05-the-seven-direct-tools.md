# 05 — 七個直接開放的 Tool

**What to build:** 讓模型能做出可見的動作：說話、換表情、動手臂、動頭、換燈色、播音效、四處看看。

七個 Tool：`speak`、`display_image`、`move_arms`、`move_head`、`change_led`、`play_audio`、`look_around`。

04 已經把機制證明過，這張是重複套用 —— 但**每一個的 clamp 都要自己想過**。角度、亮度、音量各有各的合法範圍，照抄一個模板等於沒有 clamp。

`PLAN.md` §4 說 AutoMisty 移除後的表現力由**組合**取代：一支舞是模型在多個 Turn 裡組合手臂、燈色與音效。所以這七個看起來瑣碎，但它們就是模型全部的表現力。

**Blocked by:** 04

**Status:** ready-for-agent

- [ ] 七個 Tool 都已登記，都有參數型別，模型看得到它們的 schema
- [ ] 每個參數的 clamp 依該參數的實際合法範圍設定，不是共用一個模板
- [ ] **每個 clamp 都有測試證明它會擋** —— 只證明合法值會過的測試不算數
- [ ] 送到驅動層的請求格式與官方文件一致，沿用既有契約測試的做法
- [ ] 沒有引入新的測試 seam
- [ ] 沒有任何 Tool 的參數含 velocity 或 timeMs
- [ ] 測試在專案 venv 下零 skip，不需硬體

## Notes（來自 #04 的 review）

- **參數型別定義在模組層級，不要定義在函式裡。** `from __future__ import annotations` 會把
  註解變成字串，函式內的類別解析不到。`tools.py` 會拋一個說明清楚的 `TypeError`。
- **分層守衛現在讀的是產生出來的 schema，不是 `model_fields`**，所以 alias 和巢狀模型都擋得住，
  規則在 `misty_agent/agent/layering.py`（見 `PLAN.md` §15.8）。距離參數**故意不擋**。
- `ToolContext` 有 `robot`、`readings`、`config`、`clock` 四個欄位。`speak` 的抑制窗
  （ticket 10）需要 `clock`。
- **每個 clamp 的測試要有陰性對照。** #04 的教訓是：只有一個例子的規則，分不出「屬性」和
  「剛好」—— `ends_episode` 那條就是這樣漏掉的（`PLAN.md` §15.9）。
- 拒絕理由的措辭已對齊 golden：超範圍時說**模型送了什麼**，不說上限是多少（§15.7）。
