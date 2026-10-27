"""
train_reach_model.py
Modelo predictivo de alcance (reach) por reel: XGBoost vs. regresión lineal,
con importancia de variables por permutación, SHAP y LIME.

Target: log1p(reach). Se excluyen reels con < 3 días (métricas aún acumulando).

Dos especificaciones de features:
  conteos : likes, comentarios, compartidos, guardados, skip rate, tiempo prom. visto
            (lo pedido; ojo: los conteos suben mecánicamente con el alcance)
  tasas   : interacciones por vista, skip rate, retención (% del video visto), duración,
            hora, fin de semana, edad
            (mide calidad del contenido, menos atado al tamaño del alcance)

Uso: python train_reach_model.py reels_performance.csv out_dir/
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import shap
import statsmodels.api as sm
import xgboost as xgb
from lime.lime_tabular import LimeTabularExplainer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import KFold, RepeatedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

SEED = 42
SPECS = {
    "conteos": ["log_likes", "log_comments", "log_shares", "log_saves", "skip_rate", "avg_watch_s"],
    "tasas": ["like_rate", "comment_rate", "share_rate", "save_rate", "skip_rate", "retencion", "duracion_s",
              "hora", "fin_de_semana", "log_edad"],
}


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"Reel_ID": str})
    ts = pd.to_datetime(df["Fecha de Lanzamiento"] + " " + df["Hora de Lanzamiento"], utc=True).dt.tz_convert("America/Bogota")
    extr = pd.to_datetime(df["Fecha de Extracción"].fillna("2026-06-08")).dt.tz_localize("America/Bogota")
    d = pd.DataFrame({
        "reel_id": df["Reel_ID"], "fecha": ts.dt.strftime("%Y-%m-%d"), "titulo": df["Nombre / Título"],
        "reach": df["Alcance"], "views": df["Visualizaciones"],
        "skip_rate": df["Skip Rate (%)"], "avg_watch_s": df["Promedio Tiempo de Visualización (seg)"],
        "duracion_s": df["Duración (seg)"],
        "retencion": (df["Promedio Tiempo de Visualización (seg)"] / df["Duración (seg)"] * 100).clip(upper=100),  # loops >100% se topan
        "hora": ts.dt.hour + ts.dt.minute / 60, "fin_de_semana": (ts.dt.dayofweek >= 5).astype(int),
        "edad": (extr - ts.dt.normalize()).dt.days,
    })
    for col, src in [("likes", "Me Gusta"), ("comments", "Comentarios"), ("shares", "Compartidos"), ("saves", "Guardados")]:
        d["log_" + col] = np.log1p(df[src])
        d[col[:-1] + "_rate"] = df[src] / df["Visualizaciones"] * 100  # por cada 100 vistas
    d["log_edad"] = np.log1p(d["edad"])
    d["y"] = np.log1p(d["reach"])
    return d[(d["edad"] >= 3) & d["skip_rate"].notna() & d["duracion_s"].notna()].reset_index(drop=True)


def models():
    return {
        "xgboost": xgb.XGBRegressor(n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.8,
                                    colsample_bytree=0.8, min_child_weight=3, random_state=SEED),
        "lineal": make_pipeline(StandardScaler(), LinearRegression()),
    }


def run(d: pd.DataFrame):
    metrics, importance, local, preds, coefs = [], [], [], [], []
    y = d["y"].to_numpy()
    for spec, feats in SPECS.items():
        X = d[feats].to_numpy(float)
        for name, base in models().items():
            # CV repetida: R² y error fuera de muestra
            r2s, maes, apes = [], [], []
            perm = np.zeros((len(feats),))
            perm_sq = np.zeros((len(feats),))
            nfold = 0
            for tr, te in RepeatedKFold(n_splits=5, n_repeats=4, random_state=SEED).split(X):
                m = models()[name].fit(X[tr], y[tr])
                p = m.predict(X[te])
                r2s.append(r2_score(y[te], p))
                maes.append(mean_absolute_error(y[te], p))
                apes.append(np.median(np.abs(np.expm1(p) / np.expm1(y[te]) - 1)))
                pi = permutation_importance(m, X[te], y[te], scoring="r2", n_repeats=10, random_state=SEED)
                perm += pi.importances_mean
                perm_sq += pi.importances_mean ** 2
                nfold += 1
            perm_mean = perm / nfold
            perm_sd = np.sqrt(np.maximum(perm_sq / nfold - perm_mean ** 2, 0))
            metrics.append({"spec": spec, "model": name, "n": len(d), "r2_cv": round(float(np.mean(r2s)), 3),
                            "r2_sd": round(float(np.std(r2s)), 3), "mae_log": round(float(np.mean(maes)), 3),
                            "error_mediano_pct": round(float(np.mean(apes)) * 100, 1)})

            # Predicciones fuera de muestra (una pasada de 5 folds) para el gráfico real vs. predicho
            oof = np.zeros_like(y)
            for tr, te in KFold(5, shuffle=True, random_state=SEED).split(X):
                oof[te] = models()[name].fit(X[tr], y[tr]).predict(X[te])
            for i, r in d.iterrows():
                preds.append({"spec": spec, "model": name, "reel_id": r.reel_id, "fecha": r.fecha, "titulo": r.titulo,
                              "real": int(r.reach), "predicho": int(round(np.expm1(oof[i])))})

            # Modelo final sobre todos los datos para SHAP y LIME
            final = base.fit(X, y)
            if name == "xgboost":
                sv = shap.TreeExplainer(final).shap_values(X)
                base_value = float(np.mean(final.predict(X)))
            else:
                scaler, lr = final.named_steps["standardscaler"], final.named_steps["linearregression"]
                sv = scaler.transform(X) * lr.coef_  # SHAP exacto de un modelo lineal (features independientes)
                base_value = float(lr.intercept_)

            lime_exp = LimeTabularExplainer(X, feature_names=feats, mode="regression", discretize_continuous=False,
                                            random_state=SEED)
            lime_w = np.zeros_like(X)
            for i in range(len(X)):
                e = lime_exp.explain_instance(X[i], final.predict, num_features=len(feats), num_samples=2000)
                for fi, w in e.as_map()[1]:
                    lime_w[i, fi] = w  # pendiente local por 1 desviación estándar

            for fi, f in enumerate(feats):
                for method, val, sd in [
                    ("permutacion", perm_mean[fi], perm_sd[fi]),
                    ("shap", np.mean(np.abs(sv[:, fi])), np.std(np.abs(sv[:, fi]))),
                    ("lime", np.mean(np.abs(lime_w[:, fi])), np.std(np.abs(lime_w[:, fi]))),
                ]:
                    importance.append({"spec": spec, "model": name, "method": method, "feature": f,
                                       "value": round(float(val), 4), "sd": round(float(sd), 4)})
            for i, r in d.iterrows():
                local.append({"spec": spec, "model": name, "reel_id": r.reel_id, "feature": "__base__",
                              "x": None, "pct": None, "shap": round(base_value, 4), "lime": None})
                for fi, f in enumerate(feats):
                    local.append({"spec": spec, "model": name, "reel_id": r.reel_id, "feature": f,
                                  "x": round(float(X[i, fi]), 4),
                                  "pct": round(float((X[:, fi] < X[i, fi]).mean()), 3),
                                  "shap": round(float(sv[i, fi]), 4), "lime": round(float(lime_w[i, fi]), 4)})

        # OLS con features estandarizadas: coeficientes con IC 95%
        Z = (d[feats] - d[feats].mean()) / d[feats].std()
        ols = sm.OLS(y, sm.add_constant(Z)).fit(cov_type="HC3")
        ci = ols.conf_int()
        for f in feats:
            coefs.append({"spec": spec, "feature": f, "coef": round(float(ols.params[f]), 4),
                          "lo": round(float(ci.loc[f, 0]), 4), "hi": round(float(ci.loc[f, 1]), 4),
                          "p": round(float(ols.pvalues[f]), 4),
                          "efecto_pct": round(float(np.expm1(ols.params[f]) * 100), 1)})
        metrics.append({"spec": spec, "model": "ols_in_sample", "n": len(d), "r2_cv": round(float(ols.rsquared), 3),
                        "r2_sd": None, "mae_log": None, "error_mediano_pct": None})
    return metrics, importance, local, preds, coefs


if __name__ == "__main__":
    src, out = sys.argv[1], Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    d = load(src)
    print(f"Reels para entrenar: {len(d)}")
    names = ["model_metrics", "importance", "local", "predictions", "coefs"]
    for name, rows in zip(names, run(d)):
        (out / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False))
        print(name, len(rows))
