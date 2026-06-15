#!/usr/bin/env python3
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REQUIRED_MODULES = ['pandas', 'numpy', 'yaml', 'akshare', 'backtrader', 'requests']


def check_modules():
    missing = []
    for mod in REQUIRED_MODULES:
        if importlib.util.find_spec(mod) is None:
            missing.append(mod)
    return missing


def check_qts_data():
    try:
        import qts_data as qd
        info = qd.data_info()
        return True, info
    except Exception as e:
        return False, str(e)


def main():
    print('QTS 环境检查')
    print('=' * 40)
    print(f'Python: {sys.version}')
    missing = check_modules()
    if missing:
        print(f'缺少依赖: {missing}')
        raise SystemExit(1)
    else:
        print('依赖检查通过: ' + ', '.join(REQUIRED_MODULES))

    ok, info = check_qts_data()
    if not ok:
        print(f'qts_data 加载失败: {info}')
        raise SystemExit(1)

    print('qts_data 加载成功')
    for k, v in info.items():
        print(f'  {k}: {v}')


if __name__ == '__main__':
    main()
