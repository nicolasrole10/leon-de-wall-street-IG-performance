"""
extract_reels_metrics.py  v4
Extrae métricas de Reels de Instagram (Instagram API con Instagram Login)
y las guarda en CSV. SOLO hace lecturas (GET).

Modos:
  python extract_reels_metrics.py          -> reels nuevos + refresca reels de los últimos REFRESH_DAYS días
  python extract_reels_metrics.py --full   -> re-consulta TODOS los reels (métricas lifetime actualizadas)

Salidas:
  reels_performance.csv   una fila por reel
  followers_daily.csv     seguidores nuevos por día (la API solo da los últimos 30 días,
                          por eso se acumula: cada corrida agrega los días que falten)

Cambios v3:
  - Token nuevo (se puede sobreescribir con la variable de entorno IG_ACCESS_TOKEN)
  - Nueva métrica: reels_skip_rate (% de vistas que saltaron en los primeros 3 s)
  - Nueva columna: Permalink
  - Se elimina "Duración (seg)": el campo `duration` no existe en la API de Instagram
    (siempre llegaba en 0)
  - Seguidores diarios a nivel cuenta (follower_count). La API NO da seguidores por reel.

Cambios v4:
  - Duración real del video: se lee el encabezado del MP4 de `media_url` con ffprobe
    (no descarga el video). Requiere ffmpeg instalado; si falta, la columna queda vacía.
    La duración no cambia, así que solo se mide una vez por reel.
  - Retención (%) = tiempo promedio visto ÷ duración. Las repeticiones cuentan como
    reproducciones, así que un reel corto que se repite puede pasar de 100%.
"""

import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN")  # nunca escribir el token en el código: va como secreto
IG_ACCOUNT_ID = None
API_VERSION = "v21.0"
BASE_URL = f"https://graph.instagram.com/{API_VERSION}"

DATA_DIR = Path(os.getenv("DATA_DIR", "."))
OUTPUT_CSV = DATA_DIR / "reels_performance.csv"
FOLLOWERS_CSV = DATA_DIR / "followers_daily.csv"
REFRESH_DAYS = 30  # reels más recientes que esto se re-consultan porque siguen acumulando

DIAS_ES = {
    "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
    "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo",
}

METRICS = [
    "views", "reach", "likes", "comments", "shares", "saved", "total_interactions",
    "ig_reels_avg_watch_time", "ig_reels_video_view_total_time", "reels_skip_rate",
]


def _get(url: str, params: dict) -> dict:
    try:
        r = requests.get(url, params=params, timeout=30)
        if not r.ok:
            try:
                body = r.json()
            except Exception:
                body = r.text
            print(f"  [ERROR {r.status_code}] {body}")
            return {"error": body.get("error", body) if isinstance(body, dict) else body}
        return r.json()
    except requests.RequestException as e:
        print(f"  [ERROR HTTP] {e}")
        return {}


def get_ig_account_id() -> str | None:
    resp = _get(f"{BASE_URL}/me", {"fields": "id,username", "access_token": ACCESS_TOKEN})
    if resp.get("id"):
        print(f"✅ Cuenta: @{resp.get('username', '?')} (id={resp['id']})")
        return resp["id"]
    print(f"❌ No se pudo resolver la cuenta: {resp}")
    return None


def get_all_reels(ig_id: str) -> list[dict]:
    reels, url = [], f"{BASE_URL}/{ig_id}/media"
    params = {
        "fields": "id,caption,timestamp,media_type,media_product_type,permalink,media_url",
        "access_token": ACCESS_TOKEN,
        "limit": 100,
    }
    while url:
        data = _get(url, params)
        reels += [m for m in data.get("data", [])
                  if m.get("media_product_type") == "REELS" or m.get("media_type") == "VIDEO"]
        url, params = data.get("paging", {}).get("next"), {}
    print(f"📽  Reels en la cuenta: {len(reels)}")
    return reels


def get_reel_insights(reel_id: str) -> dict:
    data = _get(f"{BASE_URL}/{reel_id}/insights",
                {"metric": ",".join(METRICS), "access_token": ACCESS_TOKEN})
    if data.get("error"):
        # Reintento sin reels_skip_rate (reels viejos o muy nuevos pueden no tenerla)
        data = _get(f"{BASE_URL}/{reel_id}/insights",
                    {"metric": ",".join(m for m in METRICS if m != "reels_skip_rate"),
                     "access_token": ACCESS_TOKEN})
    out = {}
    for item in data.get("data", []):
        value = item.get("value")
        if value is None:
            values = item.get("values", [])
            value = values[0].get("value", 0) if values else 0
        out[item["name"]] = value or 0
    return out


def get_duration(media_url: str | None) -> float | None:
    """Duración en segundos leyendo solo el encabezado del MP4 (ffprobe hace requests por rangos)."""
    if not media_url or not shutil.which("ffprobe"):
        return None
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", media_url],
                           capture_output=True, text=True, timeout=60)
        return round(float(r.stdout.strip()), 1)
    except (ValueError, subprocess.TimeoutExpired):
        return None


