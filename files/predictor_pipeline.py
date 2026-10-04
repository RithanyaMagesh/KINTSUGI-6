#!/usr/bin/env python3
"""CubeSat early-warning failure predictor: generate -> features -> baselines -> train -> eval.

Usage:  python predictor_pipeline.py all --out out/
        python predictor_pipeline.py all --out out_holdout/ --holdout-family eps
Order enforced: test manifest is written BEFORE any training data is built.
Everything is past-only (no feature at tick t reads index > t).
"""
import argparse, hashlib, json, os, sys
from pathlib import Path
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view as swv
from scipy.stats import beta

DT = 2.0                 # s per tick
T_TICKS = 5400           # 3 h = 2 orbits
ORBIT_S = 5400.0
L_S = 300.0              # label lead horizon
CH = ["volt", "soc", "duty", "lat", "jit", "temp"]
NC = len(CH)
WINS = [15, 60, 300]     # 30 s, 2 min, 10 min
STRIDE = 10              # score every 20 s
WARM = 300               # ticks before first scored row (full 10-min window)
BASE_N = 150             # startup ticks used for frozen robust baseline
N_SATS = 6
K_ALARM = 3              # consecutive scored rows >= tau  (~60 s)
FA_BUDGET = 0.5          # alarm events per healthy sat-orbit
FAM = {"none": 0, "eps": 1, "comms": 2, "sudden": 3, "compound": 4}

# nominal eclipse response (known physics; removed from BOTH baselines and ML => fair, baseline-friendly)
ECL_NOM = np.array([-0.35, -8.0, 0.0, 0.0, 0.0, -3.0])
NOM = np.array([7.4, 90.0, 0.02, 40.0, 5.0, 25.0])

PROFILES = {  # A = train/val, B = test (shifted ramps/drift/compound)
    "A": dict(R=(1800, 3600), rate=(0.03, 0.05), dtemp=(3, 6), lat_end=(100, 120), jit_end=(30, 40), compound=0.0),
    "B": dict(R=(3600, 5400), rate=(0.02, 0.07), dtemp=(2, 8), lat_end=(70, 140), jit_end=(20, 50), compound=0.3),
}
SEEDS = {"train": range(1000, 1100), "val": range(2000, 2040), "cal": range(3000, 3040),
         "dev": range(7000, 7040), "test": range(9500, 9560)}  # disjoint; test is FRESH (v1 seeds 9000-9039 are burned)
GEN_SPLIT = {"train": "A", "val": "A", "cal": "A", "dev": "B", "test": "B"}
VARIANTS = {"L1800": 1800, "L3600": 3600, "onset": None}   # label variants, chosen on cal only


def box(x, n):
    return np.convolve(x, np.ones(n) / n, mode="same")


