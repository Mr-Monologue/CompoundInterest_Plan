from sqlmodel import SQLModel, create_engine, Session

# 数据库文件会生成在 backend 目录下
sqlite_file_name = "invest.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

# 创建连接引擎
engine = create_engine(sqlite_url, echo=True)  # echo=True 会打印 SQL 语句，方便调试


def create_db_and_tables():
    """初始化数据库"""
    SQLModel.metadata.create_all(engine)


def get_session():
    """获取数据库会话的依赖函数"""
    with Session(engine) as session:
        yield session
