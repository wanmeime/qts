.PHONY: check api signal-momentum signal-multifactor backtest-momentum backtest-multifactor review test

check:
\tcd /home/jiaod/qts && python3 tools/check_env.py

api:
\tcd /home/jiaod/qts && python3 api_server.py

signal-momentum:
\tcd /home/jiaod/qts && python3 10-策略/动量轮动策略/信号生成.py

signal-multifactor:
\tcd /home/jiaod/qts && python3 10-策略/多因子选股策略/信号生成.py

backtest-momentum:
\tcd /home/jiaod/qts && python3 20-回测/动量轮动策略/20260602-v1/run_backtest.py

backtest-multifactor:
\tcd /home/jiaod/qts && python3 20-回测/多因子选股策略/20260602-v1/backtest.py

review:
\tcd /home/jiaod/qts && python3 90-复盘/每日复盘.py

test:
\tcd /home/jiaod/qts && python3 -m unittest discover -s tests -v
