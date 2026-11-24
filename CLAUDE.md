# 作業の決まり(himawari-cloudtop)

このリポジトリは公開。アプリ SkAI のための気象データの取り込み(GitHub Actions)と、定時の AI 解析の置き場。

## どの作業にも
- 返事・報告は日本語。
- 公開なので、次の物は書かない・コミットしない:
  - キー・トークン・PIN・シークレットの値(GitHub Secrets の名前は書いてよい、値は書かない)
  - 個人のアカウント名が入った URL
  - 会社の PIREP・NOTAM・資料などの非公開の情報、会社経路の RTE 文字列(路線名・FIX 名・航空路名は書いてよい)
    (会社の PIREP を答え合わせに使うのは非公開の approach-planner-private の中だけ。ここの prdiag には持ち込まない)
  - DRM・navlog の中身、人の名前
- 揺れの強さは LGT- / LGT / LGT+ / MOD だけ。SEV は使わない。MOD は SIGMET か MOD の PIREP 2 件以上のときだけ。

## 定時の AI 解析
- docs/nwp_task_prompt.md に従う。下の「開発のときだけ」は関係ない。

## 開発のときだけ
- 確認を取るのは取り消せない操作の前だけ。それ以外は進めて、終わったら何を変えたかを報告する。
- 頼まれていない追加はしない。思いついたら提案だけする。
- main へは直接 push してよい(変えた所を報告する)。
- 診断(過去の天気の調べ)は prdiag ブランチの tools/pr_diag.py を書き換えて push → Actions が動き、結果は prdiag-out の out/log.txt。main に診断を置かない。
- `tools/__pycache__` はコミットしない(git add はファイルを名指しで)。
- 主な仕組み: tools/ukmo_build.py(UKMET → KV)、tools/obs_build.py(観測と UKMET のまとめ → nwp-obs。中身を変えたら UK_V を上げる)、
  tools/nwp_build.py(天気図 → nwp-img)、tools/ltg_eval.py(雷予想の答え合わせ → ltg-data)、tools/pirep_collect.py(PIREP 集め → pirep-data)、tools/ukmo_global.py(全球 → R2)。
- 指示文 docs/nwp_task_prompt.md を変えたら、claude.ai のプロジェクトの claude/descent_planner/nwp_task_prompt.md にも同じ物を置く。
- Actions を手で動かすときは REST(`gh api -X POST repos/<持ち主>/himawari-cloudtop/actions/workflows/<ファイル>/dispatches -f ref=main`)。