def gen_run(seed, prof, fam_p):
    rng = np.random.default_rng(np.random.SeedSequence(seed).spawn(1)[0])
    P = PROFILES[prof]
    t = np.arange(T_TICKS) * DT
    ecl = box((((t + rng.uniform(0, ORBIT_S)) % ORBIT_S) > 0.65 * ORBIT_S).astype(float), 30)
    n_fail = int(rng.integers(0, 3))
    fail_sats = rng.choice(N_SATS, n_fail, replace=False) if n_fail else []
    fams, p = list(fam_p.keys()), np.array(list(fam_p.values()), float)
    p /= p.sum()
    X = np.zeros((N_SATS, T_TICKS, NC), np.float32)
    fails = []
    for s in range(N_SATS):
        x = np.tile(NOM, (T_TICKS, 1)) + ecl[:, None] * ECL_NOM
        x[:, 0] += rng.normal(0, 0.05)       # per-sat bias (removed by startup baseline)
        x[:, 5] += rng.normal(0, 1.0)
        x[:, 0] += rng.normal(0, 0.02, T_TICKS)
        x[:, 1] += rng.normal(0, 0.3, T_TICKS)
        x[:, 3] += rng.normal(0, 3, T_TICKS)
        x[:, 4] += np.abs(rng.normal(0, 1, T_TICKS))
        x[:, 5] += rng.normal(0, 0.3, T_TICKS)
        duty = np.zeros(T_TICKS)
        for _ in range(rng.integers(2, 8)):                  # burn pulses
            a = rng.integers(0, T_TICKS - 30); duty[a:a + rng.integers(5, 20)] = rng.uniform(0.3, 0.8)
        x[:, 2] += duty + rng.normal(0, 0.01, T_TICKS)
        x[:, 5] += 2.0 * box(duty, 40)
        for _ in range(rng.integers(0, 4)):                  # benign self-recovering distractors
            a, n = rng.integers(0, T_TICKS - 120), rng.integers(30, 100)
            x[a:a + n, 0] -= rng.uniform(0.2, 0.5) * np.hanning(n)[: len(x[a:a + n])]
            a2, n2 = rng.integers(0, T_TICKS - 40), rng.integers(10, 30)
            x[a2:a2 + n2, 3] += rng.uniform(10, 25)
            x[a2:a2 + n2, 4] += rng.uniform(5, 15)
        if s in fail_sats:
            fam = str(rng.choice(fams, p=p))
            R = rng.uniform(*P["R"]) if fam != "sudden" else 0.0
            lo = int((R + 600) / DT) if fam != "sudden" else int(900 / DT)
            tf = int(rng.integers(lo, T_TICKS - 50))
            if fam != "sudden" and rng.random() < P["compound"]:
                fam = "compound"
            on = tf - int(R / DT)
            i = np.arange(T_TICKS)
            ramp = np.clip((i - on) / max(tf - on, 1), 0, 1) if fam != "sudden" else np.zeros(T_TICKS)
            if fam in ("eps", "compound"):
                rate = rng.uniform(*P["rate"]) / 60.0       # V/s
                drop = np.where(i > on, rate * (i - on) * DT, 0.0)
                x[:, 0] = np.maximum(x[:, 0] - drop, 3.0)
                x[:, 1] -= rng.uniform(10, 25) * ramp
                x[:, 5] += rng.uniform(*P["dtemp"]) * ramp
            if fam in ("comms", "compound"):
                x[:, 3] += (rng.uniform(*P["lat_end"]) - 40) * ramp
                x[:, 4] += (rng.uniform(*P["jit_end"]) - 5) * ramp + np.abs(rng.normal(0, 1, T_TICKS)) * ramp * 5
            fails.append(dict(sat=int(s), tf=tf, fam=fam, onset=(on if fam != "sudden" else tf - int(L_S / DT))))
        X[s] = x
    return X, ecl, fails


def detrend(x, ecl):
    return x - ecl[:, None] * ECL_NOM


def robust_base(r):
    med = np.median(r[:BASE_N], axis=0)
    mad = np.median(np.abs(r[:BASE_N] - med), axis=0) * 1.4826
    return med, np.maximum(mad, 1e-3)


def features(x, ecl, tf=None):
    """x: (T, C) raw for one sat. Past-only. Returns F, ticks, names."""
    r = detrend(x, ecl)
    med, sd = robust_base(r)
    idx = np.arange(WARM, T_TICKS, STRIDE)
    if tf is not None:
        idx = idx[idx < tf]
    feats, names = [], []
    for c in range(NC):
        xc = r[:, c]
        means = {}
        for w in WINS:
            seg = swv(xc, w)[idx - w + 1]
            tt = np.arange(w) - (w - 1) / 2
            m = seg.mean(1); means[w] = m
            feats += [m, seg.std(1), seg.min(1), seg.max(1), (seg @ tt) / (tt @ tt), (m - med[c]) / sd[c]]
            names += [f"{CH[c]}_w{w}_{k}" for k in ("mean", "std", "min", "max", "slope", "z")]
        feats += [xc[idx], (xc[idx] - med[c]) / sd[c], means[15] - means[300], means[60] - means[300]]
        names += [f"{CH[c]}_last", f"{CH[c]}_zlast", f"{CH[c]}_c15_300", f"{CH[c]}_c60_300"]
    return np.stack(feats, 1).astype(np.float32), idx, names


def baseline_scores(X, ecl):
    """EWMA and CUSUM control charts on detrended z, scored at feature ticks. X: (S,T,C). Returns (S,T) each."""
    use = [0, 1, 3, 4, 5]
    lam, kref = 0.05, 0.5
    Z = np.zeros((X.shape[0], T_TICKS, len(use)))
    for s in range(X.shape[0]):
        r = detrend(X[s], ecl); med, sd = robust_base(r)
        Z[s] = ((r - med) / sd)[:, use]
    ew = np.zeros_like(Z); e = np.zeros((X.shape[0], len(use)))
    sp = np.zeros_like(e); sn = np.zeros_like(e); cu = np.zeros_like(Z)
    for i in range(T_TICKS):
        z = Z[:, i, :]
        e = (1 - lam) * e + lam * z; ew[:, i, :] = e
        sp = np.maximum(0, sp + z - kref); sn = np.maximum(0, sn - z - kref)
        cu[:, i, :] = np.maximum(sp, sn)
    return np.abs(ew).max(2) / np.sqrt(lam / (2 - lam)), cu.max(2)


