from ib_insync import IB, Stock, util
import pandas as pd

ib = IB()
ib.connect('127.0.0.1', 4001, clientId=15)

symbols = ['MSFT','AAPL','MRVL','NVDA','AMZN','SPY','SNDK','MU','SMH','QQQ','STX','TSLA']
durations = {'1h': ('30 D','1 hour'), '1d': ('3 Y','1 day')}

for sym in symbols:
    contract = Stock(sym, 'SMART', 'USD')
    for tf, (dur, bar) in durations.items():
        bars = ib.reqHistoricalData(contract, endDateTime='', durationStr=dur,
                                    barSizeSetting=bar, whatToShow='TRADES',
                                    useRTH=True, formatDate=1)
        if bars:
            df = util.df(bars)[['date','open','high','low','close','volume']]
            df.columns = ['Date','Open','High','Low','Close','Volume']
            df.to_csv(f'data/{sym}_{tf}.csv', index=False)
            print(f'  {sym} {tf}: {len(df)} bars, 最新={df["Date"].iloc[-1]}', flush=True)
        else:
            print(f'  {sym} {tf}: 无数据', flush=True)

ib.disconnect()
print('完成')
