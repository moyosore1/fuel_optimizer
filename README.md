Here’s a simple, human-style `README.md` you can use 👇

---

# Fuel Route Optimizer API

This project provides an API that:

* Takes a start and end location (latitude, longitude)
* Returns the optimal fuel stops along the route (based on cheapest fuel prices per state)
* Calculates total fuel cost
* Caches routes to improve performance on repeat requests

---

## 🧰 Requirements

* Docker
* Docker Compose


---

## 🚀 Setup Instructions

### 1. Clone the project

```bash
git clone https://github.com/moyosore1/fuel_optimizer.git
cd fuel_optimizer
```

---

### 2. Create your `.env` file

There is a `.env.example` file in the root directory.

Copy it:

```bash
cp .env.example .env
```

Fill in the required values.

---

### 3. Start the services

```bash
docker compose up --build
```

This will spin up:

* PostGIS database
* Django app

---

### 4. Run database migrations

Open another terminal and run:

```bash
docker compose exec app python manage.py migrate
```

---

### 5. Load fuel prices

The CSV file is in the project root.

```bash
docker compose exec app python manage.py load_fuel_prices fuel_prices.csv
```

---

### 6. Load US state boundaries

The `us.json` file is in the project root.

```bash
docker compose exec app python manage.py load_us_states us.json
```

---

## 📡 Using the API

Endpoint:

```
POST http://127.0.0.1:8000/api/v1/route/optimize
```

### Example Request Body

```json
{
  "start": "39.7392, -104.9903",
  "end": "38.9072, -77.0369"
}
```

This example represents:

* Start: Denver, CO
* End: Washington, DC

---

## ⚡ Performance Notes

* The API makes at most **2 external calls**:

  * Snap to road network
  * Route directions
* All fuel optimization is done locally using PostGIS.
* Routes are cached for 7 days.
* Subsequent identical requests return in under ~300ms.

---

## 🧠 Assumptions

* Max vehicle range: **500 miles**
* MPG: **10**
* Starting fuel: **50 gallons**
* Cheapest station per state is used for optimization

---

Run it, hit the endpoint, and you’re good to go. 🚀