def build(split, fam_p, train_sats=None):
    rows = dict(X=[], run=[], sat=[], tick=[], tf=[], onset=[], fam=[], ewma=[], cusum=[])
    names = None
    for seed in SEEDS[split]:
        X, ecl, fails = gen_run(seed, GEN_SPLIT[split], fam_p)
        fmap = {f["sat"]: f for f in fails}
        ew, cu = baseline_scores(X, ecl)
        for s in range(N_SATS):
            if train_sats is not None and s not in train_sats:
                continue
            f = fmap.get(s)
            tf = f["tf"] if f else None
            F, idx, names = features(X[s], ecl, tf)
            n = len(idx)
            rows["X"].append(F)
            rows["run"].append(np.full(n, seed)); rows["sat"].append(np.full(n, s)); rows["tick"].append(idx)
            rows["tf"].append(np.full(n, tf if f else -1)); rows["onset"].append(np.full(n, f["onset"] if f else -1))
            rows["fam"].append(np.full(n, FAM[f["fam"]] if f else 0))
            rows["ewma"].append(ew[s, idx]); rows["cusum"].append(cu[s, idx])
    D = {k: np.concatenate(v) for k, v in rows.items()}
    D["names"] = names
    k = D["run"] * 100 + D["sat"]
    b = np.flatnonzero(np.diff(k)) + 1
    D["segs"] = list(zip(np.r_[0, b], np.r_[b, len(k)]))
    D["y_eval"] = labels(D, "onset")
    return D


def labels(D, variant):
    """gradual families only: y=1 while precursor is present (from onset) -- optionally capped to last L s. Sudden => 0."""
    grad = np.isin(D["fam"], (1, 2, 4))
    start = D["onset"].copy()
    if VARIANTS[variant] is not None:
        start = np.maximum(start, D["tf"] - int(VARIANTS[variant] / DT))
    return (grad & (D["tick"] >= start) & (D["tick"] < D["tf"])).astype(np.int8)


def avg_precision(y, s):
    o = np.argsort(-s, kind="stable"); y = y[o]
    tp = np.cumsum(y); prec = tp / np.arange(1, len(y) + 1)
    return float((prec * y).sum() / max(y.sum(), 1))


def active_flags(score, tau):
    a = (score >= tau).astype(int)
    c = np.convolve(a, np.ones(K_ALARM), mode="full")[: len(a)]
    return c >= K_ALARM


def edges(a):
    return a & ~np.r_[False, a[:-1]]


def fa_rate(D, score, tau):
    """False alarms = alarm rising edges where NO precursor exists: healthy sats (all time) + failing sats BEFORE onset."""
    ev, sat_s = 0, 0.0
    for st, en in D["segs"]:
        tk, on = D["tick"][st:en], D["onset"][st]
        e = edges(active_flags(score[st:en], tau))
        reg = np.ones(len(tk), bool) if on < 0 else tk < on
        ev += int((e & reg).sum()); sat_s += reg.sum() * STRIDE * DT / ORBIT_S
    return ev / max(sat_s, 1e-9), ev, sat_s


def calibrate(D, score):
    for tau in np.unique(np.quantile(score, np.linspace(0.5, 0.99999, 400))):
        if fa_rate(D, score, tau)[0] <= FA_BUDGET:
            return float(tau)
    return float(score.max())


def cp(k, n, a=0.05):
    if n == 0:
        return (0.0, 1.0)
    return (0.0 if k == 0 else float(beta.ppf(a / 2, k, n - k + 1)), 1.0 if k == n else float(beta.ppf(1 - a / 2, k + 1, n - k)))


def event_eval(D, score, tau, sats=None):
    """Onset-aware: detected iff a NEW alarm (rising edge) starts inside [onset, tf). Alarm already on before onset = false alarm, not credit."""
    ev = []
    for st, en in D["segs"]:
        fam, s_ = D["fam"][st], D["sat"][st]
        if fam == 0 or (sats is not None and s_ not in sats):
            continue
        tk, tf, on = D["tick"][st:en], D["tf"][st], D["onset"][st]
        e = edges(active_flags(score[st:en], tau)) & (tk >= on) & (tk < tf)
        lead = float((tf - tk[e][0]) * DT) if e.any() else None
        ev.append(dict(run=int(D["run"][st]), sat=int(s_), fam=int(fam), det=bool(e.any()), lead_s=lead, ramp_s=float((tf - on) * DT)))
    return ev


