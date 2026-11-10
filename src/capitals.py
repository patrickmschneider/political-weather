"""
State capitals (contiguous US) + Washington, D.C., with coordinates and an
approximate city population used only to prioritise which labels show when
space is tight. Coordinates are WGS84/NAD83 lon/lat (city hall vicinity).
Alaska (Juneau) and Hawaii (Honolulu) are omitted from the CONUS surface.
"""
# (name, state, lat, lon, approx_city_pop_thousands)
CAPITALS = [
    ("Montgomery", "AL", 32.377, -86.300, 195),
    ("Phoenix", "AZ", 33.448, -112.074, 1644),
    ("Little Rock", "AR", 34.746, -92.289, 202),
    ("Sacramento", "CA", 38.576, -121.493, 525),
    ("Denver", "CO", 39.739, -104.990, 716),
    ("Hartford", "CT", 41.764, -72.682, 121),
    ("Dover", "DE", 39.158, -75.524, 39),
    ("Tallahassee", "FL", 30.438, -84.281, 196),
    ("Atlanta", "GA", 33.749, -84.388, 499),
    ("Boise", "ID", 43.617, -116.200, 237),
    ("Springfield", "IL", 39.798, -89.654, 114),
    ("Indianapolis", "IN", 39.768, -86.158, 887),
    ("Des Moines", "IA", 41.591, -93.604, 214),
    ("Topeka", "KS", 39.048, -95.678, 126),
    ("Frankfort", "KY", 38.197, -84.863, 28),
    ("Baton Rouge", "LA", 30.458, -91.140, 220),
    ("Augusta", "ME", 44.307, -69.782, 19),
    ("Annapolis", "MD", 38.979, -76.492, 40),
    ("Boston", "MA", 42.358, -71.064, 654),
    ("Lansing", "MI", 42.733, -84.555, 112),
    ("Saint Paul", "MN", 44.954, -93.090, 311),
    ("Jackson", "MS", 32.299, -90.185, 150),
    ("Jefferson City", "MO", 38.579, -92.173, 43),
    ("Helena", "MT", 46.589, -112.039, 34),
    ("Lincoln", "NE", 40.808, -96.700, 295),
    ("Carson City", "NV", 39.164, -119.766, 59),
    ("Concord", "NH", 43.207, -71.538, 44),
    ("Trenton", "NJ", 40.220, -74.770, 90),
    ("Santa Fe", "NM", 35.687, -105.938, 89),
    ("Albany", "NY", 42.652, -73.757, 99),
    ("Raleigh", "NC", 35.780, -78.639, 470),
    ("Bismarck", "ND", 46.808, -100.784, 74),
    ("Columbus", "OH", 39.961, -82.999, 906),
    ("Oklahoma City", "OK", 35.468, -97.516, 695),
    ("Salem", "OR", 44.943, -123.035, 177),
    ("Harrisburg", "PA", 40.264, -76.883, 50),
    ("Providence", "RI", 41.824, -71.413, 190),
    ("Columbia", "SC", 34.000, -81.035, 137),
    ("Pierre", "SD", 44.368, -100.351, 14),
    ("Nashville", "TN", 36.163, -86.781, 692),
    ("Austin", "TX", 30.267, -97.743, 975),
    ("Salt Lake City", "UT", 40.761, -111.891, 200),
    ("Montpelier", "VT", 44.260, -72.576, 8),
    ("Richmond", "VA", 37.541, -77.436, 226),
    ("Olympia", "WA", 47.038, -122.901, 55),
    ("Charleston", "WV", 38.336, -81.612, 48),
    ("Madison", "WI", 43.074, -89.384, 269),
    ("Cheyenne", "WY", 41.140, -104.820, 65),
    ("Washington", "DC", 38.895, -77.037, 702),
]

# Major cities that are NOT state capitals (contiguous US), by city population
# (thousands). Deduped against CAPITALS by construction. (name, state, lat, lon, pop)
TOWNS_SRC = "geonames/cities15000.txt"   # under data/raw; see fetch_data.sh

# GeoNames lists the NYC boroughs as separate cities; they sit on top of "New York".
# Plus known GeoNames errors (below).
_SKIP = {("Brooklyn", "NY"), ("Queens", "NY"), ("Manhattan", "NY"),
         ("The Bronx", "NY"), ("Staten Island", "NY"),
         # GeoNames data errors: a duplicate of Lexington, and a tiny place
         # listed with Lexington's population.
         ("Lexington-Fayette", "KY"), ("Meads", "KY")}
_CONUS_EXCLUDE = {"AK", "HI", "PR", "VI", "GU", "AS", "MP"}


