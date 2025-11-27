from sqlmodel import SQLModel, create_engine, Session
import os

# 数据库文件会生成在 backend 目录下
sqlite_file_name = "invest.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

# 创建连接引擎
engine = create_engine(sqlite_url, echo=True)  # echo=True 会打印 SQL 语句，方便调试


def create_db_and_tables():
    """初始化数据库"""
    # 如果数据库文件存在，检查 transaction 表是否有 fee 列
    if os.path.exists(sqlite_file_name):
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        if "transaction" in inspector.get_table_names():
            columns = [col["name"] for col in inspector.get_columns("transaction")]
            if "fee" not in columns:
                # 表存在但缺少 fee 列，需要重建
                print("⚠️ 检测到 transaction 表缺少 fee 列，正在重建表...")
                with engine.connect() as conn:
                    # 删除旧表（transaction 是保留关键字，需要用引号）
                    conn.execute(text('DROP TABLE IF EXISTS "transaction"'))
                    conn.commit()

    # 创建所有表（如果不存在）
    SQLModel.metadata.create_all(engine)


def get_session():
    """获取数据库会话的依赖函数"""
    with Session(engine) as session:
        yield session
