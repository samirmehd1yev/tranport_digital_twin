"""Build index.html: Baku Mobility Twin, buses and bicycles, as one self-contained page.

Reads the source data in data/:
  - Baku's bus network in ayna.sqlite: lines, route geometry, stops and each line's run time.
  - The bicycle lanes, bike stations (MPV) and bike parking points (MPS) in the two KMZ files.

Measures it in metres (UTM zone 39N, EPSG:32639) and derives what the page needs: where lines stack onto the same
street, which stops have no bike point within reach, how the lanes connect, and the Azadlıq avenue lane option. It
then writes everything into src/app.html's data slot. Every figure on the page comes from these files or is
computed in the page from them, and the page states the assumptions its simulated timetable rests on.

    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    .venv/bin/python build.py            # -> index.html
"""
import collections, datetime, json, re, sqlite3, statistics
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely.ops import substring
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
K = "{http://www.opengis.net/kml/2.2}"
TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32639", always_xy=True)
TO_LL = Transformer.from_crs("EPSG:32639", "EPSG:4326", always_xy=True)
CENTRAL = dict(lat=(40.30, 40.46), lon=(49.70, 50.05))   # central Baku, the frame for coverage figures
REGION = dict(lat=(39.9, 41.0), lon=(48.9, 50.7))        # every coordinate must fall in and around Absheron
WALK = 300.0      # metres: a bike point this close to a bus stop counts as a connection
ON_LANE = 50.0    # metres: a bike station this close to a lane counts as on the network


def check(ok, what):
    """A data check: stop the build when the source data does not parse or add up as expected."""
    if not ok:
        raise SystemExit(f"data check failed: {what}")


def utm(lon, lat):
    return TO_UTM.transform(lon, lat)


def in_region(lon, lat):
    return REGION["lat"][0] <= lat <= REGION["lat"][1] and REGION["lon"][0] <= lon <= REGION["lon"][1]


def in_central(lon, lat):
    return CENTRAL["lat"][0] <= lat <= CENTRAL["lat"][1] and CENTRAL["lon"][0] <= lon <= CENTRAL["lon"][1]


def ll_line(line_utm, tol=3.0):
    """A UTM line simplified to `tol` metres, back to [lon, lat] pairs at 5 decimals (about a metre)."""
    s = line_utm.simplify(tol, preserve_topology=False)
    xs, ys = s.xy
    lon, lat = TO_LL.transform(list(xs), list(ys))
    return [[round(a, 5), round(b, 5)] for a, b in zip(lon, lat)]


def ll_point(p):
    lon, lat = TO_LL.transform(p.x, p.y)
    return [round(lon, 5), round(lat, 5)]


def utm_line(path):
    xs, ys = TO_UTM.transform([p[0] for p in path], [p[1] for p in path])
    return LineString(list(zip(xs, ys)))


# ---------------------------------------------------------------------------------------------- the bicycle layers
def kml_layer(kmz, name):
    """Placemarks of the Folder named `name`: (name, [(lon, lat), ...])."""
    root = ET.fromstring(ZipFile(DATA / kmz).read("doc.kml"))
    folder = next((f for f in root.iter(K + "Folder") if f.findtext(K + "name") == name), None)
    check(folder is not None, f"{kmz} has a folder named {name!r}")
    out = []
    for pm in folder.findall(K + "Placemark"):
        pts = []
        for item in pm.findtext(f".//{K}coordinates", default="").split():
            lon, lat = item.split(",")[:2]
            pts.append((float(lon), float(lat)))
        out.append((pm.findtext(K + "name") or "", pts))
    return out


raw_now = kml_layer("movcud-zolaqlar-velo.kmz", "Mövcud zolaqlar")
raw_2025 = kml_layer("mpv-v-mps.-son.kmz", "Velosiped yolları 2025 yanvar")
raw_mpv = kml_layer("mpv-v-mps.-son.kmz", "velosiped məntəqələri yeni")
raw_mps = kml_layer("mpv-v-mps.-son.kmz", "My Places")

