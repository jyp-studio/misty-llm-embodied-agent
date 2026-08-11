# 02 — 把臉部偵測抽進 perception 套件

**What to build:** 拿到一張影像就能問出「有沒有人 / 距離多遠 / 是不是正在看鏡頭」,
而且不需要 OpenAI API key、不需要 import 主腳本、不需要 stub 任何 LLM 程式碼。

現在做不到:臉部偵測住在主腳本裡,而該模組在 import 時就會建構 OpenAI client。
任何想用它的東西都得重演 `test_sim.py` 的 stub 大戰。harness 是下一個想用它的東西。

新家是 `misty_agent.perception.face`,對應 `PLAN.md` §2 目標結構裡的 `perception/face.py`
(該檔在 §7 沒有被指派給任何里程碑,現歸入 M4)。

介面只知道影像,不知道緩衝、不知道執行緒、不知道時間——時間語意是 03 的事。

**Blocked by:** 01(需要一個真的裝得起來的臉部偵測堆疊)

**Status:** resolved

- [x] 臉部偵測與由臉寬推距離的邏輯移入 `misty_agent.perception.face`
- [x] 介面接受一張影像,回傳有沒有人 / 距離 / 是否正在看;**不接受也不回傳時間戳**
- [x] 校正常數(焦距、假設臉寬)仍從 config 取得,維持 M2 建立的單一來源
- [x] 主腳本改為委派,自己不再持有這段邏輯
- [x] 純搬移:相同輸入得到相同輸出,**沒有順手改善偵測參數或估算方式**
      → 不只是用看的:把搬移前的 `HumanDetector` 從 git 取出,與新模組餵同一串影格
      (含空白、隨機雜訊、階躍、偵測失敗)逐幀比對,15 幀 0 筆不一致
- [x] 新增針對此模組的測試:給定一張已知臉寬的影像,回報距離符合預期
- [x] 重相依(MediaPipe、OpenCV)的 import 不在模組頂層,裸環境下模組仍 import 得起來
      → 並用 subprocess 把 `cv2` / `mediapipe` 擋掉來實測,不只是靠慣例
- [x] `pytest` 與 `test_sim.py` 兩套仍全綠(105 passed / 24 passed)

## Comments

**發現一件 spec 沒有預期到的事:MediaPipe 的跨幀追蹤本身就是一個延遲來源。**

face mesh 會追蹤上一幀找到的臉而不是重新偵測,所以讀數會被前一幀拖住:同一張
200px 的影像,冷啟動的偵測器讀 48cm,而剛看過 100px 影像的偵測器讀 68cm。跳太大
還會整個丟失(200px→100px、300px→75px 都回傳 `NO_FACE`)。

**這會影響 M4 的核心主張。** spec 說「harness 紅了,而且紅的原因**只可能是**缺陷 A」
——但 harness 量到的其實是「缺陷 A + 偵測器自己的追蹤延遲」的總和。06 訂門檻、
09 寫摘要時要把這件事講清楚,否則會把不屬於缺陷 A 的延遲算到它頭上。

拖住讀數那一項已經用測試釘住(`test_a_reading_depends_on_the_frames_that_came_before_it`)。
丟失那一項刻意不釘:哪個跳幅會丟臉是 MediaPipe 版本的性質,寫成斷言會在追蹤變**好**
的升級上變紅。

**另外量到 fixture 的可用範圍**,04 / 05 會需要:合成到 640x480 時,臉寬 75px 以上
MediaPipe 還原得回 1.2% 以內;60px 少算 8%;50px 以下完全偵測不到。75px 在目前
校正下是 130cm,而接近控制器大約從 160cm 開始作用——**軌跡的遠端會落在 fixture
最不準的那一段**。

**已知缺口:凝視沒有陰性對照。** repo 只有一張正面人臉 fixture。試過用透視變形模擬
側臉,MediaPipe 的反應不穩定(某個變形強度下鼻子偏移剛好過門檻,相鄰的強度則直接
偵測不到),測試會為了與本程式無關的理由變紅。要補的是第二張「頭轉開」的 fixture,
連 provenance 一起。
