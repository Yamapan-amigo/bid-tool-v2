"""ローカルWebサーバー — 入札情報の結果確認用

ブラウザで http://localhost:8080 にアクセスすると結果一覧を表示する。
行をクリックすると案件の詳細（公告全文）をモーダルで表示。
"""

from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler

from src.core.dedup import deduplicate
from src.core.filter import apply_filters
from src.core.matcher import match_past_results
from src.core.models import BidProject
from src.core.scorer import score_projects
from src.sources.etokyo import fetch_etokyo_projects
from src.sources.kkj import fetch_kkj_projects
from src.sources.pportal import fetch_award_results

logger = logging.getLogger(__name__)

# テキスト整形用パターン
_SECTION_BREAK = re.compile(
    r"((?:^|\s)(?:\d+[．.]\s|（\d+）|\(\d+\)|[１２３４５６７８９０]+\s|[一二三四五六七八九十]+\s|記\s))"
)
_DATE_HIGHLIGHT = re.compile(r"(令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日)")
_PRICE_HIGHLIGHT = re.compile(r"([\d,]+\s*円)")


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


def _render_html(
    projects: list[BidProject],
    raw_count: int,
    award_count: int,
    matched_count: int,
) -> str:
    """結果をHTMLに変換する"""
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

        elig_class = "elig-ok" if p.eligibility_overall == "◎" else "elig-check" if p.eligibility_overall == "○" else "elig-ng"
        tr_class = ' class="row-ng"' if p.eligibility_overall == "×" else ""

        rows_html += f"""
        <tr onclick="showDetail({i - 1})" style="cursor:pointer"{tr_class}
            data-bid-type="{html.escape(p.bid_type)}"
            data-score="{p.score}"
            data-elig="{p.eligibility_overall}"
            data-org="{html.escape(p.organization)}">
          <td class="row-num">{i}</td>
          <td class="{elig_class}">{p.eligibility_overall}</td>
          <td class="title">{html.escape(p.title)}</td>
          <td>{html.escape(p.organization)}</td>
          <td>{html.escape(p.bid_type)}</td>
          <td>{p.publish_date}</td>
          <td>{deadline_display}</td>
          <td class="{score_class}">{score_label}</td>
        </tr>"""

    high_score = sum(1 for p in projects if p.score >= 4.0)
    general_bid = sum(1 for p in projects if p.bid_type == "一般競争入札")

    # フィルタ選択肢: 入札方式
    bid_types = sorted({p.bid_type for p in projects})
    bid_type_options = "".join(
        f'<option value="{html.escape(bt)}">{html.escape(bt)}</option>'
        for bt in bid_types
    )

    # 詳細データをJSONとして埋め込む
    details_data = []
    for p in projects:
        desc = _format_description(p.description) if p.description else ""

        # リンク: 実URLがあればそれを使い、なければGoogle検索URLを生成
        link_url = p.detail_url
        link_label = "元サイトで公告を見る"
        if not link_url:
            q = f"{p.title} {p.organization} 入札"
            link_url = f"https://www.google.com/search?q={html.escape(q)}"
            link_label = "この案件をGoogleで検索する"

        details_data.append(
            {
                "title": p.title,
                "org": p.organization,
                "bid_type": p.bid_type,
                "publish_date": p.publish_date,
                "deadline": p.deadline,
                "detail_url": link_url,
                "link_label": link_label,
                "source": p.source,
                "score": p.score,
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
    details_json = json.dumps(details_data, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
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
  td {{ padding: 10px; font-size: 13px; border-bottom: 1px solid #eee; }}
  tr:hover {{ background: #e3f2fd; }}
  .title {{ max-width: 320px; }}
  .has-price {{ color: #d32f2f; font-weight: 600; }}
  .score-high {{ background: #e8f5e9; color: #2e7d32; font-weight: 700; text-align: center; border-radius: 4px; }}
  .score-mid {{ background: #fff8e1; color: #f57f17; font-weight: 600; text-align: center; border-radius: 4px; }}
  .score-low {{ color: #999; text-align: center; }}

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
</style>
</head>
<body>
  <div class="header">
    <h1>入札情報収集 for おーしまたん</h1>
    <p>国の機関 + 関東1都6県 ｜ 印刷・製本関連 ｜ 官公需API + e-Tokyoから自動抽出</p>
  </div>

  <div class="stats">
    <div class="stat-card">
      <div class="number">{len(projects)}</div>
      <div class="label">公募中案件</div>
    </div>
    <div class="stat-card">
      <div class="number">{general_bid}</div>
      <div class="label">一般競争入札</div>
    </div>
    <div class="stat-card">
      <div class="number">{high_score}</div>
      <div class="label">おすすめ案件</div>
    </div>
    <div class="stat-card">
      <div class="number" id="filtered-count">{len(projects)}</div>
      <div class="label">表示中</div>
    </div>
  </div>

  <div class="container">
    <div class="filters">
      <div class="filter-group">
        <label>参加可否</label>
        <select id="filter-elig" onchange="applyFilters()">
          <option value="◎○" selected>◎○ 参加可能のみ</option>
          <option value="◎">◎ のみ</option>
          <option value="">すべて（×含む）</option>
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
          <option value="">すべて</option>
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
          <th>入札方式</th>
          <th>公告日</th>
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

        <div class="desc-section">
          <h3>公告内容</h3>
          <div class="desc-text" id="modal-desc"></div>
        </div>

        <a class="external-link" id="modal-link" href="#" target="_blank">
          元サイトで公告を見る &rarr;
        </a>
      </div>
    </div>
  </div>

  <div class="footer">
    最終更新: {datetime.now().strftime('%Y-%m-%d %H:%M')} ｜ データソース: 官公需API + e-Tokyo + 調達ポータル
  </div>

<script>
const details = {details_json};

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

  const descEl = document.getElementById('modal-desc');
  if (d.description) {{
    descEl.innerHTML = d.description;
    descEl.classList.remove('no-desc');
  }} else {{
    descEl.textContent = '公告内容はこのデータソースでは取得できませんでした。元サイトをご確認ください。';
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
  linkEl.href = d.detail_url;
  linkEl.innerHTML = (d.link_label || '元サイトで公告を見る') + ' &rarr;';
  linkEl.style.display = 'inline-block';

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
  const minScore = parseFloat(document.getElementById('filter-score').value) || 0;
  const keyword = document.getElementById('filter-keyword').value.toLowerCase();
  const rows = document.querySelectorAll('tbody tr');
  let visible = 0;
  let num = 1;
  rows.forEach(row => {{
    const rElig = row.getAttribute('data-elig') || '';
    const rBid = row.getAttribute('data-bid-type') || '';
    const rScore = parseFloat(row.getAttribute('data-score')) || 0;
    const rText = row.textContent.toLowerCase();
    const eligOk = !eligFilter || (eligFilter === '◎' ? rElig === '◎' : rElig !== '×');
    const show = eligOk && (!bidType || rBid === bidType) && rScore >= minScore && (!keyword || rText.includes(keyword));
    row.style.display = show ? '' : 'none';
    if (show) {{
      row.querySelector('.row-num').textContent = num++;
      visible++;
    }}
  }});
  document.getElementById('filtered-count').textContent = visible;
}}

function resetFilters() {{
  document.getElementById('filter-elig').value = '◎○';
  document.getElementById('filter-bid-type').value = '';
  document.getElementById('filter-score').value = '';
  document.getElementById('filter-keyword').value = '';
  applyFilters();
}}

// 初期表示時にフィルタを適用（×を非表示）
document.addEventListener('DOMContentLoaded', applyFilters);
</script>
</body>
</html>"""


class Handler(SimpleHTTPRequestHandler):
    html_content: str = ""

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(self.html_content.encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:
        pass


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
