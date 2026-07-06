"""
Family Portfolio v2
- Google Sheets 기반 영구 저장
- 매매 기록 입력 → 잔고 자동 계산
- 생애주기 + 장세 + 환율 Adaptive 리밸런싱
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

try:
    import FinanceDataReader as fdr
except Exception:
    fdr = None

try:
    import yfinance as yf
except Exception:
    yf = None

from config import (
    CATEGORY_ORDER, BASE_TARGETS, ASSET_COLOR_MAP, FX_COLOR_MAP,
    CODE_MAP, IRP_SAFE_ASSETS, CANONICAL_TO_DISPLAY, DISPLAY_TO_CANONICAL,
    SHEET_SETTINGS, USERS, get_user_by_email,
    DEFAULT_BIRTH_DATE, DEFAULT_RETIREMENT_AGE, DEFAULT_TARGET_FINANCIAL_ASSETS,
    FEATURE_FLAGS,
    DONUT_HEIGHT, DONUT_OUTER_OPACITY,
    DONUT_CURRENT_DOMAIN, DONUT_TARGET_DOMAIN, DISPLAY_WEIGHT_THRESHOLD,
)
from data.gsheets import read_sheet, write_sheet, append_row, read_setting, write_setting
from modules.portfolio_target import get_final_targets, get_fx_info
from modules.rebalance_signal import calc_rebalance
from modules.buy_signal_engine import generate_buy_signals
from modules.account_allocator import allocate_today_orders

# ── Feature Flags ───────────────────────────────────────────
# config.py에서 직접 import한 FEATURE_FLAGS를 사용한다.
# fallback을 두지 않아야 config.py 반영 여부를 정확히 확인할 수 있다.
USE_V4_LAYER1_POLICY = bool(FEATURE_FLAGS.get("v4_layer1_policy", False))
USE_ACCOUNT_ALLOCATOR = bool(FEATURE_FLAGS.get("account_allocator", False))
SHOW_CONSTRAINT_DRIFT = bool(FEATURE_FLAGS.get("constraint_drift", False)) and USE_ACCOUNT_ALLOCATOR


# ── 페이지 설정 ───────────────────────────────────────────────
st.set_page_config(page_title="Family Portfolio", layout="wide")

# ── CSS ───────────────────────────────────────────────────────
st.markdown("""
<style>
html, body, [class*="css"] { font-size: 12px !important; }
.stApp { background: linear-gradient(180deg, #07101f 0%, #0b1220 100%); }
h1 { font-size: 1.25rem !important; margin-bottom: 0.25rem !important; }
.block-container { padding-top: 0.8rem !important; max-width: 980px !important; padding-bottom: 1rem !important; }
.stDataFrame div { font-size: 11px !important; }

/* ── 상위 탭 (st.tabs) ── */
div[data-testid="stTabs"] > div:first-child {
    gap: 4px !important;
    border-bottom: 1px solid rgba(148,163,184,0.1) !important;
    padding-bottom: 0 !important;
    margin-bottom: 12px !important;
}
div[data-testid="stTabs"] button[role="tab"] {
    border-radius: 10px 10px 0 0 !important;
    padding: 8px 16px !important;
    font-size: 0.88rem !important;
    font-weight: 700 !important;
    border: 1px solid rgba(148,163,184,0.12) !important;
    border-bottom: none !important;
    background: rgba(15,23,42,0.4) !important;
    color: #64748b !important;
    transition: all 0.15s !important;
}
div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    background: rgba(99,102,241,0.2) !important;
    border-color: rgba(99,102,241,0.4) !important;
    color: #e0e7ff !important;
}

/* ── 하위 radio 탭 ── */
div[data-testid="stRadio"] > label { display: none !important; }
div[data-testid="stRadio"] > div[role="radiogroup"] {
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: wrap !important;
    gap: 4px !important;
    padding: 0 !important;
    margin: 0 0 10px 0 !important;
}
div[data-testid="stRadio"] label {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    padding: 5px 12px !important;
    border-radius: 8px !important;
    border: 1px solid rgba(148,163,184,0.12) !important;
    background: rgba(15,23,42,0.3) !important;
    color: #94a3b8 !important;
    font-size: 0.78rem !important;
    font-weight: 500 !important;
    cursor: pointer !important;
    margin: 0 !important;
    transition: all 0.15s !important;
}
div[data-testid="stRadio"] label:has(input:checked) {
    background: rgba(139,92,246,0.2) !important;
    border-color: rgba(139,92,246,0.4) !important;
    color: #ddd6fe !important;
    font-weight: 600 !important;
}
div[data-testid="stRadio"] label input { display: none !important; }
div[data-testid="stRadio"] label svg   { display: none !important; }
div[data-testid="stRadio"] label > span:first-child { display: none !important; }
div[data-testid="stRadio"] p { margin: 0 !important; line-height: 1 !important; }

/* ── 메트릭 카드 ── */
div[data-testid="stMetric"] {
    background: rgba(17,24,39,0.88);
    border: 1px solid rgba(148,163,184,0.12);
    border-radius: 16px; padding: 14px;
    box-shadow: 0 8px 30px rgba(0,0,0,0.16);
}
div[data-testid="stMetricLabel"] { color: #94a3b8 !important; }

/* ── 카드 ── */
.app-card {
    background: rgba(15,23,42,0.76);
    border: 1px solid rgba(148,163,184,0.10);
    border-radius: 16px; padding: 12px;
    margin: 6px 0 10px 0;
    box-shadow: 0 8px 20px rgba(0,0,0,0.12);
}
.app-card-title { font-size: 1rem; font-weight: 700; margin-bottom: 2px; }
.app-card-caption { color: #94a3b8; font-size: 0.82rem; margin-bottom: 6px; }

/* ── 장세 배지 ── */
.regime-badge {
    display: inline-block; padding: 3px 12px;
    border-radius: 20px; font-weight: 700; font-size: 0.88rem;
}
.signal-up   { background: rgba(239,68,68,0.15);  color: #ef4444; }
.signal-flat { background: rgba(148,163,184,0.15); color: #94a3b8; }
.signal-down { background: rgba(96,165,250,0.15);  color: #60a5fa; }
</style>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════
# 유틸 함수
# ════════════════════════════════════════════════════════════
def card(title=None, caption=None):
    t = f'<div class="app-card-title">{title}</div>' if title else ""
    c = f'<div class="app-card-caption">{caption}</div>' if caption else ""
    st.markdown(f'<div class="app-card">{t}{c}', unsafe_allow_html=True)

def end_card():
    st.markdown("</div>", unsafe_allow_html=True)

def disp(name):
    return CANONICAL_TO_DISPLAY.get(name, name)

def canon(name):
    return DISPLAY_TO_CANONICAL.get(name, name)

def fmt_krw(v):
    try:
        v = float(v)
    except Exception:
        return str(v)
    if abs(v) >= 1e8:   return f"{v/1e8:.1f}억"
    if abs(v) >= 1e4:   return f"{v/1e4:.0f}만"
    return f"{v:,.0f}원"

def pct_badge(val):
    if val is None:
        return "<span style='color:#94a3b8'>-</span>"
    color = "#ef4444" if val > 0 else "#60a5fa"
    sign  = "+" if val > 0 else ""
    return f"<span style='color:{color};font-weight:700'>{sign}{val:.2f}%</span>"


# ════════════════════════════════════════════════════════════
# 전역 정렬 규칙
# ════════════════════════════════════════════════════════════
CATEGORY_SORT_ORDER = {"세액공제 O": 10, "세액공제 X": 20, "ISA": 30}

ACCOUNT_SORT_ORDER = {
    "연금저축(키움)": 11, "연금저축": 11,
    "IRP(미래)": 12,
    "연금저축(삼성)": 21, "연금저축2": 21,
    "IRP(삼성)": 22, "경영성과IRP(삼성)": 22,
    "ISA": 31,
}

PRODUCT_SORT_ORDER = {
    "S&P500": 10, "S&P500(H)": 11,
    "나스닥100": 20, "나스닥100(H)": 21,
    "다우존스": 30, "다우존스(H)": 31,
    "미국채": 40, "미국 국채": 40,
    "금": 50,
    "한국금리": 60, "금리": 60, "현금성 (KOFR)": 60,
    "현금": 90,
}

def _account_sort_key(name):
    s = str(name or "").strip()
    if s in ACCOUNT_SORT_ORDER:
        return ACCOUNT_SORT_ORDER[s]
    su = s.upper()
    if "ISA" in su:
        return 31
    if "연금저축" in s and ("삼성" in s or "2" in s):
        return 21
    if "IRP" in su and ("삼성" in s or "성과" in s):
        return 22
    if "연금저축" in s:
        return 11
    if "IRP" in su:
        return 12
    return 999

def _product_sort_key(name):
    s_raw = str(name or "").strip()
    s = s_raw.replace(" ", "")
    su = s.upper()

    if s_raw in DISPLAY_TO_CANONICAL:
        s_raw = DISPLAY_TO_CANONICAL[s_raw]
        s = s_raw.replace(" ", "")
        su = s.upper()

    hedged = "(H)" in s or "환헤지" in s or "HEDGED" in su

    if "S&P500" in s or "SP500" in su or "SNP500" in su or "S&P" in s:
        return 11 if hedged else 10
    if "나스닥100" in s or "NASDAQ100" in su or "NASDAQ" in su or "QQQ" in su:
        return 21 if hedged else 20
    if "다우존스" in s or "DOW" in su or "DOWJONES" in su:
        return 31 if hedged else 30
    if "미국채" in s or "미국국채" in s or "미국채권" in s or "TREASURY" in su:
        return 40
    if s == "금" or "금ETF" in s or "GOLD" in su:
        return 50
    if "금리" in s or "KOFR" in su or "한국금리" in s or "현금성" in s:
        return 60
    if "현금" in s or "CASH" in su:
        return 90
    return 999

def apply_global_sort(df: pd.DataFrame, qty_priority: bool = False) -> pd.DataFrame:
    """
    계좌/종목 표시 순서를 앱 전체에서 통일.
    기본값은 '계좌 우선 → 종목 순서 → 매수/매도 → 수량'이다.
    qty_priority=True일 때만 조정수량 큰 순서를 앞세운다.
    """
    if df is None or df.empty:
        return df
    out = df.copy()
    sort_cols, temp_cols = [], []

    if "계좌카테고리" in out.columns:
        out["_cat_order"] = out["계좌카테고리"].map(CATEGORY_SORT_ORDER).fillna(999).astype(int)
        sort_cols.append("_cat_order"); temp_cols.append("_cat_order")

    if "계좌명" in out.columns:
        out["_acct_order"] = out["계좌명"].apply(_account_sort_key)
        out["_acct_name_order"] = out["계좌명"].astype(str)
        # 같은 계좌 타입(예: 연금저축)이 여러 개여도 계좌명으로 먼저 묶고,
        # 그 다음 종목 순서를 적용한다.
        sort_cols.append("_acct_order"); temp_cols.append("_acct_order")
        sort_cols.append("_acct_name_order"); temp_cols.append("_acct_name_order")

    product_col = next((c for c in ["약식종목명", "종목", "자산군", "자산군_표시"] if c in out.columns), None)
    if product_col:
        out["_prod_order"] = out[product_col].apply(_product_sort_key)
        sort_cols.append("_prod_order"); temp_cols.append("_prod_order")

    if "구분" in out.columns:
        out["_side_order"] = out["구분"].map({"매수": 0, "매도": 1}).fillna(9).astype(int)
        sort_cols.append("_side_order"); temp_cols.append("_side_order")

    if "조정수량" in out.columns:
        out["_abs_qty_order"] = pd.to_numeric(out["조정수량"], errors="coerce").abs().fillna(0)
        if qty_priority:
            # 특수 용도: 수량 우선 정렬이 필요할 때만 앞으로 보냄
            sort_cols.insert(0, "_abs_qty_order")
        else:
            # 기본: 계좌/종목 정렬 이후 같은 그룹 안에서만 수량 큰 순
            sort_cols.append("_abs_qty_order")
        temp_cols.append("_abs_qty_order")

    if sort_cols:
        ascending = [True] * len(sort_cols)
        if "_abs_qty_order" in sort_cols:
            ascending[sort_cols.index("_abs_qty_order")] = False
        out = out.sort_values(sort_cols, ascending=ascending, kind="stable")

    return out.drop(columns=temp_cols, errors="ignore")

def safe_global_sort(df: pd.DataFrame, qty_priority: bool = False) -> pd.DataFrame:
    try:
        return apply_global_sort(df, qty_priority=qty_priority)
    except Exception:
        return df




def sort_asset_names(names):
    """도넛/범례/표시용 자산명 순서 고정."""
    return sorted([str(n) for n in names], key=lambda x: (_product_sort_key(x), str(x)))


def sort_target_map(target_map: dict) -> dict:
    """목표비중 dict를 전역 종목 순서대로 재정렬."""
    if not target_map:
        return target_map
    ordered = {}
    for k in sort_asset_names(list(target_map.keys())):
        if k in target_map:
            ordered[k] = target_map[k]
    return ordered

# ════════════════════════════════════════════════════════════
# 데이터 로드 (Google Sheets)
# ════════════════════════════════════════════════════════════
def to_yf_symbol(code: str) -> str:
    """국내 숫자 코드는 .KS를 붙이고, 해외 티커는 원문 사용."""
    code = str(code).strip()
    if code.isdigit():
        return f"{code}.KS"
    return code


@st.cache_data(ttl=300, show_spinner=False)
def get_price_data(codes: tuple) -> dict:
    """
    시세 일괄 조회.
    기존 FDR 개별 호출 대비 yfinance batch download를 우선 사용해
    앱 최초 로딩과 탭 전환 시 체감 속도를 줄인다.
    """
    clean_codes = []
    price_map = {}

    for raw in codes:
        code = str(raw).strip()
        if code.upper() in {"", "NAN", "CASH", "SEED"}:
            price_map[code] = 1.0
        else:
            clean_codes.append(code)
            price_map[code] = 0.0

    clean_codes = sorted(set(clean_codes))
    if not clean_codes:
        return price_map

    # 1차: yfinance batch + threads
    if yf:
        try:
            yf_symbols = [to_yf_symbol(c) for c in clean_codes]
            hist = yf.download(
                tickers=" ".join(yf_symbols),
                period="7d",
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=True,
            )
            if hist is not None and not hist.empty:
                for code, symbol in zip(clean_codes, yf_symbols):
                    try:
                        if len(yf_symbols) == 1:
                            close = hist["Close"].dropna()
                        else:
                            close = hist[(symbol, "Close")].dropna()
                        if not close.empty:
                            price_map[code] = float(close.iloc[-1])
                    except Exception:
                        pass
        except Exception:
            pass

    # 2차 fallback: FDR 개별 조회
    if fdr:
        for code in clean_codes:
            if price_map.get(code, 0.0) > 0:
                continue
            try:
                hist = fdr.DataReader(code)
                price_map[code] = float(hist["Close"].iloc[-1]) if not hist.empty else 0.0
            except Exception:
                price_map[code] = 0.0

    return price_map


@st.cache_data(ttl=300, show_spinner=False)
def get_usdkrw() -> float:
    try:
        if fdr:
            hist = fdr.DataReader("USD/KRW")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return 1360.0


@st.cache_data(ttl=300, show_spinner=False)
def load_assets(sheet_name: str = "나_잔고") -> pd.DataFrame:
    """Google Sheets 잔고 탭 읽기 (5분 캐시)"""
    df = read_sheet(sheet_name)
    if df.empty:
        return pd.DataFrame()

    defaults = {
        "계좌명": "", "종목명": "", "종목코드": "CASH",
        "보유수량": 0, "매수평단": 0, "약식종목명": "",
        "계좌카테고리": "기타", "자산군": "",
    }
    for col, val in defaults.items():
        if col not in df.columns:
            df[col] = val

    df["종목코드"]  = df["종목코드"].fillna("CASH").astype(str).str.strip()
    df["보유수량"]  = pd.to_numeric(df["보유수량"], errors="coerce").fillna(0)
    df["매수평단"]  = pd.to_numeric(df["매수평단"], errors="coerce").fillna(0)

    is_cash = df["종목코드"].str.upper().eq("CASH") | df["약식종목명"].astype(str).eq("현금")
    df.loc[is_cash, "자산군"] = "현금"

    # 자산군 정규화
    df["자산군"] = df["자산군"].apply(lambda x: DISPLAY_TO_CANONICAL.get(str(x).strip(), str(x).strip()))

    # TDF 제외 (포트폴리오 비중 계산 대상 아님)
    df = df[~df["자산군"].str.upper().eq("TDF")].copy()
    df = df[~df["약식종목명"].astype(str).str.upper().str.contains("TDF", na=False)].copy()

    return df


def prepare_assets(df_raw: pd.DataFrame):
    """현재가 반영 평가금액 계산"""
    if df_raw.empty:
        return pd.DataFrame(), pd.DataFrame(), 0.0

    seed_df  = df_raw[df_raw["종목코드"].str.upper() == "SEED"].copy()
    asset_df = df_raw[df_raw["종목코드"].str.upper() != "SEED"].copy()

    codes     = tuple(asset_df["종목코드"].dropna().astype(str).unique())
    price_map = get_price_data(codes)
    fx        = get_usdkrw()

    asset_df["현재가"]  = asset_df["종목코드"].map(price_map).fillna(0.0)
    asset_df["매수금액"] = asset_df.apply(
        lambda r: float(r["보유수량"]) if str(r["종목코드"]).upper() == "CASH"
                  else float(r["보유수량"]) * float(r["매수평단"]), axis=1
    )
    asset_df["평가금액"] = asset_df.apply(
        lambda r: float(r["보유수량"]) if str(r["종목코드"]).upper() == "CASH"
                  else float(r["보유수량"]) * float(r["현재가"]), axis=1
    )
    asset_df["수익률"] = asset_df.apply(
        lambda r: (r["평가금액"] - r["매수금액"]) / r["매수금액"] * 100
                  if r["매수금액"] > 0 else 0.0, axis=1
    )
    return seed_df, asset_df, fx


@st.cache_data(ttl=300, show_spinner=False)
def load_trades(sheet_name: str = "나_매매기록") -> pd.DataFrame:
    empty = pd.DataFrame(columns=[
        "일자", "계좌카테고리", "계좌명", "자산군",
        "약식종목명", "종목코드", "구분",
        "체결수량", "체결가", "체결금액", "메모"
    ])
    df = read_sheet(sheet_name)
    if df.empty:
        return empty

    # 필수 컬럼 없으면 빈 df 반환
    required = ["체결수량", "체결가", "체결금액"]
    if not all(c in df.columns for c in required):
        st.warning(f"매매기록 시트에 필수 컬럼이 없습니다: {[c for c in required if c not in df.columns]}")
        return empty

    df["체결수량"] = pd.to_numeric(df["체결수량"], errors="coerce").fillna(0)
    df["체결가"]   = pd.to_numeric(df["체결가"],   errors="coerce").fillna(0)
    df["체결금액"] = pd.to_numeric(df["체결금액"], errors="coerce").fillna(0)
    return df


# ════════════════════════════════════════════════════════════
# 도넛 차트
# ════════════════════════════════════════════════════════════
# 고정 색상 맵 (표시명 포함)
FULL_COLOR_MAP = {
    # 정규명
    "S&P500":    "#6366f1",
    "나스닥100": "#8b5cf6",
    "다우존스":  "#22c55e",
    "미국채":    "#10b981",
    "금":        "#f59e0b",
    "금리":      "#06b6d4",
    "현금":      "#64748b",
    # 표시명
    "미국 국채":      "#10b981",
    "현금성 (KOFR)":  "#06b6d4",
    "한국금리":       "#06b6d4",
}

def _resolve_colors(names):
    palette = ["#6366f1","#8b5cf6","#a78bfa","#f59e0b",
               "#10b981","#06b6d4","#f97316","#64748b"]
    return [FULL_COLOR_MAP.get(n, palette[i % len(palette)])
            for i, n in enumerate(names)]


def dual_donut(cur_df, cur_val_col, cur_name_col, target_map,
               height=DONUT_HEIGHT, center_title=None, center_value=None):

    # 현재 비중 집계
    cur_agg = cur_df.groupby(cur_name_col, dropna=False)[cur_val_col].sum().to_dict()
    target_disp = {disp(k): float(v) for k, v in sort_target_map(target_map).items()}

    # 전체 자산군 목록 (현재 + 목표)
    all_names = list(dict.fromkeys(
        [str(x) for x in cur_df[cur_name_col].fillna("").tolist()] +
        list(target_disp.keys())
    ))

    # 도넛/범례도 전역 종목 순서와 동일하게 고정
    # 도넛에서는 환노출/환헤지를 합산한 자산군 단위로만 표시한다.
    names = sort_asset_names(all_names)

    cur_vals    = [float(cur_agg.get(n, 0)) for n in names]
    target_vals = [target_disp.get(n, 0.0) for n in names]
    colors      = _resolve_colors(names)

    fig = go.Figure()
    fig.add_trace(go.Pie(
        labels=names, values=cur_vals, hole=0.52,
        sort=False,
        direction="clockwise",
        textinfo="label+percent",
        textfont=dict(size=10, color="#f1f5f9"),
        insidetextorientation="radial",
        domain=DONUT_CURRENT_DOMAIN,
        marker=dict(colors=colors, line=dict(color="rgba(15,23,42,0.85)", width=2)),
        hovertemplate="<b>%{label}</b><br>현재: %{value:.1f}%<extra></extra>",
        name="현재",
        texttemplate=[
            f"{n}<br>{v:.1f}%" if v >= 1.0 else ""
            for n, v in zip(names, cur_vals)
        ],
    ))
    fig.add_trace(go.Pie(
        labels=names, values=target_vals, hole=0.74,
        sort=False,
        direction="clockwise",
        textinfo="none", opacity=DONUT_OUTER_OPACITY,
        domain=DONUT_TARGET_DOMAIN,
        marker=dict(colors=colors, line=dict(color="rgba(15,23,42,0.6)", width=1.5)),
        hovertemplate="<b>%{label}</b><br>목표: %{value:.1f}%<extra></extra>",
        name="목표",
    ))
    fig.update_layout(
        height=height + 60,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=8, b=60),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.05,
            xanchor="center",
            x=0.5,
            font=dict(size=11, color="#cbd5e1"),
            bgcolor="rgba(0,0,0,0)",
            itemsizing="constant",
            traceorder="normal",
        ),
    )

    # 중앙 텍스트 겹침 방지: 한 annotation에 <br>로 넣지 않고
    # 제목/값을 별도 annotation으로 분리해 y 위치를 고정한다.
    if center_title:
        fig.add_annotation(
            x=0.5, y=0.535,
            text=f"<span style='font-size:11px;color:#94a3b8'>{center_title}</span>",
            showarrow=False,
            xanchor="center", yanchor="middle",
        )
    if center_value:
        fig.add_annotation(
            x=0.5, y=0.485,
            text=f"<span style='font-size:20px;font-weight:800;color:#f1f5f9'>{center_value}</span>",
            showarrow=False,
            xanchor="center", yanchor="middle",
        )
    return fig

# ════════════════════════════════════════════════════════════
# 캔들차트 함수
# ════════════════════════════════════════════════════════════
@st.cache_data(ttl=3600, show_spinner=False)
def get_candle_data(code: str) -> pd.DataFrame:
    """종목코드별로 캐시 (code가 캐시 키)"""
    if not yf or not code or code.upper() in {"CASH", "SEED", ""}:
        return pd.DataFrame()
    try:
        ticker = yf.Ticker(to_yf_symbol(code))
        df = ticker.history(period="2y", interval="1d")
        if df.empty:
            return pd.DataFrame()
        df.index = pd.to_datetime(df.index.tz_localize(None))
        df = df[["Open","High","Low","Close","Volume"]].copy()
        df["MA20"]  = df["Close"].rolling(20).mean()
        df["MA60"]  = df["Close"].rolling(60).mean()
        df["MA120"] = df["Close"].rolling(120).mean()
        df["MA200"] = df["Close"].rolling(200).mean()
        return df
    except Exception:
        return pd.DataFrame()


def _add_candle_traces(fig, df, row, show_legend=True):
    """캔들 + 이평선 traces (row=None이면 단일 차트)"""
    ma_styles = [
        ("MA20",  "#facc15", "20일선",  1.5),
        ("MA60",  "#4ade80", "60일선",  1.5),
        ("MA120", "#fb923c", "120일선", 2.5),
        ("MA200", "#f87171", "200일선", 2.5),
    ]
    kwargs = {"row": row, "col": 1} if row else {}
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"],
        low=df["Low"],   close=df["Close"],
        name="일봉",
        increasing_line_color="#ef4444",
        decreasing_line_color="#60a5fa",
        increasing_fillcolor="#ef4444",
        decreasing_fillcolor="#60a5fa",
        showlegend=show_legend,
    ), **kwargs)

    for col, color, label, width in ma_styles:
        if col in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[col],
                mode="lines", name=label,
                line=dict(color=color, width=width),
                showlegend=show_legend,
                hovertemplate=f"{label}: %{{y:,.0f}}<extra></extra>",
            ), **kwargs)


