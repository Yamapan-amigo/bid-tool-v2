"""ローカルWebサーバー — 入札情報の結果確認用

ブラウザで http://localhost:8080 にアクセスすると結果一覧を表示する。
行をクリックすると案件の詳細（公告全文）をモーダルで表示。
"""

from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler

from src.config import CATEGORY_GROUPS
from src.core.dedup import deduplicate
from src.core.filter import apply_filters
from src.core.matcher import match_past_results
from src.core.models import BidProject
from src.core.scorer import score_projects
from src.sources.etokyo import fetch_etokyo_projects
from src.sources.kkj import fetch_kkj_projects
from src.sources.pportal import fetch_award_results

logger = logging.getLogger(__name__)
_JST = timezone(timedelta(hours=9))

# テキスト整形用パターン
_SECTION_BREAK = re.compile(
    r"((?:^|\s)(?:\d+[．.]\s|（\d+）|\(\d+\)|[１２３４５６７８９０]+\s|[一二三四五六七八九十]+\s|記\s))"
)
_DATE_HIGHLIGHT = re.compile(r"(令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日)")
_PRICE_HIGHLIGHT = re.compile(r"([\d,]+\s*円)")


def _extract_summary(text: str, title: str, cache_only: bool = False) -> str:
    """公告テキストをGemini Flashで要約する（cache_only=True でキャッシュのみ使用）"""
    from src.core.summarizer import summarize_description

    summary = summarize_description(text, title, cache_only=cache_only)
    if not summary:
        return ""
    escaped = html.escape(summary)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return escaped.replace("\n", "<br>")


def _format_description(text: str) -> str:
    """公告テキストを読みやすいHTMLに整形する"""
    if not text:
        return ""
    escaped = html.escape(text)

    # セクション番号の前に改行を挿入
    escaped = re.sub(
        r"((?:\d+[．.]\s|（\d+）|\(\d+\)|[１２３４５６７８９]+\s))",
        r"<br><br>\1",
        escaped,
    )
    # 「記」の前後に改行
    escaped = re.sub(r"(\s記\s)", r"<br><br><strong>\1</strong><br>", escaped)

    # 日付をハイライト
    escaped = re.sub(
        r"(令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日)",
        r'<span style="background:#fff3cd;padding:0 2px;border-radius:2px">\1</span>',
        escaped,
    )
    # 金額をハイライト
    escaped = re.sub(
        r"([\d,]+\s*円)",
        r'<span style="color:#d32f2f;font-weight:600">\1</span>',
        escaped,
    )

    return escaped


def _collect_data() -> tuple[list[BidProject], int, int, int]:
    """パイプラインを実行してデータを収集する"""
    all_projects: list[BidProject] = []

    # 官公需API（国の機関）
    try:
        kkj = fetch_kkj_projects()
        all_projects.extend(kkj)
        logger.info("官公需: %d件", len(kkj))
    except Exception as e:
        logger.warning("官公需APIエラー: %s", e)

    # e-Tokyo（東京23区+市部）
    try:
        etokyo = fetch_etokyo_projects()
        all_projects.extend(etokyo)
        logger.info("e-Tokyo: %d件", len(etokyo))
    except Exception as e:
        logger.warning("e-Tokyoエラー: %s", e)

    filtered = apply_filters(all_projects)
    unique = deduplicate(filtered)

    awards = fetch_award_results()
    matched = match_past_results(unique, awards)
    matched_count = sum(1 for p in matched if p.past_award_price is not None)

    scored = score_projects(matched)
    scored.sort(key=lambda p: p.score, reverse=True)

    return scored, len(all_projects), len(awards), matched_count


def _today_jst_date() -> datetime.date:
    """JST基準の本日日付を返す"""
    return datetime.now(_JST).date()


