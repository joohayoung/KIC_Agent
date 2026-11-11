"""그래프 (plotly). 값은 저장된 결과 그대로이고, 기준 구간·배경 띠를 그리지 않는다 (0장 7번)."""
import plotly.graph_objects as go

from ui import format as f


def _ratio(r):
    return (((r.get("liquidity") or {}).get("ratio")) or {}).get("value")


def scatter(rows: list[dict]):
    """2.6 분포도: x 부채비율, y 원천÷소요, 원 크기 24개월 내 해외 투자액. 빨강 = 재무 위험 경고 있음. 1배 점선만 긋고 구간을 두지 않는다. 값 없는 기업은 빼고 수를 돌려준다."""
    shown = [r for r in rows if r["debt_ratio"].get("value") is not None and _ratio(r) is not None]
    fig = go.Figure()
    for r in shown:
        inv = (((r.get("liquidity") or {}).get("investment_24m")) or {}).get("value") or 0
        size = max(8, min(60, (inv / 1e8) ** 0.5 * 3))
        fig.add_trace(go.Scatter(x=[r["debt_ratio"]["value"]], y=[_ratio(r)], mode="markers+text", text=[r["corp_name"]], textposition="top center", marker={"size": size, "color": "#d62728" if r.get("risk_warnings") or r["rule_hits"] else "#1f77b4", "opacity": 0.7}, showlegend=False,
                                 hovertemplate=f"{r['corp_name']}<br>부채비율 %{{x:.0f}}%<br>원천÷소요 %{{y:.2f}}배<br>24개월 내 해외 투자액 {f.eok(inv)}<extra></extra>"))
    fig.add_hline(y=1, line_dash="dash", annotation_text="1배")
    fig.update_layout(xaxis_title="부채비율 (최신 정기보고서, %)", yaxis_title="원천 ÷ 소요 (배)", height=420, margin={"t": 20})
    return fig, len(rows) - len(shown)


def liquidity_bars(sources: list[tuple[str, int | None]], uses: list[tuple[str, int | None]]):
    """B 유동성 원천·소요 항목별 누적 막대. 소요 합계 높이에 1배 점선 (원천이 이 선을 넘으면 1배 이상). 값 없는 항목은 그리지 않고 이름에 '산출 불가'."""
    fig = go.Figure()
    for side, items in (("원천", sources), ("소요", uses)):
        for label, v in items:
            fig.add_bar(name=f"{side}: {label}", x=[side], y=[v / 1e8 if v is not None else 0], text=[f"{label} {f.eok(v)}"], textposition="inside", hovertemplate=f"{label} {f.eok(v)}<extra></extra>")
    total = sum(v for _, v in uses if v is not None)
    if uses and all(v is not None for _, v in uses):
        fig.add_hline(y=total / 1e8, line_dash="dash", annotation_text="소요 합계 = 1배")
    fig.update_layout(barmode="relative", height=380, margin={"t": 20}, yaxis_title="억 원", legend={"orientation": "h"})
    return fig


def weekly(rows: list[dict]):
    """3.5 주별 해외투자 신호 (지역별 누적 막대)."""
    weeks = sorted({r["week"] for r in rows})
    fig = go.Figure()
    for region in ("미국", "EU", "아시아 기타"):
        fig.add_bar(name=region, x=weeks, y=[sum(r["count"] for r in rows if r["week"] == w and r["region"] == region) for w in weeks])
    fig.update_layout(barmode="stack", height=300, margin={"t": 20}, yaxis_title="건수")
    return fig


def gap_breakdown(parts: list[tuple[str, float | None]], unconfirmed: float | None):
    """4장 자금 공백 분해. 음수 TTM은 가용 자금을 줄이는 칸으로 그대로 표시. 미확정 조달은 점선 칸으로 따로, 공백에서 빼지 않는다."""
    labels = [p[0] for p in parts]
    vals = [None if p[1] is None else p[1] / 1e8 for p in parts]
    fig = go.Figure(go.Bar(x=labels, y=[v or 0 for v in vals], text=[f.eok(p[1]) for p in parts], textposition="outside", marker_color=["#1f77b4"] + ["#2ca02c"] * (len(parts) - 2) + ["#ff7f0e"]))
    if unconfirmed:
        fig.add_bar(x=["미확정 조달 (미반영)"], y=[unconfirmed / 1e8], text=[f.eok(unconfirmed)], textposition="outside", marker={"color": "rgba(0,0,0,0)", "line": {"color": "#555", "width": 2}, "pattern": {"shape": "/"}}, showlegend=False)
    fig.update_layout(height=340, margin={"t": 20}, yaxis_title="억 원", showlegend=False)
    return fig


def fin_bars(items: list[tuple[str, dict, str]]):
    """4.1 대표 차트. 값이 없는 막대는 0으로 그리지 않고 '산출 불가'를 글자로만 둔다."""
    fig = go.Figure()
    for label, m, sub in items:
        v = m.get("value") if m and m.get("data_status") == "ok" else None
        fig.add_bar(x=[f"{label}<br><sub>{sub}</sub>"], y=[v / 1e8 if v is not None else None], text=[f.eok(v) if v is not None else f.value(m)], textposition="outside", showlegend=False)
    fig.update_layout(height=320, margin={"t": 20}, yaxis_title="억 원")
    return fig
