from app.writer.tools import MarketSize, market_table, revenue_forecast, revenue_table


def test_revenue_forecast_formula():
    f = revenue_forecast([{"B": 100, "D": 300}, {"B": 0, "D": 0}], 2027)
    assert f[0]["A(총매출)"] == 400 and f[0]["C(비중 %)"] == 25.0
    assert f[1]["C(비중 %)"] == 0.0 and f[1]["연도"] == 2028
    assert "총매출(A=B+D)" in revenue_table(f)


def test_market_size():
    m = MarketSize(tam=1e12, sam_ratio=10, som_ratio=5, tam_source="통계청 2025")
    assert m.sam == 1e11 and m.som == 5e9
    t = market_table(m)
    assert "1.00조원" in t and "통계청 2025" in t and "[확인 필요: 근거]" in t
