"""Generate a realistic synthetic fleet telematics dataset into SQLite.

The data mimics a UAE fleet-management platform serving several customers:
customers -> vehicles -> drivers -> trips, plus maintenance and fuel logs.
Behavioural patterns are deliberately planted (inefficient vehicles, risky
drivers, overdue services) so the copilot has real insights to find.

Usage:
    python scripts/generate_data.py --out data/fleet.db --seed 42
    (or: python -m fleet_copilot.synthetic)
"""
from __future__ import annotations

import argparse
import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

START = date(2026, 7, 1)
END = date(2026, 9, 30)  # inclusive; "this month" in the app = September 2026

CUSTOMERS = [
    ("Al Noor Logistics", "Logistics", "Dubai", 120),
    ("Desert Line Transport", "Passenger Transport", "Abu Dhabi", 90),
    ("Gulf Fresh Foods", "Food Distribution", "Dubai", 60),
    ("Emirates Build Co", "Construction", "Sharjah", 75),
    ("Coastal Couriers", "Courier", "Dubai", 50),
    ("Oasis School Transport", "School Transport", "Dubai", 80),
    ("Palm Facility Services", "Facility Management", "Dubai", 40),
    ("Northern Cold Chain", "Food Distribution", "Ras Al Khaimah", 35),
]

VEHICLE_TYPES = {
    # type: (makes/models, base km per litre, fuel)
    "Light Van": ([("Toyota", "Hiace"), ("Nissan", "Urvan"), ("Ford", "Transit")], 9.5, "Petrol"),
    "Pickup": ([("Toyota", "Hilux"), ("Mitsubishi", "L200"), ("Nissan", "Navara")], 10.5, "Diesel"),
    "Bus": ([("Ashok Leyland", "Falcon"), ("Tata", "LP 909"), ("King Long", "XMQ6900")], 3.8, "Diesel"),
    "Truck": ([("Isuzu", "NPR"), ("Mitsubishi", "Fuso Canter"), ("Hino", "300")], 5.5, "Diesel"),
    "Sedan": ([("Toyota", "Corolla"), ("Hyundai", "Elantra"), ("Nissan", "Sunny")], 14.0, "Petrol"),
}

TYPE_MIX = {
    "Logistics": ["Truck", "Light Van", "Pickup"],
    "Passenger Transport": ["Bus", "Light Van"],
    "Food Distribution": ["Truck", "Light Van"],
    "Construction": ["Pickup", "Truck"],
    "Courier": ["Light Van", "Sedan"],
    "School Transport": ["Bus"],
    "Facility Management": ["Pickup", "Sedan", "Light Van"],
}

FIRST = ["Ahmed", "Mohammed", "Ravi", "Suresh", "Imran", "Ali", "Joseph", "Faisal", "Anil",
         "Omar", "Rajesh", "Bilal", "Khalid", "Arun", "Yousef", "Sanjay", "Hassan", "Tariq"]
LAST = ["Khan", "Nair", "Al Mansoori", "Pillai", "Hussain", "Sharma", "Rahman", "Thomas",
        "Al Hashimi", "Kumar", "Siddiqui", "Varghese", "Qureshi", "Menon"]

SCHEMA = """
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    industry TEXT NOT NULL,
    city TEXT NOT NULL,
    contract_start DATE NOT NULL
);
CREATE TABLE vehicles (
    vehicle_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    plate_number TEXT NOT NULL UNIQUE,
    make TEXT NOT NULL,
    model TEXT NOT NULL,
    year INTEGER NOT NULL,
    vehicle_type TEXT NOT NULL,
    fuel_type TEXT NOT NULL,
    status TEXT NOT NULL            -- active | in_workshop | inactive
);
CREATE TABLE drivers (
    driver_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    full_name TEXT NOT NULL,
    license_years INTEGER NOT NULL,
    hire_date DATE NOT NULL
);
CREATE TABLE trips (
    trip_id INTEGER PRIMARY KEY,
    vehicle_id INTEGER NOT NULL REFERENCES vehicles(vehicle_id),
    driver_id INTEGER NOT NULL REFERENCES drivers(driver_id),
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    trip_date DATE NOT NULL,
    distance_km REAL NOT NULL,
    duration_min REAL NOT NULL,
    idle_min REAL NOT NULL,
    max_speed_kmh REAL NOT NULL,
    fuel_used_l REAL NOT NULL,
    harsh_brake_count INTEGER NOT NULL,
    harsh_accel_count INTEGER NOT NULL,
    overspeed_count INTEGER NOT NULL
);
CREATE TABLE maintenance (
    record_id INTEGER PRIMARY KEY,
    vehicle_id INTEGER NOT NULL REFERENCES vehicles(vehicle_id),
    service_date DATE NOT NULL,
    service_type TEXT NOT NULL,      -- scheduled | repair | tyre | breakdown
    cost_aed REAL NOT NULL,
    odometer_km REAL NOT NULL,
    next_service_due_km REAL NOT NULL
);
CREATE TABLE fuel_transactions (
    txn_id INTEGER PRIMARY KEY,
    vehicle_id INTEGER NOT NULL REFERENCES vehicles(vehicle_id),
    txn_time TIMESTAMP NOT NULL,
    litres REAL NOT NULL,
    price_per_litre_aed REAL NOT NULL,
    amount_aed REAL NOT NULL,
    station_city TEXT NOT NULL
);
CREATE INDEX idx_trips_vehicle_date ON trips(vehicle_id, trip_date);
CREATE INDEX idx_trips_driver ON trips(driver_id);
CREATE INDEX idx_maint_vehicle ON maintenance(vehicle_id);
CREATE INDEX idx_fuel_vehicle ON fuel_transactions(vehicle_id);
"""