def make_single_candle_chart(df: pd.DataFrame, title: str) -> go.Figure:
    """단일 캔들차트 (단기/장기 탭용)"""
    if df.empty:
        return go.Figure()
    fig = go.Figure()
    _add_candle_traces(fig, df, row=None, show_legend=True)
    fig.update_layout(
        title=dict(text=title, font=dict(size=12, color="#e2e8f0")),
        height=460,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,42,0.6)",
        margin=dict(l=8, r=8, t=36, b=90),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.28,
            x=0.5, xanchor="center",
            font=dict(color="#cbd5e1", size=10),
            bgcolor="rgba(0,0,0,0)",
            entrywidth=70,
            entrywidthmode="fraction",
        ),
        xaxis=dict(
            rangeslider=dict(visible=False),
            showgrid=True, gridcolor="rgba(148,163,184,0.08)",
            tickfont=dict(color="#94a3b8", size=10),
        ),
        yaxis=dict(
            showgrid=True, gridcolor="rgba(148,163,184,0.08)",
            tickfont=dict(color="#94a3b8", size=10),
            tickformat=",",
            side="left",
            autorange=True,
        ),
        hovermode="x unified",
    )
    return fig


def make_candle_chart(df: pd.DataFrame, title: str) -> go.Figure:
    """
    상단: 단기 (최근 90일) 캔들 + 이평선
    하단: 장기 (전체 2년) 캔들 + 이평선
    """
    from plotly.subplots import make_subplots

    if df.empty:
        return go.Figure()

    # 단기: 최근 90일
    short_df = df.tail(90)
    # 장기: 전체
    long_df  = df

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=False,
        row_heights=[0.5, 0.5],
        vertical_spacing=0.12,
        subplot_titles=["📊 단기 (최근 90일)", "📈 장기 (전체 2년)"],
    )

    # 상단: 단기 (범례 표시)
    _add_candle_traces(fig, short_df, row=1, show_legend=True)
    # 하단: 장기 (범례 숨김 - 중복 방지)
    _add_candle_traces(fig, long_df,  row=2, show_legend=False)

    common_axis = dict(
        showgrid=True,
        gridcolor="rgba(148,163,184,0.08)",
        tickfont=dict(color="#94a3b8", size=10),
    )

    fig.update_layout(
        title=dict(text=title, font=dict(size=13, color="#e2e8f0")),
        height=780,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,42,0.6)",
        margin=dict(l=8, r=8, t=48, b=60),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.08,          # 차트 아래로 완전히 내림
            x=0.5, xanchor="center",
            font=dict(color="#cbd5e1", size=11),
            bgcolor="rgba(0,0,0,0)",
            itemsizing="constant",
        ),
        hovermode="x unified",
    )

    # 상단 축
    fig.update_xaxes(
        **common_axis,
        rangeslider=dict(visible=False),
        row=1, col=1,
    )
    fig.update_yaxes(
        **common_axis,
        tickformat=",",
        side="right",
        autorange=True,
        row=1, col=1,
    )

    # 하단 축
    fig.update_xaxes(
        **common_axis,
        rangeslider=dict(visible=False),
        row=2, col=1,
    )
    fig.update_yaxes(
        **common_axis,
        tickformat=",",
        side="right",
        autorange=True,
        row=2, col=1,
    )

    # subplot 타이틀 색상
    for ann in fig.layout.annotations:
        ann.font.color = "#94a3b8"
        ann.font.size  = 11

    return fig

