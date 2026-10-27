# Performance de Reels · El León de Wall Street

Dashboard de performance de los Reels de [@leondewallstreett](https://www.instagram.com/leondewallstreett/), publicado en GitHub Pages y actualizado **todos los días** con la API de Instagram.

**Dashboard:** https://nicolasrole10.github.io/leon-de-wall-street-IG-performance/

## Pestañas

| Pestaña | Qué muestra |
|---|---|
| Data | Documentación de cada variable de la API y tabla de reels con filtros por columna |
| Scorecard | Promedios por reel (likes, guardados, enviados, seguidores nuevos, engagement, alcance) vs. el período anterior |
| Trends | Tendencia por métrica con promedio, mediana y rango medio (30/60/90/180 días); click en un punto para excluirlo |
| Duración × Hook | Matriz de duración del video × grupo de skip rate |
| Modelo | XGBoost y regresión lineal sobre log(alcance), con importancia por permutación, SHAP y LIME |

## Cómo se actualiza

El workflow [`.github/workflows/daily.yml`](.github/workflows/daily.yml) corre cada día a las 6:17 a. m. (Bogotá):

1. `scripts/extract_reels_metrics.py` consulta la API (solo lecturas) y actualiza `data/reels_performance.csv` y `data/followers_daily.csv`.
2. `scripts/build_data.py` convierte los CSV en los JSON del dashboard.
3. `scripts/train_reach_model.py` re-entrena el modelo de alcance.
4. Guarda los CSV en el repo y publica `site/` en GitHub Pages.

También se puede correr a mano desde **Actions → Actualización diaria del dashboard → Run workflow**.

## Secretos (Settings → Secrets and variables → Actions)

| Secreto | Para qué | Obligatorio |
|---|---|---|
| `IG_ACCESS_TOKEN` | Token de larga duración de la Instagram API | Sí |
| `GH_PAT` | Token personal de GitHub (fine-grained, permiso *Secrets: read and write* sobre este repo) para renovar el token de Instagram cada lunes | Recomendado: sin él, el token de Instagram vence a los 60 días |

El token de Instagram **nunca** va en el código: el repo es público.

## Correr localmente

```bash
pip install -r requirements.txt   # y ffmpeg instalado
export IG_ACCESS_TOKEN=...
DATA_DIR=data python scripts/extract_reels_metrics.py
python scripts/build_data.py data site/data
python scripts/train_reach_model.py data/reels_performance.csv model_out
# renombrar model_out/*.json a site/data/m_*.json (ver el workflow)
cd site && python -m http.server
```
