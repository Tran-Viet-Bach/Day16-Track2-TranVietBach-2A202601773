#!/usr/bin/env python3
"""LAB16 - Benchmark LightGBM tren CPU node (Credit Card Fraud Detection)."""
import json, os, time
import numpy as np
import pandas as pd
import lightgbm as lgb
from lightgbm import LGBMClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import (roc_auc_score, accuracy_score, f1_score,
                             precision_score, recall_score, confusion_matrix)

DATA = os.path.expanduser("~/ml-benchmark/creditcard.csv")
OUT = os.path.expanduser("~/ml-benchmark/benchmark_result.json")

# ---------- 1. Load ----------
t0 = time.perf_counter()
df = pd.read_csv(DATA)
load_time = time.perf_counter() - t0
print(f"[LOAD]  {df.shape[0]:,} rows x {df.shape[1]} cols in {load_time:.2f}s")
print(f"[DATA]  fraud rate = {df['Class'].mean()*100:.3f}%  ({int(df['Class'].sum())} ca gian lan)")

# ---------- 2. Split ----------
X, y = df.drop(columns=["Class"]), df["Class"]
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, stratify=y, random_state=42)
# tach them validation TU TRONG train de early stopping khong nhin thay test
X_tr, X_val, y_tr, y_val = train_test_split(
    X_train, y_train, test_size=0.2, stratify=y_train, random_state=42)
print(f"[SPLIT] train={len(X_tr):,}  val={len(X_val):,}  test={len(X_test):,}")

# ---------- 3. Train ----------
# learning_rate=0.02: voi 315 ca gian lan trong tap train, lr=0.05 lam model
# overfit ngay tu cay thu 2 (AUC dinh o iter 1 roi tut). lr thap hon cho phep
# model hoc dan qua ~270 vong -> AUC 0.978 thay vi 0.939.
model = LGBMClassifier(n_estimators=3000, learning_rate=0.02, num_leaves=31,
                       min_child_samples=20, n_jobs=-1, random_state=42,
                       verbosity=-1)
t0 = time.perf_counter()
model.fit(X_tr, y_tr, eval_X=X_val, eval_y=y_val, eval_metric="auc",
          callbacks=[lgb.early_stopping(200, verbose=False, first_metric_only=True),
                     lgb.log_evaluation(50)])
train_time = time.perf_counter() - t0
best_iter = int(model.best_iteration_)
print(f"[TRAIN] {train_time:.2f}s, best_iteration = {best_iter}")

# ---------- 4. Evaluate ----------
y_prob = model.predict_proba(X_test)[:, 1]   # xac suat -> cho AUC
y_pred = model.predict(X_test)               # nhan 0/1 -> cho F1/P/R
tn, fp, fn, tp = confusion_matrix(y_test, y_pred).ravel()

# ---------- 5. Latency: 1 dong ----------
one = X_test.iloc[[0]]
for _ in range(10):
    model.predict(one)                       # warmup
lat = []
for _ in range(100):
    t0 = time.perf_counter()
    model.predict(one)
    lat.append((time.perf_counter() - t0) * 1000)

# ---------- 6. Throughput: 1000 dong ----------
batch = X_test.iloc[:1000]
model.predict(batch)                         # warmup
t0 = time.perf_counter()
model.predict(batch)
batch_time = time.perf_counter() - t0

# ---------- 7. Ket qua ----------
result = {
    "instance": {"vcpu": os.cpu_count(),
                 "dataset_rows": int(df.shape[0]),
                 "fraud_rate_pct": round(float(df["Class"].mean()) * 100, 4)},
    "load_time_sec": round(load_time, 3),
    "train_time_sec": round(train_time, 3),
    "best_iteration": best_iter,
    "auc_roc": round(float(roc_auc_score(y_test, y_prob)), 6),
    "accuracy": round(float(accuracy_score(y_test, y_pred)), 6),
    "f1_score": round(float(f1_score(y_test, y_pred)), 6),
    "precision": round(float(precision_score(y_test, y_pred)), 6),
    "recall": round(float(recall_score(y_test, y_pred)), 6),
    "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    "inference_latency_1row_ms": {"mean": round(float(np.mean(lat)), 3),
                                  "p95": round(float(np.percentile(lat, 95)), 3)},
    "inference_throughput_1000rows": {"batch_time_sec": round(batch_time, 5),
                                      "rows_per_sec": round(1000 / batch_time, 1)},
}
with open(OUT, "w") as f:
    json.dump(result, f, indent=2)

print("\n" + "=" * 46)
print(f"{'Metric':<32}{'Value':>14}")
print("=" * 46)
for k, v in [("Load data (s)", result["load_time_sec"]),
             ("Training (s)", result["train_time_sec"]),
             ("Best iteration", result["best_iteration"]),
             ("AUC-ROC", result["auc_roc"]),
             ("Accuracy", result["accuracy"]),
             ("F1-Score", result["f1_score"]),
             ("Precision", result["precision"]),
             ("Recall", result["recall"]),
             ("Latency 1 row (ms)", result["inference_latency_1row_ms"]["mean"]),
             ("Throughput (rows/s)", result["inference_throughput_1000rows"]["rows_per_sec"])]:
    print(f"{k:<32}{v:>14}")
print("=" * 46)
print(f"Confusion: TN={tn} FP={fp} FN={fn} TP={tp}")
print(f"-> saved {OUT}")
