# Japan — LawCodex (日本の法令)

The legislation of Japan in force, as plain Markdown, generated from the official
**e-Gov 法令検索** database (https://laws.e-gov.go.jp/), run by the Digital Agency (デジタル庁).
Part of [LawCodex](https://github.com/LawCodex): one repository per jurisdiction.

All texts are in Japanese, the official language, reproduced verbatim from the official
法令標準XML (Standard Law XML). Nothing is translated or summarised.

- Retrieved: **2026-10-11** (e-Gov bulk archive dated 2026-10-10)
- Version: the current consolidated text (現行法令) of each law as published by e-Gov,
  incorporating amendments enforced up to the retrieval date.

## Coverage

| Directory | 法令種別 (Japanese category) | Files |
| --- | --- | ---: |
| `constitution/` | 憲法 (Constitution of Japan) | 1 |
| `laws/` | 法律 (Acts of the Diet), plus a few 太政官布告/達, 勅令 and 省令 that have the force of law | 2,102 |
| `cabinet-orders/` | 政令 (Cabinet Orders), plus 太政官布告/達 classified as 政令 by e-Gov | 2,328 |
| `imperial-ordinances/` | 勅令 (pre-1947 Imperial Ordinances still in force) | 66 |
| `ministerial-ordinances/` | 府省令 (Cabinet Office / ministerial ordinances, incl. joint ordinances) | 4,111 |
| `rules/` | 規則 (rules of the National Personnel Authority 人事院規則, commissions such as 国家公安委員会規則, the Diet, the courts, etc.) | 409 |
| **Total** | | **9,017** |

This is every law in e-Gov's law list (API v2 `/laws`, 9,578 entries) whose
`repeal_status` is `None`, i.e. not repealed, expired or lapsed. Of these, 14 are promulgated
but not yet in force (未施行); they are included with `status: unknown` and
`enforcement: "未施行"` in the front matter.

### Not covered

- **Repealed / expired / lapsed laws** (廃止・失効): 561 entries in the e-Gov list (418 廃止, 105
  失効, 38 期限切れ) are skipped. e-Gov does not offer a complete historical archive of repealed
  laws anyway.
- **Past versions and future amendments**: only the current version is converted. e-Gov also
  publishes versions with amendments scheduled to take effect later (施行日未到来); these are not
  included. Use git history of this repo to follow changes over time on refresh.
- **Figures, images and PDF forms** (図・様式 images, 別記様式 PDFs): the bulk XML archive
  references ~28,000 image/PDF files (photos of forms, diagrams, formulas, some amendment
  comparison tables). They are not included; each is replaced by a marker
  `［図：./pict/FILENAME］` giving the original file name. See the law's page on e-Gov
  (`source:` URL in the front matter) to view them.
- **Local ordinances** (条例・規則 of prefectures and municipalities), treaties (条約), notices
  (告示), circulars (通達) and court decisions are not part of e-Gov 法令検索 and are not included.

## Structure

```
constitution/321CONSTITUTION.md                      日本国憲法
laws/<year>/<LawId>.md                               e.g. laws/1896/129AC0000000089.md  民法
cabinet-orders/<year>/<LawId>.md                     e.g. cabinet-orders/1965/340CO0000000096.md  所得税法施行令
imperial-ordinances/<year>/<LawId>.md
ministerial-ordinances/<year>/<LawId>.md
rules/<year>/<LawId>.md
```

- `<year>` is the Gregorian year of promulgation (公布).
- `<LawId>` is the official e-Gov 法令ID, e.g. `129AC0000000089`
  = 明治29年 (era code 1 = 明治, 2 = 大正, 3 = 昭和, 4 = 平成, 5 = 令和, + 2-digit year),
  `AC` = 法律 (`CO` 政令, `IO` 勅令, `M…`/`R…` 府省令・規則 (`RJ` 人事院規則), `DF`/`DT` 太政官布告/達),
  then the issuing body / law number. The directory is chosen from e-Gov's `law_type`, not
  from the ID prefix. Filenames use the ID because titles are Japanese; the Japanese title is
  in the front matter and the H1.

### File format

```markdown
---
title: "民法"
identifier: "129AC0000000089"          # e-Gov 法令ID
law_number: "明治二十九年法律第八十九号"     # 法令番号
type: act                               # constitution | act | cabinet_order | imperial_ordinance | ministerial_ordinance | rule
jurisdiction: jp
language: ja
date: 1896-04-27                        # 公布日 (promulgation)
last_amended: 2026-06-24                # enforcement date of the consolidated version
status: in_force
title_kana: "みんぽう"
category: "民事"                         # e-Gov 分類
revision_id: "129AC0000000089_20260624_508AC0000000045"   # e-Gov 法令履歴ID
last_amendment_law: "令和八年法律第四十五号"
source: "https://laws.e-gov.go.jp/law/129AC0000000089"
retrieved: 2026-10-11
---

# 民法
```

Body mapping from the 法令標準XML:

| XML | 日本語 | Markdown |
| --- | --- | --- |
| `LawNum`, `EnactStatement`, `Preamble`, `TOC` | 法令番号・制定文・前文・目次 | paragraphs (目次 as nested list) |
| `Part` / `Chapter` / `Section` / `Subsection` / `Division` | 編 / 章 / 節 / 款 / 目 | headings, one level per actual nesting depth starting at `##` |
| `Article` | 条 (with 見出し, e.g. `第一条（基本原則）`) | heading one level below its parent; past `######` it becomes a **bold** line |
| `Paragraph` | 項 (`２　…`) | paragraph, with its official number |
| `Item`, `Subitem1…10` | 号 (一、二…), イ・ロ・ハ, (1)… | nested `-` lists, labels kept verbatim |
| `SupplProvision` | 附則 (one per amending law, with its 法令番号, `抄` if extract) | `##` heading |
| `AppdxTable`, `AppdxStyle`, `AppdxNote`, … | 別表・様式・別記 | `##` heading + content |
| `TableStruct` | 表 | Markdown table when simple, HTML `<table>` (with rowspan/colspan) otherwise |
| `AmendProvision` / `NewProvision` | 改正規定 | quoted (`>`) block |
| `Ruby`, `Sup`, `Sub` | ルビ・上付・下付 | `<ruby>`, `<sup>`, `<sub>` |

Text is verbatim, including full-width spaces (　) between labels and text, historical kana
usage and kanji numerals. Markdown-significant ASCII characters are backslash-escaped.

## Sources

- e-Gov 法令検索 bulk download (all current laws, XML only):
  https://laws.e-gov.go.jp/bulkdownload?file_section=1&only_xml_flag=true
- e-Gov 法令API Version 2 law list (metadata: type, 法令番号, dates, repeal status):
  https://laws.e-gov.go.jp/api/2/laws (documentation: https://laws.e-gov.go.jp/apitop/)
- Per-law fallback: https://laws.e-gov.go.jp/api/2/law_data/{law_revision_id}

## Copyright / licence

Under Article 13 of the Copyright Act of Japan (著作権法第十三条), the Constitution and other
laws and regulations (憲法その他の法令), as well as notices and instructions of State organs, are
**not subject to copyright** and may be freely reproduced. Source data: e-Gov 法令検索
(https://laws.e-gov.go.jp/), デジタル庁; see its terms of use for attribution of the database. This Markdown conversion is not an official publication; in case
of discrepancy, the official gazette (官報) prevails.

## Regenerating

```sh
python -m venv .venv && .venv/bin/pip install -r scripts/requirements.txt
.venv/bin/python scripts/fetch.py      # law list + bulk XML zip (~300 MB, ~3 GB extracted) into ../_raw/jp
.venv/bin/python scripts/convert.py    # writes constitution/ laws/ cabinet-orders/ ... into the repo
rm -rf ../_raw/jp                      # raw data is not committed
```

`fetch.py --force` re-downloads. `convert.py --only <LawId> …` or `--category laws` converts a
subset. A conversion report is written to `../_raw/jp/convert_report.json`. Laws missing from
the bulk archive are fetched individually from API v2 (cached; 1 request/second).

---

日本の現行法令（憲法・法律・政令・勅令・府省令・規則）を、e-Gov法令検索の法令標準XMLから
Markdownに変換したものです。本文は原文のまま（翻訳・要約なし）。図・様式の画像は含まれていません。
正確な内容は官報およびe-Gov法令検索で確認してください。
