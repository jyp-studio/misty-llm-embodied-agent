# 02 — prefactor：一筆紀錄怎麼讀，只說一次

**What to build:** 把「一筆 Journal 紀錄對人類讀起來是什麼」抽成一個被測試蓋到的結構，
`TerminalRenderer` 從它格式化。

**這是 prefactor，不交付使用者看得到的東西。** 理由是 07 的畫面資料需要回答同一個問題，
不先抽就會有兩份說法 —— 而這個專案剛因此付過學費：`TerminalRenderer` 對 `speak` 印出
`-> , 52cm away`，逗號前面是空的，因為只有 `approach` 的結果帶 `result` 這個鍵。那個 bug
不是沒被測到，是**測試蓋不到那一層** —— 既有測試斷言的是 Journal，不是印出來的字。

**Blocked by:** None — can start immediately

**Status:** done

- [x] 「一筆紀錄說了什麼」是一個純函式，紀錄進、結構出，不含任何排版
- [x] `TerminalRenderer` 從那個結構格式化，不再自己決定顯示什麼
- [x] **每一種紀錄都有對應**，而且有測試證明新增一種紀錄卻忘記處理會變紅
- [x] `speak`、`change_led`、`move_head` 等沒有 `result` 鍵的 Tool，其 Observation 讀起來
      是通順的 —— 不再有空的逗號
- [x] `approach` 的 Observation 仍然讀得到它的四種狀態
- [x] 陰性對照：一個對每種紀錄都回傳同一句話的實作，會被測試擋下來
- [x] 全套測試綠且零 skip


## Comments

完成於 2026-09-06。`describe()` / `Described` / `describe_line()` 在 `journal.py`，
`tests/test_journal_writing.py` 加 31 條。**1054 passed、7 deselected、零 skip**。
28 個 mutation 全紅。

逗號 bug 修好了：`speak` 的 Observation 從 `-> , 52cm away` 變成 `-> ok, 52cm away`。

---

## ⚠️ 第一條驗收我沒有做到，而且不打算做到

「「一筆紀錄說了什麼」是一個純函式，紀錄進、結構出，**不含任何排版**」——
Spec 軸的盤點是對的：`speak(text='hi')` 的括號與引號、`812+11 tokens` 的加號、`2 turn(s)`
的複數形，每一個都是顯示選擇。

要真的做到，`Described` 得攜帶結構化的欄位對映。**兩個後果讓我否決它**：終端機會變成
field dump（而 `test_the_terminal_renderer_is_not_a_field_dump` 存在的理由正是兩個訂閱者
回答不同的問題）；而那份對映**今天沒有呼叫端**，正是 §15.23 刪掉 `instructions=` 的形狀。

定案寫在 `PLAN.md` §16.7：**`Described` 是一個句子，不是一份資料。**

**代價**：兩軸都指出這個 prefactor 因此比票面小。它買到的是 bug 修正、窮舉保證、和每種紀錄
只有一個地方決定它怎麼讀 —— **不是 §16.4 描述的那個完整 seam，07 仍要自己出力。**

---

## Review（兩軸）

### 那個 bug 有第二個入口，而我沒守

Standards 軸把 `_came_back` 的 fallback 從 `"returned"` 換成 `""` —— **整套測試照樣綠**，
渲染出 `  -> , 52cm away`，與這張票要修的 bug **逐字元相同**。

因為我寫的四條測試全部用 `ok: True`。`ok: False`、`{}`、只有 `steps` 的結果全走 fallback，
一條都沒測。同一個形狀的另一端：刪掉「detail 為空就不加分隔符」那個分支會渲染出 `turn 3, `，
也沒有測試會紅。§16.8。

### 十五個存活的 mutation，一個共同原因

我那條 `test_describing_a_record_does_not_format_it` 只檢查開頭空白與結尾標點 —— 連它自己的
`??` 標記都沒抓到。於是：headline 與 detail 互換、trigger 消失、`turn` 沒有數字、
`speak()` 裡的話不見了、token 數對調、**每一個 depth 的變異**，全部活著。

改成**逐種紀錄的精確整行對照表**（十種），一次全殺。這正是 golden 檔案的做法。

### `depth: int` 換成 `tone`

Standards 指出 0/1 兩值用 int 是 Primitive Obsession，而且「invited the surviving
`depth=2`」—— 確實有一個 `depth=2` 活著。換成封閉集合 `TONES` 之後，縮排、標記與分隔符全部
由它推導，而且 **`refused` 與 `failed` 分開**：拒絕是系統在正常運作，失敗是系統壞了。
Standards 說少了這個區分「is the drift the prefactor exists to prevent」。

### 四個可讀性退化，全部復原

Spec 軸逐一渲染五個 golden 前後對照抓到的：`-> ` 消失、`refused, reason` 該是冒號、
`stop requested, by X` 多了逗號、`episode done after ...` 的 after 被丟掉。**其中冒號那個
是真的錯** —— 拒絕的理由是解釋，而我的分隔符只看 `failed`。

### 一個誤判與一個流程問題

Spec 軸把 `.env.example` 等四個檔案報成本票的 scope creep。**它們是 `HANDOFF.md` §4 記載的
四筆既有修改**，`tests/conftest.py` 上次進 commit 是 M4 #10。

Standards 軸的 worktree 建在共用 scratchpad 裡，**跑到一半被平行的 Spec 軸清掉**。那是
§14（M6 #06）記過的事又發生一次，寫進 §16.9：往後兩軸要各用私有路徑。
