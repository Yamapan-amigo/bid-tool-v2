"""公告テキストからの応募条件抽出

公告全文から等級・地域要件・提出方法・連絡先を正規表現で抽出し、
大島さん（D等級・東京）が参加可能かを自動判定する。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.config import (
    COMPANY_ANNUAL_REVENUE,
    COMPANY_CAPITAL,
    COMPANY_CERTIFICATIONS,
    COMPANY_EMPLOYEES,
    COMPANY_YEARS_SINCE_FOUNDING,
)

# 大島さんの拠点がある地域（これらの「県内」「都内」限定なら参加可能）
# ※ 大島さんは東京拠点。近隣県の「県内限定」には参加できない
_OK_REGIONS = {"東京"}

# 「関東」を含む表現は参加可能
_KANTO_KEYWORDS = ["関東", "甲信越", "全国"]


@dataclass(frozen=True)
class EligibilityInfo:
    """応募条件の構造化データ"""

    grade_text: str  # "A,B,C,D" / "A,B" / "不明"
    d_grade_ok: bool | None  # True/False/None(不明)
    region_text: str  # "群馬県内" / "関東・甲信越" / "制限なし" / "不明"
    region_ok: bool | None  # True/False/None(不明)
    submission_method: str  # "電子入札" / "郵便入札" / "持参" / "不明"
    contact: str  # 問合せ先
    overall: str  # "◎" / "○" / "×"


# === 等級抽出 ===

# 「A、B、C又はD等級」「A,B,C,D」「Ａ又はＢ」等
_GRADE_PATTERNS = [
    # 「「Ｃ」又は「Ｄ」の等級」（全角括弧付き）
    re.compile(r"[「]([A-DＡ-Ｄ])[」](?:[、,\s]*(?:又は|もしくは)[、,\s]*[「]([A-DＡ-Ｄ])[」])*\s*(?:の?\s*等級|に格付)"),
    # 「A、B、C又はD等級」「A,B,C又はD」
    re.compile(r"([A-DＡ-Ｄ][、,\s]*(?:[A-DＡ-Ｄ][、,\s]*)*(?:又は|もしくは|or)?[、,\s]*[A-DＡ-Ｄ])\s*(?:の?\s*等級|に格付)", re.IGNORECASE),
    # 「等級格付区分がA又はBの者」
    re.compile(r"等級(?:格付)?(?:区分)?(?:が|は)\s*([A-DＡ-Ｄ](?:[、,又はもしくはor\s]+[A-DＡ-Ｄ])*)", re.IGNORECASE),
    # 「D等級」単独
    re.compile(r"([A-DＡ-Ｄ])\s*等級"),
]


def _extract_grade(text: str) -> tuple[str, bool | None]:
    """等級情報を抽出する"""
    for pattern in _GRADE_PATTERNS:
        m = pattern.search(text)
        if m:
            # 全マッチグループからアルファベットを収集
            all_groups = " ".join(g for g in m.groups() if g)
            all_groups = all_groups.translate(str.maketrans("ＡＢＣＤ", "ABCD"))
            grades = set(re.findall(r"[A-D]", all_groups, re.IGNORECASE))
            grades_upper = {g.upper() for g in grades}
            if grades_upper:
                grade_text = ",".join(sorted(grades_upper))
                d_ok = "D" in grades_upper
                return grade_text, d_ok

    # テキスト全体から「Ｃ」又は「Ｄ」等級のようなパターンを直接探す
    fullwidth_match = re.findall(r"[「]([A-DＡ-Ｄ])[」]", text)
    if fullwidth_match:
        grades = {g.translate(str.maketrans("ＡＢＣＤ", "ABCD")) for g in fullwidth_match}
        grade_text = ",".join(sorted(grades))
        return grade_text, "D" in grades

    # 「全省庁統一資格」の記載があるが等級が明記されていない場合
    if "全省庁統一資格" in text:
        return "不明（全省庁統一資格）", None

    return "不明", None


# === 地域抽出 ===

# 「県内に本店」「市内に本店又は支店」「都内に営業所」
_REGION_RESTRICT = re.compile(
    r"(?:本社|本店|営業所|支店|事業所).{0,10}?"
    r"(?:所在地|所在).{0,5}?"
    r"((?:北海道|青森|岩手|宮城|秋田|山形|福島|茨城|栃木|群馬|埼玉|千葉|東京|神奈川"
    r"|新潟|富山|石川|福井|山梨|長野|岐阜|静岡|愛知|三重|滋賀|京都|大阪|兵庫|奈良"
    r"|和歌山|鳥取|島根|岡山|広島|山口|徳島|香川|愛媛|高知|福岡|佐賀|長崎|熊本|大分"
    r"|宮崎|鹿児島|沖縄)(?:都|府|県)?)"
)

_REGION_RESTRICT_SHORT = re.compile(
    r"((?:県|都|府|市|区|町|村)内)\s*(?:に|の)?\s*(?:本店|本社|営業所|支店|事業所|住所)"
)

# 「関東地域の競争参加資格」「関東・甲信越地域」等の広域地域表現
_REGION_AREA = re.compile(
    r"(関東[・\s]*甲信越|関東|全国)\s*(?:地域|地方)?\s*(?:の|における)?\s*競争参加資格"
)

# 関東を含む地域名は参加OK
_OK_AREA_KEYWORDS = {"関東", "関東・甲信越", "関東甲信越", "全国"}

# 東京以外の地方自治体プレフィックス（これらが発注元の場合、制限テキスト不在でも要確認）
_NON_TOKYO_PREFS = {
    "千葉", "神奈川", "埼玉", "茨城", "群馬", "栃木",
    "大阪", "愛知", "福岡", "北海道", "宮城", "広島",
}

# "千葉県に本社/本店を有する" "大阪府内に営業所を置く" パターン（逆順）
_REGION_RESTRICT_REVERSED = re.compile(
    r"((?:北海道|青森|岩手|宮城|秋田|山形|福島|茨城|栃木|群馬|埼玉|千葉|神奈川"
    r"|新潟|富山|石川|福井|山梨|長野|岐阜|静岡|愛知|三重|滋賀|京都|大阪|兵庫|奈良"
    r"|和歌山|鳥取|島根|岡山|広島|山口|徳島|香川|愛媛|高知|福岡|佐賀|長崎|熊本|大分"
    r"|宮崎|鹿児島|沖縄)(?:都|府|県)?(?:内)?)"
    r"\s*に.{0,5}?(?:本社|本店|営業所|支店|事業所|住所)\s*(?:を)?\s*(?:有する|置く|設置)"
)

# 実績要件パターン — これがあると新規事業者は参加不可
_EXPERIENCE_REQUIRED = re.compile(
    r"(?:過去|直近)\s*\d+\s*年(?:度)?\s*以内.{0,30}?"
    r"(?:同種|同様|類似)?.{0,10}?(?:業務|役務|案件|契約|工事)\s*(?:の|を)?\s*(?:受注|納品|納入|履行|実施)\s*(?:実績|経験)"
    r"|(?:\d+\s*回\s*以上\s*(?:の)?\s*(?:受注|納品|納入)\s*実績)"
    r"|(?:受注(?:し|して)\s*(?:及び|かつ)?\s*納入?\s*した.{0,10}?実績)"
    # 「公示日から起算して〇年以内に〇件以上」— 外郭団体によく見られる表現
    r"|(?:(?:公示日|契約日|基準日)から起算して\s*\d+\s*年以内.{0,50}?\d+\s*件以上)"
    # 「受託した実績を〇件以上有すること」— 語学・研修系でよく使われる
    r"|(?:(?:受託|受注|履行|実施|納入)した.{0,20}?実績.{0,50}?\d+\s*件以上)"
)


# ============================================================
# 会社プロフィールとの照合チェック
# ============================================================

def _parse_yen_amount(text: str) -> int | None:
    """「500万円」「1億円」「3000万円」を整数(円)に変換"""
    text = text.replace(",", "").replace("，", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*億\s*(\d+)\s*万\s*円", text)
    if m:
        return int(float(m.group(1)) * 1e8 + float(m.group(2)) * 1e4)
    m = re.search(r"(\d+(?:\.\d+)?)\s*億\s*円", text)
    if m:
        return int(float(m.group(1)) * 1e8)
    m = re.search(r"(\d+(?:\.\d+)?)\s*千\s*万\s*円", text)
    if m:
        return int(float(m.group(1)) * 1e7)
    m = re.search(r"(\d+(?:\.\d+)?)\s*万\s*円", text)
    if m:
        return int(float(m.group(1)) * 1e4)
    m = re.search(r"(\d+)\s*円", text)
    if m:
        return int(m.group(1))
    return None


_CAPITAL_PATTERN = re.compile(
    r"資本(?:金|の額)\s*(?:が|は|の)?\s*(\d[\d,，.]*\s*(?:億|千万|万)?\s*円)\s*以上"
)

_EMPLOYEE_PATTERN = re.compile(
    r"(?:常時(?:雇用|使用|従事)(?:する|させる|している)?)?\s*従業員(?:数|等)?\s*(?:が|は|を|の)?\s*(\d+)\s*(?:人|名)\s*以上"
)

_REVENUE_PATTERN = re.compile(
    r"(?:直近.{0,10})?(?:年間|年度)?(?:売上高|売上額|年商)\s*(?:が|は)?\s*(\d[\d,，.]*\s*(?:億|千万|万)?\s*円)\s*以上"
)

_CERT_PATTERN = re.compile(
    r"(?:ISO\s*\d+|JIS[A-Z]?\s*\d+|印刷技能士|グリーン印刷|FSC(?:認証)?|バリアフリー印刷士|Ｉ[ＳＯ]*Ｏ)"
    r".{0,30}?(?:認証|資格|認定|検定)?\s*(?:を)?\s*(?:取得|保有|有する|していること|している者)"
    r"|(?:FSC|PEFC|グリーン印刷)\s*認証"
)

_FOUNDING_YEARS_PATTERN = re.compile(
    r"(?:設立|創業|創立)\s*(?:後|から|より)?\s*(\d+)\s*年\s*(?:以上|を経過)"
)


def _check_capital(text: str) -> tuple[bool, str]:
    """資本金要件チェック。(ng_flag, reason_text)を返す"""
    m = _CAPITAL_PATTERN.search(text)
    if not m:
        return False, ""
    req = _parse_yen_amount(m.group(1))
    if req is None or req == 0:
        return False, ""
    if COMPANY_CAPITAL < req:
        req_man = req // 10000
        return True, f"資本金{req_man}万円以上（500万円のため要件未満）"
    return False, ""


def _check_employees(text: str) -> tuple[bool, str]:
    """従業員数要件チェック"""
    m = _EMPLOYEE_PATTERN.search(text)
    if not m:
        return False, ""
    req = int(m.group(1))
    if COMPANY_EMPLOYEES < req:
        return True, f"従業員{req}名以上（1名のため要件未満）"
    return False, ""


def _check_revenue(text: str) -> tuple[bool, str]:
    """年商要件チェック"""
    m = _REVENUE_PATTERN.search(text)
    if not m:
        return False, ""
    req = _parse_yen_amount(m.group(1))
    if req is None or req == 0:
        return False, ""
    if COMPANY_ANNUAL_REVENUE < req:
        req_man = req // 10000
        label = f"{req // 100_000_000}億円" if req >= 1e8 else f"{req_man}万円"
        return True, f"年商{label}以上（要件未満）"
    return False, ""


def _check_certifications(text: str) -> tuple[bool, str]:
    """資格・認証要件チェック"""
    m = _CERT_PATTERN.search(text)
    if not m:
        return False, ""
    if not COMPANY_CERTIFICATIONS:
        cert_snippet = m.group(0)[:15].strip()
        return True, f"資格要件あり（{cert_snippet}…）"
    return False, ""


def _check_founding_years(text: str) -> tuple[bool, str]:
    """創業年数要件チェック"""
    m = _FOUNDING_YEARS_PATTERN.search(text)
    if not m:
        return False, ""
    req = int(m.group(1))
    if COMPANY_YEARS_SINCE_FOUNDING < req:
        return True, f"設立{req}年以上（{COMPANY_YEARS_SINCE_FOUNDING}年のため要件未満）"
    return False, ""


def _extract_region(text: str, organization: str) -> tuple[str, bool | None]:
    """地域要件を抽出する"""
    # 具体的な都道府県名での制限を検出
    m = _REGION_RESTRICT.search(text)
    if m:
        pref = m.group(1).rstrip("都府県")
        ok = pref in _OK_REGIONS
        return f"{m.group(1)}内", ok

    # 「県内」「市内」等の短い表現
    m = _REGION_RESTRICT_SHORT.search(text)
    if m:
        prefix = m.group(1)
        for region in _OK_REGIONS:
            if region in organization:
                return f"{prefix}（{organization}）", True
        return f"{prefix}限定", False

    # 「千葉県に本社を有する」等の逆順パターン
    m = _REGION_RESTRICT_REVERSED.search(text)
    if m:
        pref_name = m.group(1).rstrip("都府県内")
        ok = pref_name in _OK_REGIONS
        return f"{m.group(1)}限定", ok

    # 「関東地域」等の広域表現
    m = _REGION_AREA.search(text)
    if m:
        area = m.group(1).replace(" ", "").replace("　", "")
        ok = any(kw in area for kw in _OK_AREA_KEYWORDS)
        return f"{area}地域", ok

    # 地域制限の記載がない場合:
    # 非東京の地方自治体は仕様書PDFに制限が書かれていることが多い → 要確認
    if any(pref in organization for pref in _NON_TOKYO_PREFS):
        return "要確認（地元優先の可能性あり）", None

    # 国の機関・東京都発注は制限なしと見なす
    return "制限なし", True


# === 提出方法抽出 ===

_SUBMISSION_PATTERNS = [
    (re.compile(r"電子入札"), "電子入札"),
    (re.compile(r"郵便入札|郵送"), "郵便入札"),
    (re.compile(r"持参"), "持参"),
    (re.compile(r"紙入札|紙による"), "紙入札"),
]


def _extract_submission_method(text: str) -> str:
    """提出方法を抽出する"""
    methods = []
    for pattern, label in _SUBMISSION_PATTERNS:
        if pattern.search(text):
            methods.append(label)
    return " / ".join(methods) if methods else "不明"


# === 連絡先抽出 ===

_PHONE = re.compile(r"(?:電話|TEL|ＴＥＬ|℡)\s*[：:]?\s*([\d\-（）()]+[\d])")
_ADDRESS = re.compile(r"〒\s*(\d{3}[-ー]\d{4})\s*([^\n]{5,40})")


def _extract_contact(text: str) -> str:
    """連絡先を抽出する"""
    parts = []

    m = _ADDRESS.search(text)
    if m:
        parts.append(f"〒{m.group(1)} {m.group(2).strip()}")

    m = _PHONE.search(text)
    if m:
        parts.append(f"TEL: {m.group(1)}")

    return " ｜ ".join(parts) if parts else ""


# === 総合判定 ===


def extract_eligibility(text: str, organization: str) -> EligibilityInfo:
    """公告テキストから応募条件を抽出し、参加可否を判定する"""
    if not text:
        return EligibilityInfo(
            grade_text="不明",
            d_grade_ok=None,
            region_text="不明",
            region_ok=None,
            submission_method="不明",
            contact="",
            overall="○",
        )

    grade_text, d_grade_ok = _extract_grade(text)
    region_text, region_ok = _extract_region(text, organization)
    submission_method = _extract_submission_method(text)
    contact = _extract_contact(text)

    # 実績要件チェック（「過去〇年以内に受注実績」等がある場合は参加不可）
    experience_required = bool(_EXPERIENCE_REQUIRED.search(text))
    if experience_required:
        region_ok = False
        region_text = "実績要件あり（受注実績が必要）" + (f"｜{region_text}" if region_text != "不明" else "")

    # 会社プロフィールとの照合（資本金・従業員数・年商・資格・創業年数）
    profile_checks = [
        _check_capital(text),
        _check_employees(text),
        _check_revenue(text),
        _check_certifications(text),
        _check_founding_years(text),
    ]
    extra_reasons = [reason for ng, reason in profile_checks if ng]
    if extra_reasons:
        region_ok = False
        prefix = "｜".join(extra_reasons)
        region_text = prefix + (f"｜{region_text}" if region_text not in ("不明", "制限なし") else "")

    # 総合判定
    if d_grade_ok is False or region_ok is False:
        overall = "×"
    elif d_grade_ok is True and region_ok is True:
        overall = "◎"
    else:
        overall = "○"

    return EligibilityInfo(
        grade_text=grade_text,
        d_grade_ok=d_grade_ok,
        region_text=region_text,
        region_ok=region_ok,
        submission_method=submission_method,
        contact=contact,
        overall=overall,
    )
