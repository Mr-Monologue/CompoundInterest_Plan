from sqlmodel import SQLModel, create_engine, Session
import os

# 数据库文件会生成在 backend 目录下
sqlite_file_name = "invest.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

# 创建连接引擎
engine = create_engine(sqlite_url, echo=True)  # echo=True 会打印 SQL 语句，方便调试


def create_db_and_tables():
    """初始化数据库"""
    if os.path.exists(sqlite_file_name):
        from sqlalchemy import inspect, text

        inspector = inspect(engine)

        # 检查 transaction 表是否有 fee 列
        if "transaction" in inspector.get_table_names():
            columns = [col["name"] for col in inspector.get_columns("transaction")]
            if "fee" not in columns:
                # 表存在但缺少 fee 列，需要重建
                print("⚠️ 检测到 transaction 表缺少 fee 列，正在重建表...")
                with engine.connect() as conn:
                    # 删除旧表（transaction 是保留关键字，需要用引号）
                    conn.execute(text('DROP TABLE IF EXISTS "transaction"'))
                    conn.commit()

        # 检查 planstate 表是否需要迁移（从旧结构到新结构）
        if "planstate" in inspector.get_table_names():
            columns = [col["name"] for col in inspector.get_columns("planstate")]
            # 检查是否有旧字段（weekly_budget, global_reserve）或缺少新字段（pool_balance, base_investment）
            has_old_fields = "weekly_budget" in columns or "global_reserve" in columns
            missing_new_fields = (
                "pool_balance" not in columns or "base_investment" not in columns
            )

            if has_old_fields or missing_new_fields:
                print("⚠️ 检测到 planstate 表结构过时，正在重建表...")
                print(f"   旧字段: {has_old_fields}, 缺少新字段: {missing_new_fields}")
                with engine.connect() as conn:
                    # 删除旧表
                    conn.execute(text('DROP TABLE IF EXISTS "planstate"'))
                    conn.commit()
                print("✅ planstate 表已重建")

        # 检查 asset 表是否有 max_weight_limit 列
        if "asset" in inspector.get_table_names():
            columns = [col["name"] for col in inspector.get_columns("asset")]
            if "max_weight_limit" not in columns:
                print("⚠️ 检测到 asset 表缺少 max_weight_limit 列，正在重建表...")
                with engine.connect() as conn:
                    conn.execute(text("DROP TABLE IF EXISTS asset"))
                    conn.commit()
                print("✅ asset 表已重建")

    # 创建所有表（如果不存在）
    SQLModel.metadata.create_all(engine)


def get_session():
    """获取数据库会话的依赖函数"""
    with Session(engine) as session:
        yield session