# ════════════════════════════════════════════════════════════
# 경량 룰베이스 매매 신호
# ════════════════════════════════════════════════════════════
def make_light_trade_signal(row, regime_name: str) -> dict:
    """
    yfinance 추가 호출 없이 리밸런싱 결과만으로 매매 실행 우선순위 표시.
    기준:
    - 조정수량 방향
    - 목표비중 대비 괴리율
    - 장세
    - 기존 리밸런싱 엔진의 실행여부/보류사유
    """
    qty = float(row.get("조정수량", 0) or 0)
    dev = float(row.get("괴리율", 0) or 0)
    exec_flag = str(row.get("실행여부", "실행") or "실행")
    hold_reason = str(row.get("보류사유", "") or "")

    if qty == 0:
        return {"매매신호": "관망", "신호점수": 0, "신호사유": "조정수량 없음"}

    score = 0
    reasons = []

    # 리밸런싱 괴리도: 절대 괴리가 클수록 실행 우선순위 상승
    abs_dev = abs(dev)
    if abs_dev >= 7:
        score += 3
        reasons.append("목표비중 괴리 큼")
    elif abs_dev >= 4:
        score += 2
        reasons.append("목표비중 괴리 보통")
    elif abs_dev >= 2:
        score += 1
        reasons.append("목표비중 괴리 작음")
    else:
        reasons.append("목표비중 근처")

    # 장세 필터
    if regime_name == "상승장":
        if qty > 0:
            score += 1
            reasons.append("상승장 매수 우호")
        else:
            score -= 1
            reasons.append("상승장 매도는 완화")
    elif regime_name == "하락장":
        if qty > 0:
            score -= 1
            reasons.append("하락장 매수는 분할")
        else:
            score += 1
            reasons.append("하락장 위험축소 우호")
    else:
        reasons.append("보합장 리밸런싱 중심")

    # 기존 엔진에서 보류 판정이면 최종 신호도 약화
    if exec_flag != "실행":
        score -= 2
        if hold_reason:
            reasons.append(f"보류사유: {hold_reason}")

    # 최종 신호
    if qty > 0:
        if score >= 4:
            signal = "매수 우선"
        elif score >= 2:
            signal = "분할매수"
        elif score >= 0:
            signal = "매수 관망"
        else:
            signal = "매수 보류"
    else:
        if score >= 4:
            signal = "매도 우선"
        elif score >= 2:
            signal = "일부매도"
        elif score >= 0:
            signal = "매도 관망"
        else:
            signal = "매도 보류"

    return {
        "매매신호": signal,
        "신호점수": int(score),
        "신호사유": "; ".join(reasons),
    }

