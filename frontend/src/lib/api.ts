import type { BacktestRequest, BacktestResponse } from '../types/api';

export async function runBacktest(
  req: BacktestRequest,
  signal?: AbortSignal,
): Promise<BacktestResponse> {
  const res = await fetch('/api/backtest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
    signal,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Backtest failed: ${err}`);
  }
  return res.json();
}
