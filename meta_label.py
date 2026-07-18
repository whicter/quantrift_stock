"""Small dependency-free meta-label model, guarded against small samples."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

MODEL_PATH = Path("logs/meta_label_model.json")
MIN_SAMPLES = 150
FEATURES = ("quality", "market_score", "vix", "sector_aligned", "screener_rank")


def _matrix(frame: pd.DataFrame) -> np.ndarray:
    values = frame.reindex(columns=FEATURES).copy()
    values["sector_aligned"] = values["sector_aligned"].map({True: 1, False: 0}).fillna(values["sector_aligned"])
    return values.apply(pd.to_numeric, errors="coerce").fillna(0).to_numpy(dtype=float)


def train(frame: pd.DataFrame, path: Path = MODEL_PATH) -> dict:
    usable = frame[pd.to_numeric(frame.get("r_mult"), errors="coerce").notna()].copy()
    if len(usable) < MIN_SAMPLES:
        return {"trained": False, "reason": f"样本不足：{len(usable)}/{MIN_SAMPLES}"}
    x = _matrix(usable)
    y = (pd.to_numeric(usable["r_mult"]) > 0).astype(float).to_numpy()
    mean, std = x.mean(axis=0), x.std(axis=0)
    std[std == 0] = 1
    x = (x - mean) / std
    x = np.c_[np.ones(len(x)), x]
    weights = np.zeros(x.shape[1])
    for _ in range(1500):
        pred = 1 / (1 + np.exp(-np.clip(x @ weights, -30, 30)))
        weights -= 0.05 * ((x.T @ (pred - y)) / len(x) + 0.001 * weights)
    payload = {"features": list(FEATURES), "mean": mean.tolist(), "std": std.tolist(), "weights": weights.tolist(), "samples": len(usable)}
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return {"trained": True, "samples": len(usable), "path": str(path)}


def suggest(features: dict, path: Path = MODEL_PATH) -> float | None:
    if not path.exists():
        return None
    model = json.loads(path.read_text())
    x = np.array([float(features.get(name, 0) or 0) for name in model["features"]])
    x = (x - np.array(model["mean"])) / np.array(model["std"])
    return float(1 / (1 + np.exp(-np.clip(np.r_[1.0, x] @ np.array(model["weights"]), -30, 30))))