def load_towns(path, curated, min_km=10.0, dup_km=5.0):
    """Extra places (pop >= 15k) for labels revealed on zoom, from a GeoNames
    dump. Drops neighbourhood entries, non-CONUS places, NYC boroughs and any
    town within min_km of a curated capital/major city (same place, other name).
    Returns rows shaped like CAPITALS: (name, state, lat, lon, pop_thousands)."""
    import math
    keep_codes = {"PPL", "PPLA", "PPLA2", "PPLA3", "PPLC"}
    cur = [(math.radians(lat), math.radians(lon)) for _, _, lat, lon, _ in curated]
    def near(lat, lon):
        la, lo = math.radians(lat), math.radians(lon)
        for cl, co in cur:
            d = 6371 * math.acos(min(1, math.sin(la)*math.sin(cl) + math.cos(la)*math.cos(cl)*math.cos(lo-co)))
            if d < min_km:
                return True
        return False
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = line.rstrip("\n").split("\t")
            if len(r) < 15 or r[8] != "US" or r[7] not in keep_codes:
                continue
            name, st = r[1], r[10]
            if st in _CONUS_EXCLUDE or (name, st) in _SKIP:
                continue
            lat, lon, pop = float(r[4]), float(r[5]), int(r[14] or 0)
            if pop < 15000 or near(lat, lon):
                continue
            out.append((name, st, lat, lon, round(pop / 1000)))
    # Collapse duplicates GeoNames lists twice under two names
    # (e.g. "Lexington" / "Lexington-Fayette"): keep the larger one.
    out.sort(key=lambda t: -t[4])
    kept = []
    for t in out:
        cosl = math.cos(math.radians(t[2]))
        if any(((t[2]-k[2])*111) ** 2 + ((t[3]-k[3])*111*cosl) ** 2 < dup_km ** 2 for k in kept):
            continue
        kept.append(t)
    return kept


MAJORS = [
    ("New York", "NY", 40.713, -74.006, 8336),
    ("Los Angeles", "CA", 34.052, -118.244, 3980),
    ("Chicago", "IL", 41.878, -87.630, 2746),
    ("Houston", "TX", 29.760, -95.370, 2304),
    ("San Antonio", "TX", 29.424, -98.494, 1434),
    ("San Diego", "CA", 32.716, -117.161, 1386),
    ("Dallas", "TX", 32.777, -96.797, 1304),
    ("San Jose", "CA", 37.339, -121.895, 1013),
    ("Jacksonville", "FL", 30.332, -81.656, 950),
    ("Fort Worth", "TX", 32.756, -97.331, 918),
    ("Charlotte", "NC", 35.227, -80.843, 875),
    ("Seattle", "WA", 47.606, -122.332, 737),
    ("El Paso", "TX", 31.759, -106.487, 679),
    ("Portland", "OR", 45.515, -122.679, 652),
    ("Las Vegas", "NV", 36.170, -115.139, 644),
    ("Memphis", "TN", 35.150, -90.049, 633),
    ("Louisville", "KY", 38.253, -85.758, 633),
    ("Baltimore", "MD", 39.290, -76.612, 585),
    ("Milwaukee", "WI", 43.039, -87.906, 577),
    ("Albuquerque", "NM", 35.084, -106.651, 562),
    ("Tucson", "AZ", 32.222, -110.975, 542),
    ("Fresno", "CA", 36.738, -119.787, 542),
    ("Kansas City", "MO", 39.099, -94.578, 508),
    ("Mesa", "AZ", 33.416, -111.832, 504),
    ("Omaha", "NE", 41.257, -95.934, 486),
    ("Colorado Springs", "CO", 38.834, -104.821, 478),
    ("Long Beach", "CA", 33.770, -118.194, 466),
    ("Virginia Beach", "VA", 36.853, -75.978, 459),
    ("Miami", "FL", 25.762, -80.192, 442),
    ("Oakland", "CA", 37.804, -122.271, 440),
    ("Minneapolis", "MN", 44.978, -93.265, 430),
    ("Tulsa", "OK", 36.154, -95.993, 413),
    ("Tampa", "FL", 27.951, -82.457, 399),
    ("Arlington", "TX", 32.736, -97.108, 394),
    ("New Orleans", "LA", 29.951, -90.072, 384),
    ("Cleveland", "OH", 41.499, -81.694, 372),
    ("Newark", "NJ", 40.735, -74.172, 311),
    ("Cincinnati", "OH", 39.103, -84.512, 309),
    ("St. Louis", "MO", 38.627, -90.199, 301),
    ("Pittsburgh", "PA", 40.441, -79.996, 302),
    ("Buffalo", "NY", 42.886, -78.878, 278),
]
