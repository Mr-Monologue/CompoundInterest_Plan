# daily_run.py
import logging
from storage import init_db
from config import load_all_funds_config
from services.dca_service import run_once_for_fund

# 配置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    init_db()
    funds, _ = load_all_funds_config()
    for f in funds:
        try:
            res = run_once_for_fund(f)
            logger.info(
                f"[{res['fund_code']}] NAV={res['nav']:.4f} src={res['nav_src']} "
                f"dev={res['dev']['deviation_pct']:.2f}% level={res['plan']['level']} "
                f"plan={res['plan']['total_amount']:.2f}"
            )
        except Exception as e:
            logger.error(f"run failed for {f['fund_code']}: {e}")


if __name__ == "__main__":
    main()
