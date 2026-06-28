# ssl-aggregator

Two C++ data-capture services for a slip-detection dataset:

- **`robot_logger`** — receives the robot's telemetry packets (UDP multicast),
  decodes the ASCII format, and logs them to Postgres schema `robot`.
- **`vision_logger`** — receives SSL-Vision detection frames (UDP multicast),
  extracts robot/ball detections, and logs them to Postgres schema `vision`.

Both write to one database (`robot_data`) with a receive timestamp on every row.
Velocity/slip analysis is done later from the captured raw data.

## Time synchronisation (robot ⇄ camera)

The robot has no RTC. Packets are emitted every 10 ms with a monotonic
`packet_id` (gaps = lost packets), and an orange LED on top toggles at 1 Hz.
SSL-Vision sees the lit LED as a *ball*, so:

- robot side: `robot.telemetry.led_state` flips at a known `packet_id`
- camera side: `vision.ball_detection` appears/disappears at a known `t_capture`

Matching the edges of these two square waves aligns the robot's `packet_id × 10 ms`
timeline to the camera's `t_capture` clock (and the repeated toggles let you track
clock drift). Align on `t_capture`, **not** `rx_wall`.

## Layout

```
sql/            00_init.sql (db/roles), 01_robot.sql, 02_vision.sql
third_party/    vendored ssl-vision .proto files
libcommon/      shared: udp receiver, timestamps, config (.env loader), batched db writer
robot_logger/   ASCII resync parser + main
vision_logger/  protobuf parse + main
scripts/        db_init.sh (provision), export.sh (CSV), db_dump.sh / db_restore.sh
grafana/        capture_health.json (importable dashboard)
.env.example    copy to .env for local config (DB password, robot NIC)
.vscode/        build task + gdb debug configs
```

## Build

Requires a C++23 compiler (GCC 14+ / Clang 17+) for `std::print` / `std::format`
/ `std::jthread`. The project builds as `gnu++23`.

```bash
sudo apt install libpqxx-dev      # only missing dependency (pulls libpq-dev)
cmake -S . -B build
cmake --build build -j
```
Binaries: `build/robot_logger/robot_logger`, `build/vision_logger/vision_logger`.
The build also emits `build/compile_commands.json` for IntelliSense/clangd.

## Install PostgreSQL (Ubuntu/Debian)

```bash
sudo apt install postgresql
sudo systemctl enable --now postgresql      # start now + on boot
```

Verify it's up and listening on localhost:

```bash
systemctl is-active postgresql              # -> active
sudo -u postgres psql -c "SELECT version();"
```

That's all the server config you need: the `postgres` superuser is reached
locally via `sudo -u postgres` (peer auth), and the project's `robot_writer` /
`grafana_ro` roles connect over TCP on `127.0.0.1:5432` with a password — which
Ubuntu's default `pg_hba.conf` already allows (`scram-sha-256` for localhost).
The roles and their passwords are created in the next step.

> Other platforms: on macOS use Postgres.app or `brew install postgresql@18`;
> on Windows use the EDB installer. The rest of the steps are identical once
> `psql` works.

## Database setup (once)

Set `PGPASSWORD` and `GRAFANA_PASSWORD` in `.env` (they become the
`robot_writer` / `grafana_ro` role passwords), then:

```bash
cp .env.example .env     # if you haven't already, then edit the passwords
./scripts/db_init.sh     # creates db + schemas + roles, runs all three SQL files
```

`db_init.sh` reads the passwords from `.env` and passes them to psql via the
environment (`sql/00_init.sql` uses `\getenv`), so **no credentials are stored
in the SQL files** — secrets live only in the gitignored `.env`.

## Run

Configuration is read from a `.env` file in the working directory, loaded at
startup (real environment variables take precedence). Copy the template and fill
in your machine's values:

```bash
cp .env.example .env
# edit .env: PGPASSWORD, and ROBOT_MCAST_IFACE if the host is multi-homed
./build/robot_logger/robot_logger
./build/vision_logger/vision_logger
```

On startup each logger prints `config: loaded .env`, then a once-per-second
health line to stderr (packet counts, lost-packet count for the robot,
frame/detection counts for vision).

### Configuration keys (set in `.env` or the environment)

