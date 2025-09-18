from typing import List, Literal, Tuple, Dict
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import requests
import itertools

# =======================
# CONFIG
# =======================
# Serveur public OSRM (démo). ATTENTION: pas de vrai profil camion, quota/ratelimits possibles.
OSRM_BASE = "https://router.project-osrm.org"
ALLOWED_PROFILES = {"truck"}        # Ton API n'accepte que "truck"
DEFAULT_PROFILE = "truck"
DEFAULT_METRIC = "distance"         # on optimise la distance

# Mapping interne -> OSRM public
# truck -> driving (car) car le serveur public ne supporte pas un vrai profil camion
PROFILE_MAP_TO_OSRM = {
    "truck": "driving"
}

# =======================
# SCHEMAS
# =======================
class Point(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    role: Literal["start", "via", "end"]

class RouteRequest(BaseModel):
    points: List[Point]
    metric: Literal["distance", "time"] = DEFAULT_METRIC
    optimize: bool = True
    profile: Literal["truck"] = DEFAULT_PROFILE

class RouteResponse(BaseModel):
    distance_m: float
    duration_s: float
    ordering_input_indices: List[int]
    ordered_points: List[Point]
    geometry: Dict

# =======================
# APP
# =======================
app = FastAPI(title="Maroc Routing API (truck->driving demo)", version="1.1.0")

# =======================
# UTILS
# =======================
def _coords_str(points: List[Point]) -> str:
    """OSRM attend lon,lat séparés par ';' """
    return ";".join([f"{p.lon},{p.lat}" for p in points])

def _osrm_table(points: List[Point], osrm_profile: str, metric: str) -> List[List[float]]:
    """
    Appelle /table du serveur public OSRM et renvoie la matrice NxN des distances (m) ou durées (s).
    """
    annotations = "distance" if metric == "distance" else "duration"
    url = f"{OSRM_BASE}/table/v1/{osrm_profile}/{_coords_str(points)}"
    params = {"annotations": annotations}
    try:
        r = requests.get(url, params=params, timeout=25)
    except requests.RequestException as e:
        raise HTTPException(502, f"OSRM /table unreachable: {e}")
    if r.status_code != 200:
        raise HTTPException(502, f"OSRM /table error: {r.text}")
    data = r.json()
    key = annotations + "s"  # "distances" ou "durations"
    mat = data.get(key)
    if not mat:
        raise HTTPException(502, "OSRM /table returned no matrix")
    return mat

def _route_via_osrm(points: List[Point], osrm_profile: str) -> Dict:
    """
    Appelle /route du serveur public OSRM pour obtenir la géométrie et les totaux.
    On demande 'geometries=geojson' pour avoir directement coordinates [[lon,lat],...].
    """
    url = f"{OSRM_BASE}/route/v1/{osrm_profile}/{_coords_str(points)}"
    params = {
        "overview": "simplified",
        "geometries": "geojson",
        "steps": "false",
        "annotations": "false"
    }
    try:
        r = requests.get(url, params=params, timeout=40)
    except requests.RequestException as e:
        raise HTTPException(502, f"OSRM /route unreachable: {e}")
    if r.status_code != 200:
        raise HTTPException(502, f"OSRM /route error: {r.text}")
    data = r.json()
    routes = data.get("routes", [])
    if not routes:
        raise HTTPException(404, "No route found")
    return routes[0]

def _reindex_points(points: List[Point]) -> Tuple[List[Point], List[int]]:
    """
    Force l'ordre [start, *vias, end] en gardant la trace des indices d'entrée.
    """
    start_idx_in = next(i for i, p in enumerate(points) if p.role == "start")
    end_idx_in   = next(i for i, p in enumerate(points) if p.role == "end")
    vias = [(i, p) for i, p in enumerate(points) if p.role == "via"]

    ordered_pairs = [(start_idx_in, points[start_idx_in])] + vias + [(end_idx_in, points[end_idx_in])]
    indices = [idx for idx, _ in ordered_pairs]
    pts = [p for _, p in ordered_pairs]
    return pts, indices

def _best_ordering(points: List[Point], metric: str, osrm_profile: str) -> Tuple[List[int], List[Point], List[int]]:
    """
    Cherche l'ordre optimal [start, vias..., end] en minimisant la somme des distances (ou durées).
    Retourne l'ordre (indices locaux), les points réindexés et les indices d'entrée correspondants.
    """
    pts_reindexed, input_indices = _reindex_points(points)  # [start, *vias, end]
    n = len(pts_reindexed)
    via_local_indices = list(range(1, n - 1))  # indices des vias

    if not via_local_indices:
        return list(range(n)), pts_reindexed, input_indices

    mat = _osrm_table(pts_reindexed, osrm_profile, metric)

    best_perm = None
    best_cost = float("inf")
    for perm in itertools.permutations(via_local_indices):
        order = [0] + list(perm) + [n - 1]
        cost = sum(mat[order[i]][order[i + 1]] for i in range(len(order) - 1))
        if cost < best_cost:
            best_cost = cost
            best_perm = order

    return best_perm, pts_reindexed, input_indices

def _ordering_from_local_to_input(ordering_local: List[int], input_indices_reindexed: List[int]) -> List[int]:
    """Mappe l'ordre local vers les indices de la liste d'entrée."""
    return [input_indices_reindexed[i] for i in ordering_local]

# =======================
# ENDPOINTS
# =======================
@app.get("/health")
def health():
    return {"status": "ok", "osrm_base": OSRM_BASE, "mapped_profile": "truck->driving (public demo)"}

@app.post("/route", response_model=RouteResponse)
def route(req: RouteRequest):
    # -------- Validation 3..5 points + start/end --------
    if not (3 <= len(req.points) <= 5):
        raise HTTPException(400, "You must provide between 3 and 5 points (inclusive).")
    roles = [p.role for p in req.points]
    if roles.count("start") != 1 or roles.count("end") != 1:
        raise HTTPException(400, "Exactly one 'start' and one 'end' are required.")
    if any(r not in {"start", "via", "end"} for r in roles):
        raise HTTPException(400, "Roles must be 'start', 'via', or 'end'.")

    # -------- Profil: on accepte seulement 'truck' puis on mappe vers 'driving' --------
    if req.profile not in ALLOWED_PROFILES:
        raise HTTPException(422, f"Unsupported profile '{req.profile}'. Allowed: {sorted(ALLOWED_PROFILES)}")
    osrm_profile = PROFILE_MAP_TO_OSRM[req.profile]  # "driving" côté public

    # -------- Métrique forcée à 'distance' --------
    metric = "distance"

    # -------- Ordonancement (TSP bruteforce ≤ 3 via) --------
    if req.optimize:
        ordering_local, pts_reindexed, input_indices_reindexed = _best_ordering(
            req.points, metric, osrm_profile
        )
        ordered_points = [pts_reindexed[i] for i in ordering_local]
        ordering_input_indices = _ordering_from_local_to_input(ordering_local, input_indices_reindexed)
    else:
        # garder l'ordre d'entrée mais sous forme [start, *vias, end]
        pts_reindexed, input_indices_reindexed = _reindex_points(req.points)
        ordered_points = pts_reindexed
        ordering_input_indices = input_indices_reindexed

    # -------- Routage final --------
    route_obj = _route_via_osrm(ordered_points, osrm_profile)

    # -------- Réponse --------
    return RouteResponse(
        distance_m=route_obj.get("distance"),
        duration_s=route_obj.get("duration"),
        ordering_input_indices=ordering_input_indices,
        ordered_points=ordered_points,
        geometry=route_obj.get("geometry")
    )
