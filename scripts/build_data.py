"""
build_data.py
Convierte los CSV de data/ en los JSON que lee el dashboard (site/data/).
Uso: python scripts/build_data.py data site/data
"""

import json
import sys
from pathlib import Path

import pandas as pd

DIAS = {0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"}


def main(src: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(src / "reels_performance.csv", dtype={"Reel_ID": str})
    ts = pd.to_datetime(df["Fecha de Lanzamiento"] + " " + df["Hora de Lanzamiento"], utc=True).dt.tz_convert("America/Bogota")
    reels = pd.DataFrame({
        "reel_id": df["Reel_ID"], "fecha": ts.dt.strftime("%Y-%m-%d"), "hora": ts.dt.strftime("%H:%M"),
        "dia": ts.dt.dayofweek.map(DIAS), "titulo": df["Nombre / Título"], "permalink": df["Permalink"].fillna(""),
        "views": df["Visualizaciones"], "reach": df["Alcance"], "likes": df["Me Gusta"], "comments": df["Comentarios"],
        "shares": df["Compartidos"], "saves": df["Guardados"], "interactions": df["Total Interacciones"],
        "avg_watch_s": df["Promedio Tiempo de Visualización (seg)"], "total_watch_s": df["Tiempo Total de Visualización (seg)"],
        "skip_rate": df["Skip Rate (%)"], "duracion_s": df["Duración (seg)"], "extraido": df["Fecha de Extracción"].fillna("2026-06-08"),
    }).sort_values("fecha", ascending=False)
    (out / "reels.json").write_text(reels.to_json(orient="records", force_ascii=False))

    fol = pd.read_csv(src / "followers_daily.csv")
    fol.columns = ["fecha", "seguidores_nuevos"]
    (out / "followers.json").write_text(fol.to_json(orient="records"))
    print(f"reels.json: {len(reels)} · followers.json: {len(fol)}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