def _render_html(
    projects: list[BidProject],
    raw_count: int,
    award_count: int,
    matched_count: int,
) -> str:
    """結果をHTMLに変換する"""
    today = _today_jst_date()
    rows_html = ""
    for i, p in enumerate(projects, 1):
        score_class = ""
        score_label = ""
        if p.score >= 4.5:
            score_class = "score-high"
            score_label = "&#9733;&#9733;&#9733;"
        elif p.score >= 3.5:
            score_class = "score-mid"
            score_label = "&#9733;&#9733;"
        elif p.score >= 2.5:
            score_class = "score-low"
            score_label = "&#9733;"
        else:
            score_class = "score-low"
            score_label = "-"

        deadline_display = p.deadline or "要確認"

        # 締切日までの残日数に応じたクラス
        deadline_class = ""
        deadline_date = None
        if p.deadline:
            try:
                deadline_date = datetime.strptime(p.deadline, "%Y-%m-%d").date()
            except ValueError:
                deadline_date = None
            if deadline_date and deadline_date >= today:
                days_left = (deadline_date - today).days
                if days_left <= 3:
                    deadline_class = "deadline-urgent"
                elif days_left <= 7:
                    deadline_class = "deadline-warn"

        # 残日数バッジ
        if deadline_date and deadline_date >= today:
            dl = (deadline_date - today).days
            if dl <= 3:
                days_html = f'<span class="days-urgent">残{dl}日</span>'
            elif dl <= 7:
                days_html = f'<span class="days-warn">残{dl}日</span>'
            elif dl <= 30:
                days_html = f'<span class="days-ok">残{dl}日</span>'
            else:
                days_html = f'<span class="days-far">残{dl}日</span>'
        else:
            days_html = '<span class="days-unknown">-</span>'

        # 提出方法ピル
        method_raw = p.eligibility_method or ""
        pills: list[str] = []
        if "電子" in method_raw:
            pills.append('<span class="pill-denshi">電子</span>')
        if "郵便" in method_raw:
            pills.append('<span class="pill-yubin">郵便</span>')
        if "持参" in method_raw:
            pills.append('<span class="pill-jisan">持参</span>')
        method_pill = "".join(pills) if pills else '<span class="pill-unknown">不明</span>'

        # data-deadline (空はソートで末尾に回す)
        deadline_sort = p.deadline if p.deadline else "9999-99-99"

        # 公告日から3日以内なら新着バッジ
        new_badge = ""
        if p.publish_date:
            try:
                publish_date = datetime.strptime(p.publish_date, "%Y-%m-%d").date()
            except ValueError:
                publish_date = None
            if publish_date:
                days_since = (today - publish_date).days
                if 0 <= days_since <= 3:
                    new_badge = ' <span class="badge-new">NEW</span>'

        elig_class = "elig-ok" if p.eligibility_overall == "◎" else "elig-check" if p.eligibility_overall == "○" else "elig-ng"
        tr_class = ' class="row-ng"' if p.eligibility_overall == "×" else ""

        rows_html += f"""
        <tr onclick="showDetail({i - 1})" style="cursor:pointer"{tr_class}
            data-bid-type="{html.escape(p.bid_type)}"
            data-score="{p.score}"
            data-elig="{p.eligibility_overall}"
            data-category="{html.escape(p.category)}"
            data-org="{html.escape(p.organization)}"
            data-deadline="{deadline_sort}">
          <td class="row-num" data-label="#">{i}</td>
          <td class="{elig_class}" data-label="可否">{p.eligibility_overall}</td>
          <td class="title" data-label="案件名">{html.escape(p.title)}{new_badge}</td>
          <td data-label="発注元">{html.escape(p.organization)}</td>
          <td data-label="残日数">{days_html}</td>
          <td data-label="提出方法">{method_pill}</td>
          <td data-label="分類">{html.escape(p.category)}</td>
          <td data-label="入札方式">{html.escape(p.bid_type)}</td>
          <td class="{deadline_class}" data-label="締切日">{deadline_display}</td>
          <td class="{score_class}" data-label="おすすめ">{score_label}</td>
        </tr>"""

    count_ok = sum(1 for p in projects if p.eligibility_overall == "◎")
    count_check = sum(1 for p in projects if p.eligibility_overall == "○")
    count_ng = sum(1 for p in projects if p.eligibility_overall == "×")
    count_urgent = 0
    for p in projects:
        if p.eligibility_overall == "×" or not p.deadline:
            continue
        try:
            d = datetime.strptime(p.deadline, "%Y-%m-%d").date()
            if (d - today).days <= 7:
                count_urgent += 1
        except ValueError:
            pass

    # フィルタ選択肢: 入札方式
    bid_types = sorted({p.bid_type for p in projects})
    bid_type_options = "".join(
        f'<option value="{html.escape(bt)}">{html.escape(bt)}</option>'
        for bt in bid_types
    )

    # フィルタ選択肢: 分類（グループ + 個別カテゴリのoptgroup構造）
    categories = sorted({p.category for p in projects})
    group_options = "".join(
        f'<option value="group:{html.escape(k)}">&#9733; {html.escape(k)}</option>'
        for k in CATEGORY_GROUPS
    )
    individual_options = "".join(
        f'<option value="{html.escape(c)}">{html.escape(c)}</option>'
        for c in categories
    )
    category_options = (
        f'<optgroup label="まとめて選択">{group_options}</optgroup>'
        f'<optgroup label="個別カテゴリ">{individual_options}</optgroup>'
    )
    groups_json = json.dumps(CATEGORY_GROUPS, ensure_ascii=False).replace("</", "<\\/")

    # 詳細データをJSONとして埋め込む（説明文は500文字に切り詰めてHTML肥大化を防ぐ）
    _DESC_MAX = 500
    details_data = []
    for p in projects:
        desc = _format_description(p.description[:_DESC_MAX]) if p.description else ""

        link_url = p.detail_url

        details_data.append(
            {
                "title": p.title,
                "org": p.organization,
                "bid_type": p.bid_type,
                "publish_date": p.publish_date,
                "deadline": p.deadline,
                "detail_url": link_url,
                "spec_url": p.spec_url,
                "source": p.source,
                "score": p.score,
                "summary": _extract_summary(p.description, p.title, cache_only=True),
                "description": desc,
                "past_price": (
                    f"{p.past_award_price:,}円" if p.past_award_price else ""
                ),
                "past_winner": p.past_award_winner,
                "similar_awards": [
                    {
                        "title": t,
                        "price": f"{pr:,}円",
                        "winner": w,
                    }
                    for t, pr, w in p.similar_awards
                ],
                "elig_overall": p.eligibility_overall,
                "elig_grade": p.eligibility_grade,
                "elig_region": p.eligibility_region,
                "elig_method": p.eligibility_method,
                "elig_contact": p.eligibility_contact,
            }
        )
    # </script> が JSON内に現れるとscriptタグが早期終了するため \/ にエスケープ
    # ensure_ascii=False で日本語を\uXXXXに変換せずサイズを抑える
    details_json = json.dumps(details_data, ensure_ascii=False).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data: https:;">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>入札情報収集 for おーしまたん</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, 'Hiragino Sans', 'Yu Gothic', sans-serif; background: #f5f7fa; color: #333; }}

  .header {{ background: linear-gradient(135deg, #1a73e8, #0d47a1); color: #fff; padding: 24px 32px; }}
  .header h1 {{ font-size: 22px; font-weight: 600; }}
  .header p {{ font-size: 13px; opacity: 0.85; margin-top: 4px; }}

  .stats {{ display: flex; gap: 16px; padding: 20px 32px; background: #fff; border-bottom: 1px solid #e0e0e0; flex-wrap: wrap; }}
  .stat-card {{ background: #f8f9fa; border-radius: 8px; padding: 14px 20px; min-width: 130px; }}
  .stat-card .number {{ font-size: 28px; font-weight: 700; color: #1a73e8; }}
  .stat-card .label {{ font-size: 12px; color: #666; margin-top: 2px; }}

  .container {{ padding: 20px 32px; }}
  .filters {{ display: flex; gap: 12px; align-items: flex-end; margin-bottom: 16px; flex-wrap: wrap; }}
  .filter-group {{ display: flex; flex-direction: column; gap: 4px; }}
  .filter-group label {{ font-size: 11px; color: #666; font-weight: 600; }}
  .filter-group select, .filter-group input {{ padding: 6px 10px; border: 1px solid #ddd; border-radius: 6px; font-size: 13px; background: #fff; }}
  .filter-group input {{ width: 200px; }}
  .filter-reset {{ padding: 6px 14px; border: 1px solid #ddd; border-radius: 6px; background: #fff; font-size: 13px; cursor: pointer; align-self: flex-end; }}
  .filter-reset:hover {{ background: #f0f0f0; }}
  .elig-ok {{ text-align: center; font-weight: 700; color: #2e7d32; font-size: 16px; }}
  .elig-check {{ text-align: center; font-weight: 600; color: #f57f17; font-size: 16px; }}
  .elig-ng {{ text-align: center; color: #bbb; font-size: 16px; }}
  .row-ng {{ opacity: 0.5; }}
  .hint {{ font-size: 12px; color: #888; margin-bottom: 12px; }}

  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  th {{ background: #1a73e8; color: #fff; padding: 12px 10px; font-size: 12px; font-weight: 600; text-align: left; white-space: nowrap; position: sticky; top: 0; }}
  th.sortable {{ cursor: pointer; user-select: none; }}
  th.sortable:hover {{ background: #1557b0; }}
  th.sortable::after {{ content: ' ⇅'; opacity: 0.6; font-size: 10px; }}
  td {{ padding: 10px; font-size: 13px; border-bottom: 1px solid #eee; }}
  tr:hover {{ background: #e3f2fd; }}
  .title {{ max-width: 320px; }}
  .has-price {{ color: #d32f2f; font-weight: 600; }}
  .score-high {{ background: #e8f5e9; color: #2e7d32; font-weight: 700; text-align: center; border-radius: 4px; }}
  .score-mid {{ background: #fff8e1; color: #f57f17; font-weight: 600; text-align: center; border-radius: 4px; }}
  .score-low {{ color: #999; text-align: center; }}
  .deadline-urgent {{ color: #d32f2f; font-weight: 700; }}
  .deadline-warn {{ color: #e65100; font-weight: 600; }}
  .badge-new {{ display: inline-block; background: #1a73e8; color: #fff; font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 3px; margin-left: 6px; vertical-align: middle; letter-spacing: 0.5px; }}

  /* === 残日数バッジ === */
  .days-urgent {{ display: inline-block; background: #d32f2f; color: #fff; font-size: 11px; font-weight: 700; padding: 2px 6px; border-radius: 4px; white-space: nowrap; }}
  .days-warn {{ display: inline-block; background: #e65100; color: #fff; font-size: 11px; font-weight: 600; padding: 2px 6px; border-radius: 4px; white-space: nowrap; }}
  .days-ok {{ display: inline-block; color: #555; font-size: 12px; white-space: nowrap; }}
  .days-far {{ display: inline-block; color: #aaa; font-size: 12px; white-space: nowrap; }}
  .days-unknown {{ display: inline-block; color: #ccc; font-size: 11px; }}

  /* === 提出方法ピル === */
  .pill-denshi {{ display: inline-block; background: #1565c0; color: #fff; font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 10px; white-space: nowrap; }}
  .pill-yubin {{ display: inline-block; background: #2e7d32; color: #fff; font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 10px; white-space: nowrap; }}
  .pill-jisan {{ display: inline-block; background: #6a1b9a; color: #fff; font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 10px; white-space: nowrap; }}
  .pill-unknown {{ display: inline-block; background: #bbb; color: #fff; font-size: 10px; padding: 2px 6px; border-radius: 10px; white-space: nowrap; }}

  /* === statsカード色 === */
  .stat-ok .number {{ color: #2e7d32 !important; }}
  .stat-check .number {{ color: #f57f17 !important; }}
  .stat-urgent .number {{ color: #d32f2f !important; }}
  .stat-ng .number {{ color: #bbb !important; font-size: 20px !important; }}

  /* === ヒーロー: 今すぐ応募可を大型表示 === */
  .hero-go-card {{ border: 2px solid #2e7d32 !important; background: #f1f8f1 !important; }}
  .hero-go-number {{ font-size: 52px !important; font-weight: 800 !important; line-height: 1 !important; }}

  /* === モーダル === */
  .overlay {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 100; }}
  .overlay.active {{ display: flex; justify-content: center; align-items: flex-start; padding-top: 40px; }}
  .modal {{ background: #fff; border-radius: 12px; width: 90%; max-width: 800px; max-height: 85vh; overflow-y: auto; box-shadow: 0 8px 32px rgba(0,0,0,0.2); }}
  .modal-header {{ background: #1a73e8; color: #fff; padding: 20px 24px; border-radius: 12px 12px 0 0; position: relative; }}
  .modal-header h2 {{ font-size: 16px; font-weight: 600; line-height: 1.5; padding-right: 40px; }}
  .modal-close {{ position: absolute; top: 16px; right: 20px; background: none; border: none; color: #fff; font-size: 24px; cursor: pointer; opacity: 0.8; }}
  .modal-close:hover {{ opacity: 1; }}

  .modal-body {{ padding: 24px; }}
  .detail-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }}
  .detail-item {{ }}
  .detail-item .label {{ font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }}
  .detail-item .value {{ font-size: 14px; font-weight: 500; }}
  .detail-item .value.price {{ color: #d32f2f; font-size: 18px; font-weight: 700; }}

  .desc-section {{ margin-top: 20px; border-top: 1px solid #eee; padding-top: 20px; }}
  .desc-section h3 {{ font-size: 14px; font-weight: 600; margin-bottom: 12px; color: #1a73e8; }}
  .desc-text {{ font-size: 13px; line-height: 1.8; color: #444; white-space: pre-wrap; word-break: break-all; max-height: 400px; overflow-y: auto; background: #fafafa; padding: 16px; border-radius: 8px; border: 1px solid #eee; }}
  .no-desc {{ color: #aaa; font-style: italic; }}

  .external-link {{ display: inline-block; margin-top: 16px; padding: 10px 20px; background: #1a73e8; color: #fff; border-radius: 6px; text-decoration: none; font-size: 13px; font-weight: 500; }}
  .external-link:hover {{ background: #1557b0; text-decoration: none; }}

  .footer {{ text-align: center; padding: 20px; font-size: 12px; color: #999; }}
  a {{ color: #1a73e8; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}

  /* === モバイル対応 (スマホ: 768px以下) === */
  @media (max-width: 768px) {{
    .header {{ padding: 16px 16px; }}
    .header h1 {{ font-size: 18px; }}
    .header p {{ font-size: 11px; }}

    .stats {{ padding: 12px 16px; gap: 8px; }}
    .stat-card {{ min-width: 0; flex: 1 1 calc(50% - 4px); padding: 10px 12px; }}
    .stat-card .number {{ font-size: 22px; }}
    .stat-card .label {{ font-size: 11px; }}

    .container {{ padding: 12px 12px; }}
    .filters {{ gap: 8px; margin-bottom: 12px; }}
    .filter-group {{ flex: 1 1 calc(50% - 4px); min-width: 0; }}
    .filter-group select, .filter-group input {{ width: 100%; font-size: 14px; padding: 8px 10px; }}
    .filter-reset {{ width: 100%; padding: 10px; font-size: 14px; }}
    .hint {{ font-size: 11px; }}

    /* テーブルをカード形式に変換 */
    table, thead, tbody, th, td, tr {{ display: block; }}
    thead {{ position: absolute; top: -9999px; left: -9999px; }}
    table {{ box-shadow: none; background: transparent; border-radius: 0; }}
    tr {{
      background: #fff;
      border-radius: 8px;
      margin-bottom: 10px;
      padding: 12px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
      border-bottom: none;
    }}
    tr:hover {{ background: #fff; }}
    td {{
      border: none;
      padding: 4px 0;
      font-size: 13px;
      position: relative;
      padding-left: 78px;
      min-height: 22px;
      white-space: normal;
      word-break: break-word;
    }}
    td::before {{
      content: attr(data-label);
      position: absolute;
      left: 0;
      top: 4px;
      width: 70px;
      font-size: 11px;
      color: #888;
      font-weight: 600;
    }}
    td.row-num {{
      padding-left: 0;
      font-weight: 700;
      color: #1a73e8;
      font-size: 12px;
      margin-bottom: 4px;
    }}
    td.row-num::before {{ content: "#"; position: static; width: auto; color: #1a73e8; margin-right: 4px; }}
    td.title {{ max-width: none; font-weight: 600; font-size: 14px; padding: 6px 0; }}
    td.title::before {{ display: none; }}

    /* モーダル */
    .overlay.active {{ padding-top: 0; align-items: stretch; }}
    .modal {{ width: 100%; max-width: 100%; max-height: 100vh; border-radius: 0; }}
    .modal-header {{ padding: 16px; border-radius: 0; position: sticky; top: 0; z-index: 10; }}
    .modal-header h2 {{ font-size: 15px; padding-right: 36px; }}
    .modal-close {{ top: 12px; right: 14px; font-size: 28px; padding: 4px 8px; }}
    .modal-body {{ padding: 16px; }}
    .detail-grid {{ grid-template-columns: 1fr; gap: 10px; }}
    .detail-item .value {{ font-size: 13px; }}
    .detail-item .value.price {{ font-size: 16px; }}
    .desc-section h3 {{ font-size: 13px; }}
    .desc-text {{ font-size: 12px; padding: 12px; max-height: 300px; }}
    .external-link {{ display: block; text-align: center; margin-top: 12px; margin-left: 0 !important; padding: 12px; font-size: 14px; }}
  }}

  /* 極小画面 (iPhone SE等: 380px以下) */
  @media (max-width: 380px) {{
    .stat-card {{ flex: 1 1 100%; }}
    .filter-group {{ flex: 1 1 100%; }}
    .header h1 {{ font-size: 16px; }}
  }}
</style>
</head>
<body>
  <div class="header">
    <h1>入札情報収集 for おーしまたん</h1>
    <p>国の機関 + 関東1都6県 ｜ 印刷・製本関連 ｜ 官公需API + e-Tokyoから自動抽出</p>
  </div>

  <div class="stats">
    <div class="stat-card stat-ok hero-go-card">
      <div class="number hero-go-number">{count_ok}</div>
      <div class="label">◎ 今すぐ応募可</div>
    </div>
    <div class="stat-card stat-check">
      <div class="number">{count_check}</div>
      <div class="label">○ 要確認</div>
    </div>
    <div class="stat-card stat-urgent">
      <div class="number">{count_urgent}</div>
      <div class="label">今週締切（7日以内）</div>
    </div>
    <div class="stat-card stat-ng">
      <div class="number">{count_ng}</div>
      <div class="label">× NG（除外済み）</div>
    </div>
    <div class="stat-card">
      <div class="number" id="filtered-count">{count_ok + count_check}</div>
      <div class="label">表示中</div>
    </div>
  </div>

  <div class="container">
    <div class="filters">
      <div class="filter-group">
        <label>参加可否</label>
        <select id="filter-elig" onchange="applyFilters()">
          <option value="◎">◎ 確定のみ（推奨）</option>
          <option value="◎○">◎○ 参加可能のみ</option>
          <option value="">すべて（×含む）</option>
        </select>
      </div>
      <div class="filter-group">
        <label>分類</label>
        <select id="filter-category" onchange="applyFilters()">
          <option value="">すべて</option>
          {category_options}
        </select>
      </div>
      <div class="filter-group">
        <label>入札方式</label>
        <select id="filter-bid-type" onchange="applyFilters()">
          <option value="">すべて</option>
          {bid_type_options}
        </select>
      </div>
      <div class="filter-group">
        <label>おすすめ度</label>
        <select id="filter-score" onchange="applyFilters()">
          <option value="" selected>すべて</option>
          <option value="4.5">&#9733;&#9733;&#9733; のみ</option>
          <option value="3.5">&#9733;&#9733; 以上</option>
        </select>
      </div>
      <div class="filter-group">
        <label>キーワード</label>
        <input type="text" id="filter-keyword" placeholder="案件名・発注元で検索" oninput="applyFilters()">
      </div>
      <button class="filter-reset" onclick="resetFilters()">リセット</button>
    </div>
    <p class="hint">行をクリックすると詳細を表示 ｜ ◎ 参加可能 ／ ○ 要確認 ／ × 参加不可（等級・地域NG）</p>
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>可否</th>
          <th>案件名</th>
          <th>発注元</th>
          <th class="sortable" onclick="sortBy('deadline')">残日数</th>
          <th>提出方法</th>
          <th class="sortable" onclick="sortBy('category')">分類</th>
          <th>入札方式</th>
          <th>締切日</th>
          <th>おすすめ度</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </div>

  <!-- 詳細モーダル -->
  <div class="overlay" id="overlay" onclick="closeDetail(event)">
    <div class="modal" onclick="event.stopPropagation()">
      <div class="modal-header">
        <h2 id="modal-title"></h2>
        <button class="modal-close" onclick="document.getElementById('overlay').classList.remove('active')">&times;</button>
      </div>
      <div class="modal-body">
        <div class="detail-grid">
          <div class="detail-item">
            <div class="label">発注元</div>
            <div class="value" id="modal-org"></div>
          </div>
          <div class="detail-item">
            <div class="label">入札方式</div>
            <div class="value" id="modal-bid-type"></div>
          </div>
          <div class="detail-item">
            <div class="label">公告日</div>
            <div class="value" id="modal-pub-date"></div>
          </div>
          <div class="detail-item">
            <div class="label">締切日</div>
            <div class="value" id="modal-deadline"></div>
          </div>
          <div class="detail-item">
            <div class="label">過去落札金額</div>
            <div class="value price" id="modal-past-price"></div>
          </div>
          <div class="detail-item">
            <div class="label">過去落札者</div>
            <div class="value" id="modal-past-winner"></div>
          </div>
          <div class="detail-item">
            <div class="label">データソース</div>
            <div class="value" id="modal-source"></div>
          </div>
          <div class="detail-item">
            <div class="label">おすすめ度</div>
            <div class="value" id="modal-score"></div>
          </div>
        </div>

        <div class="desc-section">
          <h3>概要</h3>
          <div id="modal-summary" style="font-size:14px;line-height:2;padding:12px 0"></div>
        </div>

        <div class="desc-section">
          <h3>応募条件</h3>
          <div class="detail-grid">
            <div class="detail-item">
              <div class="label">参加可否</div>
              <div class="value" id="modal-elig-overall" style="font-size:20px"></div>
            </div>
            <div class="detail-item">
              <div class="label">等級要件</div>
              <div class="value" id="modal-elig-grade"></div>
            </div>
            <div class="detail-item">
              <div class="label">地域要件</div>
              <div class="value" id="modal-elig-region"></div>
            </div>
            <div class="detail-item">
              <div class="label">提出方法</div>
              <div class="value" id="modal-elig-method"></div>
            </div>
          </div>
          <div id="modal-elig-contact" style="font-size:12px;color:#666;margin-top:8px"></div>
        </div>

        <div class="desc-section" id="similar-section" style="display:none">
          <h3>参考: 類似案件の過去落札実績</h3>
          <table style="width:100%;font-size:13px;border-collapse:collapse">
            <thead><tr style="background:#f0f0f0">
              <th style="padding:8px;text-align:left">案件名</th>
              <th style="padding:8px;text-align:right;white-space:nowrap">落札金額</th>
              <th style="padding:8px;text-align:left">落札者</th>
            </tr></thead>
            <tbody id="similar-body"></tbody>
          </table>
        </div>

        <details class="desc-section" style="margin-top:20px;border-top:1px solid #eee;padding-top:20px">
          <summary style="cursor:pointer;color:#1a73e8;font-size:14px;font-weight:600">公告全文を表示</summary>
          <div class="desc-text" id="modal-desc" style="margin-top:12px"></div>
        </details>

        <a class="external-link" id="modal-link" href="#" target="_blank">
          元サイトで公告を見る &rarr;
        </a>
        <a class="external-link" id="modal-spec-link" href="#" target="_blank" style="display:none;background:#2e7d32;margin-left:8px">
          仕様書を見る &rarr;
        </a>
        <p id="modal-spec-note" style="display:none;font-size:12px;color:#888;margin-top:10px">
          ※ 仕様書は電子入札システムまたは調達ポータルから取得してください
        </p>
      </div>
    </div>
  </div>

  <div class="footer">
    最終更新: {datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M')} (JST) ｜ データソース: 官公需API + e-Tokyo + 調達ポータル
  </div>

<script>
const details = {details_json};
const CATEGORY_GROUPS = {groups_json};

function showDetail(idx) {{
  const d = details[idx];
  document.getElementById('modal-title').textContent = d.title;
  document.getElementById('modal-org').textContent = d.org;
  document.getElementById('modal-bid-type').textContent = d.bid_type;
  document.getElementById('modal-pub-date').textContent = d.publish_date || '-';
  document.getElementById('modal-deadline').textContent = d.deadline || '-';
  document.getElementById('modal-past-price').innerHTML = d.past_price || '-';
  document.getElementById('modal-past-winner').textContent = d.past_winner || '-';
  document.getElementById('modal-source').textContent = d.source;
  const stars = d.score >= 4.5 ? '\u2733\u2733\u2733' : d.score >= 3.5 ? '\u2733\u2733' : d.score >= 2.5 ? '\u2733' : '-';
  document.getElementById('modal-score').textContent = stars;

  // 応募条件
  const eligEl = document.getElementById('modal-elig-overall');
  eligEl.textContent = d.elig_overall || '○';
  eligEl.style.color = d.elig_overall === '◎' ? '#2e7d32' : d.elig_overall === '×' ? '#d32f2f' : '#f57f17';
  document.getElementById('modal-elig-grade').textContent = d.elig_grade || '不明';
  document.getElementById('modal-elig-region').textContent = d.elig_region || '不明';
  document.getElementById('modal-elig-method').textContent = d.elig_method || '不明';
  document.getElementById('modal-elig-contact').textContent = d.elig_contact || '';

  // 概要（キャッシュあり → 即表示、なし → 生成ボタン）
  const summaryEl = document.getElementById('modal-summary');
  if (d.summary) {{
    summaryEl.innerHTML = d.summary;
  }} else {{
    summaryEl.innerHTML = '<button onclick="loadSummary(' + idx + ')" style="padding:8px 16px;background:#1a73e8;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:13px">AI要約を生成</button>';
  }}

  // 全文（折りたたみ）
  const descEl = document.getElementById('modal-desc');
  if (d.description) {{
    descEl.innerHTML = d.description;
    descEl.classList.remove('no-desc');
  }} else {{
    descEl.textContent = '公告全文はこのデータソースでは取得できませんでした。';
    descEl.classList.add('no-desc');
  }}

  // 類似案件表示
  const esc = t => t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const simSection = document.getElementById('similar-section');
  const simBody = document.getElementById('similar-body');
  if (d.similar_awards && d.similar_awards.length > 0) {{
    simBody.innerHTML = d.similar_awards.map(s =>
      '<tr>' +
      '<td style="padding:6px 8px;border-bottom:1px solid #eee">' + esc(s.title.substring(0, 50)) + '</td>' +
      '<td style="padding:6px 8px;border-bottom:1px solid #eee;text-align:right;color:#d32f2f;font-weight:600;white-space:nowrap">' + esc(s.price) + '</td>' +
      '<td style="padding:6px 8px;border-bottom:1px solid #eee">' + esc(s.winner.substring(0, 20)) + '</td>' +
      '</tr>'
    ).join('');
    simSection.style.display = 'block';
  }} else {{
    simSection.style.display = 'none';
  }}

  const linkEl = document.getElementById('modal-link');
  const safeUrl = d.detail_url && (d.detail_url.startsWith('https://') || d.detail_url.startsWith('http://')) ? d.detail_url : '';
  linkEl.href = safeUrl || '#';
  linkEl.textContent = '元サイトで公告を見る →';
  linkEl.style.display = safeUrl ? 'inline-block' : 'none';

  const specEl = document.getElementById('modal-spec-link');
  const specNote = document.getElementById('modal-spec-note');
  const safeSpec = d.spec_url && (d.spec_url.startsWith('https://') || d.spec_url.startsWith('http://')) ? d.spec_url : '';
  specEl.href = safeSpec || '#';
  specEl.textContent = '仕様書を見る →';
  specEl.style.display = safeSpec ? 'inline-block' : 'none';
  specNote.style.display = safeSpec ? 'none' : 'block';

  document.getElementById('overlay').classList.add('active');
}}

function closeDetail(e) {{
  if (e.target === document.getElementById('overlay')) {{
    document.getElementById('overlay').classList.remove('active');
  }}
}}

document.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape') {{
    document.getElementById('overlay').classList.remove('active');
  }}
}});

function applyFilters() {{
  const eligFilter = document.getElementById('filter-elig').value;
  const bidType = document.getElementById('filter-bid-type').value;
  const categoryRaw = document.getElementById('filter-category').value;
  const minScore = parseFloat(document.getElementById('filter-score').value) || 0;
  const keyword = document.getElementById('filter-keyword').value.toLowerCase();

  // グループ選択（group:プレフィクス）と個別選択を区別
  let catOk;
  if (!categoryRaw) {{
    catOk = () => true;
  }} else if (categoryRaw.startsWith('group:')) {{
    const allowed = new Set(CATEGORY_GROUPS[categoryRaw.slice(6)] || []);
    catOk = (rc) => allowed.has(rc);
  }} else {{
    catOk = (rc) => rc === categoryRaw;
  }}

  const rows = document.querySelectorAll('tbody tr');
  let visible = 0;
  let num = 1;
  rows.forEach(row => {{
    const rElig = row.getAttribute('data-elig') || '';
    const rBid = row.getAttribute('data-bid-type') || '';
    const rCategory = row.getAttribute('data-category') || '';
    const rScore = parseFloat(row.getAttribute('data-score')) || 0;
    const rText = row.textContent.toLowerCase();
    const eligOk = !eligFilter || (eligFilter === '◎' ? rElig === '◎' : rElig !== '×');
    const show = eligOk
      && (!bidType || rBid === bidType)
      && catOk(rCategory)
      && rScore >= minScore
      && (!keyword || rText.includes(keyword));
    row.style.display = show ? '' : 'none';
    if (show) {{
      row.querySelector('.row-num').textContent = num++;
      visible++;
    }}
  }});
  document.getElementById('filtered-count').textContent = visible;
}}

function resetFilters() {{
  document.getElementById('filter-elig').value = '◎';
  document.getElementById('filter-bid-type').value = '';
  document.getElementById('filter-category').value = 'group:印刷業種すべて';
  document.getElementById('filter-score').value = '';
  document.getElementById('filter-keyword').value = '';
  sortBy('score'); sortBy('score');  // スコア降順に戻す
}}

function loadSummary(idx) {{
  const summaryEl = document.getElementById('modal-summary');
  summaryEl.innerHTML = '<span style="color:#888;font-size:13px">AI要約を生成中...</span>';
  fetch('/api/summary?idx=' + idx)
    .then(r => r.json())
    .then(data => {{
      details[idx].summary = data.summary;
      summaryEl.innerHTML = data.summary || '<span style="color:#aaa">要約を生成できませんでした</span>';
    }})
    .catch(() => {{
      summaryEl.innerHTML = '<span style="color:#d32f2f">要約の取得に失敗しました</span>';
    }});
}}

let _sortAsc = {{}};
function sortBy(key) {{
  const tbody = document.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const asc = !_sortAsc[key];
  _sortAsc = {{}};
  _sortAsc[key] = asc;
  const attr = 'data-' + key;
  rows.sort((a, b) => {{
    const va = a.getAttribute(attr) || '';
    const vb = b.getAttribute(attr) || '';
    return asc ? va.localeCompare(vb, 'ja') : vb.localeCompare(va, 'ja');
  }});
  rows.forEach(r => tbody.appendChild(r));
  applyFilters();
}}

// 初期表示: ◎のみ + 印刷業種すべて + スコア降順（大島さん向けデフォルト）
document.addEventListener('DOMContentLoaded', function() {{
  document.getElementById('filter-elig').value = '◎';
  document.getElementById('filter-category').value = 'group:印刷業種すべて';
  sortBy('score');  // 1回目: 昇順
  sortBy('score');  // 2回目: 降順（高スコア上位から）
}});
</script>
</body>
</html>"""


class Handler(SimpleHTTPRequestHandler):
    html_content: str = ""
    projects: list[BidProject] = []

    def do_GET(self) -> None:
        if self.path.startswith("/api/summary"):
            self._handle_summary()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(self.html_content.encode("utf-8"))

    def _handle_summary(self) -> None:
        from urllib.parse import parse_qs, urlparse

        params = parse_qs(urlparse(self.path).query)
        try:
            idx = int(params.get("idx", [-1])[0])
        except (ValueError, IndexError):
            idx = -1

        if idx < 0 or idx >= len(Handler.projects):
            self.send_response(404)
            self.end_headers()
            return

        p = Handler.projects[idx]
        summary_html = _extract_summary(p.description, p.title, cache_only=False)
        body = json.dumps({"summary": summary_html}, ensure_ascii=True).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


_NOTIFIED_IDS_PATH = ".github/state/notified_ids.json"


def _load_notified_ids() -> set[str]:
    import json
    from pathlib import Path

    path = Path(_NOTIFIED_IDS_PATH)
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_notified_ids(ids: set[str]) -> None:
    import json
    from pathlib import Path

    path = Path(_NOTIFIED_IDS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(ids), ensure_ascii=False, indent=2), encoding="utf-8")


def generate(output_path: str = "docs/index.html") -> str:
    """静的HTMLファイルを生成する（GitHub Pages用）"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    logger.info("データ取得中...")
    projects, raw_count, award_count, matched_count = _collect_data()
    logger.info("完了: %d件の案件を取得", len(projects))

    html_content = _render_html(projects, raw_count, award_count, matched_count)

    from pathlib import Path

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_content, encoding="utf-8")
    logger.info("HTMLを出力: %s", output_path)

    # LINE通知: 前回通知済み以外の案件を送信
    notified = _load_notified_ids()
    new_projects = [p for p in projects if p.dedup_key not in notified]
    if new_projects:
        from src.core.notifier import notify_new_projects
        notify_new_projects(new_projects)
    notified.update(p.dedup_key for p in projects)
    _save_notified_ids(notified)

    return output_path


def serve(port: int = 8080) -> None:
    """ローカル開発サーバー"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    logger.info("データ取得中...")
    projects, raw_count, award_count, matched_count = _collect_data()
    logger.info("完了: %d件の案件を取得", len(projects))

    Handler.html_content = _render_html(projects, raw_count, award_count, matched_count)
    Handler.projects = projects

    server = HTTPServer(("localhost", port), Handler)
    logger.info("ブラウザで確認: http://localhost:%d", port)
    logger.info("停止: Ctrl+C")
    server.serve_forever()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--generate":
        output = sys.argv[2] if len(sys.argv) > 2 else "docs/index.html"
        generate(output)
    else:
        serve()
