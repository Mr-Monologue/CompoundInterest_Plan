import akshare as ak
import pandas as pd

# 设置 Pandas 显示选项，防止打印时列被折叠，方便查看
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 1000)


def test_fund_holdings(symbol, date):
    print(f"----- 正在查询基金: {symbol} 在 {date} 年的持仓数据 -----")

    try:
        # 调用接口：fund_portfolio_hold_em
        # symbol: 基金代码 (字符串)
        # date: 年份 (字符串)
        df = ak.fund_portfolio_hold_em(symbol=symbol, date=date)

        # 检查是否获取到数据
        if df is None or df.empty:
            print("未获取到数据，可能是基金代码错误或该年份无数据。")
            return

        # 打印前 10 行数据
        print("获取成功！显示前 10 条持仓记录：")
        print(df.head(10))

        # 打印数据类型验证（对应截图中的输出参数表格）
        print("\n数据列信息：")
        print(df.columns.tolist())

    except Exception as e:
        print(f"接口调用出错: {e}")


if __name__ == "__main__":
    # 测试示例 1: 华夏成长 (000001) - 截图中的例子
    # 注意：基金只有发布了季报/年报才有数据，建议查询上一年的完整数据或当年的已发布季度
    test_fund_holdings(symbol="000001", date="2025")

    # 你可以取消注释下面这行来测试其他基金
    # test_fund_holdings(symbol="005827", date="2023")  # 易方达蓝筹精选
