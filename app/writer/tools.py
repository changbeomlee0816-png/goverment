"""계획서 보조 도구: 시장규모(TAM-SAM-SOM), 5개년 매출표, 성능지표 표, 역할분담표.

계산은 모두 Python 규칙으로 하고, 결과표는 Markdown으로 만들어 초안·DOCX에 그대로 쓴다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MarketSize:
    tam: float  # 원
    sam_ratio: float  # TAM 대비 %
    som_ratio: float  # SAM 대비 %
    tam_source: str = ""
    sam_basis: str = ""
    som_basis: str = ""

    @property
    def sam(self) -> float:
        return self.tam * self.sam_ratio / 100

    @property
    def som(self) -> float:
        return self.sam * self.som_ratio / 100


def fmt_krw(value: float) -> str:
    if abs(value) >= 1e12:
        return f"{value / 1e12:,.2f}조원"
    if abs(value) >= 1e8:
        return f"{value / 1e8:,.1f}억원"
    if abs(value) >= 1e4:
        return f"{value / 1e4:,.0f}만원"
    return f"{value:,.0f}원"


def market_table(m: MarketSize) -> str:
    return "\n".join(
        [
            "| 구분 | 규모 | 산출 근거 |",
            "|---|---|---|",
            f"| TAM(전체시장) | {fmt_krw(m.tam)} | {m.tam_source or '[확인 필요: 출처]'} |",
            f"| SAM(유효시장) | {fmt_krw(m.sam)} | TAM × {m.sam_ratio:g}% ({m.sam_basis or '[확인 필요: 근거]'}) |",
            f"| SOM(수익시장) | {fmt_krw(m.som)} | SAM × {m.som_ratio:g}% ({m.som_basis or '[확인 필요: 근거]'}) |",
        ]
    )


def revenue_forecast(rows: list[dict], start_year: int) -> list[dict]:
    """5개년 매출표.

    입력 rows[i]: {"B": 본 기술 매출(원), "D": 기존 매출(원), "export": 수출액(원, 선택)}
    출력: A=B+D(총매출), C=B/A×100(본 기술 매출 비중 %)
    """
    out = []
    for i, r in enumerate(rows):
        b = float(r.get("B") or 0)
        d = float(r.get("D") or 0)
        a = b + d
        c = round(b / a * 100, 1) if a else 0.0
        out.append({"연도": start_year + i, "A(총매출)": a, "B(본 기술 매출)": b, "C(비중 %)": c, "D(기존 매출)": d, "수출": float(r.get("export") or 0)})
    return out


def revenue_table(forecast: list[dict]) -> str:
    header = "| 구분 | " + " | ".join(str(r["연도"]) for r in forecast) + " |"
    sep = "|---" * (len(forecast) + 1) + "|"
    def row(label, key, is_pct=False):
        cells = [f"{r[key]:g}%" if is_pct else fmt_krw(r[key]) for r in forecast]
        return f"| {label} | " + " | ".join(cells) + " |"
    return "\n".join(
        [
            header,
            sep,
            row("총매출(A=B+D)", "A(총매출)"),
            row("본 기술 매출(B)", "B(본 기술 매출)"),
            row("본 기술 비중(C=B/A×100)", "C(비중 %)", is_pct=True),
            row("기존 매출(D)", "D(기존 매출)"),
            row("수출", "수출"),
        ]
    )


def indicator_table(indicators: list[dict]) -> str:
    lines = [
        "| 성능지표 | 단위 | 현재 수준 | 최종 목표 | 측정방법 | 시험기관 | 근거 |",
        "|---|---|---|---|---|---|---|",
    ]
    for ind in indicators:
        lines.append(
            "| {name} | {unit} | {baseline} | {target} | {method} | {org} | {src} |".format(
                name=ind.get("name") or "",
                unit=ind.get("unit") or "",
                baseline=ind.get("baseline") or "[확인 필요]",
                target=ind.get("target") or "[확인 필요]",
                method=ind.get("measure_method") or "[확인 필요]",
                org=ind.get("test_org") or "[확인 필요]",
                src=ind.get("source") or "[확인 필요]",
            )
        )
    return "\n".join(lines)


def role_table(roles: list[dict]) -> str:
    lines = ["| 수행주체 | 담당 업무 | 참여 인력 | 기간 |", "|---|---|---|---|"]
    for r in roles:
        lines.append(f"| {r.get('주체', '')} | {r.get('업무', '')} | {r.get('인력', '')} | {r.get('기간', '')} |")
    return "\n".join(lines)