| Variable | Default | Used by |
|----------|---------|---------|
| `DB_CONNINFO` | `host=localhost port=5432 dbname=robot_data user=robot_writer` | both |
| `PGPASSWORD` | — | both (libpq) |
| `DB_BATCH_SIZE` | 50 (robot) / 100 (vision) | both |
| `DB_MAX_LATENCY_MS` | 200 | both |
| `ROBOT_MCAST_GROUP` / `ROBOT_MCAST_PORT` | `239.0.0.1` / `10001` | robot |
| `VISION_MCAST_GROUP` / `VISION_MCAST_PORT` | `224.5.23.2` / `10006` | vision |
| `*_MCAST_IFACE` | `0.0.0.0` | both |

## Optional: data inspection (DBeaver & Grafana)

Neither is required to capture data — they just make it easier to look at.

### DBeaver (SQL browser)

```bash
sudo snap install dbeaver-ce      # or download the .deb from dbeaver.io
```
New connection → **PostgreSQL**, then: Host `localhost`, Port `5432`, Database
`robot_data`, Username `robot_writer`, Password = your `PGPASSWORD`. Connect, and
browse the `robot` and `vision` schemas under *Databases → robot_data → Schemas*.

### Grafana (live dashboards)

```bash
# install (Grafana OSS apt repo)
sudo apt install -y apt-transport-https software-properties-common wget
sudo mkdir -p /etc/apt/keyrings
wget -qO - https://apt.grafana.com/gpg.key | gpg --dearmor | sudo tee /etc/apt/keyrings/grafana.gpg >/dev/null
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list
sudo apt update && sudo apt install grafana

# run it
sudo systemctl enable --now grafana-server
```

Then:

1. Open <http://localhost:3000> (default login `admin` / `admin`; it forces a
   password change on first login).
2. **Connections → Data sources → Add data source → PostgreSQL**:
   Host URL `localhost:5432`, Database `robot_data`, User `grafana_ro`,
   Password = your `GRAFANA_PASSWORD`, TLS/SSL Mode `disable`. **Save & test**.
3. **Dashboards → New → Import**, upload `grafana/capture_health.json`, and pick
   the PostgreSQL data source when prompted.

The dashboard shows packet/detection rates, lost-packet count, and the
robot-LED-vs-camera-ball **sync check** — handy to glance at while capturing.
Use the read-only `grafana_ro` role here; Grafana never needs to write.

## Exporting the dataset

Two helpers in `scripts/` (both default to the `.env` credentials):

- **CSV** (for pandas analysis — no Postgres needed on the far end):
  ```bash
  ./scripts/export.sh            # -> export_<timestamp>.tar.gz (3 CSVs + manifest)
  ```
- **Full database** (to restore into Postgres elsewhere, keep SQL/Grafana):
  ```bash
  ./scripts/db_dump.sh                       # -> robot_data_<timestamp>.dump
  # on the other machine:
  ./scripts/db_restore.sh robot_data_*.dump  # creates the DB and restores
  ```
  The dump uses `--no-owner --no-privileges`, so it restores without recreating
  the `robot_writer`/`grafana_ro` roles. To also run the loggers/Grafana on the
  new machine, apply `sql/00_init.sql` there first.

## Notes / gotchas

- **Multi-homed host (multicast interface):** on a machine with more than one
  NIC, an `INADDR_ANY` multicast join binds to the *default-route* interface,
  which may not be the robot's network. Set `ROBOT_MCAST_IFACE` (in `.env`) to
  the IP of the NIC on the robot's subnet. SSL-Vision is unaffected when it runs
  locally on the same machine.
- **Clean exit / libpqxx:** the loggers call `std::quick_exit()` after flushing
  and joining their DB worker(s). libpqxx 7.10 double-frees a static `std::string`
  in its shared-library destructors at process exit; since all rows are already
  committed, we skip C++ global destructors to avoid that abort. Not our bug.
- **Packet loss is expected over Wi-Fi:** UDP from the ESP8266 can drop ~1% of
  packets. That is why the firmware emits `packet_id` — gaps are detectable
  (logged as `lost=` in the stats line) and the missing samples are simply absent
  from the dataset, not silently misaligned.

## Robot wire format

ASCII over UDP multicast `239.0.0.1:10001`, emitted every 10 ms:

```
>Speed:<packet_id>,<f0>,<f1>,<f2>,<f3>,<f4>,<f5>,<f6>,<led>
```

| field | column | meaning |
|-------|--------|---------|
| packet_id | `packet_id` | uint32 sequence |
| f0,f1 | `wheel0_speed`,`wheel1_speed` | encoder speed (mm/s) |
| f2,f3 | `wheel0_setpoint`,`wheel1_setpoint` | commanded (mm/s) |
| f4,f5,f6 | `imu_accel_x`,`imu_accel_y`,`imu_gyro_z` | IMU |
| led | `led_state` | sync LED (0/1) |