def summarize(ev):
    out = {}
    for name in ("eps", "comms", "compound", "sudden"):
        e = [x for x in ev if x["fam"] == FAM[name]]
        d = [x for x in e if x["det"]]
        out[name] = dict(detected=len(d), events=len(e), recall_ci95=cp(len(d), len(e)),
                         median_lead_s=float(np.median([x["lead_s"] for x in d])) if d else None,
                         median_lead_frac_of_ramp=float(np.median([x["lead_s"] / x["ramp_s"] for x in d])) if d and name != "sudden" else None)
    g = [x for x in ev if x["fam"] in (1, 2, 4)]
    out["gradual_all"] = dict(detected=sum(x["det"] for x in g), events=len(g),
                              recall_ci95=cp(sum(x["det"] for x in g), len(g)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["manifest", "run"])
    ap.add_argument("--out", default="out2")
    ap.add_argument("--dev", action="store_true", help="evaluate on DEV seeds (7000s) instead of the sealed test seeds")
    a = ap.parse_args()
    # Path-confinement guard (added 2026-10-03 with user approval, I/O edge only):
    # --out must resolve inside the repository (this file's parents[1]) before
    # any open() below uses it.
    repo_root = Path(__file__).resolve().parents[1]
    # a.out must be a SINGLE path component: the output directory is always a
    # direct child of the repository root, so no separator or traversal can
    # survive into any open() below.
    if Path(a.out).name != a.out:
        sys.exit(f"refusing: --out {a.out!r} is not a plain directory name")
    out = repo_root / Path(a.out).name
    try:
        confined = os.path.commonpath((str(out), str(repo_root))) == str(repo_root)
    except ValueError:  # different drives on Windows
        confined = False
    if not confined:
        sys.exit(f"refusing: --out {a.out!r} resolves outside the repository {repo_root}")
    os.makedirs(out, exist_ok=True)
    this_file = Path(__file__).resolve()  # resolved BEFORE the confined chdir below
    os.chdir(out)  # confined: out is a validated single directory name under repo_root
    fam_all = {"eps": 0.4, "comms": 0.3, "sudden": 0.3}
    src = hashlib.sha256(open(this_file, "rb").read()).hexdigest()
    mpath = out / "test_manifest.json"
    if a.cmd == "manifest":
        man = dict(test_seeds=[SEEDS["test"].start, SEEDS["test"].stop], profile="B", profiles=PROFILES, fam_all=fam_all, L_s=L_S,
                   k_alarm=K_ALARM, fa_budget=FA_BUDGET, label_variants=VARIANTS, selection="variant chosen on CAL only",
                   ship_rule="LGB ships iff gradual recall >= best baseline AND test FA <= 1.2*budget AND paired median lead gain > 0 with sign-test p<0.05; else best baseline ships",
                   src_sha256=src)
        Path("test_manifest.json").write_text(json.dumps(man, indent=1, default=str))
        print("MANIFEST WRITTEN. git add/commit it NOW, then run `run`. src sha", src[:12]); return
    if not os.path.exists(mpath) or json.load(open(mpath))["src_sha256"] != src:
        sys.exit("refusing to run: manifest missing or code changed since manifest (re-run `manifest`, commit, then `run`)")
    import lightgbm as lgb
    tr = build("train", fam_all, train_sats={0, 1, 2, 3})       # sats 4-5 held out
    va, ca = build("val", fam_all), build("cal", fam_all)
    te = build("dev" if a.dev else "test", fam_all)
    print(f"rows train={len(tr['fam'])} val={len(va['fam'])} cal={len(ca['fam'])} test={len(te['fam'])} | eval-positive rate test={te['y_eval'].mean():.2%}")
    params = dict(objective="binary", metric="average_precision", num_leaves=15, min_data_in_leaf=200, lambda_l2=1.0,
                  learning_rate=0.05, feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, is_unbalance=True,
                  deterministic=True, force_row_wise=True, seed=42, num_threads=4, verbosity=-1)
    boosters, sel = {}, {}
    for v in VARIANTS:
        ytr, yva = labels(tr, v), labels(va, v)
        dtr = lgb.Dataset(tr["X"], ytr, feature_name=tr["names"])
        m = lgb.train(params, dtr, 1500, valid_sets=[lgb.Dataset(va["X"], yva, reference=dtr)], callbacks=[lgb.early_stopping(50, verbose=False)])
        boosters[v] = m
        ca_s = m.predict(ca["X"], num_iteration=m.best_iteration)
        tau = calibrate(ca, ca_s)
        sm = summarize(event_eval(ca, ca_s, tau))["gradual_all"]
        ev = event_eval(ca, ca_s, tau)
        lead = np.median([x["lead_s"] / x["ramp_s"] for x in ev if x["det"] and x["fam"] != 3] or [0])
        sel[v] = dict(train_pos=int(ytr.sum()), best_iter=m.best_iteration, cal_recall=sm["detected"] / max(sm["events"], 1), cal_median_lead_frac=float(lead), tau=tau)
        print("variant", v, sel[v])
    best = max(sel, key=lambda v: (sel[v]["cal_recall"], sel[v]["cal_median_lead_frac"]))
    print("selected on CAL:", best)
    m = boosters[best]; m.save_model(str(out / "predictor.txt"))
    ca["lgb"] = m.predict(ca["X"], num_iteration=m.best_iteration); te["lgb"] = m.predict(te["X"], num_iteration=m.best_iteration)
    res = dict(selected_variant=best, variant_selection=sel, dev_mode=a.dev, methods={}, sealed_seeds=[SEEDS["test"].start, SEEDS["test"].stop])
    allev = {}
    for name in ("ewma", "cusum", "lgb"):
        tau = calibrate(ca, ca[name]); far, evn, ss = fa_rate(te, te[name], tau)
        ev = event_eval(te, te[name], tau); allev[name] = ev
        res["methods"][name] = dict(tau=tau, pr_auc_test=avg_precision(te["y_eval"], te[name]), test_fa_per_sat_orbit=far,
                                    test_fa_events=evn, fa_sat_orbits=ss, events=summarize(ev),
                                    events_holdout_sats_4_5=summarize(event_eval(te, te[name], tau, {4, 5})))
    # paired lead comparison LGB vs best baseline (by recall then median lead)
    def key(n):
        g = res["methods"][n]["events"]["gradual_all"]; return (g["detected"], np.median([x["lead_s"] for x in allev[n] if x["det"]] or [0]))
    base = max(("ewma", "cusum"), key=key)
    pair = {(x["run"], x["sat"]): x for x in allev[base]}
    d = [(x["lead_s"] - pair[(x["run"], x["sat"])]["lead_s"]) for x in allev["lgb"]
         if x["fam"] in (1, 2, 4) and x["det"] and pair[(x["run"], x["sat"])]["det"]]
    from scipy.stats import binomtest
    pos, neg = sum(v > 0 for v in d), sum(v < 0 for v in d)
    p = binomtest(pos, pos + neg, 0.5).pvalue if pos + neg else 1.0
    gl, gb = res["methods"]["lgb"]["events"]["gradual_all"], res["methods"][base]["events"]["gradual_all"]
    ships = (gl["detected"] >= gb["detected"] and res["methods"]["lgb"]["test_fa_per_sat_orbit"] <= 1.2 * FA_BUDGET
             and np.median(d or [0]) > 0 and p < 0.05)
    res["comparison"] = dict(best_baseline=base, paired_events=len(d), lgb_earlier=pos, lgb_later=neg,
                             median_lead_gain_s=float(np.median(d)) if d else None, sign_test_p=float(p),
                             VERDICT="LGB ships" if ships else f"{base.upper()} ships (LGB did not clear the pre-declared rule)")
    imp = sorted(zip(tr["names"], m.feature_importance("gain")), key=lambda z: -z[1])[:8]
    res["top_features_gain"] = [(n, float(g)) for n, g in imp]
    model_bytes = open(out / "predictor.txt", "rb").read()
    manifest_payload = dict(
        model_sha256=hashlib.sha256(model_bytes).hexdigest(), params=params,
        feature_names=tr["names"], label_variant=best,
        tau_lgb=res["methods"]["lgb"]["tau"], k_alarm=K_ALARM, stride=STRIDE,
    )
    Path("predictor_manifest.json").write_text(json.dumps(manifest_payload, indent=1))
    Path("results.json").write_text(json.dumps(res, indent=1))
    for n, v in res["methods"].items():
        g = v["events"]
        print(f"{n:6s} FA/sat-orbit={v['test_fa_per_sat_orbit']:.2f} PR-AUC={v['pr_auc_test']:.3f} gradual={g['gradual_all']['detected']}/{g['gradual_all']['events']} "
              f"CI={[round(x,2) for x in g['gradual_all']['recall_ci95']]} sudden={g['sudden']['detected']}/{g['sudden']['events']} "
              f"lead_frac(eps/comms/comp)={[None if g[f]['median_lead_frac_of_ramp'] is None else round(g[f]['median_lead_frac_of_ramp'],2) for f in ('eps','comms','compound')]}")
    print(json.dumps(res["comparison"], indent=1))


if __name__ == "__main__":
    main()
