# 食材點位共同標註

獨立倉庫：<https://github.com/harrykuang-dev/Hololive-Dreams-Food-Annotation>。不包含料理程式引擎或 Kurumimarket 網站程式碼。

網頁提供圖片與平面的食物圖示選項。每次選擇立即提交至獨立SQLite資料庫；多人共用進度，圖片領取保留15分鐘，避免重複分配。瀏覽器暫存尚未確認同步的選擇，重新連線後重試。不確定圖片保留記錄，不作食物分類訓練標籤。

前端部署於GitHub Pages，後端使用Python標準函式庫，可部署至既有Linux伺服器。圖片放在靜態網站，伺服器不執行模型、錄影編碼或訓練。伺服器入口使用獨立子網域及HTTPS，程式只監聽回環端口18765。systemd服務限制256 MB記憶體與單核25% CPU，使用獨立系統使用者及資料目錄。

## 部署

目前配置尚未連接正式API，網頁會明確顯示「共享服務尚未接通」。設定完成後才提供多人即時同步；GitHub Pages本身不儲存共享標註。

1. 在伺服器配置`cooking-annotation`系統使用者、`/opt/cooking-annotation`程式目錄與`/var/lib/cooking-annotation`資料目錄。
2. 放置`backend/server.py`及與前端同一資料集的`seed.json`。種子包含樣本ID、裁片路徑及既有人工標註，不包含模型預測或私密憑據。
3. 依`backend/environment.example`建立`/etc/cooking-annotation.env`，限制只有部署管理者可讀。私下設定高熵邀請碼，不把真實值提交Git。
4. 安裝`backend/annotation.service`，啟動新服務。不要停止原網站服務、重用其資料庫或覆蓋其代理設定。
5. 以現有反向代理新增獨立HTTPS入口，轉送至`127.0.0.1:18765`。先驗證設定，再平滑載入。實際端口、代理軟體、網域與DNS需依伺服器現況確認。
6. 將`site/config.json`的`api_base`填為正式HTTPS API網址，與後端的`ANNOTATION_ORIGIN`對應GitHub Pages來源網域。
7. 開啟GitHub Pages的Actions部署方式，以`publish-annotation.yml`發布前端。

既有人工標註在資料庫初始化時標記為受保護，不被網頁覆蓋。新增標註只有目前領取者能提交；重試相同選擇不重複寫入。撤銷僅適用本人五分鐘內的新增標註，歷史事件仍保留。

## 標註與匯出

以暱稱和邀請碼加入，不使用伺服器SSH私鑰或GitHub存取權杖。填邀請碼後取得30日標註工作階段；關閉瀏覽器保留本機接續資料。每次選擇即同步到伺服器，其他參與者的共享計數每5秒更新。

下載`shared-annotations.json`後，先核對資料集指紋，再匯入本地人工標註庫。Web標註只確認紅圈中心外觀，不把實際點擊結果當成食物外觀；模型訓練仍共用原64×64裁片及相同的96×96輸入。

備份SQLite須使用backup介面，不能在寫入期間只複製主檔而漏掉WAL。停用或移除新標註服務不需要停止原網站。部署前應實際核對原服務與端口，不能只依範例設定假定伺服器狀態。