def reel_to_record(reel: dict, ins: dict, duration: float | None) -> dict:
    ts = datetime.fromisoformat(reel["timestamp"].replace("Z", "+00:00"))
    caption = reel.get("caption") or ""
    likes, comments = int(ins.get("likes", 0)), int(ins.get("comments", 0))
    shares, saved = int(ins.get("shares", 0)), int(ins.get("saved", 0))
    return {
        "Reel_ID": str(reel["id"]),
        "Fecha de Lanzamiento": ts.strftime("%Y-%m-%d"),
        "Día de Lanzamiento": DIAS_ES[ts.strftime("%A")],
        "Hora de Lanzamiento": ts.strftime("%H:%M:%S"),
        "Nombre / Título": caption.split("\n")[0].strip()[:120] or f"Reel {reel['id']}",
        "Permalink": reel.get("permalink", ""),
        "Visualizaciones": int(ins.get("views", 0)),
        "Alcance": int(ins.get("reach", 0)),
        "Duración (seg)": duration,
        "Promedio Tiempo de Visualización (seg)": round((ins.get("ig_reels_avg_watch_time") or 0) / 1000, 2),
        "Retención (%)": round((ins.get("ig_reels_avg_watch_time") or 0) / 10 / duration, 1) if duration else None,
        "Tiempo Total de Visualización (seg)": round((ins.get("ig_reels_video_view_total_time") or 0) / 1000, 2),
        "Skip Rate (%)": ins.get("reels_skip_rate"),
        "Me Gusta": likes,
        "Comentarios": comments,
        "Compartidos": shares,
        "Guardados": saved,
        "Total Interacciones": int(ins.get("total_interactions") or (likes + comments + shares + saved)),
        "Fecha de Extracción": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


def update_followers_daily(ig_id: str) -> None:
    """follower_count (period=day) = seguidores nuevos por día. La API solo permite los últimos 30 días."""
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=29)
    data = _get(f"{BASE_URL}/{ig_id}/insights", {
        "metric": "follower_count", "period": "day",
        "since": int(since.timestamp()), "until": int(until.timestamp()),
        "access_token": ACCESS_TOKEN,
    })
    rows = []
    for item in data.get("data", []):
        for v in item.get("values", []):
            day = (datetime.fromisoformat(v["end_time"].replace("Z", "+00:00")) - timedelta(days=1))
            rows.append({"Fecha": day.strftime("%Y-%m-%d"), "Seguidores Nuevos": v["value"]})
    if not rows:
        print("⚠  No se obtuvieron seguidores diarios.")
        return
    df = pd.DataFrame(rows)
    if Path(FOLLOWERS_CSV).exists():
        df = pd.concat([pd.read_csv(FOLLOWERS_CSV), df]).drop_duplicates("Fecha", keep="last")
    df.sort_values("Fecha").to_csv(FOLLOWERS_CSV, index=False, encoding="utf-8-sig")
    print(f"👥 {FOLLOWERS_CSV}: {len(df)} días")


def main():
    if not ACCESS_TOKEN:
        sys.exit("❌ Falta la variable de entorno IG_ACCESS_TOKEN")
    full = "--full" in sys.argv
    ig_id = IG_ACCOUNT_ID or get_ig_account_id()
    if not ig_id:
        sys.exit(1)

    df_old = pd.DataFrame()
    if Path(OUTPUT_CSV).exists():
        df_old = pd.read_csv(OUTPUT_CSV, encoding="utf-8-sig", dtype={"Reel_ID": str})

    reels = get_all_reels(ig_id)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=REFRESH_DAYS)).isoformat()
    known = set(df_old.get("Reel_ID", pd.Series(dtype=str)))
    to_query = reels if full else [r for r in reels if r["id"] not in known or r["timestamp"] >= cutoff]
    print(f"🔄 Consultando {len(to_query)} reels ({'full' if full else 'nuevos + últimos ' + str(REFRESH_DAYS) + ' días'})")

    # La duración no cambia: se reutiliza la ya guardada y solo se mide la que falta
    known_dur = {}
    if "Duración (seg)" in df_old.columns:
        known_dur = {k: v for k, v in zip(df_old["Reel_ID"], df_old["Duración (seg)"]) if pd.notna(v) and v > 0}
    missing = [r for r in to_query if r["id"] not in known_dur]
    if missing:
        if not shutil.which("ffprobe"):
            print("⚠  ffprobe no está instalado: la duración y la retención quedarán vacías (instala ffmpeg).")
        with ThreadPoolExecutor(8) as ex:
            known_dur.update(zip([r["id"] for r in missing], ex.map(lambda r: get_duration(r.get("media_url")), missing)))
        print(f"⏱  Duraciones medidas: {sum(known_dur.get(r['id']) is not None for r in missing)}/{len(missing)}")

    records = []
    for i, reel in enumerate(to_query, 1):
        rec = reel_to_record(reel, get_reel_insights(reel["id"]), known_dur.get(reel["id"]))
        records.append(rec)
        print(f"  [{i:>3}/{len(to_query)}] {rec['Fecha de Lanzamiento']} views={rec['Visualizaciones']}")

    df = pd.concat([df_old, pd.DataFrame(records)], ignore_index=True)
    df = df.drop_duplicates("Reel_ID", keep="last").sort_values("Fecha de Lanzamiento", ascending=False)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"✅ {OUTPUT_CSV}: {len(df)} reels")

    update_followers_daily(ig_id)


if __name__ == "__main__":
    main()
