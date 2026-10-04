"""Family-holdout generalization test (DEV seeds only). Imports the sealed pipeline unchanged."""
import json, numpy as np, lightgbm as lgb
import predictor_pipeline as P
res = {}
for hold in ("eps", "comms"):
    other = "comms" if hold == "eps" else "eps"
    ftr = {other: 0.7, "sudden": 0.3}
    tr = P.build("train", ftr, {0, 1, 2, 3}); va = P.build("val", ftr); ca = P.build("cal", ftr)
    te = P.build("dev", {hold: 0.7, "sudden": 0.3})
    params = dict(objective="binary", metric="average_precision", num_leaves=15, min_data_in_leaf=200, lambda_l2=1.0,
                  learning_rate=0.05, feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, is_unbalance=True,
                  deterministic=True, force_row_wise=True, seed=42, num_threads=4, verbosity=-1)
    dtr = lgb.Dataset(tr["X"], P.labels(tr, "onset"), feature_name=tr["names"])
    m = lgb.train(params, dtr, 1500, valid_sets=[lgb.Dataset(va["X"], P.labels(va, "onset"), reference=dtr)],
                  callbacks=[lgb.early_stopping(50, verbose=False)])
    ca["lgb"] = m.predict(ca["X"], num_iteration=m.best_iteration); te["lgb"] = m.predict(te["X"], num_iteration=m.best_iteration)
    print(f"\n=== trained WITHOUT {hold}; tested on {hold} (dev seeds) ===")
    for n in ("ewma", "cusum", "lgb"):
        tau = P.calibrate(ca, ca[n]); far, ev, _ = P.fa_rate(te, te[n], tau)
        s = P.summarize(P.event_eval(te, te[n], tau))
        h = s[hold]; c = s["compound"]
        print(f"{n:6s} FA={far:.2f}  {hold}: {h['detected']}/{h['events']} CI={[round(x,2) for x in h['recall_ci95']]} "
              f"lead_frac={None if h['median_lead_frac_of_ramp'] is None else round(h['median_lead_frac_of_ramp'],2)} | "
              f"compound(contains seen family): {c['detected']}/{c['events']} | PR-AUC={P.avg_precision(te['y_eval'], te[n]):.3f}")
