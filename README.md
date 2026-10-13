# 食材點位共同標註

獨立的多人食材標註程式。提供點位裁片、周邊畫面與平面的食物圖示選項；每次選擇立即保存至共享 SQLite 資料庫。

標註入口：[label.kurumimarket.store](https://label.kurumimarket.store)，轉向 [GitHub Pages 前端](https://harrykuang-dev.github.io/Hololive-Dreams-Food-Annotation/)。API 使用相同子網域的 `/api/` 路徑。

## 標註

只需填寫標註者 ID 即可加入。ID 用於記錄標註者，不作為身分驗證。只判斷紅圈中心正下方、最上層可見的食物；看不清時選「不確定」。不使用點擊結果、槽位狀態或模型預測作為人工標籤。

- 每次選擇立即同步，其他參與者的共享計數每 5 秒更新。
- 圖片領取保留 15 分鐘，避免多人重複分配；開啟中的圖片會定期續期。
- 網路中斷時，未確認提交的選擇留在瀏覽器，重新連線後重試。如果領取已失效或已由其他人保存，可下載未同步選擇後接續，不覆蓋別人的標註。
- 既有人工標註受保護。新增標註可由本人於 5 分鐘內撤銷；歷史事件保留。
- 工作階段有效期 30 天；關閉瀏覽器可接續。

資料集含 15,631 張樣本。裁片為原始 64×64 PNG，周邊圖片僅用於人工判斷。訓練仍使用相同裁片與 96×96 輸入。此倉庫不包含料理程式引擎、Kurumimarket 網站程式碼、原始錄影、模型權重或 SSH 金鑰。

## 部署

靜態圖片和網頁由 GitHub Pages 提供，伺服器只處理標註 API，不執行模型或訓練。`site/config.json` 設定 HTTPS API 位址，後端 `ANNOTATION_ORIGIN` 設定前端來源網域。

`backend/compose.yml` 部署獨立容器、網路及資料目錄。容器不發布主機埠，使用非 root 身分、唯讀程式檔、256 MB 記憶體與單核 25% CPU 上限。資料庫保存於 `/srv/cooking-annotation/runtime/data`，不共用原網站資料庫。

1. 放置 `server.py`、`backup.py`、`compose.yml` 和私有 `seed.json` 至 `/srv/cooking-annotation`。種子只含樣本 ID、圖片路徑與既有人工標註；禁止提交 Git。
2. 建立 `runtime/data`，將擁有者設為 UID/GID 10001。建立 `runtime/api.env`，依 `environment.example` 設定前端來源，檔案權限設為 600。
3. 啟動 `docker compose -p cooking-annotation -f /srv/cooking-annotation/compose.yml up -d`。
4. 將 Caddy 閘道連接到 `cooking-annotation` 網路，新增獨立子網域的 `/api/*` 轉送至 `cooking-annotation:18765`。先備份並驗證代理設定，再使用 `caddy reload` 平滑載入。
5. 既有網站重新部署若重建閘道容器，需要恢復新網路連接。可使用 `ensure-gateway-network.py` 的獨立定期作業；不要修改原網站程式碼或停止原服務。
6. 每日執行 `docker exec cooking-annotation python -B /app/backup.py`。透過 SQLite backup 介面產生一致備份，保留 14 天。
7. 開啟 GitHub Pages 的 Actions 部署方式，以 `publish-annotation.yml` 發布前端。

移除標註服務不需要停止原網站。代理設定的更新應保留其他網站的路由，更新後確認它們仍可存取。

## 匯出與訓練

下載 `shared-annotations.json` 後，先核對 `dataset_sha256` 與本地資料集一致，再匯入人工標註庫。不確定標註不作食物分類訓練標籤。原始素材及既有人工標註須保留；標註結果不會自動替換遊戲程式的模型。