FUEL_PRICE = {7: 2.69, 8: 2.74, 9: 2.71}  # AED / litre, illustrative


def daterange(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def build(out: Path, seed: int = 42, scale: float = 1.0) -> dict:
    rng = random.Random(seed)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    con = sqlite3.connect(out)
    con.executescript(SCHEMA)

    customers, vehicles, drivers = [], [], []
    trips, maint, fuel = [], [], []
    plates = set()
    vid = did = 0

    for cid, (name, industry, city, size) in enumerate(CUSTOMERS, start=1):
        size = max(5, int(size * scale))
        customers.append((cid, name, industry, city,
                          (date(2021, 1, 1) + timedelta(days=rng.randint(0, 1500))).isoformat()))
        cust_drivers = []
        for _ in range(int(size * 1.1)):
            did += 1
            hire = date(2018, 1, 1) + timedelta(days=rng.randint(0, 2900))
            drivers.append((did, cid, f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                            rng.randint(1, 25), hire.isoformat()))
            # ~8% of drivers are "risky" -> more harsh events/overspeeding
            cust_drivers.append((did, rng.random() < 0.08))

        for _ in range(size):
            vid += 1
            vtype = rng.choice(TYPE_MIX[industry])
            models, base_kmpl, fuel_type = VEHICLE_TYPES[vtype]
            make, model = rng.choice(models)
            year = rng.randint(2015, 2025)
            while True:
                plate = f"{rng.choice('ABCDEFGHJKLMNOPQRSTUVWXYZ')} {rng.randint(10000, 99999)}"
                if plate not in plates:
                    plates.add(plate)
                    break
            r = rng.random()
            status = "active" if r < 0.92 else ("in_workshop" if r < 0.97 else "inactive")
            vehicles.append((vid, cid, plate, make, model, year, vtype, fuel_type, status))

            # Hidden vehicle traits
            age_penalty = max(0.0, (2026 - year) * 0.012)
            inefficient = rng.random() < 0.10          # e.g. engine issue / bad tyres
            kmpl = base_kmpl * (1 - age_penalty) * (0.72 if inefficient else rng.uniform(0.93, 1.07))
            idle_bias = rng.uniform(0.04, 0.12) + (0.40 if rng.random() < 0.07 else 0.0)
            daily_km = {"Bus": 180, "Truck": 160, "Light Van": 140, "Pickup": 110, "Sedan": 130}[vtype]
            daily_km *= rng.uniform(0.7, 1.3)

            odometer = rng.uniform(20000, 60000) * (2026 - year + 1)
            last_service_odo = odometer - rng.uniform(1000, 12000)
            service_interval = 10000 if fuel_type == "Diesel" else 7500
            # some vehicles are overdue: last service long ago
            if rng.random() < 0.12:
                last_service_odo = odometer - service_interval - rng.uniform(500, 6000)
            maint.append((None, vid, (START - timedelta(days=rng.randint(10, 120))).isoformat(),
                          "scheduled", round(rng.uniform(450, 1400), 2), round(last_service_odo, 1),
                          round(last_service_odo + service_interval, 1)))

            primary_driver, risky = rng.choice(cust_drivers)
            fuel_leak = 1.25 if rng.random() < 0.03 else 1.0  # planted: fuel bought >> fuel used
            tank_level = 0.0
            for d in daterange(START, END):
                if status == "inactive":
                    break
                if d.weekday() == 4 and vtype != "Bus" and rng.random() < 0.6:  # Friday off
                    continue
                if vtype == "Bus" and industry == "School Transport" and d < date(2026, 8, 24):
                    if rng.random() < 0.85:  # summer holidays
                        continue
                if rng.random() < 0.06:
                    continue
                n_trips = rng.choice([1, 2, 2, 3, 3, 4])
                km_left = daily_km * rng.uniform(0.6, 1.4)
                t = datetime(d.year, d.month, d.day, rng.randint(5, 9), rng.randint(0, 59))
                for _ in range(n_trips):
                    if rng.random() < 0.85:
                        drv, drv_risky = primary_driver, risky
                    else:
                        drv, drv_risky = rng.choice(cust_drivers)
                    dist = max(2.0, km_left / n_trips * rng.uniform(0.6, 1.4))
                    moving_min = dist / rng.uniform(32, 58) * 60
                    idle = moving_min * idle_bias * rng.uniform(0.6, 1.5)
                    dur = moving_min + idle
                    fuel_l = dist / (kmpl * rng.uniform(0.92, 1.08)) + idle * 0.012
                    ev = 3.0 if drv_risky else 1.0
                    hb = _poisson(rng, dist / 100 * 1.2 * ev)
                    ha = _poisson(rng, dist / 100 * 0.9 * ev)
                    osp = _poisson(rng, dist / 100 * 0.7 * ev * (1.6 if drv_risky else 1))
                    vmax = rng.uniform(75, 118) + (rng.uniform(10, 35) if osp else 0)
                    end = t + timedelta(minutes=dur)
                    trips.append((None, vid, drv, t.isoformat(sep=" ", timespec="minutes"),
                                  end.isoformat(sep=" ", timespec="minutes"), d.isoformat(),
                                  round(dist, 2), round(dur, 1), round(idle, 1), round(vmax, 1),
                                  round(fuel_l, 2), hb, ha, osp))
                    odometer += dist
                    tank_level += fuel_l
                    t = end + timedelta(minutes=rng.randint(15, 120))
                if tank_level > 45 or (vtype == "Bus" and tank_level > 90):
                    litres = tank_level * rng.uniform(0.95, 1.05) * fuel_leak
                    price = FUEL_PRICE[d.month]
                    fuel.append((None, vid, t.isoformat(sep=" ", timespec="minutes"), round(litres, 2),
                                 price, round(litres * price, 2), rng.choice([city, city, "Dubai"])))
                    tank_level = 0.0
                if odometer - last_service_odo > service_interval and rng.random() < 0.15:
                    maint.append((None, vid, d.isoformat(), "scheduled",
                                  round(rng.uniform(450, 1400), 2), round(odometer, 1),
                                  round(odometer + service_interval, 1)))
                    last_service_odo = odometer
                elif rng.random() < 0.004 * (1 + (2026 - year) / 5):
                    stype = rng.choice(["repair", "tyre", "breakdown"])
                    cost = {"repair": (800, 6000), "tyre": (600, 2400), "breakdown": (1500, 9000)}[stype]
                    maint.append((None, vid, d.isoformat(), stype, round(rng.uniform(*cost), 2),
                                  round(odometer, 1), round(last_service_odo + service_interval, 1)))

    con.executemany("INSERT INTO customers VALUES (?,?,?,?,?)", customers)
    con.executemany("INSERT INTO vehicles VALUES (?,?,?,?,?,?,?,?,?)", vehicles)
    con.executemany("INSERT INTO drivers VALUES (?,?,?,?,?)", drivers)
    con.executemany("INSERT INTO trips VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", trips)
    con.executemany("INSERT INTO maintenance VALUES (?,?,?,?,?,?,?)", maint)
    con.executemany("INSERT INTO fuel_transactions VALUES (?,?,?,?,?,?,?)", fuel)
    con.commit()
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ["customers", "vehicles", "drivers", "trips", "maintenance", "fuel_transactions"]}
    con.close()
    return counts


def _poisson(rng: random.Random, lam: float) -> int:
    # Knuth's algorithm; lam is small here
    import math
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/fleet.db")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--scale", type=float, default=1.0, help="Multiply fleet sizes")
    a = ap.parse_args()
    print(build(Path(a.out), a.seed, a.scale))


def ensure_database(path: Path, seed: int = 42) -> Path:
    """Create the demo database on first run (used by the app, API and Docker image)."""
    path = Path(path)
    if not path.exists():
        build(path, seed=seed)
    return path
