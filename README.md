# himawari-cloudtop

Cloudflare の KV に、日本付近の気象の格子を置くだけのリポジトリです(GitHub Actions。起動は Cloudflare の Worker から)。

- ひまわり 9 号の雲頂の高さ・雲の種類・赤外の温度(`tools/himawari_build.py`、10 分ごと)。データ: NOAA Open Data Dissemination(noaa-himawari9、AWS)。
- UKMET(Met Office 全球 10km)の上空の気温・風・湿度と圏界面(`tools/ukmo_build.py`、新しい回が出るたび)。データ: Met Office(CC BY-SA 4.0、© Crown copyright)。
- 個人・非商用。必要な Secrets: `CF_API_TOKEN`・`CF_ACCOUNT_ID`・`CF_KV_WX_ID`