# a lane placemark needs two distinct points to be a line; any that do not are reported, not drawn
lanes_now = [(n.strip(), LineString([utm(*p) for p in pts])) for n, pts in raw_now if len(set(pts)) >= 2]
lanes_2025 = [(n.strip(), LineString([utm(*p) for p in pts])) for n, pts in raw_2025 if len(set(pts)) >= 2]
lane_dropped = [n for n, pts in raw_now if len(set(pts)) < 2]
mpv = [(n, pts[0]) for n, pts in raw_mpv if pts]
mps = [(n, pts[0]) for n, pts in raw_mps if pts and n.startswith("MPS")]

check(len(mpv) == len(raw_mpv) > 0, "every MPV placemark is a bike station with a point")
check(len(mps) == len(raw_mps) > 0, "every My Places placemark is an MPS point")
check(len(lanes_now) >= len(raw_now) - 2, f"the current lane layer parses ({len(lanes_now)} of {len(raw_now)})")
check(all(in_region(*p) for _, pts in raw_now + raw_2025 for p in pts), "every lane point lies in Absheron")
check(all(in_region(*p) for _, p in mpv + mps), "every station lies in Absheron")
lanes_km = sum(l.length for _, l in lanes_now) / 1000
lanes_2025_km = sum(l.length for _, l in lanes_2025) / 1000
check(10 < lanes_km < 1000 and 10 < lanes_2025_km < 1000, f"lane lengths are plausible ({lanes_km:.1f}, {lanes_2025_km:.1f} km)")

lane_geoms = [l for _, l in lanes_now]
lane_tree = STRtree(lane_geoms)


def nearest_lane(p):
    j = lane_tree.nearest(p)
    return p.distance(lane_geoms[j]), lanes_now[j][0]


# lane pieces within 20 m of each other form one connected section
parent = list(range(len(lanes_now)))


def find(i):
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


for i, l in enumerate(lane_geoms):
    for j in lane_tree.query(l.buffer(20.0)):
        if j != i and l.distance(lane_geoms[j]) <= 20.0:
            parent[find(i)] = find(int(j))
sections = collections.defaultdict(float)
for i, l in enumerate(lane_geoms):
    sections[find(i)] += l.length
section_order = {root: k for k, root in enumerate(sorted(sections, key=lambda r: -sections[r]))}

stations = []
for kind, rows in (("MPV", mpv), ("MPS", mps)):
    for name, (lon, lat) in rows:
        p = Point(utm(lon, lat))
        d, street = nearest_lane(p)
        stations.append(dict(name=name, kind=kind, lon=round(lon, 6), lat=round(lat, 6), lane=round(d), street=street,
                             central=in_central(lon, lat), p=p))
mpv_on = sum(1 for s in stations if s["kind"] == "MPV" and s["lane"] <= ON_LANE)

# ---------------------------------------------------------------------------------------------- the bus network
db = sqlite3.connect(f"file:{DATA / 'ayna.sqlite'}?mode=ro", uri=True)
db.row_factory = sqlite3.Row
zones = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM working_zone_types")}
regions = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM regions")}
payments = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM payment_types")}
buses = list(db.execute("SELECT * FROM buses ORDER BY id"))
stop_rows = {r["id"]: r for r in db.execute("SELECT * FROM stop_details")}
check(len(buses) > 0 and len(stop_rows) > 0, "the bus database has lines and stops")
check(all((b["route_length"] or 0) > 0 and (b["duration_minuts"] or 0) > 0 for b in buses), "every line has a length and a run time")
check(all(in_region(s["longitude"], s["latitude"]) for s in stop_rows.values()), "every stop lies in Absheron")

coords = collections.defaultdict(list)
for r in db.execute("SELECT route_id, longitude, latitude FROM route_coordinates ORDER BY route_id, sequence_order"):
    coords[r["route_id"]].append((r["longitude"], r["latitude"]))
route_rows = list(db.execute("SELECT * FROM routes ORDER BY bus_id, direction_type_id, id"))
links = collections.defaultdict(list)            # (bus_id, direction) -> [stop_id in the database's order]
for r in db.execute("SELECT bus_id, direction_type_id, stop_id FROM bus_stops ORDER BY id"):
    links[(r["bus_id"], r["direction_type_id"])].append(r["stop_id"])