try:
    # ── 사용자 설정 ────────────────────────────────────────────
    user_names = {u["name"]: u for u in USERS.values()}

    # 기본 사용자 = "me" (뽕구)
    current_user = USERS["me"]
    SHEET_ASSETS = current_user["sheet_assets"]
    SHEET_TRADES = current_user["sheet_trades"]
    user_name    = current_user["name"]

    # ── 데이터 로드 (두 사람 한 번에) ────────────────────────
    with st.spinner("데이터 불러오는 중..."):
        df_raw    = load_assets(SHEET_ASSETS)
        trades_df = load_trades(SHEET_TRADES)
        # 상대방 데이터도 미리 로드 (캐시 활용, API 요청 최소화)
        other_user = USERS["spouse"] if current_user == USERS["me"] else USERS["me"]
        other_raw  = load_assets(other_user["sheet_assets"])

    if df_raw.empty:
        st.warning("⚠️ 잔고 데이터가 없습니다. 'Google Sheets의 잔고 탭'에 데이터를 입력하거나 아래에서 직접 추가하세요.")
        seed_df = asset_df = pd.DataFrame()
        current_fx = get_usdkrw()
    else:
        seed_df, asset_df, current_fx = prepare_assets(df_raw)

    # ── 설정 읽기 ──────────────────────────────────────────────
    # 기존 retirement_year는 호환용으로만 유지하고, 실제 Layer 1은 생년월일/은퇴나이/목표자산 기반으로 계산
    retirement_year  = int(read_setting("retirement_year") or 2050)
    birth_date_setting = read_setting("birth_date") or DEFAULT_BIRTH_DATE
    retirement_age = int(read_setting("retirement_age") or DEFAULT_RETIREMENT_AGE)
    target_financial_assets = float(read_setting("target_financial_assets") or DEFAULT_TARGET_FINANCIAL_ASSETS)
    # v2부터 목표 금융자산 기본값은 뽕구 기준 15억원.
    # 이미 Google Sheets 설정에 예전 기본값(20억원)이 저장돼 있으면 자동으로 15억원으로 보정.
    if int(target_financial_assets) == 2000000000:
        target_financial_assets = DEFAULT_TARGET_FINANCIAL_ASSETS
    risk_adjust = float(read_setting("risk_adjust") or 0)
    regime_override  = read_setting("regime_override") or None
    if regime_override == "자동":
        regime_override = None

    # 현재 금융자산 = 뽕구 기준 앱 관리 자산(나_잔고)만 사용.
    # 뽕구/뽕디 계좌 규모가 거의 비슷하므로 목표자산도 부부 합산 30억원의 절반인 15억원 기준으로 관리.
    # 외부자산 보정은 1단계에서 제외.
    managed_assets_total = 0.0
    if not df_raw.empty:
        managed_assets_total += float(asset_df["평가금액"].sum()) if not asset_df.empty else 0.0

    # ── 최종 목표 비중 계산 ────────────────────────────────────
    final = get_final_targets(
        retirement_year,
        current_fx,
        regime_override,
        birth_date=birth_date_setting,
        retirement_age=retirement_age,
        current_financial_assets=managed_assets_total,
        target_financial_assets=target_financial_assets,
        risk_adjust=risk_adjust,
    )
    lifecycle   = final["lifecycle"]
    regime_info = final["regime"]
    fx_info     = final["fx"]
    targets     = final["targets"]
    targets_fx  = final["targets_fx"]

    # ── 합계 ──────────────────────────────────────────────────
    total_eval   = float(asset_df["평가금액"].sum()) if not asset_df.empty else 0.0
    total_seed   = float((seed_df["보유수량"] * seed_df["매수평단"]).sum()) if not seed_df.empty else 0.0
    if total_seed <= 0 and not asset_df.empty:
        total_seed = float(asset_df["매수금액"].sum())
    total_profit = total_eval - total_seed
    hero_pct     = total_profit / total_seed * 100 if total_seed > 0 else 0

    # ── 헤더 ──────────────────────────────────────────────────
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    st.title("💰 Family Portfolio v2")

    # 장세 배지
    regime_name = regime_info["regime"]
    regime_cls  = {"상승장": "signal-up", "보합장": "signal-flat", "하락장": "signal-down"}.get(regime_name, "signal-flat")
    regime_emoji = {"상승장": "📈", "보합장": "➡️", "하락장": "📉"}.get(regime_name, "")
    st.markdown(
        f'<span class="regime-badge {regime_cls}">'
        f'{regime_emoji} {regime_name} | {lifecycle["stage"]} | {fx_info["label"]} {current_fx:,.0f}원'
        f'</span>', unsafe_allow_html=True
    )
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # 수익 히어로
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # 2단계 탭 소분류 헬퍼
    def sub_tabs(options: list, state_key: str):
        st.markdown("<div style='margin-bottom:-28px'></div>", unsafe_allow_html=True)
        choice = st.radio(
            label="hidden",
            options=options,
            horizontal=True,
            key=state_key,
            label_visibility="hidden",
        )
        return choice

    # ════════════════════════════════════════════════════════
    # 내부 렌더 함수 (소분류별)
    # ════════════════════════════════════════════════════════
    def _render_detail(p_asset_df, p_total_eval, p_label="default"):
        card("📊 종목 상세", "보유 종목 현황")
        if p_asset_df.empty:
            st.info("잔고 데이터가 없습니다.")
        else:
            sum_df = (
                p_asset_df.groupby(["자산군","약식종목명","종목코드"], dropna=False)
                .agg({"보유수량":"sum","매수금액":"sum","평가금액":"sum"})
                .reset_index()
            )
            sum_df["자산군_표시"] = sum_df["자산군"].apply(disp)
            sum_df["매수평단"] = sum_df.apply(lambda r: r["매수금액"]/r["보유수량"] if r["보유수량"] > 0 else 0, axis=1)
            sum_df["현재가"]   = sum_df.apply(lambda r: r["평가금액"]/r["보유수량"] if r["보유수량"] > 0 else 0, axis=1)
            sum_df["수익률"]   = sum_df.apply(lambda r: (r["평가금액"]-r["매수금액"])/r["매수금액"]*100 if r["매수금액"] > 0 else 0.0, axis=1)
            sum_df["비중"]     = sum_df["평가금액"] / p_total_eval * 100 if p_total_eval > 0 else 0

            show = sum_df[sum_df["보유수량"] > 0][
                ["자산군_표시","약식종목명","보유수량","매수평단","현재가","평가금액","비중","수익률"]
            ].rename(columns={"자산군_표시":"자산군","약식종목명":"종목"})
            show = safe_global_sort(show)
            st.dataframe(
                show.style.format({"보유수량":"{:,.0f}","매수평단":"{:,.0f}","현재가":"{:,.0f}","평가금액":"{:,.0f}","비중":"{:.1f}%","수익률":"{:.2f}%"}),
                use_container_width=True, hide_index=True,
            )

            # 종목 차트
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

            # 보유 종목 (★ 표시) + CODE_MAP 전체 종목
            held_tickers = {}
            for _, row in sum_df[(sum_df["보유수량"] > 0) & (~sum_df["종목코드"].str.upper().isin({"CASH","SEED","NAN",""}))].iterrows():
                key = f"★ {row['약식종목명']} ({row['종목코드']})"
                held_tickers[key] = {"code": str(row["종목코드"]), "name": str(row["약식종목명"]), "held": True}
            all_tickers = dict(held_tickers)
            for asset_k, meta in CODE_MAP.items():
                for side in ["노출","헤지","기본"]:
                    code = meta.get(side,"")
                    if not code: continue
                    label = meta["label"] + ("(H)" if side=="헤지" else "")
                    key = f"{label} ({code})"
                    if not any(v["code"]==code for v in all_tickers.values()):
                        all_tickers[key] = {"code": code, "name": label, "held": False}

            uid = p_label  # 고정 키 (매 렌더링마다 바뀌는 id() 대신 이름 사용)
            selected = st.selectbox("종목 선택 (★ 보유중)", list(all_tickers.keys()), key=f"chart_sel_{uid}")
            sel_code = all_tickers[selected]["code"]
            sel_name = all_tickers[selected]["name"]
            is_held  = all_tickers[selected]["held"]

            if is_held:
                sel_row = sum_df[sum_df["종목코드"] == sel_code]
                if not sel_row.empty:
                    pct = float(sel_row["수익률"].iloc[0])
                    color = "#ef4444" if pct >= 0 else "#60a5fa"
                    st.markdown(f"<div style='color:{color};font-size:1.0rem;font-weight:700'>보유 수익률 {'+' if pct>=0 else ''}{pct:.2f}%</div>", unsafe_allow_html=True)
            else:
                st.caption("미보유 종목 — 참고용 차트")

            # 3. 단기/장기 탭으로 분리
            chart_tab_key = f"chart_tab_{uid}_{sel_code}"
            chart_period  = sub_tabs(["📊 단기 (90일)", "📈 장기 (2년)"], chart_tab_key)

            with st.spinner("차트 불러오는 중..."):
                candle_df = get_candle_data(sel_code)

            if candle_df.empty:
                st.warning(f"'{sel_name}' 차트 데이터를 불러올 수 없습니다.")
            else:
                if chart_period == "📊 단기 (90일)":
                    st.plotly_chart(
                        make_single_candle_chart(candle_df.tail(90), f"{sel_name} 최근 90일"),
                        use_container_width=True, key=f"candle_s_{sel_code}_{uid}", config={"displayModeBar": False}
                    )
                else:
                    st.plotly_chart(
                        make_single_candle_chart(candle_df, f"{sel_name} 전체 (2년)"),
                        use_container_width=True, key=f"candle_l_{sel_code}_{uid}", config={"displayModeBar": False}
                    )

            if is_held:
                with st.expander("📋 계좌별 상세 보기", expanded=False):
                    acct_df = p_asset_df[p_asset_df["종목코드"]==sel_code][["계좌명","보유수량","매수평단","현재가","평가금액","수익률"]]
                    acct_df = safe_global_sort(acct_df)
                    if not acct_df.empty:
                        st.dataframe(acct_df.style.format({"보유수량":"{:,.0f}","매수평단":"{:,.0f}","현재가":"{:,.0f}","평가금액":"{:,.0f}","수익률":"{:.2f}%"}), use_container_width=True, hide_index=True)
        end_card()

    def _render_overall(p_asset_df, p_total_eval, p_targets):
        card("🍩 전체 포트폴리오 비중", "현재 vs 목표")
        if p_asset_df.empty:
            st.info("잔고 데이터가 없습니다.")
        else:
            grp = p_asset_df.groupby("자산군")["평가금액"].sum().reset_index()
            grp["자산군_표시"] = grp["자산군"].apply(disp)
            grp["비중"] = grp["평가금액"] / p_total_eval * 100 if p_total_eval > 0 else 0
            overall_target = {}
            for cat, t in p_targets.items():
                cat_total_v = float(p_asset_df[p_asset_df["계좌카테고리"]==cat]["평가금액"].sum())
                for a, w in t.items():
                    overall_target[a] = overall_target.get(a, 0) + w * cat_total_v
            if p_total_eval > 0:
                overall_target = {k: v/p_total_eval*100 for k,v in overall_target.items()}
            uid = "overall"
            st.plotly_chart(dual_donut(grp,"비중","자산군_표시",overall_target,center_title="총자산",center_value=fmt_krw(p_total_eval)),
                           use_container_width=True, key=f"overall_donut_{p_total_eval:.0f}", config={"displayModeBar":False})
            grp["목표"] = grp["자산군"].map(overall_target).fillna(0)
            grp["차이"] = grp["비중"] - grp["목표"]
            grp_show = safe_global_sort(grp[["자산군_표시","평가금액","비중","목표","차이"]])
            st.dataframe(grp_show.style.format({"평가금액":"{:,.0f}","비중":"{:.1f}%","목표":"{:.1f}%","차이":"{:+.1f}%"}), use_container_width=True, hide_index=True)
        end_card()

    def _render_category(p_asset_df, p_targets):
        if p_asset_df.empty:
            st.info("잔고 데이터가 없습니다.")
            return
        for cat in CATEGORY_ORDER:
            cat_df = p_asset_df[p_asset_df["계좌카테고리"]==cat]
            if cat_df.empty: continue
            cat_total_v = float(cat_df["평가금액"].sum())
            card(f"🏦 {cat}", f"총 {fmt_krw(cat_total_v)}")
            grp = cat_df.groupby("자산군")["평가금액"].sum().reset_index()
            grp["자산군_표시"] = grp["자산군"].apply(disp)
            grp["비중"] = grp["평가금액"] / cat_total_v * 100 if cat_total_v > 0 else 0
            target_map = {k: v*100 for k,v in p_targets.get(cat,{}).items()}
            grp["목표"] = grp["자산군"].map(target_map).fillna(0)
            grp["차이"] = grp["비중"] - grp["목표"]
            st.plotly_chart(dual_donut(grp,"비중","자산군_표시",target_map,center_title=cat,center_value=fmt_krw(cat_total_v)),
                           use_container_width=True, key=f"cat_donut_{cat}", config={"displayModeBar":False})
            grp_show = safe_global_sort(grp[["자산군_표시","평가금액","비중","목표","차이"]])
            st.dataframe(grp_show.style.format({"평가금액":"{:,.0f}","비중":"{:.1f}%","목표":"{:.1f}%","차이":"{:+.1f}%"}), use_container_width=True, hide_index=True)
            end_card()
            st.markdown("---")

    # ── 포트폴리오 컨텐츠 렌더 함수 ──────────────────────────
    def render_portfolio(p_asset_df, p_seed_df, p_total_eval, p_total_seed, p_targets, p_targets_fx, p_label):
        """포트폴리오 탭 컨텐츠 (뽕구/뽕디 공통)"""
        # 하위 탭
        sub = sub_tabs(["종목 상세", "전체 비중", "카테고리"], f"sub_{p_label}")

        # 컨텐츠
        if sub == "종목 상세":
            _render_detail(p_asset_df, p_total_eval, p_label)
        elif sub == "전체 비중":
            _render_overall(p_asset_df, p_total_eval, p_targets)
        elif sub == "카테고리":
            _render_category(p_asset_df, p_targets)

    # ── 1단계 탭 (st.tabs 복구) ───────────────────────────────
    tab_bbong, tab_spouse, tab_trade, tab_settings = st.tabs([
        f"📊 {USERS['me']['name']}",
        f"📊 {USERS['spouse']['name']}",
        "⚖️ 매매 / 리밸런싱",
        "⚙️ 설정",
    ])

    # ── 수익 카드 렌더 헬퍼 ───────────────────────────────────
    def hero_card(p_eval, p_seed, p_label):
        p_profit     = p_eval - p_seed
        p_pct        = p_profit / p_seed * 100 if p_seed > 0 else 0
        delta_color  = "#4ade80" if p_profit >= 0 else "#60a5fa"
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,rgba(30,41,59,0.96),rgba(15,23,42,0.96));
             border:1px solid rgba(148,163,184,0.12);border-radius:16px;
             padding:14px 18px;margin:8px 0 10px 0;">
            <div style="color:#94a3b8;font-size:0.76rem">{p_label} 누적 수익</div>
            <div style="font-size:1.7rem;font-weight:800;letter-spacing:-0.03em;line-height:1.3">{p_pct:.2f}%</div>
            <div style="color:{delta_color};font-size:0.82rem;margin-bottom:10px">{p_profit:+,.0f}원</div>
            <div style="border-top:1px solid rgba(148,163,184,0.08);padding-top:8px;
                        display:flex;justify-content:space-between">
                <div>
                    <div style="color:#94a3b8;font-size:0.70rem">현재 자산</div>
                    <div style="font-size:0.95rem;font-weight:700">{p_eval:,.0f}원</div>
                </div>
                <div style="text-align:right">
                    <div style="color:#94a3b8;font-size:0.70rem">총 투입원금</div>
                    <div style="font-size:0.95rem;font-weight:700">{p_seed:,.0f}원</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # ════════════════════════════════════════════════════════
    # 탭 1: 뽕구
    # ════════════════════════════════════════════════════════
    with tab_bbong:
        # 최초 로딩한 df_raw/asset_df 재사용: Google Sheets와 시세 API 중복 호출 최소화
        me_raw = df_raw
        if me_raw.empty:
            st.info("잔고 데이터가 없습니다.")
        else:
            me_seed_df, me_asset = seed_df, asset_df
            me_eval     = float(me_asset["평가금액"].sum()) if not me_asset.empty else 0
            me_seed_amt = float((me_seed_df["보유수량"] * me_seed_df["매수평단"]).sum()) if not me_seed_df.empty else float(me_asset["매수금액"].sum()) if not me_asset.empty else 0
            hero_card(me_eval, me_seed_amt, USERS["me"]["name"])
            render_portfolio(me_asset, me_seed_df, me_eval, me_seed_amt, targets, targets_fx, USERS["me"]["name"])

    # ════════════════════════════════════════════════════════
    # 탭 2: 뽕디
    # ════════════════════════════════════════════════════════
    with tab_spouse:
        sp_raw = load_assets(USERS["spouse"]["sheet_assets"])
        if sp_raw.empty:
            st.info("아직 잔고 데이터가 없습니다.")
        else:
            sp_seed_df, sp_asset, _ = prepare_assets(sp_raw)
            sp_eval     = float(sp_asset["평가금액"].sum()) if not sp_asset.empty else 0
            sp_seed_amt = float((sp_seed_df["보유수량"] * sp_seed_df["매수평단"]).sum()) if not sp_seed_df.empty else float(sp_asset["매수금액"].sum()) if not sp_asset.empty else 0
            hero_card(sp_eval, sp_seed_amt, USERS["spouse"]["name"])
            render_portfolio(sp_asset, sp_seed_df, sp_eval, sp_seed_amt, targets, targets_fx, USERS["spouse"]["name"])

    # ════════════════════════════════════════════════════════
    # 탭 3: 매매 / 리밸런싱
    # ════════════════════════════════════════════════════════
    with tab_trade:
        trade_sub = sub_tabs(["리밸런싱", "매매 입력", "매매 기록"], "trade_sub")

        if trade_sub == "리밸런싱":
            card("⚖️ 리밸런싱", f"{user_name} 계좌 기준 목표 비중 대비 조정 수량")

            st.caption(
                f"엔진 상태: 기존 안정 엔진"
                f" · v4 Layer1 {'ON' if USE_V4_LAYER1_POLICY else 'OFF'}"
            )

            # 환헤지 비율 요약
            fx_hedge_pct   = fx_info["헤지"] * 100
            fx_exposed_pct = fx_info["노출"] * 100
            st.markdown(f"""
            <div style="background:rgba(15,23,42,0.6);border:1px solid rgba(148,163,184,0.1);
                        border-radius:12px;padding:10px 16px;margin-bottom:12px;font-size:0.82rem">
                🌎 현재 환율: <b>{current_fx:,.0f}원</b> →
                <span style="color:#f97316">헤지 {fx_hedge_pct:.0f}%</span> /
                <span style="color:#3b82f6">노출 {fx_exposed_pct:.0f}%</span>
                &nbsp;|&nbsp; 구간: <b>{fx_info['label']}</b>
            </div>
            """, unsafe_allow_html=True)

            # 장세/생애주기/환율 - 컴팩트 카드
            def sig_color(s):
                return "#4ade80" if s in ("상승","안정") else "#60a5fa" if s in ("하락","공포") else "#f59e0b"

            st.markdown(f"""
            <div style="display:flex;flex-direction:column;gap:6px;margin-bottom:10px">
              <div style="background:rgba(17,24,39,0.7);border:1px solid rgba(148,163,184,0.1);
                          border-radius:10px;padding:10px 14px;display:flex;justify-content:space-between;align-items:center">
                <div>
                  <div style="color:#94a3b8;font-size:0.70rem">장세</div>
                  <div style="font-size:1.0rem;font-weight:700">{regime_info['regime']}</div>
                </div>
                <div style="color:{sig_color(regime_info['regime'])};font-size:0.75rem;font-weight:600;
                            background:rgba(0,0,0,0.2);padding:3px 8px;border-radius:6px">
                  신뢰도 {regime_info['confidence']*100:.0f}%
                </div>
              </div>
              <div style="background:rgba(17,24,39,0.7);border:1px solid rgba(148,163,184,0.1);
                          border-radius:10px;padding:10px 14px;display:flex;justify-content:space-between;align-items:center">
                <div>
                  <div style="color:#94a3b8;font-size:0.70rem">생애주기</div>
                  <div style="font-size:1.0rem;font-weight:700">{lifecycle['stage']}</div>
                </div>
                <div style="color:#4ade80;font-size:0.75rem;font-weight:600;
                            background:rgba(0,0,0,0.2);padding:3px 8px;border-radius:6px">
                  은퇴까지 {lifecycle['years_left']}년
                </div>
              </div>
              <div style="background:rgba(17,24,39,0.7);border:1px solid rgba(148,163,184,0.1);
                          border-radius:10px;padding:10px 14px;display:flex;justify-content:space-between;align-items:center">
                <div>
                  <div style="color:#94a3b8;font-size:0.70rem">환율 구간</div>
                  <div style="font-size:1.0rem;font-weight:700">{fx_info['label']} ({current_fx:,.0f}원)</div>
                </div>
                <div style="font-size:0.75rem;font-weight:600;
                            background:rgba(0,0,0,0.2);padding:3px 8px;border-radius:6px">
                  <span style="color:#f97316">헤지 {fx_hedge_pct:.0f}%</span>
                  <span style="color:#94a3b8"> / </span>
                  <span style="color:#3b82f6">노출 {fx_exposed_pct:.0f}%</span>
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)

            # 장세 판단 상세
            with st.expander("📡 장세 판단 상세", expanded=False):
                sigs = regime_info.get("signals", {})
                t_s = sigs.get("trend", {})
                m_s = sigs.get("momentum", {})
                v_s = sigs.get("vix", {})
                t_val   = f"{t_s.get('value', 0):,.0f}" if t_s.get('value') else "-"
                t_delta = f"MA200 대비 {t_s.get('gap_pct', 0):+.1f}%" if t_s.get('gap_pct') is not None else "-"
                m_val   = f"{m_s.get('value', 0):+.2f}%" if m_s.get('value') is not None else "-"
                v_val   = f"{v_s.get('value', 0):.1f}" if v_s.get('value') else "-"
                st.markdown(f"""
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:8px">
                  <div style="background:rgba(17,24,39,0.88);border:1px solid rgba(148,163,184,0.12);border-radius:16px;padding:16px;height:110px;box-sizing:border-box">
                    <div style="color:#94a3b8;font-size:0.78rem">추세 (200일선)</div>
                    <div style="font-size:1.4rem;font-weight:700;margin:4px 0">{t_val}</div>
                    <div style="color:#4ade80;font-size:0.78rem">^ {t_delta}</div>
                    <div style="color:{sig_color(t_s.get('signal','-'))};font-size:0.75rem;margin-top:4px">신호: {t_s.get('signal','-')}</div>
                  </div>
                  <div style="background:rgba(17,24,39,0.88);border:1px solid rgba(148,163,184,0.12);border-radius:16px;padding:16px;height:110px;box-sizing:border-box">
                    <div style="color:#94a3b8;font-size:0.78rem">모멘텀 (3개월)</div>
                    <div style="font-size:1.4rem;font-weight:700;margin:4px 0">{m_val}</div>
                    <div style="font-size:0.78rem;color:transparent">-</div>
                    <div style="color:{sig_color(m_s.get('signal','-'))};font-size:0.75rem;margin-top:4px">신호: {m_s.get('signal','-')}</div>
                  </div>
                  <div style="background:rgba(17,24,39,0.88);border:1px solid rgba(148,163,184,0.12);border-radius:16px;padding:16px;height:110px;box-sizing:border-box">
                    <div style="color:#94a3b8;font-size:0.78rem">VIX</div>
                    <div style="font-size:1.4rem;font-weight:700;margin:4px 0">{v_val}</div>
                    <div style="font-size:0.78rem;color:transparent">-</div>
                    <div style="color:{sig_color(v_s.get('signal','-'))};font-size:0.75rem;margin-top:4px">신호: {v_s.get('signal','-')}</div>
                  </div>
                </div>
                """, unsafe_allow_html=True)

            st.divider()

            if asset_df.empty:
                st.info("잔고 데이터가 없습니다.")
            else:
                c_opt1, c_opt2, c_opt3 = st.columns(3)
                with c_opt1:
                    min_trade_amt = st.number_input("최소 주문금액", min_value=0, value=50_000, step=10_000, key="rebal_min_trade")
                with c_opt2:
                    cash_buffer_pct = st.number_input("현금 버퍼 (%)", min_value=0.0, value=0.5, step=0.1, key="rebal_cash_buffer")
                with c_opt3:
                    fee_rate_pct = st.number_input("예상 수수료 (%)", min_value=0.0, value=0.015, step=0.005, format="%.3f", key="rebal_fee")

                all_plans, all_rules, all_warns = [], [], []
                for cat in CATEGORY_ORDER:
                    plan, rules, warns = calc_rebalance(
                        asset_df, cat, targets_fx.get(cat, {}),
                        min_trade_amt=float(min_trade_amt),
                        cash_buffer_ratio=float(cash_buffer_pct) / 100,
                        fee_rate=float(fee_rate_pct) / 100,
                    )
                    all_plans.extend(plan)
                    all_rules.extend(rules)
                    all_warns.extend(warns)

                for w in all_warns:
                    st.warning(w)

                plan_df = pd.DataFrame(all_plans) if all_plans else pd.DataFrame()
                cat_list = ["전체"] + CATEGORY_ORDER
                sel_cat  = st.selectbox("계좌 카테고리 선택", cat_list, key="rebal_cat_sel")

                if plan_df.empty or "계좌카테고리" not in plan_df.columns:
                    view_df = pd.DataFrame()
                else:
                    view_df = plan_df if sel_cat == "전체" else plan_df[plan_df["계좌카테고리"] == sel_cat]

                if not view_df.empty:
                    # Adaptive Buy Signal Engine v1.1
                    # 목표부족금액을 연말까지 남은 거래일로 안분하고, Timing Score로 DCA 강도만 조절한다.
                    timing_df = generate_buy_signals(
                        view_df,
                        regime_info=regime_info,
                        fx_info=fx_info,
                        monthly_budget=0,
                    )
                    if not timing_df.empty:
                        view_df = pd.concat(
                            [view_df.reset_index(drop=True), timing_df.drop(columns=["_row_id"], errors="ignore").reset_index(drop=True)],
                            axis=1,
                        )
                    else:
                        signal_rows = view_df.apply(lambda r: make_light_trade_signal(r, regime_info["regime"]), axis=1)
                        signal_df = pd.DataFrame(signal_rows.tolist(), index=view_df.index)
                        view_df = pd.concat([view_df.reset_index(drop=True), signal_df.reset_index(drop=True)], axis=1)

                    # 실행 중심 요약
                    st.markdown("#### 📋 실행 요약")

                    exec_df = view_df[view_df.get("실행여부", "실행") == "실행"].copy()
                    if not exec_df.empty and "조정수량" in exec_df.columns:
                        exec_df = exec_df[pd.to_numeric(exec_df["조정수량"], errors="coerce").fillna(0) != 0].copy()

                    buy_amt = float(exec_df[exec_df["구분"] == "매수"]["예상주문금액"].sum()) if not exec_df.empty and "예상주문금액" in exec_df.columns else 0.0
                    sell_amt = float(exec_df[exec_df["구분"] == "매도"]["예상주문금액"].sum()) if not exec_df.empty and "예상주문금액" in exec_df.columns else 0.0
                    base_dca_amt = float(exec_df["기본DCA"].sum()) if not exec_df.empty and "기본DCA" in exec_df.columns else 0.0
                    bonus_amt = float(exec_df["AdaptiveBonus"].sum()) if not exec_df.empty and "AdaptiveBonus" in exec_df.columns else 0.0
                    rec_buy_amt = float(exec_df["추천금액"].sum()) if not exec_df.empty and "추천금액" in exec_df.columns else 0.0
                    exec_count = int(len(exec_df)) if not exec_df.empty else 0

                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("목표부족 매수액", f"{buy_amt:,.0f}원")
                    m2.metric("기본 DCA", f"{base_dca_amt:,.0f}원")
                    m3.metric("Adaptive Bonus", f"{bonus_amt:+,.0f}원")
                    m4.metric("오늘 추천매수", f"{rec_buy_amt:,.0f}원")
                    st.caption(f"실행 종목 수 {exec_count}개 · 총 매도 예상금액 {sell_amt:,.0f}원")

                    if exec_df.empty:
                        st.info("실행할 리밸런싱 주문이 없습니다.")
                    else:
                        compact_df = exec_df.copy()

                        def _short_memo(row):
                            hold = str(row.get("보류사유", "") or "").strip()
                            rec = str(row.get("추천사유", "") or "").strip()
                            sig = str(row.get("신호사유", "") or "").strip()
                            if hold:
                                return hold
                            if rec:
                                return rec.split(";")[0].strip()
                            if sig:
                                return sig.split(";")[0].strip()
                            return ""

                        compact_df["메모"] = compact_df.apply(_short_memo, axis=1)

                        compact_cols = ["계좌카테고리", "약식종목명", "구분", "추천등급", "추천행동", "TimingScore", "기본DCA", "AdaptiveBonus", "추천금액", "조정수량", "예상주문금액", "메모"]
                        compact_cols = [c for c in compact_cols if c in compact_df.columns]
                        compact_df = safe_global_sort(compact_df)

                        compact_style = compact_df[compact_cols].style
                        if "조정수량" in compact_cols:
                            compact_style = compact_style.map(
                                lambda x: "color:#ef4444;font-weight:700" if isinstance(x, (int, float, np.integer, np.floating)) and x > 0
                                else "color:#60a5fa;font-weight:700" if isinstance(x, (int, float, np.integer, np.floating)) and x < 0
                                else "",
                                subset=["조정수량"],
                            )
                        if "구분" in compact_cols:
                            compact_style = compact_style.map(
                                lambda x: "color:#ef4444" if x == "매수" else "color:#60a5fa" if x == "매도" else "",
                                subset=["구분"],
                            )

                        st.dataframe(
                            compact_style.format({
                                "TimingScore": "{:.1f}",
                                "기본DCA": "{:,.0f}",
                                "AdaptiveBonus": "{:+,.0f}",
                                "추천금액": "{:,.0f}",
                                "조정수량": "{:+,.0f}",
                                "예상주문금액": "{:,.0f}",
                            }),
                            use_container_width=True,
                            hide_index=True,
                        )

                    st.markdown("#### 🎯 오늘 계좌별 매수 추천")
                    today_order_df = allocate_today_orders(asset_df, exec_df)
                    if today_order_df.empty:
                        st.info("오늘 실행 가능한 계좌별 매수 추천이 없습니다.")
                    else:
                        today_order_df = safe_global_sort(today_order_df)

                        buy_now_df = today_order_df[pd.to_numeric(today_order_df["추천수량"], errors="coerce").fillna(0) > 0].copy()
                        carry_df = today_order_df[pd.to_numeric(today_order_df["추천수량"], errors="coerce").fillna(0) <= 0].copy()

                        a1, a2, a3 = st.columns(3)
                        a1.metric("오늘 실제 주문 가능액", f"{buy_now_df['실행추천금액'].sum() if not buy_now_df.empty else 0:,.0f}원")
                        a2.metric("1주 미만 누적액", f"{carry_df['미집행누적금액'].sum() if not carry_df.empty else 0:,.0f}원")
                        a3.metric("오늘 주문 수", f"{len(buy_now_df)}개")

                        main_cols = [
                            "계좌카테고리", "추천계좌", "약식종목명",
                            "추천등급", "추천행동", "TimingScore",
                            "기본DCA", "AdaptiveBonus", "추천금액",
                            "현재가", "추천수량", "실행추천금액", "선택근거",
                        ]
                        main_cols = [c for c in main_cols if c in today_order_df.columns]

                        if buy_now_df.empty:
                            st.info("오늘 1주 이상 실제 매수 가능한 추천은 없습니다. 1주 미만 금액은 아래 누적 후보에서 확인하세요.")
                        else:
                            st.caption("실제 오늘 주문 가능한 종목만 표시합니다.")
                            st.dataframe(
                                buy_now_df[main_cols].style.format({
                                    "TimingScore": "{:.1f}",
                                    "기본DCA": "{:,.0f}",
                                    "AdaptiveBonus": "{:+,.0f}",
                                    "추천금액": "{:,.0f}",
                                    "현재가": "{:,.0f}",
                                    "추천수량": "{:,.0f}",
                                    "실행추천금액": "{:,.0f}",
                                }),
                                use_container_width=True,
                                hide_index=True,
                            )

                        with st.expander("🧺 1주 미만 누적 후보 보기", expanded=False):
                            if carry_df.empty:
                                st.info("1주 미만 누적 후보가 없습니다.")
                            else:
                                carry_cols = [
                                    "계좌카테고리", "추천계좌", "약식종목명",
                                    "추천등급", "추천행동", "TimingScore",
                                    "기본DCA", "AdaptiveBonus", "추천금액",
                                    "현재가", "미집행누적금액", "선택근거",
                                ]
                                carry_cols = [c for c in carry_cols if c in carry_df.columns]
                                st.caption("추천금액이 1주 가격보다 작아 오늘은 주문하지 않고 누적 관찰할 후보입니다.")
                                st.dataframe(
                                    carry_df[carry_cols].style.format({
                                        "TimingScore": "{:.1f}",
                                        "기본DCA": "{:,.0f}",
                                        "AdaptiveBonus": "{:+,.0f}",
                                        "추천금액": "{:,.0f}",
                                        "현재가": "{:,.0f}",
                                        "미집행누적금액": "{:,.0f}",
                                    }),
                                    use_container_width=True,
                                    hide_index=True,
                                )

                    with st.expander("🔎 계산 상세 보기", expanded=False):
                        st.caption("현재비중, 목표비중, 괴리율, 신호점수 등 검증용 컬럼입니다.")
                        detail_cols = [
                            "계좌카테고리", "약식종목명", "구분",
                            "현재비중", "목표비중", "괴리율",
                            "TimingScore", "추천등급", "추천행동", "DCA조정", "BonusRate", "남은거래일",
                            "목표부족금액", "기본DCA", "AdaptiveBonus", "추천금액", "추천사유",
                            "조정수량", "예상주문금액",
                            "실행여부", "보류사유",
                        ]
                        detail_cols = [c for c in detail_cols if c in view_df.columns]
                        detail_df = safe_global_sort(view_df.copy())
                        detail_style = detail_df[detail_cols].style
                        if "조정수량" in detail_cols:
                            detail_style = detail_style.map(
                                lambda x: "color:#ef4444" if isinstance(x, (int, float, np.integer, np.floating)) and x > 0
                                else "color:#60a5fa" if isinstance(x, (int, float, np.integer, np.floating)) and x < 0
                                else "",
                                subset=["조정수량"],
                            )
                        st.dataframe(
                            detail_style.format({
                                "현재비중": "{:.2f}%",
                                "목표비중": "{:.2f}%",
                                "괴리율": "{:+.2f}%",
                                "TimingScore": "{:.1f}",
                                "DCA조정": "{:.2f}x",
                                "BonusRate": "{:+.1f}%",
                                "남은거래일": "{:,.0f}",
                                "목표부족금액": "{:,.0f}",
                                "기본DCA": "{:,.0f}",
                                "AdaptiveBonus": "{:+,.0f}",
                                "추천금액": "{:,.0f}",
                                "조정수량": "{:+,.0f}",
                                "예상주문금액": "{:,.0f}",
                            }),
                            use_container_width=True,
                            hide_index=True,
                        )

                    st.markdown("#### 💼 전체 목표부족 기준 계좌별 참고")
                    st.caption("아래 표는 오늘 DCA가 아니라 전체 목표부족 수량을 계좌 평가금액 비율로 나눈 참고표입니다.")
                    acct_summary = []
                    for cat in (CATEGORY_ORDER if sel_cat == "전체" else [sel_cat]):
                        cat_plan = view_df[view_df["계좌카테고리"] == cat]
                        if cat_plan.empty: continue
                        cat_asset_df  = asset_df[asset_df["계좌카테고리"] == cat]
                        cat_total_amt = float(cat_asset_df["평가금액"].sum())
                        acct_ratios   = {}
                        if cat_total_amt > 0:
                            for acct in cat_asset_df["계좌명"].dropna().unique():
                                acct_amt = float(cat_asset_df[cat_asset_df["계좌명"]==acct]["평가금액"].sum())
                                acct_ratios[acct] = acct_amt / cat_total_amt
                        else:
                            accts_list = cat_asset_df["계좌명"].dropna().unique().tolist()
                            for acct in accts_list:
                                acct_ratios[acct] = 1.0 / len(accts_list) if accts_list else 0

                        for _, row in cat_plan.iterrows():
                            if row.get("실행여부", "실행") != "실행":
                                continue
                            total_qty = int(row.get("조정수량", 0))
                            if total_qty == 0: continue
                            remaining = abs(total_qty)
                            for i, acct in enumerate(acct_ratios.keys()):
                                if i == len(acct_ratios) - 1:
                                    qty = remaining
                                else:
                                    qty = round(abs(total_qty) * acct_ratios[acct])
                                    remaining -= qty
                                if qty <= 0: continue
                                acct_summary.append({
                                    "계좌카테고리": cat,
                                    "계좌명": acct,
                                    "약식종목명": row["약식종목명"],
                                    "구분": "매수" if total_qty > 0 else "매도",
                                    "조정수량": qty,
                                    "예상금액": qty * float(row["현재가"]),
                                })

                    if acct_summary:
                        summ_df = safe_global_sort(pd.DataFrame(acct_summary), qty_priority=False)

                        acct_options = ["전체"] + summ_df["계좌명"].dropna().astype(str).drop_duplicates().tolist()
                        sel_exec_acct = st.selectbox(
                            "실행 계좌 선택",
                            acct_options,
                            key="exec_acct_sel",
                        )

                        if sel_exec_acct != "전체":
                            summ_view_df = summ_df[summ_df["계좌명"].astype(str) == sel_exec_acct].copy()
                        else:
                            summ_view_df = summ_df.copy()

                        if summ_view_df.empty:
                            st.info("선택한 계좌의 실행 내역이 없습니다.")
                        else:
                            st.dataframe(
                                summ_view_df[["계좌명","약식종목명","구분","조정수량","예상금액"]]
                                .style.format({"조정수량":"{:,.0f}","예상금액":"{:,.0f}"})
                                .map(lambda x: "color:#ef4444" if x=="매수" else "color:#60a5fa" if x=="매도" else "", subset=["구분"]),
                                use_container_width=True, hide_index=True,
                            )
                            c1, c2 = st.columns(2)
                            c1.metric("표시 매수 예상금액", f"{summ_view_df[summ_view_df['구분']=='매수']['예상금액'].sum():,.0f}원")
                            c2.metric("표시 매도 예상금액", f"{summ_view_df[summ_view_df['구분']=='매도']['예상금액'].sum():,.0f}원")

                if all_rules:
                    st.divider()
                    st.markdown("#### 🏦 IRP 안전자산 30% 점검")
                    rules_df = pd.DataFrame(all_rules)
                    if sel_cat != "전체":
                        irp_accts = asset_df[(asset_df["계좌카테고리"]==sel_cat) & (asset_df["계좌명"].str.upper().str.contains("IRP", na=False))]["계좌명"].unique()
                        rules_df = rules_df[rules_df["계좌명"].isin(irp_accts)]
                    if not rules_df.empty:
                        rules_df = safe_global_sort(rules_df)
                        st.dataframe(rules_df.style.format({"현재 안전자산 비중":"{:.1f}%","목표 안전자산 비중":"{:.1f}%","부족 안전자산":"{:.1f}%","부족 안전자산 금액":"{:,.0f}"}), use_container_width=True, hide_index=True)
            end_card()

        elif trade_sub == "매매 입력":
            card("📝 매매 체결 입력", f"{user_name} 계좌 — 체결 내역 입력 시 잔고 자동 반영")

            ticker_map = {}
            for asset_k, meta in CODE_MAP.items():
                for side in ["노출","헤지","기본"]:
                    code = meta.get(side,"")
                    if not code: continue
                    label = meta["label"] + ("(H)" if side=="헤지" else "")
                    ticker_map[label] = {"code": code, "asset": asset_k}
            ticker_map["현금"] = {"code": "CASH", "asset": "현금"}
            ticker_list = list(ticker_map.keys())

            inp_date = st.date_input("체결 일자", value=datetime.today(), key="inp_date")
            inp_type = st.radio("구분", ["매수","매도"], horizontal=True, key="inp_type")

            col_a, col_b = st.columns(2)
            with col_a:
                inp_cat = st.selectbox("계좌카테고리", CATEGORY_ORDER, key="inp_cat")
            with col_b:
                cat_accts = sorted(asset_df[asset_df["계좌카테고리"]==inp_cat]["계좌명"].dropna().unique().tolist()) if not asset_df.empty else []
                inp_acct  = st.selectbox("계좌명", cat_accts if cat_accts else ["직접입력"], key="inp_acct_sel") if cat_accts else st.text_input("계좌명", key="inp_acct_txt")

            inp_name   = st.selectbox("종목명", ticker_list, key="inp_name_sel")
            auto_code  = ticker_map[inp_name]["code"]
            auto_asset = ticker_map[inp_name]["asset"]

            @st.cache_data(ttl=600, show_spinner=False)
            def get_latest_price(code: str) -> int:
                if not code or code.upper() in {"CASH","SEED"}: return 0
                val = get_price_data((code,)).get(str(code).strip(), 0)
                return int(val) if val and val > 0 else 0

            latest_price = get_latest_price(auto_code)
            price_label  = f"{latest_price:,}원" if latest_price > 0 else "조회 실패"
            st.caption(f"📌 종목코드: `{auto_code}` | 자산군: `{auto_asset}` | 당일 종가: **{price_label}**")

            col_c, col_d = st.columns(2)
            with col_c:
                inp_qty = st.number_input("체결수량 (주)", min_value=0, value=0, step=1, format="%d", key="inp_qty")
            with col_d:
                inp_price = st.number_input("체결가 (원)", min_value=0, step=100, value=latest_price, key="inp_price")

            inp_memo = st.text_input("메모 (선택)", key="inp_memo")
            inp_amt  = inp_qty * inp_price
            if inp_qty > 0 and inp_price > 0:
                st.info(f"💰 체결금액: **{inp_amt:,.0f}원**")

            final_acct = str(inp_acct)
            if st.button("✅ 매매 기록 저장 + 잔고 업데이트", use_container_width=True, type="primary"):
                if not final_acct or not inp_name or inp_qty <= 0 or inp_price <= 0:
                    st.error("계좌명, 종목명, 수량, 체결가는 필수입니다.")
                else:
                    append_row(SHEET_TRADES, {"일자":str(inp_date),"계좌카테고리":inp_cat,"계좌명":final_acct,"자산군":auto_asset,"약식종목명":inp_name,"종목코드":auto_code,"구분":inp_type,"체결수량":inp_qty,"체결가":inp_price,"체결금액":inp_amt,"메모":inp_memo})
                    assets = load_assets(SHEET_ASSETS)
                    if not assets.empty:
                        # Google Sheets에서 읽은 숫자 컬럼이 int64로 잡히면
                        # 평균단가(예: 23171.67) 같은 소수 값을 대입할 때 pandas가 오류를 냅니다.
                        # 매매 업데이트 전 수량/평단 컬럼을 float로 고정합니다.
                        for _num_col in ["보유수량", "매수평단"]:
                            if _num_col in assets.columns:
                                assets[_num_col] = pd.to_numeric(assets[_num_col], errors="coerce").fillna(0).astype(float)

                        mask = (assets["계좌명"]==final_acct) & (assets["종목코드"]==auto_code)
                        if mask.any():
                            idx = assets[mask].index[0]
                            cur_qty = float(assets.at[idx,"보유수량"])
                            cur_avg = float(assets.at[idx,"매수평단"])
                            if inp_type == "매수":
                                new_qty = cur_qty + inp_qty
                                new_avg = (cur_qty*cur_avg + inp_amt) / new_qty if new_qty > 0 else 0
                            else:
                                new_qty = max(cur_qty - inp_qty, 0)
                                new_avg = cur_avg
                            assets.at[idx,"보유수량"] = new_qty
                            assets.at[idx,"매수평단"] = round(new_avg, 2)
                        else:
                            assets = pd.concat([assets, pd.DataFrame([{"계좌명":final_acct,"종목명":inp_name,"종목코드":auto_code,"보유수량":inp_qty if inp_type=="매수" else 0,"매수평단":inp_price if inp_type=="매수" else 0,"약식종목명":inp_name,"계좌카테고리":inp_cat,"자산군":auto_asset}])], ignore_index=True)
                        # 예수금(현금) 자동 조정
                        cash_mask = (
                            (assets["계좌명"] == final_acct) &
                            (assets["자산군"] == "현금")
                        )
                        if cash_mask.any():
                            cash_idx = assets[cash_mask].index[0]
                            cur_cash = float(assets.at[cash_idx, "보유수량"])
                            if inp_type == "매수":
                                assets.at[cash_idx, "보유수량"] = max(cur_cash - inp_amt, 0)
                            else:  # 매도
                                assets.at[cash_idx, "보유수량"] = cur_cash + inp_amt

                        write_sheet(SHEET_ASSETS, assets)
                        st.cache_data.clear()
                        st.success(f"✅ {inp_type} 완료! 예수금 {'차감' if inp_type == '매수' else '추가'}: {inp_amt:,.0f}원")
                        st.rerun()
                    else:
                        st.warning("잔고 시트가 비어있습니다.")
            end_card()

        elif trade_sub == "매매 기록":
            card("📋 매매 기록", f"{user_name} 계좌 전체 매매 이력")
            if trades_df.empty:
                st.info("매매 기록이 없습니다.")
            else:
                st.dataframe(
                    safe_global_sort(trades_df.iloc[::-1][["일자","계좌카테고리","계좌명","약식종목명","구분","체결수량","체결가","체결금액"]])
                    .style.format({"체결수량":"{:,.0f}","체결가":"{:,.0f}","체결금액":"{:,.0f}"}),
                    use_container_width=True, hide_index=True,
                )
            end_card()

    # ════════════════════════════════════════════════════════
    # 탭 4: 설정
    # ════════════════════════════════════════════════════════
    with tab_settings:
        setting_sub = sub_tabs(["포트폴리오 설정", "잔고 수정"], "setting_sub")

        if setting_sub == "포트폴리오 설정":
            card("⚙️ 포트폴리오 설정", "은퇴 연도, 장세 설정")
            st.markdown("#### Adaptive Layer 1")
            st.caption(
                f"Feature Flags · v4 Layer1: {'ON' if USE_V4_LAYER1_POLICY else 'OFF'} / "
                f"Account Allocator: {'ON' if USE_ACCOUNT_ALLOCATOR else 'OFF'} / "
                f"Constraint Drift: {'ON' if SHOW_CONSTRAINT_DRIFT else 'OFF'}"
            )
            st.caption(f"Raw FEATURE_FLAGS: {FEATURE_FLAGS}")
            lc = lifecycle
            c_l1, c_l2, c_l3, c_l4 = st.columns(4)
            c_l1.metric("현재 나이", f"{lc.get('age', 0)}세")
            c_l2.metric("은퇴까지", f"{lc.get('years_left', 0)}년")
            c_l3.metric("Risk Score", f"{lc.get('risk_score', 0):.1f}")
            c_l4.metric("목표 달성률", f"{lc.get('goal_progress', 0):.1f}%")

            st.caption(
                f"현재 금융자산은 외부자산 보정 없이 뽕구 앱 관리 자산만 사용합니다: "
                f"{fmt_krw(lc.get('current_financial_assets', 0))} / 목표 {fmt_krw(lc.get('target_financial_assets', 0))}"
                f" · 부부 합산 목표 30억원의 절반 기준"
            )

            col_s1, col_s2 = st.columns(2)
            with col_s1:
                new_birth_date = st.date_input(
                    "생년월일",
                    value=pd.to_datetime(birth_date_setting).date(),
                    key="birth_date_input",
                )
                new_ret_age = st.number_input(
                    "목표 은퇴나이",
                    min_value=40, max_value=80,
                    value=int(retirement_age), step=1,
                    key="retirement_age_input",
                )
                new_target_assets_oku = st.number_input(
                    "목표 금융자산 (억원)",
                    min_value=1.0, max_value=100.0,
                    value=float(target_financial_assets) / 1e8,
                    step=0.5,
                    format="%.1f",
                    key="target_assets_oku",
                )
                new_risk_adjust = st.slider(
                    "위험성향 보정",
                    min_value=-10, max_value=10,
                    value=int(risk_adjust), step=1,
                    help="Risk Score에 직접 더하는 보정값입니다. 1단계에서는 선택값으로만 사용합니다.",
                    key="risk_adjust_slider",
                )
                if st.button("Adaptive 설정 저장"):
                    write_setting("birth_date", new_birth_date.isoformat())
                    write_setting("retirement_age", int(new_ret_age))
                    write_setting("target_financial_assets", int(new_target_assets_oku * 1e8))
                    write_setting("risk_adjust", int(new_risk_adjust))
                    st.cache_data.clear()
                    st.success("✅ Adaptive Layer 1 설정 저장 완료")
                    st.rerun()
            with col_s2:
                regime_options = ["자동 (지표 기반)", "상승장", "보합장", "하락장"]
                cur_override   = regime_override or "자동 (지표 기반)"
                if cur_override not in regime_options: cur_override = "자동 (지표 기반)"
                new_regime = st.selectbox("장세 수동 설정", regime_options, index=regime_options.index(cur_override), key="regime_sel")
                if st.button("장세 설정 저장"):
                    write_setting("regime_override", "자동" if new_regime == "자동 (지표 기반)" else new_regime)
                    st.cache_data.clear()
                    st.success(f"✅ {new_regime}")
                    st.rerun()

                st.markdown("##### 현재 Layer 1 기본비중")
                layer1_df = pd.DataFrame([
                    {"자산군": disp(k), "비중": f"{v*100:.1f}%"}
                    for k, v in lc.get("targets", {}).items()
                ])
                st.dataframe(layer1_df, use_container_width=True, hide_index=True)

            st.divider()
            st.markdown("#### 현재 최종 목표 비중")
            for cat in CATEGORY_ORDER:
                t = targets.get(cat, {})
                if t:
                    st.caption(f"**{cat}**")
                    st.dataframe(pd.DataFrame([{"자산군":disp(k),"목표 비중":f"{v*100:.1f}%"} for k,v in t.items()]), use_container_width=True, hide_index=True)
            end_card()

        elif setting_sub == "잔고 수정":
            card("✏️ 잔고 직접 수정", f"{user_name} 잔고 — 초기 입력 및 수동 보정용")
            st.info("💡 매매 입력을 통해 체결 기록을 넣으면 잔고가 자동 반영됩니다.")
            assets = load_assets(SHEET_ASSETS)
            with st.expander("➕ 종목 추가", expanded=False):
                c1, c2, c3 = st.columns(3)
                with c1:
                    n_cat  = st.selectbox("카테고리", CATEGORY_ORDER, key="n_cat")
                    n_acct = st.text_input("계좌명", key="n_acct")
                    n_asset= st.selectbox("자산군", list(CODE_MAP.keys())+["현금"], key="n_asset")
                with c2:
                    n_name = st.text_input("약식종목명", key="n_name")
                    n_code = st.text_input("종목코드", key="n_code")
                with c3:
                    n_qty  = st.number_input("보유수량", min_value=0.0, step=1.0, key="n_qty")
                    n_avg  = st.number_input("매수평단", min_value=0, step=100, key="n_avg")
                if st.button("추가", key="add_btn"):
                    if n_acct and n_name and n_code:
                        assets = pd.concat([assets if not assets.empty else pd.DataFrame(), pd.DataFrame([{"계좌명":n_acct,"종목명":n_name,"종목코드":n_code,"보유수량":n_qty,"매수평단":n_avg,"약식종목명":n_name,"계좌카테고리":n_cat,"자산군":n_asset}])], ignore_index=True)
                        write_sheet(SHEET_ASSETS, assets)
                        st.cache_data.clear()
                        st.success("✅ 추가 완료!")
                        st.rerun()
            if not assets.empty:
                edited = st.data_editor(assets[["계좌카테고리","계좌명","약식종목명","종목코드","보유수량","매수평단","자산군"]], use_container_width=True, hide_index=False, num_rows="dynamic", key="asset_editor")
                if st.button("💾 변경사항 저장", type="primary", key="save_assets"):
                    write_sheet(SHEET_ASSETS, edited)
                    st.cache_data.clear()
                    st.success("✅ 저장 완료!")
                    st.rerun()
            else:
                st.info("잔고 데이터가 없습니다.")
            end_card()

except Exception as e:
    st.error(f"🚨 오류: {e}")
    import traceback
    st.code(traceback.format_exc())
