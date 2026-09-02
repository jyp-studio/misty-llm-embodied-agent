# 05 — 七個直接開放的 Tool

**What to build:** 讓模型能做出可見的動作：說話、換表情、動手臂、動頭、換燈色、播音效、四處看看。

七個 Tool：`speak`、`display_image`、`move_arms`、`move_head`、`change_led`、`play_audio`、`look_around`。

04 已經把機制證明過，這張是重複套用 —— 但**每一個的 clamp 都要自己想過**。角度、亮度、音量各有各的合法範圍，照抄一個模板等於沒有 clamp。

`PLAN.md` §4 說 AutoMisty 移除後的表現力由**組合**取代：一支舞是模型在多個 Turn 裡組合手臂、燈色與音效。所以這七個看起來瑣碎，但它們就是模型全部的表現力。

**Blocked by:** 04

**Status:** done

- [x] 七個 Tool 都已登記，都有參數型別，模型看得到它們的 schema
- [x] 每個參數的 clamp 依該參數的實際合法範圍設定，不是共用一個模板
- [x] **每個 clamp 都有測試證明它會擋** —— 只證明合法值會過的測試不算數
- [x] 送到驅動層的請求格式與官方文件一致，沿用既有契約測試的做法
- [x] 沒有引入新的測試 seam
- [x] 沒有任何 Tool 的參數含 velocity 或 timeMs
- [x] 測試在專案 venv 下零 skip，不需硬體

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


## Comments

完成於 2026-09-02。`misty_agent/agent/tools.py` 加上七個 Tool，`tests/test_direct_tools.py`
90 條測試。全套 **682 passed、零 skip**（668 → 682）。

**六個範圍，互不相同。** head pitch / roll / yaw、arm、LED、volume 各有各的，
`test_every_documented_range_is_its_own` 把六組逐一列出來比對，就是為了讓「整理成一個共用
常數」變紅。每個 clamp 都有兩側測試：界限本身要過、界限外一格要被擋、而且被擋的**沒有送到
機器人**（`robot.requests == []`）。表格寫在 `PLAN.md` §15.10。

**`display_image` / `play_audio` 收語意名稱不收檔名**，理由與音效只放六個的取捨記在 §15.11。

---

## Review（兩軸）

### Standards 軸：我把一個數字抄錯了

**head pitch 上限是 26 不是 29。** 我照網路搜尋結果寫了 29，但 REST reference 的表格是 26，
而且 repo 裡本來就有三處旁證。教訓寫在 §15.10：**in-tree 的既有數字和外部搜尋打架時，先假設
in-tree 是對的**。兩個引用 URL 也是 404，一併修正。

**`speech_max_chars` 宣告了卻沒接線** —— §10 #4 那條，「看起來可調、實際不可調」。Tool 的
參數型別在 import 時就建好，讀不到 per-Episode config，所以 `Settings(speech_max_chars=5)`
之下 200 字的句子照樣送到機器人。而 `look_around` 的 settle **是**從 `ctx.config` 讀的 ——
同一個 config 物件被一個 Tool 尊重、被另一個忽略。改成模組常數，見 §15.12。

**`SOUND_FILES` 的註解是假話**（「文件只列了這些」；文件列了約六十個）。已改成說清楚是刪減。

另外抓到 9 個活著的 mutation：`move_arms` 漏掉 `units="degrees"`、settle 寫死、掃描時把頭仰到
-40、掃描幅度縮到 ±1°、字數上限放寬十倍、`gt=0` 改 `ge=0`、三個預設值、以及回傳內容完全沒被
斷言。`FakeClock` 被我寫成第四份拷貝，已移進 `misty_agent/fakes/`（`test_approach.py` 的
第三份也一併收掉）。

### Spec 軸：兩條結構性的

**1. `speak` 產不出 golden 2，而我把它推給了一張排在後面的票。** 我寫了一段註解說估計函式屬於
ticket 10 —— 但 10 是 **Blocked by 05**，會落在 07 之後，而 07 的驗收條件就是重現 golden 2。
等於交給 07 一個它自己不擁有的相依。估計函式提前到 05，速率常數進 `Settings` 並標
UNCALIBRATED（正是 10 那條 checkbox 要的）。

`estimate_speech_ms("Coming over.", Settings())` = **1409 ms**，與 golden 2 逐位相符。那個
golden 寫在這個函式之前，所以這是它真的從 §4 公式推導出來的證據。**同時發現這個公式對中文是
壞的** —— 一整句中文 `split()` 只算一個詞。記在 §15.13，ticket 10 必須處理。

**2. `look_around` 差點就該被砍掉。** 第一版掃完回正，所以 ±60° 看到的東西一樣沒留下 —— 07
附加的 Snapshot 描述的是正前方。過不了 §15.2 砍 `back_up` 用的那條測試：模型連兩個 Turn 呼叫
`move_head` 反而拿到更多。改成**邊轉邊看、找到人就停在那裡**，見 §15.14。

`showing` / `played` / `said` 把模型自己送的參數抄一遍（已在 `tool_called.args` 上），
§15.4 拒絕同一個事實兩份，已移除。

**Spec 軸還算出一件 07 要決定的事：** 舊腳本的 `wave` 是 5 個 Turn，而 `max_react_steps`
預設就是 5 —— §4 說表現力靠組合，這個上限讓組合付不起。記在 §15.15，**這裡不改**。

### Mutation

三輪。第一輪 20 個全紅，但 Standards 軸另外找到 9 個我沒想到的；補完之後第二輪 20/20，
改完 Spec 軸的兩條之後第三輪 18/18。

**兩次踩到同一個坑：測試用的值剛好等於 mutation 寫死的值。** `play_audio` 的 volume 我測 50、
mutation 也寫死 50；`look_around` 找到人的位置我挑 `SCAN_YAWS[1]`，那個值是 **0.0**，而
mutation 回傳的常數也是 0.0。兩次都是把測試值改成不會撞到的數字就紅了。

**還有一次 `str.replace` 沒對上就靜靜什麼都沒做**（測試簽名換行了），因為那一段我沒寫
`assert old in src`。是 mutation 存活才發現測試根本沒改到。