stop_index = {sid: i for i, sid in enumerate(sorted(stop_rows))}
stop_lines = collections.defaultdict(set)
lines, routes, route_utm = [], [], []
line_index = {}
for b in buses:
    line_index[b["id"]] = len(lines)
    lines.append(dict(
        n=b["number"].strip(), carrier=(b["carrier"] or "").strip(), a=(b["first_point"] or "").strip(),
        b=(b["last_point"] or "").strip(), km=round(b["route_length"], 2), min=b["duration_minuts"],
        fare=(b["tariff"] or 0) / 100, zone=zones.get(b["working_zone_type_id"], ""), zoneId=b["working_zone_type_id"],
        region=regions.get(b["region_id"], ""), pay=payments.get(b["payment_type_id"], ""), routes=[],
    ))

for r in route_rows:
    pts = coords.get(r["id"]) or []
    if len(pts) < 2:
        continue
    li = line_index[r["bus_id"]]
    path = ll_line(LineString([utm(*p) for p in pts]))
    line_utm = utm_line(path)       # measured on the simplified path the page animates, so distances agree
    # stops in the order the bus meets them: projected onto its own path, duplicates and far strays dropped
    seq, seen = [], set()
    for sid in links.get((r["bus_id"], r["direction_type_id"]), []):
        if sid in seen or sid not in stop_rows:
            continue
        seen.add(sid)
        s = stop_rows[sid]
        sp = Point(utm(s["longitude"], s["latitude"]))
        if line_utm.distance(sp) > 150:
            continue
        seq.append((line_utm.project(sp), stop_index[sid]))
        stop_lines[stop_index[sid]].add(li)
    seq.sort()
    lines[li]["routes"].append(len(routes))
    routes.append(dict(line=li, dir=r["direction_type_id"], name=(r["destination"] or r["name"] or "").strip(),
                       m=round(line_utm.length), path=path, stops=[[s, round(d)] for d, s in seq]))
    route_utm.append(line_utm)

mapped = [li for li, l in enumerate(lines) if l["routes"]]
no_geometry = [lines[li]["n"] for li in range(len(lines)) if not lines[li]["routes"]]
check(len(mapped) >= 0.9 * len(lines), f"most lines have route geometry ({len(mapped)} of {len(lines)})")

