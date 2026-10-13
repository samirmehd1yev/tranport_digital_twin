# Baku Mobility Twin — buses and bicycles

A digital twin of Baku's bus network and bike lanes in **one self-contained page**, `index.html`. Open it in a
browser. It needs the internet for the base map and two libraries, and nothing else: no server, no build step to
view it.

It shows what a transport digital twin is for. It mirrors the network as it runs, measures the moment, explains
where the network is strained, and tests a decision before the city pays for it.

## What it does

| Mode | What you see | The value |
| --- | --- | --- |
| **Mirror** | Every mapped line's buses moving on their real route geometry through a whole day: stops and hubs, bike lanes now and in January 2025, bike stations, parking points and bike flow, with 3D buildings lit by the real sun for Baku. | One shared picture of the network, the same for every department. |
| **Monitor** | Live figures for the moment on the clock: buses on the road, lines running, average speed, scheduled headway, the busiest stop, and alerts for stops over capacity and corridors where buses bunch. | Problems surface before they become complaints. |
| **Understand** | Bus corridors where up to 39 lines share one street (3D columns), the first and last mile (busy stops with no bike point within 300 m), and the bike network's gaps. | Where to act, ranked by data, not opinion. |
| **Simulate and decide** | Five what-ifs, each with before and after and the assumption it rests on: a bus lane on a corridor, a headway change (waiting time against fleet), a street closure with detours, the Azadlıq prospekti bike lane, and new bike stations at busy stops. | The cost and benefit of a decision, tested in minutes. |
| **Present** | A 48-second story with a scripted camera and captions, Play the day (00:00 to 23:59), full screen and a phone layout. | The case, ready for a boardroom screen. |

Hover or tap a line or stop for details: the route lights up, with lines served, headways, the next simulated
buses and the nearest bike point. **Ask the twin** (the bar at the bottom, or `/`) understands plain phrases such
as "rush hour", "where are the gaps", "line 88", "close a street", "Azadlıq" or a stop's name. It runs in the page,
with no AI service behind it.

Keys: `Space` pause · `D` play the day · `P` present · `F` full screen · `1`–`5` modes · `←` `→` move the clock ·
`Esc` exit.

## Measured and simulated

The data describes the network. It holds no timetable, no ridership and no live vehicle positions, so the twin
says clearly which figures it measured and which it simulated.

| From the data | Simulated, from stated assumptions |
| --- | --- |
| 208 lines (199 with route geometry), 398 routes, 3,456 stops, run time and service type per line | The timetable: departures from each line's run time and assumed headways |
| 57.1 km of bike lanes, 44.2 km in the January 2025 layer | Traffic: slower at the peaks, faster at night |
| 185 bike stations (MPV) and 649 bike parking points (MPS) | Bike flow on the lanes (illustrative only, with no counts) |
| Corridors, coverage, connectivity and the lane option, all measured from the geometry | Bus-lane savings, waiting times, fleet and detours |

There is no ridership in the data, so the twin shows no passenger numbers.

**Assumptions**, also listed in the page under *Assumptions*:

- **Peak hours** are 07:00–09:30 and 17:00–19:30.
- **Headways by service type, peak / off-peak:**
  - city 10/15 min
  - city express 12/18 min
  - suburban 15/25 min
  - suburban express 20/30 min
  - settlement 20/30 min
  - inter-settlement 25/40 min
  - intercity 40/60 min
- **Service hours** run from about 06:00 to 23:30, by type.
- **Traffic** brings speeds down to 82% of the data's at 08:15 and 78% at 18:15.
- **Layover** takes 10% of a round trip.
- **Waiting time** is half the headway, assuming passengers arrive at random.
- **Stop capacity** is 90 buses an hour.
- **Bunching** is flagged below 30 s between buses in one direction.
- **A bus lane** gains +20% bus speed. This one can be adjusted in the page.
- **Walking reach** is 300 m from a stop to a bike point. A station within 50 m of a lane counts as on it.

**Detours** follow streets that other bus lines already use, at each line's speed. The data has no one-way rules.
A line turns short when its terminus is inside the closure, or when the only way round is more than three times
longer than the closed stretch.

**A note on the data.** The register's run times work out to about 18 km/h on every line, so they are a planning
figure rather than a measurement. Its line lengths are round trips: the median ratio to the mapped geometry is
0.99.

## Data

The data comes from the archive attached to [issue #1](https://github.com/zirconvalley/tranport_digital_twin/issues/1)
and is kept in `data/`:

| File | Contents |
| --- | --- |
| `ayna.sqlite` | The bus network: `buses` (lines, carrier, run time, fare, service type), `routes` and `route_coordinates` (geometry per direction), `stop_details` and `bus_stops` (stops and each line's stops) |
| `movcud-zolaqlar-velo.kmz` | *Mövcud zolaqlar*: the existing bike lanes |
| `mpv-v-mps.-son.kmz` | *Velosiped yolları 2025 yanvar* (bike lanes, January 2025), *velosiped məntəqələri yeni* (bike stations, MPV) and the MPS bike parking points |

## Rebuild

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python build.py            # writes index.html
```

`build.py` reads `data/` and works in metres (UTM zone 39N). It writes everything into the data slot of
`src/app.html`, the page template.

It first runs data checks and stops if any fails:

- every placemark parses;
- every coordinate lies in Absheron;
- every line has a length and a run time;
- route lengths match the geometry.

Then it derives what the page needs:

- the corridors;
- the stops without a bike point in reach;
- how the lanes connect;
- the **Azadlıq prospekti lane option**. It starts at the north end of the Vaqif pr. lane and follows the bus route
  that runs up the avenue to Azadlıq metro: 4.5 km, putting 7 more bike stations on a lane and 36 more bus stops
  within 300 m of one.

The page computes everything else live, from the data and the stated assumptions. It uses:

- MapLibre GL 4.7.1;
- deck.gl 9.0.38;
- the OpenFreeMap *positron* base map, recoloured for night.

The simulated timetable runs on the GPU. Each route is one path, and a shader works out, for every point on it,
when the last scheduled bus passed. Only the clock changes per frame.

## Checked

The page was checked in Chromium with Playwright:

- **Screens:** desktop 1440×900 and 1200×800, and a phone (iPhone 14 profile).
- **Every mode and scenario,** plus the story, Play the day, full screen, Ask the twin and selection.
- **Console:** no errors or warnings.
- **Flicker:** still frames under forced repaint are pixel-identical, by day, at dusk, at night and in the 3D
  corridor view.
- **Speed:** the phone profile holds 120 fps with the CPU throttled four times.
