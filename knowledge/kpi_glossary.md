# Fleet KPI Glossary

Each section below is one retrievable chunk. The copilot retrieves the most
relevant definitions for a question and gives them to the LLM, so business
terms are always calculated the same way.

## Fuel efficiency (km per litre)
Fuel efficiency = SUM(trips.distance_km) / SUM(trips.fuel_used_l), measured in km/L.
Always aggregate distance and fuel first, then divide (never average per-trip ratios).
Compare vehicles only against the same vehicle_type, because buses and sedans differ hugely.

## Underperforming vehicle
A vehicle is underperforming in a period when its fuel efficiency is more than 20% below
the average fuel efficiency of its vehicle_type in the same period
(vehicle_kmpl < 0.8 * type_avg_kmpl), OR its idle ratio is above 30%.
Only consider vehicles with at least 300 km driven in the period.

## Idle ratio and idle time
Idle ratio = SUM(trips.idle_min) / SUM(trips.duration_min).
Idle time in hours = SUM(trips.idle_min) / 60.
Idle cost (AED) is estimated as idle hours * 1.5 litres/hour * 2.71 AED/litre.

## Utilization
Vehicle utilization = number of distinct trip_date values with at least one trip
divided by the number of calendar days in the period.
A vehicle with 0 trips in the period is idle/unused.

## Driver risk score
Driver risk score = (SUM(harsh_brake_count) + SUM(harsh_accel_count) + 2 * SUM(overspeed_count))
/ SUM(distance_km) * 100, i.e. weighted events per 100 km.
Score above 4 = high risk, 2 to 4 = medium, below 2 = low.
Only rank drivers with at least 500 km in the period.

## Overspeeding
An overspeed event is counted in trips.overspeed_count. Overspeed rate = SUM(overspeed_count)
per 100 km. trips.max_speed_kmh is the highest speed recorded during a trip.

## Maintenance due and overdue
A vehicle is overdue for service when its current odometer is greater than
next_service_due_km from its most recent maintenance record.
Current odometer is approximated as the latest maintenance odometer_km plus all trip
distance_km after that service_date.
Due soon = within 1,000 km of next_service_due_km.

## Maintenance cost
Maintenance cost = SUM(maintenance.cost_aed). Unplanned maintenance means service_type
IN ('repair', 'breakdown', 'tyre'). Breakdown rate = breakdown records per vehicle.

## Fuel spend and fuel cards
Fuel spend = SUM(fuel_transactions.amount_aed). Fuel bought vs fuel used: compare
SUM(fuel_transactions.litres) with SUM(trips.fuel_used_l) for the same vehicle and period;
a gap above 15% may indicate fuel theft or sensor issues.

## Cost per km
Cost per km (AED) = (fuel spend + maintenance cost) / total distance_km for the same period.

## Time periods
The dataset covers 2026-07-01 to 2026-09-30. "This month" means September 2026,
"last month" means August 2026, "this quarter" means Q3 2026 (July to September).
Use trips.trip_date for date filtering of trips, e.g. trip_date BETWEEN '2026-09-01' AND '2026-09-30'.
In SQLite use strftime('%Y-%m', trip_date) to group by month.

## Fleet, customer and vehicle names
"Fleet" or "customer" refers to the customers table (one customer = one fleet).
Vehicles are identified to users by plate_number, make and model, not by vehicle_id.
Drivers are identified by full_name. Customer names are in customers.name.