# the register's route_length is the round trip: it should be about twice the measured one-way geometry
one_way = {li: statistics.mean(routes[ri]["m"] for ri in lines[li]["routes"]) for li in mapped}
ratios = sorted(lines[li]["km"] * 1000 / (2 * one_way[li]) for li in mapped)
register_ratio = ratios[len(ratios) // 2]
check(0.9 <= register_ratio <= 1.1, f"route_length is the round trip of the mapped geometry (median ratio {register_ratio:.2f})")
speeds = sorted(one_way[li] / 1000 / (lines[li]["min"] / 60) for li in mapped)
implied_kmh = speeds[len(speeds) // 2]

stops = []
for sid in sorted(stop_rows):
    s = stop_rows[sid]
    p = Point(utm(s["longitude"], s["latitude"]))
    stops.append(dict(name=(s["name"] or "").strip(), code=(s["code"] or "").strip(), lon=round(s["longitude"], 5),
                      lat=round(s["latitude"], 5), hub=int(bool(s["is_transport_hub"])),
                      lines=sorted(stop_lines.get(stop_index[sid], ())), central=in_central(s["longitude"], s["latitude"]),
                      lane=round(nearest_lane(p)[0]), p=p))

# ---------------------------------------------------------------------------------------------- bus and bike together
bike_pts = [s["p"] for s in stations]
bike_tree = STRtree(bike_pts)
for s in stops:
    j = bike_tree.nearest(s["p"])
    s["bike"] = round(s["p"].distance(bike_pts[j]))
    s["bikeAt"] = int(j)
served = [i for i, s in enumerate(stops) if s["lines"]]
central_served = [i for i in served if stops[i]["central"]]
gaps = sorted((i for i in served if stops[i]["bike"] > WALK and len(stops[i]["lines"]) >= 10),
              key=lambda i: (-len(stops[i]["lines"]), stops[i]["name"]))

# ---------------------------------------------------------------------------------------------- corridors
# Where lines pile onto the same street. Every route is sampled every 20 m into 80 m cells and each cell counts the
# distinct lines through it. A corridor grows along one route from a peak cell while the cells keep at least 45% of
# the peak's lines; the next corridor starts at least 2.5 km from the ones already taken.
CELL, STEP = 80.0, 20.0
cell_lines = collections.defaultdict(set)
samples = []
for ri, ro in enumerate(routes):
    line = route_utm[ri]
    n = max(2, int(line.length // STEP))
    dist = np.linspace(0, line.length, n + 1)
    pts = shapely.line_interpolate_point(line, dist)
    keys = [(int(q.x // CELL), int(q.y // CELL)) for q in pts]
    for k in keys:
        cell_lines[k].add(ro["line"])
    samples.append((dist, pts, keys))
heat = []
for (cx, cy), ls in cell_lines.items():
    if len(ls) >= 6:
        lon, lat = TO_LL.transform((cx + 0.5) * CELL, (cy + 0.5) * CELL)
        heat.append([round(lon, 5), round(lat, 5), len(ls)])
heat.sort(key=lambda c: -c[2])

STREET = re.compile(r"^(.*?\b(?:küç\.|küçəsi|pr\.|prospekti|şos\.|şosesi|şossesi|yolu|bulvarı))", re.I)
PLACE = re.compile(r"(m/st|NMM|dairəsi|meydanı|Avtovağzal|stansiyası|Stadionu)", re.I)


def corridor_name(geom):
    streets, places, busiest = collections.Counter(), collections.Counter(), None
    for i, s in enumerate(stops):
        if s["lines"] and geom.distance(s["p"]) <= 40:
            w = len(s["lines"])
            m = STREET.match(s["name"])
            if m:
                words = m.group(1).split()
                streets[" ".join(words[-2:] if len(words) > 3 else words)] += w     # "… Stadionu Böyükşor Bulvarı" -> the street
            if PLACE.search(s["name"]):
                places[re.sub(r"\s*\(.*?\)", "", s["name"]).strip()] += w
            if not busiest or w > busiest[1]:
                busiest = (s["name"], w)
    place = places.most_common(1)[0][0] if places else (busiest[0] if busiest else "")
    street = streets.most_common(1)[0][0] if streets else ""
    if street and street.split()[0] in place:      # "Bakı-Sumqayıt şosesi" near "Bakı-Sumqayıt şosesi YDM" says it twice
        place = ""
    return (street or place), (place if street else "")


corridors, taken = [], []
for seed in sorted(cell_lines, key=lambda k: (-len(cell_lines[k]), k)):
    peak = len(cell_lines[seed])
    if len(corridors) == 5 or peak < 12:
        break
    centre = Point((seed[0] + 0.5) * CELL, (seed[1] + 0.5) * CELL)
    if any(g.distance(centre) < 2500 for g in taken):
        continue
    keep = max(10, 0.45 * peak)
    best = None
    for ri, (dist, pts, keys) in enumerate(samples):
        hit = [i for i, k in enumerate(keys) if k == seed]
        if not hit:
            continue
        i0 = i1 = hit[0]
        while i0 > 0 and len(cell_lines[keys[i0 - 1]]) >= keep:
            i0 -= 1
        while i1 < len(keys) - 1 and len(cell_lines[keys[i1 + 1]]) >= keep:
            i1 += 1
        if not best or dist[i1] - dist[i0] > best[0]:
            best = (dist[i1] - dist[i0], ri, dist[i0], dist[i1])
    taken.append(centre.buffer(1.0))
    if not best or best[0] < 400:
        continue
    _, ri, a, b = best
    if b - a > 3000:                        # a bus lane is decided stretch by stretch: keep 3 km around the peak
        mid = route_utm[ri].project(centre)
        a, b = max(a, mid - 1500), min(b, mid + 1500)
    geom = substring(route_utm[ri], a, b)
    taken[-1] = geom
    # every route's share of the stretch, either direction: samples within 25 m of it, as runs along the route
    stretches, corridor_lines = [], set()
    for rj, (dist, pts, keys) in enumerate(samples):
        if route_utm[rj].distance(geom) > 25:
            continue
        on = shapely.distance(pts, geom) <= 25
        runs, start = [], None
        for i, flag in enumerate(on):
            if flag and start is None:
                start = i
            if (not flag or i == len(on) - 1) and start is not None:
                end = i if flag else i - 1
                if dist[end] - dist[start] >= 100:
                    runs.append([round(dist[start]), round(dist[end])])
                start = None
        if runs:
            # which way the route runs along the stretch, +1 with the stretch's drawing direction, -1 against it
            a0, b0 = max(runs, key=lambda r: r[1] - r[0])
            way = 1 if geom.project(route_utm[rj].interpolate(b0)) >= geom.project(route_utm[rj].interpolate(a0)) else -1
            stretches.append([rj, runs, way])
            corridor_lines.add(routes[rj]["line"])
    name, near = corridor_name(geom)
    corridor_stops = [i for i, s in enumerate(stops) if s["lines"] and geom.distance(s["p"]) <= 40]
    corridors.append(dict(
        name=name, near=near, peak=peak, m=round(geom.length), path=ll_line(geom, 2.0),
        centre=ll_point(geom.interpolate(0.5, normalized=True)), lines=sorted(corridor_lines),
        stretches=stretches, stops=corridor_stops,
    ))
check(len(corridors) >= 3, "at least three corridors stand out")

# ---------------------------------------------------------------------------------------------- the Azadlıq lane option
# The largest group of bike stations off the lane network sits north of where the Vaqif pr. lane ends, along Azadlıq
# prospekti. The option extends the lane up the avenue: its alignment comes from the buses that run it, the route
# that starts within 50 m of the lane's end and passes the most stops named on Azadlıq prospekti (a stop within 50 m
# of the path, the avenue's width) on the way north,
# cut from the lane's end to its northernmost Azadlıq stop.
vaqif = next(l for n, l in lanes_now if n == "Vaqif pr.")
start = Point(max(vaqif.coords, key=lambda c: c[1]))
off_network = [i for i, s in enumerate(stations) if s["kind"] == "MPV" and s["lane"] > ON_LANE]
cluster = [i for i in off_network if stations[i]["street"] == "Vaqif pr." and stations[i]["p"].y > start.y]
azad = [s["p"] for s in stops if re.match(r"^Azadlıq (pr\.|prospekti|m/st)", s["name"])]
best = None
for ri, line in enumerate(route_utm):
    if line.distance(start) > 50:
        continue
    north = [p for p in azad if line.distance(p) <= 50 and p.y > start.y]
    if not north:
        continue
    ends = sorted([line.project(start), line.project(max(north, key=lambda p: p.y))])
    seg = substring(line, *ends)
    score = (sum(1 for p in azad if seg.distance(p) <= 50), -seg.length)
    if not best or score > best[0]:
        best = (score, ri, seg)
check(best is not None, "a bus route runs up Azadlıq prospekti from the Vaqif pr. lane")
_, ri, seg = best
north_end = TO_LL.transform(*seg.coords[-1] if seg.coords[-1][1] > seg.coords[0][1] else seg.coords[0])
check(north_end[1] > 40.42, f"the Azadlıq lane reaches Azadlıq metro (ends at {north_end[1]:.4f})")
newly_on = [i for i in off_network if seg.distance(stations[i]["p"]) <= ON_LANE]
near_300 = [i for i, s in enumerate(stations) if seg.distance(s["p"]) <= WALK]
stops_new = [i for i in served if stops[i]["lane"] > WALK and seg.distance(stops[i]["p"]) <= WALK]
stops_lane_before = sum(1 for i in served if stops[i]["lane"] <= WALK)
proposal = dict(
    name="Azadlıq prospekti", path=ll_line(seg, 2.0), m=round(seg.length), link=round(route_utm[ri].distance(start)),
    via=lines[routes[ri]["line"]]["n"], azadliqStops=best[0][0], cluster=len(cluster), clusterIdx=cluster,
    stationsOn=newly_on, stations300=near_300, stopsNew=stops_new,
    linesNew=sorted({li for i in stops_new for li in stops[i]["lines"]}),
)

# ---------------------------------------------------------------------------------------------- write
stats = dict(
    lines=len(lines), linesMapped=len(mapped), noGeometry=no_geometry, routes=len(routes), stops=len(stops),
    stopsServed=len(served), hubs=sum(s["hub"] for s in stops), carriers=len({l["carrier"] for l in lines}),
    networkKm=round(sum(one_way.values()) / 1000), registerRatio=round(register_ratio, 2), impliedKmh=round(implied_kmh, 1),
    lanesKm=round(lanes_km, 2), lanes2025Km=round(lanes_2025_km, 2), lanePieces=len(lanes_now), laneDropped=lane_dropped,
    sections=len(sections), largestSectionKm=round(max(sections.values()) / 1000, 2),
    mpv=len(mpv), mps=len(mps), mpvOnLane=mpv_on, mpvOffLane=len(off_network),
    centralStops=len(central_served), centralStopsBike=sum(1 for i in central_served if stops[i]["bike"] <= WALK),
    stopsBike=sum(1 for i in served if stops[i]["bike"] <= WALK), stopsLane=stops_lane_before,
    gaps=gaps, walk=WALK, onLane=ON_LANE, peakCell=heat[0][2] if heat else 0,
)
for s in stations:
    del s["p"]
for s in stops:
    del s["p"]
lane_rows = []
for i, (n, l) in enumerate(lanes_now):
    lane_rows.append(dict(name=n, m=round(l.length), section=section_order[find(i)], path=ll_line(l, 1.0)))
payload = dict(
    generated=datetime.date.today().isoformat(),
    sources=dict(bus="ayna.sqlite — bus lines, routes, stops and run times",
                 lanes="movcud-zolaqlar-velo.kmz — Mövcud zolaqlar (existing bike lanes)",
                 lanes2025="mpv-v-mps.-son.kmz — Velosiped yolları 2025 yanvar (bike lanes, January 2025)",
                 mpv="mpv-v-mps.-son.kmz — velosiped məntəqələri yeni (bike stations, MPV)",
                 mps="mpv-v-mps.-son.kmz — Ümumi 12 iyul (bike parking points, MPS)"),
    lines=lines, routes=routes, stops=stops, stations=stations, lanes=lane_rows,
    lanes2025=[dict(name=n, m=round(l.length), path=ll_line(l, 1.0)) for n, l in lanes_2025],
    heat=heat, corridors=corridors, proposal=proposal, stats=stats,
)
blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
template = (ROOT / "src" / "app.html").read_text(encoding="utf8")
check("/*__DATA__*/null" in template, "src/app.html has the data slot")
html = template.replace("/*__DATA__*/null", blob.replace("</", "<\\/"))
(ROOT / "index.html").write_text(html, encoding="utf8")

print(f"index.html {len(html.encode('utf8')) / 1e6:.2f} MB")
print(f"  bus: {len(lines)} lines ({len(mapped)} with geometry; none for {', '.join(no_geometry)}) · {len(routes)} routes · "
      f"{len(stops)} stops ({len(served)} served) · register/geometry {register_ratio:.2f} · run times imply {implied_kmh:.1f} km/h")
print(f"  bike: lanes {lanes_km:.2f} km in {len(lanes_now)} pieces, {len(sections)} sections (largest {max(sections.values()) / 1000:.2f} km)"
      f"{' · dropped ' + ', '.join(lane_dropped) if lane_dropped else ''} · January 2025 {lanes_2025_km:.2f} km · MPV {len(mpv)} "
      f"({mpv_on} on a lane) · MPS {len(mps)}")
print(f"  together: stops with a bike point within {WALK:.0f} m {stats['stopsBike']}/{len(served)} · central "
      f"{stats['centralStopsBike']}/{len(central_served)} · busy stops without one {len(gaps)}")
for c in corridors:
    print(f"  corridor {c['name']!r} near {c['near']!r}: {c['peak']} lines at peak, {len(c['lines'])} lines, {c['m']} m, "
          f"{len(c['stops'])} stops")
print(f"  Azadlıq lane: {proposal['m']} m via line {proposal['via']}, {proposal['link']} m from the Vaqif lane, "
      f"{proposal['azadliqStops']} Azadlıq stops, ends at {north_end[1]:.4f} · off-lane cluster {len(cluster)} · "
      f"stations onto the network {len(newly_on)} · within 300 m {len(near_300)} · stops newly near a lane {len(stops_new)} "
      f"({len(proposal['linesNew'])} lines)")
