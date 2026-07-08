# compound-cross-device-migration

## trigger
"迁移", "换设备", "新机部署"

## procedure
1. git clone + pip install
2. 复制 invest.db
3. compoundctl doctor
4. compoundctl start --mode backend-only
5. compoundctl gate --target hermes
6. verify /api/health assets=6

## forbidden
- 手动 pip install
- 手动 taskkill
- 手动 python backend/main.py
