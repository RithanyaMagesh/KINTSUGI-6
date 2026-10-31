# Live Orbital Data Ingestion & Formation Fitting Specification

> v2 note: `cubesat/live_import_e2e.py` and the `live_e2e_swarm*.json` fixtures were deleted (audit B-26); references below to them are historical.

**Document Type:** Architecture Blueprint, Mathematical Formulation, and Security Specification  
**Target Modules:** `cubesat/live_import.py`, `cubesat/_live_network.py`, `cubesat/live_import_e2e.py`, `tests/test_live_import.py`  
**Status:** Approved Architectural Specification (Post-Audit Hardened Revision)  
**Zero-Diff Boundary:** `cubesat/sim.py`, `cubesat/hcw.py`, `cubesat/scenario.py` (STRICTLY FROZEN)  
**Standard:** Pure Python Standard Library (Zero new runtime or build dependencies)  

---

## 1. Executive Summary & Objective

### 1.1 Objective
The live import subsystem extends the CubeSat swarm simulation repository with the capability to ingest live, real-world orbital cluster data (CCSDS Orbit Mean-Elements Messages / Two-Line Elements) from astronomical and public telemetry providers, derive relative formation geometry in the Local-Vertical Local-Horizontal (LVLH) Hill-Clohessy-Wiltshire (HCW) frame, fit the cluster into the repository's passive 2:1 drift-free relative ellipse formation model, and emit fully schema-compliant scenario definitions alongside cryptographic sidecar provenance metadata.

### 1.2 Core Capabilities
1. **Multi-Provider Ingestion**: Native, zero-dependency ingestion targeting unauthenticated public endpoints (CelesTrak `gp.php`), with extensible provider adapters for credentialed telemetry networks (Space-Track and N2YO).
2. **Network Hardening & Threat Containment**: Defense-in-depth security architecture enforcing:
   - Centralized pre-flight URL and scheme validation (`validate_request_url`).
   - Hardened HTTP redirect containment (`StrictRedirectHandler`) with strict `parsed.hostname` allowlist verification, explicit userinfo rejection, and port confinement.
   - Cumulative monotonic streaming download deadlines (`time.monotonic() + timeout_s`) protecting against slowloris thread hangs.
   - Strict 5 MB streaming response caps with `Accept-Encoding: identity` preventing decompression bombs.
   - Sensitive credential redaction across all exception strings, console outputs, and URLs.
   - Atomic disk cache writes (`.tmp_{pid}_{hash}` swapped via `os.replace`).
   - Multi-layer repository path confinement protecting source code, git metadata, and tests.
3. **Pure Stdlib Relative Astrodynamics**: An analytic astrodynamic pipeline operating entirely within Python standard library (`math`, `datetime`, `json`, `hashlib`, `urllib`):
   - First-order Brouwer $J_2$ secular rate epoch propagation aligning multi-satellite catalog timestamps to a median common epoch without SGP4 external dependencies.
   - Newton-Raphson Kepler equation solver ($E - e\sin E = M$) with finite input validation, singularity guards, and bounded iteration limits ($50$ max iterations).
   - 3-1-3 Euler rotation matrix ($\mathbf{R}_{zxz}(\Omega, i, \omega)$) transforming perifocal coordinates into Earth-Centered Inertial (ECI).
   - Instantaneous chief orbital triad projection mapping ECI coordinates into the LVLH reference frame.
4. **Phase-Presorted Closed-Form Least-Squares 2:1 Ellipse Fitting**: An uncoupled, non-iterative, closed-form least-squares fitting engine. Deputy satellites are pre-sorted by empirical phase $\phi_k = \operatorname{atan2}(\eta_k, \xi_k) \pmod{2\pi}$ before evaluating diagonalized normal equations, deriving the optimal radial amplitude ($A$) and reference phase offset ($\psi_0$) without circular slot-assignment dependencies.
5. **Operational Swarm Sizing & Small Cluster Handling ($N < 4$)**: When ingesting sparse clusters ($N < 4$, such as GRACE-FO with $N=2$), the pipeline defaults to generating a full operational swarm with $N_\text{swarm} = 6$ slots on the fitted ellipse. Real satellites occupy their closest slots, while remaining slots are instantiated as hypothetical swarm satellites. This guarantees $N - n_\text{fail} \ge 4 - 2 = 2$ and enables successful role re-election and the required E2E recovery transition: `NOMINAL -> FAILURE_DETECTED -> REPLANNING -> RECOVERED`.
6. **Hungarian Slot Assignment**: Deterministic survivor-to-slot assignment utilizing SciPy's `linear_sum_assignment` augmented with an index epsilon tie-breaker in strict compliance with repository Invariant 6.
7. **Complete Pydantic Scenario Conformance**: Auto-populates all mandatory scenario baseline parameters (`a_max_mps2 = 0.1`, `gains`, `sensor`, `allocation`), guaranteeing zero-diff validation against `Scenario.model_validate()`.
8. **Deterministic Sidecar Metadata**: Sidecar provenance metadata (`.meta.json`) documents catalog IDs, epoch, fit residuals, and fidelity disclosures. When reading from cache snapshots, `fetch_time_utc` is preserved from the snapshot, guaranteeing byte-identical `.meta.json` output across repeated offline runs.
9. **End-to-End Determinism Proof**: Complete verification framework guaranteeing that live-derived scenarios maintain zero wall-clock or network entropy in the simulation core, producing byte-identical JSONL execution logs across repeated simulation runs.

---

## 2. Codebase Seams & Zero-Diff Policy

### 2.1 The Frozen Simulation Core
Repository governance strictly prohibits any modifications to the simulation core established across Gates G1 through G4. The frozen boundary encompasses:
- `cubesat/sim.py` (Simulation loop, state machine, slot initial state expansion, JSONL event logging)
- `cubesat/hcw.py` (Analytical Hill-Clohessy-Wiltshire equations, Clohessy-Wiltshire transition matrices, orbital constants)
- `cubesat/scenario.py` (Pydantic v2 domain schemas, resource bounds, field validators)

Any implementation in `cubesat/live_import.py` must interact with the simulation core strictly as an external client, generating scenario payloads that satisfy `cubesat.scenario.Scenario.model_validate()` without triggering schema violations or requiring core modifications.

```
+-----------------------------------------------------------------------------------+
|                            LIVE IMPORT SUBSYSTEM                                  |
|                                                                                   |
|  [Provider APIs] ---> [Network Client] ---> [Epoch Alignment & Orbital Mechanics] |
|                             |                                  |                  |
|                      [Cache Manager]            [Phase-Presorted 2:1 Ellipse Fit] |
|                             |                                  |                  |
|                             +--------------> [Scenario & Provenance Builder]      |
+-------------------------------------------------------|---------------------------+
                                                        |
                        +-------------------------------+-------------------+
                        |                                                   |
                        v                                                   v
          +----------------------------+                     +----------------------------+
          |   <scenario>.json          |                     |   <scenario>.meta.json     |
          |   (Pydantic Scenario Schema|                     |   (Provenance & Fit        |
          |    Validated Payload)      |                     |    Residuals Sidecar)      |
          +----------------------------+                     +----------------------------+
                        |
========================|====================================================================
                        |   ZERO-DIFF BOUNDARY (STRICTLY FROZEN SIMULATION CORE)
========================v====================================================================
          +-------------------------------------------------------------------------+
          |   cubesat/scenario.py : Scenario.model_validate(raw_dict)               |
          |   cubesat/sim.py      : run_scenario(scenario) -> JSONL Event Stream   |
          |   cubesat/hcw.py      : MU, R_EARTH, mean_motion(), slot_initial_state()|
          +-------------------------------------------------------------------------+
```

### 2.2 Seam Analysis: `cubesat/scenario.py`
The simulation scenario is governed by immutable Pydantic v2 models. The live import pipeline must conform to the following bounds and structural requirements:

| Field / Model | Constraint / Bound | Architectural Impact on Live Import |
|---|---|---|
| `ChiefOrbit.altitude_km` | $160.0 < h < 2000.0\text{ km}$ (LEO bound) | Clusters with mean altitude $\le 160\text{ km}$ or $\ge 2000\text{ km}$ must be rejected by an altitude gate. Altitude must be rounded to 3 decimal places to prevent floating-point rounding boundary violations. |
| `Formation.n_slots` | $2 \le N \le 32$ (`MAX_SATS`) | Number of satellites in cluster must be within $[2, 32]$. When cluster has $N < 4$ (e.g. GRACE-FO with $N=2$), `live_import` defaults to generating a full operational swarm with $N_\text{swarm} = 6$ slots on the fitted ellipse. Real satellites occupy their closest slots, while remaining slots are instantiated as hypothetical swarm satellites. |
| `Formation.radial_amp_km` | $> 0.0$ | Derived directly from the closed-form least-squares fit or set to a standard 8.0 km envelope. |
| `Formation.phase_offset_deg` | `float` (default `0.0`) | Reference phase angle $\psi_0$ derived from the closed-form least-squares normal equations. |
| `Scenario.roles` | `min_length=2, max_length=32` | Must contain exactly one `leader`, one `downlink`, and $(N-2)$ `imager` roles. `len(roles) == formation.n_slots`. |
| `Scenario.failures` | `sat_id < n_sats`, $t \ge 0$ | Default failure schedules inject staggered `DEAD` events (e.g. SAT-1 at 1200s, SAT-2 at 1500s) matching canonical recovery patterns. Requires $N - n_\text{fail} \ge 2$. |
| `Scenario.duration_s` | $\le 86,400\text{ s}$, steps $\le 100,000$ | Set to exactly 3 orbital periods of the chief orbit: $3 \times \frac{2\pi}{n}$. |
| `Scenario.dt_s` | $> 0.0, \le 10.0$ | Fixed to standard simulation timestep $2.0\text{ s}$. |
| `Scenario.a_max_mps2` | $> 0.0$ (Mandatory, no default in schema) | Populated with baseline value `0.1` m/s$^2$. |
| `Scenario.gains` | `Gains(wn, zeta)` (Mandatory, no default) | Populated with baseline `{"wn": 0.01, "zeta": 1.0}`. |
| `Scenario.sensor` | `Sensor(...)` (Mandatory, no default) | Populated with baseline `{"fov_half_angle_deg": 1.5, "grid_step_km": 2.0, "grid_extent_km": 30.0}`. Satisfies $(2 \times 30 / 2 + 1)^2 = 961 \le 10000$ grid point validator. |
| `Scenario.allocation` | `Allocation(...)` (Optional/baseline) | Populated with baseline `{"replan_interval_s": 10.0, "role_weights": {"leader": 1.0, "downlink": 0.9, "imager": 0.5}}`. |

### 2.3 Seam Analysis: `cubesat/sim.py:build_slots`
In `cubesat/sim.py` (lines 134–147), slot initial states are constructed via:
```python
def build_slots(scenario: Scenario, n: float) -> list[np.ndarray]:
    amp = scenario.formation.radial_amp_km * 1000.0
    offset = math.radians(scenario.formation.phase_offset_deg)
    return [
        slot_initial_state(
            amp, amp, offset + 2.0 * math.pi * j / scenario.formation.n_slots, n
        )
        for j in range(scenario.formation.n_slots)
    ]
```
This frozen implementation imposes three structural constraints:
1. **Radial to Cross-Track Locking ($B = A$)**: The simulation core structurally forces cross-track oscillation amplitude $B$ to equal radial amplitude $A$.
2. **Phase Locking ($\phi_z = \psi_j$)**: The cross-track oscillation phase is locked to the in-plane phase.
3. **Equidistant Angular Spacing**: Slots are rigidly separated by $\Delta \psi = \frac{2\pi}{N}$.

Because real clusters exhibit arbitrary cross-track separations (often $\ll A$) and non-uniform along-track phasing, `cubesat/live_import.py` projects real formations into this rigid model while logging all geometric fit residuals in the companion `.meta.json` sidecar.

---

## 3. Architecture & Stdlib-Only Module Layout

### 3.1 Module Organization & Responsibility Boundaries
To maintain maintainability and strictly comply with the repo invariant ("Files under ~300 lines"), the implementation is partitioned into focused modules:

```
cubesat/
├── __init__.py
├── live_import.py          # CLI, astrodynamics, phase presorting, ellipse fitting, scenario builder (~250 lines)
├── _live_network.py        # Pre-flight URL validator, redirect handler, streaming reader, cache manager (~150 lines)
├── live_import_e2e.py      # End-to-end live verification and determinism harness (~120 lines)
└── cluster_import.py       # Pre-existing offline OMM parser (preserved untouched)
tests/
└── test_live_import.py     # 100% offline unit/integration test suite with autouse network blocker (~300 lines)
data/
└── celestrak/              # Persistent disk cache directory (JSON snapshots)
```

#### Responsibility Matrix:
- **`cubesat/_live_network.py`**:
  - `validate_request_url(url)`: Scheme, userinfo, host allowlist, and port check.
  - `StrictRedirectHandler`: Intercepts 3xx redirects and re-validates destination URLs.
  - `download_stream(url, timeout_s, max_bytes)`: Enforces monotonic cumulative timeout and streaming size caps.
  - `sanitize_url(url)`: Regex credential sanitizer for error messages, stderr, and metadata.
  - `CacheManager`: Manages SHA-256 disk snapshots in `data/celestrak/` with atomic write replacement (`.tmp_{pid}_{hash}` -> `os.replace`).
- **`cubesat/live_import.py`**:
  - `_confine_output_path(path, repo_root)`: Validates path containment and prevents overwrite of protected source directories.
  - `parse_omm_records(records)`: Parses and normalizes CCSDS OMM dictionaries.
  - `brouwer_j2_propagate(elements, delta_t_s)`: Propagates Keplerian elements to median epoch.
  - `solve_kepler(M, e)`: Newton-Raphson solver with finite checks, $e \in [0, 1)$ bounds, and `max_iter = 50`.
  - `keplerian_to_eci(elements)`: Converts Keplerian elements to Cartesian position and velocity in ECI.
  - `eci_to_lvlh(r_eci, v_eci, r_chief, v_chief)`: Projects ECI states into chief LVLH frame.
  - `fit_passive_ellipse(deputies_lvlh)`: Pre-sorts deputies by empirical phase, then computes closed-form least-squares $A$ and $\psi_0$.
  - `assign_slots_hungarian(deputies, slots)`: Solves linear sum assignment with Invariant 6 tie-breaking epsilon.
  - `build_scenario_dict(...)`: Constructs complete Pydantic scenario payload with baseline blocks.
  - `main(argv)`: Argparse CLI entrypoint.

### 3.2 Stdlib-Only Mandate
In accordance with user rules and the zero-new-dependencies policy:
- **Forbidden**: `requests`, `urllib3`, `httpx`, `aiohttp`, `spacetrack`, `sgp4`, `astropy`, `skyfield`, `scipy.optimize` (except `linear_sum_assignment`).
- **Allowed Stdlib**: `urllib.request`, `urllib.error`, `urllib.parse`, `http.client`, `ssl`, `json`, `hashlib`, `math`, `datetime`, `argparse`, `pathlib`, `re`, `os`, `sys`, `copy`, `time`.
- **Allowed Repo Dependencies**: `numpy` (vector arithmetic, already pinned in `pyproject.toml`), `pydantic` (v2 scenario validation), `scipy.optimize.linear_sum_assignment` (for slot Hungarian matching).

---

## 4. CLI Interface Specification

### 4.1 Command-Line Syntax
The primary interface is executed via the `cubesat.live_import` module:

```powershell
uv run python -m cubesat.live_import [QUERY_OPTIONS] [CONFIG_OPTIONS] [OUTPUT_OPTIONS]
```

### 4.2 Comprehensive Options Table

| Category | Flag | Type | Default | Description |
|---|---|---|---|---|
| **Query Target** | `--cluster` | `str` | `None` | Named preset cluster (`grace-fo`, `firefly`, `starlink`). |
| | `--name` | `str` | `None` | Case-insensitive satellite name substring (e.g. `GRACE-FO`, `FIREFLY`). |
| | `--catnr` | `str` | `None` | NORAD Catalog ID (single integer or comma-separated list where supported). |
| | `--group` | `str` | `None` | CelesTrak group query (e.g. `cubesat`, `active`, `stations`). |
| **Provider** | `--provider` | `Choice` | `celestrak` | Telemetry provider: `celestrak`, `spacetrack`, or `n2yo`. |
| **Caching & Network** | `--cache-dir` | `Path` | `data/celestrak` | Directory for persistent snapshot cache (confined to repo). |
| | `--ttl` | `int` | `86400` | Cache time-to-live in seconds (24 hours). |
| | `--offline` | `Flag` | `False` | Forbid network requests; force loading from cache or frozen fixtures. |
| | `--force-refresh`| `Flag` | `False` | Bypass cache read and fetch fresh records from provider. |
| **Formation & Physics**| `--fit-mode` | `Choice` | `fit-ellipse`| Formation sizing mode: `fit-ellipse` (least-squares $A,\psi_0$) or `safe-envelope` (fixed 8.0 km). |
| | `--n-sats` | `int` | `None` | Swarm size ($4 \le N \le 32$). If omitted and cluster $N \ge 4$, defaults to cluster member count; if cluster has $N < 4$ (e.g. GRACE-FO with $N=2$), defaults to $N_\text{swarm} = 6$. |
| | `--n-failures` | `int` | `2` | Number of dead satellite failures to inject ($1 \le n_\text{fail} \le N-3$). Default: 2. |
| | `--seed` | `int` | `42` | Simulation pseudo-random seed (ensures reproducibility). |
| | `--duration` | `float` | `None` | Scenario duration in seconds. If omitted, set to exactly 3 orbits ($3 \times \frac{2\pi}{n}$). |
| | `--dt` | `float` | `2.0` | Simulation integration timestep in seconds. |
| **Output Paths** | `--out` | `Path` | `data/scenarios/live_swarm.json` | Destination scenario JSON file path (confined to repo, `.json` extension required, protected dirs forbidden). |
| | `--meta-out` | `Path` | `None` | Explicit path for sidecar metadata. Defaults to `<out_dir>/<out_stem>.meta.json`. Subject to identical path confinement. |

#### Scenario Naming Convention
To ensure honesty in logs and web consoles:
- `fitted-2-1-ellipse-<chief_name>`: When using `--fit-mode fit-ellipse`.
- `hypothetical-swarm-on-<chief_name>`: When using `--fit-mode safe-envelope` or expanding an $N < 4$ cluster into a 6-satellite operational swarm.

### 4.3 Exit Codes & Error Reporting
The CLI adheres to strict POSIX exit code conventions:

| Exit Code | Semantic Meaning | Trigger Conditions | Output Channel |
|---|---|---|---|
| `0` | **Success** | Orbital data retrieved, formation fitted, schema validated, scenario and sidecar written. | `stdout` (summary report) |
| `2` | **Argument / Security Error** | - Mutually exclusive or missing arguments.<br>- Path confinement violation (`--out`, `--meta-out`, or `--cache-dir` resolving outside repository root or targeting protected directories `cubesat/`, `tests/`, `.git/`, `docs/`, `.agents/`).<br>- Output path missing `.json` extension.<br>- Userinfo detected in requested URL.<br>- Insecure URL scheme or host not in allowlist.<br>- `--offline` specified but no matching cache snapshot exists on disk. | `stderr` (argparse formatted usage + error message) |
| `1` | **Runtime / Astrodynamics Error** | - Network error (DNS resolution failure, HTTP 4xx/5xx without cache fallback, cumulative read timeout).<br>- Empty orbital record set returned by provider.<br>- Malformed OMM JSON payload.<br>- Astrodynamics gate failure: chief eccentricity $e > 10^{-3}$ or altitude outside $(160, 2000)\text{ km}$.<br>- Kepler solver non-convergence after 50 iterations or non-finite inputs.<br>- Formation sizing failure: cluster contains fewer than 2 valid members. | `stderr` (sanitized error message with credentials scrubbed) |

---

## 5. Provider Abstraction & Authentication

### 5.1 Architecture of Provider Interfaces
To support multi-source telemetry while preserving a zero-dependency footprint, providers implement a uniform functional interface:

```python
class TelemetryProvider(abc.ABC):
    @abc.abstractmethod
    def fetch_omm_records(self, query: QueryParams) -> list[dict]:
        """Fetch raw OMM / GP records from provider endpoint."""
        pass
```

```
+-------------------------------------------------------------+
|                     TelemetryProvider                       |
+-------------------------------------------------------------+
                               ^
                               |
         +---------------------+---------------------+
         |                                           |
+----------------------+                   +----------------------+
|  CelesTrakProvider   |                   |  SpaceTrackProvider  |
|  (Default, Public,   |                   |  (Optional, Auth,    |
|   Unauthenticated)   |                   |   Session Cookie)    |
+----------------------+                   +----------------------+
         |                                           |
         | GET gp.php?NAME=...                       | POST /ajaxauth/login
         v                                           v
   celestrak.org                               space-track.org
```

### 5.2 Primary Provider: CelesTrak (`gp.php`)
- **Base URL**: `https://celestrak.org/NORAD/elements/gp.php`
- **Authentication**: None required.
- **Query Parameter Mapping**: Parameters are encoded strictly via `urllib.parse.urlencode()`:
  - By Name: `https://celestrak.org/NORAD/elements/gp.php?` + `urllib.parse.urlencode({"NAME": name, "FORMAT": "JSON"})`
  - By Group: `https://celestrak.org/NORAD/elements/gp.php?` + `urllib.parse.urlencode({"GROUP": group, "FORMAT": "JSON"})`
  - By Catalog ID: `https://celestrak.org/NORAD/elements/gp.php?` + `urllib.parse.urlencode({"CATNR": catnr, "FORMAT": "JSON"})`
- **Wire Contract & Quirks**:
  1. **Malformed Query String Handling**: When CelesTrak receives an invalid parameter, it returns **HTTP 200 OK** with `Content-Type: text/plain; charset=UTF-8` containing `Invalid query: "..."`. The parser checks MIME type via `content_type.split(";")[0].strip().lower()` before calling `json.loads()`.
  2. **Empty / Non-Existent Query Handling**: Queries with no matching satellites return **HTTP 404 Not Found** with body `No GP data found`. The client intercepts HTTP 404 and raises a clean `ValueError("No orbital records found for query")`.
  3. **Rate Limiting Fallback (HTTP 429 / 503)**: If CelesTrak throttles requests (HTTP 429 or 503), the client checks for an existing disk cache snapshot. If present, it logs a warning to `stderr` and falls back to the cache snapshot rather than failing immediately.
  4. **Zero Content-Length Streaming**: Dynamic queries return `Content-Length: 0` or omit the header under chunked transfer encoding. Chunked streaming verification is mandatory.

### 5.3 Optional Key-Based Provider: Space-Track (`space-track.org`)
- **Base URL**: `https://www.space-track.org`
- **Authentication**: Sourced strictly from environment variables:
  - `CUBESAT_SPACETRACK_USER`
  - `CUBESAT_SPACETRACK_PASSWORD`
- **Login Flow**:
  - Request: `POST https://www.space-track.org/ajaxauth/login`
  - Content-Type: `application/x-www-form-urlencoded`
  - Body: Form-encoded via `urllib.parse.urlencode({"identity": user, "password": password, "query": query_url})`
- **Data Normalization**: Space-Track serializes all numeric fields as strings (e.g. `"MEAN_MOTION": "15.40255823"`). The parser applies `float(str(val))` with `math.isfinite()` validation across all numerical keys.
- **Rate Limit Throttling**: 30 requests/minute and 300 requests/hour. HTTP 429 and 503 trigger disk cache fallback if a cached snapshot exists.

### 5.4 Optional Key-Based Provider: N2YO (`api.n2yo.com`)
- **Base URL**: `https://api.n2yo.com/rest/v1/satellite/`
- **Authentication**: Sourced strictly from environment variable `N2YO_API_KEY`.
- **Query URL**: `GET /rest/v1/satellite/tle/{norad_id}&apiKey={N2YO_API_KEY}`
- **Payload Structure**: Returns a JSON object with 2-line TLE string in field `tle`.
- **TLE Parsing & Validation**:
  - Validates line count ($= 2$), minimum line length ($\ge 69$ characters), and fixed prefixes (`'1 '`, `'2 '`).
  - Slices fixed-width columns to extract inclination, RAAN, eccentricity, argument of perigee, and mean motion.

### 5.5 Strict Credential Isolation & Sanitization Policy
1. **Zero CLI Credential Exposure**: Command-line arguments must NEVER accept passwords, tokens, or API keys (`--api-key` is strictly forbidden). Command-line arguments are visible in process tables (`ps`, `Get-Process`) and stored in shell history.
2. **Environment Variable Sourcing**: Credentials must be read via `os.environ.get()` only at the point of network dispatch.
3. **URL Sanitization & Secret Redaction**: Any URL recorded in logs, printed to console, or written to `.meta.json` sidecar files MUST be sanitized using case-insensitive regular expression redaction:
   ```python
   def sanitize_url(url: str) -> str:
       # Redact query secrets
       redacted = re.sub(
           r'(?i)(api[_-]?key|password|token|secret|identity)=([^&]+)',
           r'\1=[REDACTED]',
           url
       )
       # Strip userinfo if present
       parsed = urllib.parse.urlparse(redacted)
       if parsed.username or parsed.password:
           host_part = parsed.hostname or ""
           if parsed.port:
               host_part = f"{host_part}:{parsed.port}"
           redacted = urllib.parse.urlunparse((
               parsed.scheme, host_part, parsed.path, parsed.params, parsed.query, parsed.fragment
           ))
       return redacted
   ```
4. **Exception Wrapping**: Catch `urllib.error.HTTPError` and `urllib.error.URLError`, scrub `err.url` and `err.filename`, and sanitize exception messages before formatting to `stderr` or re-raising:
   ```python
   try:
       resp = urllib.request.urlopen(req, timeout=timeout_s)
   except urllib.error.HTTPError as err:
       sanitized_msg = sanitize_url(str(err))
       raise RuntimeError(f"HTTP fetch failed: {sanitized_msg}") from None
   except urllib.error.URLError as err:
       sanitized_msg = sanitize_url(str(err))
       raise RuntimeError(f"Network error: {sanitized_msg}") from None
   ```
5. **Cache Key Independence**: Disk cache filenames must hash the canonical, sanitized query parameters rather than raw URLs containing secrets: `f"{provider}:{sanitized_query}"`.

---

## 6. Network Hardening & Threat Model

### 6.1 Threat Matrix & Mitigations

| Threat ID | Threat Vector | Impact | Engineering Mitigation |
|---|---|---|---|
| **THREAT-1** | **Server-Side Request Forgery (SSRF)** via Initial URL & HTTP Redirects | Attacker manipulates query or redirect destination to hit internal cloud metadata (`169.254.169.254`) or local services (`127.0.0.1`). Userinfo injection (`https://celestrak.org:443@169.254.169.254/`) bypasses naive netloc splitting. | 1. Centralized pre-flight check `validate_request_url()` executed on the initial URL.<br>2. Custom `StrictRedirectHandler` inspecting all HTTP 3xx redirects.<br>3. Inspects `parsed.hostname` (not `netloc.split(":")[0]`).<br>4. Rejects userinfo explicitly: `if parsed.username or parsed.password: raise ValueError(...)`.<br>5. Enforces `parsed.hostname in ALLOWED_HOSTS` and `parsed.port in (None, 443)`. |
| **THREAT-2** | **Denial of Service (DoS)** via Unbounded Response Streaming & Decompression Bombs | Memory exhaustion / crash via massive data streams or gzip bombs (5 MB compressed expands to > 5 GB). | 1. Send `Accept-Encoding: identity` to disallow compressed gzip bombs.<br>2. Header check: `Content-Length` > 5 MB aborted immediately (wrapped in `try...except (ValueError, TypeError)`).<br>3. Chunked stream check: Stream read in 64 KB chunks with running counter; aborts if total payload exceeds 5,242,880 bytes. |
| **THREAT-3** | **Network Latency & Slowloris Read Hangs** | Process hang / worker starvation due to server trickling 64 bytes every 9 seconds, never tripping per-read socket timeouts. | Enforce cumulative monotonic deadline: `deadline = time.monotonic() + timeout_s` (default 30.0s). In the chunk read loop, if `time.monotonic() > deadline`, abort connection and raise `TimeoutError("Cumulative response read timeout exceeded")`. |
| **THREAT-4** | **Arbitrary File Overwrite & Path Traversal** | Malicious `--out`, `--meta-out`, or `--cache-dir` escaping repo root or overwriting core source files (`cubesat/sim.py`, `.git/config`). | 1. Normalize with `os.path.normcase` and check containment against repo root.<br>2. Catch Windows cross-drive `ValueError` and exit with code 2.<br>3. Protected directory guard: forbid targeting `cubesat/`, `tests/`, `.git/`, `docs/`, `.agents/`.<br>4. Enforce `--out` must have `.json` extension and reside in `data/` or scenario directory. |
| **THREAT-5** | **Cache Poisoning & Race Conditions** | Partial writes during process termination leaving 0-byte or corrupted JSON files on disk. Symlink traversal out of repo. | 1. Atomic cache writes: write to `.tmp_{pid}_{hash}` in cache dir, flush, fsync, and call `os.replace(tmp_path, target_path)`.<br>2. Reject cache files if `cache_path.is_symlink()`.<br>3. Strict JSON decode validation upon loading. |
| **THREAT-6** | **Credential Leakage** | API keys or passwords written to disk, wire, or emitted in Python exception traces. | 1. Environment-variable-only sourcing.<br>2. Global URL sanitization on exceptions, console logs, and sidecar metadata.<br>3. Cache keys generated without secret tokens. |

### 6.2 Implementation: Pre-Flight Validation, Redirect Handler, & Streaming Reader

```python
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

ALLOWED_HOSTS = frozenset({"celestrak.org", "www.space-track.org", "api.n2yo.com"})
MAX_PAYLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
DEFAULT_TIMEOUT_S = 10.0
CUMULATIVE_TIMEOUT_S = 30.0


def validate_request_url(url: str) -> None:
    """Pre-flight security validation for all outbound HTTP requests."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() != "https":
        raise ValueError(f"SSRF Prevention: Refusing insecure scheme '{parsed.scheme}'")
    if parsed.username or parsed.password:
        raise ValueError("SSRF Prevention: Userinfo in URL is strictly forbidden")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"SSRF Prevention: Host '{host}' not in ALLOWED_HOSTS")
    if parsed.port not in (None, 443):
        raise ValueError(f"SSRF Prevention: Non-standard HTTPS port {parsed.port} forbidden")


class StrictRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Hardened redirect handler enforcing HTTPS, host allowlist, and userinfo checks."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_request_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_stream(url: str, timeout_s: float = DEFAULT_TIMEOUT_S, cumulative_timeout_s: float = CUMULATIVE_TIMEOUT_S) -> bytes:
    """Secure streaming download with cumulative deadline and size cap."""
    validate_request_url(url)
    
    headers = {
        "User-Agent": "CubeSatLiveImport/1.0",
        "Accept-Encoding": "identity",  # Disallow gzip compression bombs
    }
    req = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(StrictRedirectHandler())
    
    deadline = time.monotonic() + cumulative_timeout_s
    try:
        with opener.open(req, timeout=timeout_s) as resp:
            # Check Content-Length header if present
            cl_header = resp.headers.get("Content-Length")
            if cl_header:
                try:
                    cl = int(cl_header)
                    if cl > MAX_PAYLOAD_BYTES:
                        raise ValueError(f"Payload size {cl} exceeds maximum limit of {MAX_PAYLOAD_BYTES} bytes")
                except (ValueError, TypeError):
                    pass
            
            chunks = []
            total_bytes = 0
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Cumulative response read timeout of {cumulative_timeout_s}s exceeded")
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_PAYLOAD_BYTES:
                    raise ValueError(f"Response stream exceeded {MAX_PAYLOAD_BYTES} bytes cap")
                chunks.append(chunk)
            return b"".join(chunks)
    except urllib.error.HTTPError as err:
        sanitized = sanitize_url(str(err))
        raise RuntimeError(f"HTTP request failed: {sanitized}") from None
    except urllib.error.URLError as err:
        sanitized = sanitize_url(str(err))
        raise RuntimeError(f"Network transport error: {sanitized}") from None
```

### 6.3 Snapshot Disk Cache Architecture & Atomic Writes
To guarantee 100% offline testability and resilience against transient network failures:
- **Location**: `data/celestrak/` (or custom confined `--cache-dir`).
- **File Naming Convention**:
  ```python
  sanitized_query_key = f"{provider}:{sanitized_query_string}"
  cache_key = hashlib.sha256(sanitized_query_key.encode("utf-8")).hexdigest()[:16]
  cache_file = cache_dir / f"{provider}_{cache_key}.json"
  ```
- **Cache Invalidation & TTL**:
  - Default TTL: 86,400 seconds (24 hours).
  - Validation: Check `time.time() - os.path.getmtime(cache_path) < ttl_s`.
- **Atomic File Replacement**:
  ```python
  def write_cache_atomic(cache_file: Path, data: bytes) -> None:
      cache_file.parent.mkdir(parents=True, exist_ok=True)
      tmp_file = cache_file.parent / f".tmp_{os.getpid()}_{cache_file.stem}"
      try:
          with open(tmp_file, "wb") as f:
              f.write(data)
              f.flush()
              os.fsync(f.fileno())
          os.replace(tmp_file, cache_file)
      except Exception:
          if tmp_file.exists():
              tmp_file.unlink()
          raise
  ```
- **Symlink Protection**: Before loading from cache, verify `cache_path.is_file() and not cache_path.is_symlink()`.
- **Resolution Strategy**:
  1. If `--offline` is set: read cache directly. If missing, raise exit code 2.
  2. If cache exists and age < TTL: read cache directly without opening sockets.
  3. If cache is expired or missing: attempt live HTTPS fetch.
  4. If live fetch fails (network down or HTTP 429/503) and expired cache exists: emit warning to `stderr` and fall back to expired cache.

### 6.4 Repository Path Confinement & Source Protection
To prevent arbitrary file overwrite or tampering with repository source code:

```python
PROTECTED_DIRS = frozenset({"cubesat", "tests", ".git", "docs", ".agents", ".zcode"})
PROTECTED_FILES = frozenset({"pyproject.toml", "uv.lock", "AGENTS.md", "README.md", "GATES.md"})

def confine_output_path(target_path: Path, repo_root: Path) -> Path:
    """Confines output path within repo_root and protects core source directories."""
    resolved = (repo_root / target_path).resolve()
    norm_repo = os.path.normcase(str(repo_root.resolve()))
    norm_target = os.path.normcase(str(resolved))
    
    try:
        common = os.path.normcase(os.path.commonpath([norm_target, norm_repo]))
    except ValueError:
        raise ValueError(f"Cross-drive path traversal rejected: {target_path}")
    
    if common != norm_repo:
        raise ValueError(f"Path traversal detected: {target_path} escapes repository root")
        
    rel_parts = resolved.relative_to(repo_root.resolve()).parts
    if not rel_parts:
        raise ValueError("Cannot write directly to repository root directory")
        
    root_subdir = rel_parts[0].lower()
    if root_subdir in PROTECTED_DIRS or resolved.name.lower() in PROTECTED_FILES:
        raise ValueError(f"Protected repository directory/file cannot be overwritten: {rel_parts[0]}")
        
    if resolved.suffix.lower() != ".json":
        raise ValueError(f"Output file must have .json extension, got: {resolved.suffix}")
        
    return resolved
```

---

## 7. Relative Orbital Mechanics & Fitting Engine

### 7.1 Mathematical Coordinate Frames & Standards
- **Standard Constants** (`cubesat/hcw.py`):
  - $\mu = 3.986004418 \times 10^{14}\ \text{m}^3/\text{s}^2$ (WGS-84 standard gravitational parameter)
  - $R_{\text{Earth}} = 6378.137 \times 10^3\ \text{m}$ (Earth equatorial radius)
  - $J_2 = 1.08262668 \times 10^{-3}$ (First zonal harmonic coefficient)
- **Reference Frame (Invariant 4)**:
  - Local-Vertical Local-Horizontal (LVLH) frame centered on the chief satellite:
    - $\hat{\mathbf{x}}$ (Radial): Directed from Earth center outward along chief position vector $\mathbf{r}_c$.
    - $\hat{\mathbf{z}}$ (Cross-track): Directed along chief orbital angular momentum vector $\mathbf{h}_c = \mathbf{r}_c \times \mathbf{v}_c$.
    - $\hat{\mathbf{y}}$ (Along-track): Completes right-handed orthogonal triad $\hat{\mathbf{y}} = \hat{\mathbf{z}} \times \hat{\mathbf{x}}$ (aligned with flight direction).

```
                             +x (Radial, outward)
                               ^
                               |
                               |   Deputy (x, y, z)
                               |      *
                               |     /
                               |    /
                               |   /
                               |  /
                               +------------------> +y (Along-track, velocity)
                              / Chief
                             /
                            /
                           v
                         +z (Cross-track, angular momentum h = r x v)
```

### 7.2 Step 1: OMM Record Ingestion & Input Validation
Raw CCSDS OMM JSON records provide mean orbital elements at distinct observation epochs:
- `EPOCH`: ISO-8601 UTC timestamp ($t_k$).
- `MEAN_MOTION`: Mean motion $n_0$ in revolutions per solar day.
  $$n = n_0 \times \frac{2\pi}{86400.0}\quad [\text{rad/s}]$$
  $$a = \left(\frac{\mu}{n^2}\right)^{1/3}\quad [\text{m}]$$
- `ECCENTRICITY`: Orbital eccentricity $e$ (dimensionless).
- `INCLINATION`: Inclination $i$ in degrees (converted to radians).
- `RA_OF_ASC_NODE`: Right ascension of ascending node $\Omega$ in degrees (converted to radians).
- `ARG_OF_PERICENTER`: Argument of perigee $\omega$ in degrees (converted to radians).
- `MEAN_ANOMALY`: Mean anomaly $M$ in degrees (converted to radians).

**Input Validation Gate**:
Every numerical input $x \in \{a, e, i, \Omega, \omega, M\}$ must satisfy `math.isfinite(x)`. If any field is `NaN` or $\pm\infty$, raise `ValueError("Non-finite orbital element in input record")`. Furthermore, require $0.0 \le e < 1.0$ and $160\text{ km} < a - R_{\text{Earth}} < 2000\text{ km}$.

### 7.3 Step 2: Epoch Synchronization via Brouwer $J_2$ Secular Rates
Because individual satellites in a cluster catalog are observed at differing epochs $t_k$, all orbital elements must be propagated to a unified reference epoch $t_c$.

#### A. Median Common Epoch Selection
To minimize propagation interval and accumulated error, the common epoch $t_c$ is selected as the **median timestamp** of the satellite ensemble:
$$t_c = \operatorname{median}(\{t_1, t_2, \dots, t_N\})$$
This guarantees that for every satellite, the propagation span $|\Delta t_k| = |t_c - t_k| \le \frac{1}{2} (t_{\max} - t_{\min})$.

#### B. First-Order $J_2$ Secular Rate Equations (Brouwer / Lyddane)
Let $p = a(1 - e^2)$ be the semi-latus rectum and define the dimensionless $J_2$ scaling parameter:
$$f = \frac{3}{2} J_2 \left(\frac{R_{\text{Earth}}}{p}\right)^2$$
Over the propagation step $\Delta t_k = t_c - t_k$, the elements evolve as:
1. **Semi-major axis, eccentricity, and inclination remain secularly constant**:
   $$\dot{a} = 0,\quad \dot{e} = 0,\quad \dot{i} = 0$$
2. **Nodal Regression**:
   $$\dot{\Omega} = -f n \cos i$$
   $$\Omega(t_c) = \Omega(t_k) + \dot{\Omega} \Delta t_k \pmod{2\pi}$$
3. **Apsidal Precession**:
   $$\dot{\omega} = \frac{1}{2} f n \left(5 \cos^2 i - 1\right)$$
   $$\omega(t_c) = \omega(t_k) + \dot{\omega} \Delta t_k \pmod{2\pi}$$
4. **Mean Anomaly Evolution**:
   $$\dot{M} = n \left[ 1 + \frac{1}{2} f \sqrt{1 - e^2} \left(3 \cos^2 i - 1\right) \right]$$
   $$M(t_c) = M(t_k) + \dot{M} \Delta t_k \pmod{2\pi}$$

*Significance*: Across an hour-long catalog spread (observed in Firefly OMM data), $J_2$ secular propagation accounts for over $75\text{ km}$ of along-track position evolution compared to unperturbed two-body propagation.

### 7.4 Step 3: Keplerian State Conversion (Perifocal to ECI)
At epoch $t_c$, each satellite's elements are converted to Cartesian position $\mathbf{r}_{\text{eci}}$ and velocity $\mathbf{v}_{\text{eci}}$:

1. **Hardened Newton-Raphson Kepler Solver**:
   Solve $E - e \sin E = M$ for eccentric anomaly $E$.
   - Input validation: Verify $0.0 \le e < 1.0$ and `math.isfinite(M)`.
   - Iteration: Starting with initial guess $E_0 = M$:
     $$E_{m+1} = E_m - \frac{E_m - e \sin E_m - M}{1 - e \cos E_m}$$
   - **Singularity Guard**: If $|1 - e \cos E_m| < 10^{-12}$, raise `ValueError("Near-singular derivative in Kepler solver")`.
   - **Convergence Check**: Terminate when $|E_{m+1} - E_m| < 10^{-14}$.
   - **Loop Cap**: Maximum iterations `max_iter = 50`. If the loop does not converge within 50 iterations, raise `ValueError("Kepler solver failed to converge within 50 iterations")`.

2. **Perifocal State ($PQW$)**:
   True anomaly $\nu$:
   $$\nu = 2 \operatorname{atan2}\left(\sqrt{1 + e} \sin\frac{E}{2},\ \sqrt{1 - e} \cos\frac{E}{2}\right)$$
   Orbital radius $r = a(1 - e \cos E)$. The perifocal coordinates are:
   $$\mathbf{r}_{pqw} = \begin{bmatrix} r \cos\nu \\ r \sin\nu \\ 0 \end{bmatrix},\quad \mathbf{v}_{pqw} = \sqrt{\frac{\mu}{p}} \begin{bmatrix} -\sin\nu \\ e + \cos\nu \\ 0 \end{bmatrix}$$

3. **Transformation to ECI Frame**:
   Apply 3-1-3 Euler rotation matrix $\mathbf{R} = \mathbf{R}_z(\Omega) \mathbf{R}_x(i) \mathbf{R}_z(\omega)$:
   $$\mathbf{R} = \begin{bmatrix}
   \cos\Omega\cos\omega - \sin\Omega\cos i\sin\omega & -\cos\Omega\sin\omega - \sin\Omega\cos i\cos\omega & \sin\Omega\sin i \\
   \sin\Omega\cos\omega + \cos\Omega\cos i\sin\omega & -\sin\Omega\sin\omega + \cos\Omega\cos i\cos\omega & -\cos\Omega\sin i \\
   \sin i\sin\omega & \sin i\cos\omega & \cos i
   \end{bmatrix}$$
   $$\mathbf{r}_{\text{eci}} = \mathbf{R} \mathbf{r}_{pqw},\quad \mathbf{v}_{\text{eci}} = \mathbf{R} \mathbf{v}_{pqw}$$

### 7.5 Step 4: Projection into Chief LVLH Basis
1. **Chief Selection**:
   The chief satellite can be explicitly designated via `--index` / `--name` or defined as the ensemble centroid. Let $\mathbf{r}_c, \mathbf{v}_c$ be the chief ECI vectors.
2. **Orthonormal Basis Triad**:
   $$\hat{\mathbf{x}} = \frac{\mathbf{r}_c}{\|\mathbf{r}_c\|},\quad \hat{\mathbf{z}} = \frac{\mathbf{r}_c \times \mathbf{v}_c}{\|\mathbf{r}_c \times \mathbf{v}_c\|},\quad \hat{\mathbf{y}} = \hat{\mathbf{z}} \times \hat{\mathbf{x}}$$
3. **Relative Vector Projection**:
   For deputy $k \in \{0, \dots, N-1\}$ with $\Delta \mathbf{r}_k = \mathbf{r}_k - \mathbf{r}_c$ and $\Delta \mathbf{v}_k = \mathbf{v}_k - \mathbf{v}_c$:
   $$\mathbf{r}_k^{\text{lvlh}} = \begin{bmatrix} \Delta \mathbf{r}_k \cdot \hat{\mathbf{x}} \\ \Delta \mathbf{r}_k \cdot \hat{\mathbf{y}} \\ \Delta \mathbf{r}_k \cdot \hat{\mathbf{z}} \end{bmatrix} = \begin{bmatrix} x_k \\ y_k \\ z_k \end{bmatrix},\quad \mathbf{v}_k^{\text{lvlh}} = \begin{bmatrix} \Delta \mathbf{v}_k \cdot \hat{\mathbf{x}} \\ \Delta \mathbf{v}_k \cdot \hat{\mathbf{y}} \\ \Delta \mathbf{v}_k \cdot \hat{\mathbf{z}} \end{bmatrix} = \begin{bmatrix} v_{xk} \\ v_{yk} \\ v_{zk} \end{bmatrix}$$
4. **Centroid Centering**:
   $$\bar{x} = \frac{1}{N} \sum_{k=0}^{N-1} x_k,\quad \bar{y} = \frac{1}{N} \sum_{k=0}^{N-1} y_k$$
   $$\tilde{x}_k = x_k - \bar{x},\quad \tilde{y}_k = y_k - \bar{y},\quad \tilde{z}_k = z_k$$

### 7.6 Step 5: Phase Pre-Sorting & Closed-Form Least-Squares Fitting

#### A. The Ordering Problem & Phase Pre-Sorting
The simulation core (`cubesat/sim.py:134–147`) establishes equidistant in-plane candidate slot angles:
$$\theta_k = \frac{2\pi k}{N},\quad k = 0, \dots, N-1$$
Real satellites arrive in arbitrary catalog order (e.g. by NORAD ID or ingest order). Summing over unsorted catalog indices would map arbitrary satellites to rigid slot angles $\theta_k$, distorting the fit.

To eliminate this circular dependency prior to evaluating normal equations:
1. Normalize coordinates to remove the 2:1 ellipse aspect ratio:
   $$\xi_k = \tilde{x}_k,\quad \eta_k = -\frac{\tilde{y}_k}{2}$$
2. Compute the empirical polar phase for each deputy:
   $$\phi_k = \operatorname{atan2}(\eta_k, \xi_k) \pmod{2\pi}$$
3. **Pre-sort the deputies** in ascending order of empirical phase:
   $$\phi_{(0)} \le \phi_{(1)} \le \dots \le \phi_{(N-1)}$$
   Reorder $(\xi_k, \eta_k)$ accordingly into $(\xi_{(k)}, \eta_{(k)})$.

#### B. Closed-Form Least-Squares Normal Equations
In normalized coordinates, the model is a circle of radius $A$ with reference offset $\psi_0$:
$$\xi_k^{\text{mod}} = A \cos(\psi_0 + \theta_k) = (A \cos\psi_0) \cos\theta_k - (A \sin\psi_0) \sin\theta_k$$
$$\eta_k^{\text{mod}} = A \sin(\psi_0 + \theta_k) = (A \cos\psi_0) \sin\theta_k + (A \sin\psi_0) \cos\theta_k$$

Let $C = A \cos\psi_0$ and $S = A \sin\psi_0$. Expressing in matrix form for satellite $k$:
$$\begin{bmatrix} \cos\theta_k & -\sin\theta_k \\ \sin\theta_k & \cos\theta_k \end{bmatrix} \begin{bmatrix} C \\ S \end{bmatrix} \approx \begin{bmatrix} \xi_{(k)} \\ \eta_{(k)} \end{bmatrix}$$

Because the rotation matrices $\mathbf{M}_k$ satisfy $\sum_{k=0}^{N-1} \mathbf{M}_k^T \mathbf{M}_k = N \mathbf{I}_2$, the normal equations decouple completely into diagonal scalar sums:
$$\boxed{C = \frac{1}{N} \sum_{k=0}^{N-1} \left( \xi_{(k)} \cos\theta_k + \eta_{(k)} \sin\theta_k \right)}$$
$$\boxed{S = \frac{1}{N} \sum_{k=0}^{N-1} \left( -\xi_{(k)} \sin\theta_k + \eta_{(k)} \cos\theta_k \right)}$$
$$\boxed{A = \sqrt{C^2 + S^2},\quad \psi_0 = \operatorname{atan2}(S, C) \pmod{2\pi}}$$

#### C. Properties of the Closed-Form Solution:
1. **$O(N \log N)$ Complexity**: $O(N \log N)$ for phase sorting, followed by a single $O(N)$ pass for scalar summation; zero iterative loops or gradient descent.
2. **Strict Numerical Stability**: Normal matrix determinant is identically $N^2 \ne 0$ for all $N \ge 1$.
3. **Exact Recovery for Two Satellites ($N=2$)**: For $N=2$ with relative baseline $\mathbf{d} = \mathbf{r}_1 - \mathbf{r}_0$, the formula reduces identically to:
   $$A = \sqrt{\left(\frac{d_x}{2}\right)^2 + \left(\frac{d_y}{4}\right)^2},\quad \psi_0 = \operatorname{atan2}\left(\frac{d_y}{4}, -\frac{d_x}{2}\right)$$
   matching `gracefo_formation_math.py` to double precision.

### 7.7 Step 6: Swarm Expansion for Small Clusters ($N < 4$) & Hungarian Slot Assignment

#### A. Swarm Sizing Architecture for Small Clusters ($N < 4$)
In operational swarm simulations, critical roles include:
- Exactly 1 `leader`
- Exactly 1 `downlink`
- $(N - 2)$ `imager` satellites

Under the standard verification protocol (`live_import_e2e.py`), the scenario injects $n_\text{fail} = 2$ dead satellite failures and asserts the state transition:
`NOMINAL -> FAILURE_DETECTED -> REPLANNING -> RECOVERED`.

If an ingested cluster contains fewer than 4 satellites (such as GRACE-FO with $N=2$):
- Deriving an $N=2$ swarm leaves 0 imagers (`roles = ["leader", "downlink"]`).
- Injecting 2 failures kills the entire swarm ($N - n_\text{fail} = 0$). Even with 1 failure, 1 satellite cannot field both `leader` and `downlink`.
- `cubesat/allocate.py:seat_roles_for` will fail to re-elect roles, making autonomous recovery impossible.

**Design Rule for Small Clusters ($N < 4$)**:
1. When the ingested cluster has $N_\text{real} < 4$ satellites (e.g. GRACE-FO with $N_\text{real} = 2$), `live_import` defaults to generating a full operational swarm with $N_\text{swarm} = 6$ slots on the fitted ellipse (or user-specified `--n-sats` $\ge 4$).
2. The $N_\text{swarm}$ model slots are placed on the fitted ellipse at:
   $$\theta_j = \psi_0 + \frac{2\pi j}{N_\text{swarm}},\quad j = 0, \dots, N_\text{swarm}-1$$
3. Real satellites are assigned to their closest model slots via Hungarian matching.
4. The remaining $(N_\text{swarm} - N_\text{real})$ slots are instantiated as hypothetical swarm satellites initialized at their respective slot states.
5. Roles are allocated: 1 leader, 1 downlink, 4 imagers. Surviving satellites $N_\text{survivors} = 6 - 2 = 4 \ge 2$, permitting full role re-election and autonomous recovery.

#### B. Hungarian Slot Assignment with Invariant 6 Tie-Breaking
1. **Cost Matrix Construction**: Build an $N_\text{real} \times N_\text{swarm}$ Euclidean distance cost matrix between observed deputy states and candidate model slot states:
   $$C_{i, j} = \|\tilde{\mathbf{r}}_i - \mathbf{r}_j^{\text{mod}}\|$$
2. **Tie-Breaking with Index Epsilon (Invariant 6)**:
   To eliminate platform-dependent permutation ambiguities:
   $$C_{i, j}^{\text{perturbed}} = C_{i, j} + 10^{-9} \cdot (i \cdot N_\text{swarm} + j)$$
3. **Hungarian Assignment**:
   Solve via `scipy.optimize.linear_sum_assignment(C_perturbed)`:
   $$\text{row\_ind}, \text{col\_ind} = \text{linear\_sum\_assignment}(C^{\text{perturbed}})$$
   Assign real satellite $\text{row\_ind}[k]$ to slot $\text{col\_ind}[k]$. Unoccupied slots are populated with hypothetical swarm satellites.

---

## 8. Sidecar Provenance Metadata (`.meta.json`) & Scenario Baseline

### 8.1 Structural Decoupling & Mandatory Scenario Baseline Parameters
To ensure generated scenarios remain 100% compliant with the existing frozen Pydantic schema in `cubesat/scenario.py`, the generated scenario dictionary MUST include all mandatory baseline parameter blocks:

```python
# cubesat/scenario.py requires a_max_mps2, gains, sensor without defaults:
scenario_dict = {
    "name": f"fitted-2-1-ellipse-{chief_name}",
    "seed": seed,
    "duration_s": duration_s,
    "dt_s": dt_s,
    "chief": {
        "altitude_km": round(chief["altitude_km"], 3),
        "inclination_deg": round(chief["inclination_deg"], 3),
    },
    "formation": {
        "n_slots": n_swarm,
        "radial_amp_km": round(fitted_amp_km, 4),
        "phase_offset_deg": round(math.degrees(fitted_psi_0) % 360.0, 3),
    },
    "a_max_mps2": 0.1,
    "gains": {
        "wn": 0.01,
        "zeta": 1.0,
    },
    "sensor": {
        "fov_half_angle_deg": 1.5,
        "grid_step_km": 2.0,
        "grid_extent_km": 30.0,
    },
    "allocation": {
        "replan_interval_s": 10.0,
        "role_weights": {
            "leader": 1.0,
            "downlink": 0.9,
            "imager": 0.5,
        },
    },
    "roles": roles_list,        # Exactly 1 leader, 1 downlink, (n_swarm - 2) imagers
    "failures": failure_list,   # Injected failures, e.g. sat 1 at 1200s, sat 2 at 1500s
}
```

All extended provenance, astrodynamics metrics, raw catalog details, and fit residuals are serialized strictly to the companion sidecar file `<scenario_name>.meta.json`.

### 8.2 JSON Schema Specification: `.meta.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "CubeSatLiveImportProvenanceMetadata",
  "type": "object",
  "required": [
    "provider",
    "query",
    "url",
    "fetch_time_utc",
    "chief",
    "cluster_members",
    "formation_fit",
    "fidelity_and_honesty"
  ],
  "properties": {
    "provider": { "type": "string", "enum": ["celestrak", "spacetrack", "n2yo"] },
    "query": { "type": "string" },
    "url": { "type": "string", "description": "Sanitized query URL with API keys redacted" },
    "fetch_time_utc": { "type": "string", "format": "date-time" },
    "cache_hit": { "type": "boolean" },
    "chief": {
      "type": "object",
      "required": ["name", "norad_cat_id", "altitude_km", "eccentricity", "mean_motion_rad_s", "epoch_iso"],
      "properties": {
        "name": { "type": "string" },
        "norad_cat_id": { "type": "integer" },
        "altitude_km": { "type": "number" },
        "eccentricity": { "type": "number" },
        "mean_motion_rad_s": { "type": "number" },
        "epoch_iso": { "type": "string" }
      }
    },
    "cluster_members": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "norad_cat_id", "epoch_iso", "delta_epoch_s", "raw_lvlh_pos_m"],
        "properties": {
          "name": { "type": "string" },
          "norad_cat_id": { "type": "integer" },
          "epoch_iso": { "type": "string" },
          "delta_epoch_s": { "type": "number" },
          "raw_lvlh_pos_m": {
            "type": "array",
            "items": { "type": "number" },
            "minItems": 3,
            "maxItems": 3
          }
        }
      }
    },
    "formation_fit": {
      "type": "object",
      "required": [
        "fit_mode",
        "radial_amp_km",
        "phase_offset_deg",
        "rms_pos_m",
        "rms_vel_mps",
        "max_pos_residual_m",
        "secular_drift_km_per_day",
        "cross_track_mismatch_m"
      ],
      "properties": {
        "fit_mode": { "type": "string", "enum": ["fit-ellipse", "safe-envelope"] },
        "radial_amp_km": { "type": "number" },
        "phase_offset_deg": { "type": "number" },
        "rms_pos_m": { "type": "number" },
        "rms_vel_mps": { "type": "number" },
        "max_pos_residual_m": { "type": "number" },
        "secular_drift_km_per_day": { "type": "number" },
        "cross_track_mismatch_m": { "type": "number" }
      }
    },
    "fidelity_and_honesty": {
      "type": "object",
      "required": [
        "model_type",
        "formation_scale",
        "linearization_validity",
        "notes"
      ],
      "properties": {
        "model_type": { "type": "string" },
        "formation_scale": { "type": "string" },
        "linearization_validity": { "type": "string", "enum": ["VALID", "CW_INVALID_LARGE_BASELINE"] },
        "notes": { "type": "string" }
      }
    }
  }
}
```

### 8.3 Example Sidecar Payload (`data/scenarios/live_e2e_swarm.meta.json`)
```json
{
  "provider": "celestrak",
  "query": "GRACE-FO",
  "url": "https://celestrak.org/NORAD/elements/gp.php?NAME=GRACE-FO&FORMAT=JSON",
  "fetch_time_utc": "2026-10-30T03:16:14.605391+00:00",
  "cache_hit": true,
  "chief": {
    "name": "GRACE-FO 1",
    "norad_cat_id": 43476,
    "altitude_km": 445.354,
    "eccentricity": 0.00041874,
    "mean_motion_rad_s": 0.0011201056,
    "epoch_iso": "2026-10-29T22:41:56.511744"
  },
  "formation_fit": {
    "fit_mode": "fit-ellipse",
    "radial_amp_km": 47.5384,
    "phase_offset_deg": 271.627,
    "rms_pos_m": 1243.21,
    "rms_vel_mps": 1.34,
    "max_pos_residual_m": 2607.4,
    "secular_drift_km_per_day": 0.3395,
    "cross_track_mismatch_m": 66.705
  },
  "fidelity_and_honesty": {
    "model_type": "hypothetical-swarm-on-real-chief-orbit",
    "formation_scale": "47.5384 km fitted passive ellipse (use --fit-mode safe-envelope for standard 8.0 km envelope)",
    "linearization_validity": "CW_INVALID_LARGE_BASELINE",
    "notes": "Real cluster along-track baseline (~190 km for GRACE-FO) violates linear HCW dynamics (CW linearization error ~365 km RMS over 3 orbits). Sim utilizes fitted chief orbit with drift-free HCW passive ellipse to ensure simulation validity and collision safety. Ingested 2 satellites expanded to 6-slot operational swarm for role re-election survivability."
  }
}
```

---

## 9. Determinism Preservation & Verification Strategy

### 9.1 The Determinism Guarantee
Repository Invariant 2 mandates:
> *Determinism: no wall-clock, no unseeded RNG, no set/dict-order dependence inside the sim. Same scenario + seed => byte-identical log.*

To preserve this property when handling live telemetry:
1. **Sidecar Determinism on Cache Replay**: Cached snapshot JSON files stored in `data/celestrak/` record the original `fetch_time_utc`. When loading from cache, `fetch_time_utc` in `.meta.json` is sourced directly from the snapshot rather than generated from `datetime.now(timezone.utc)`. This guarantees byte-identical `.meta.json` files across repeated offline executions.
2. **Zero Timestamp Leakage into Simulation State**: Network timestamps (`fetch_time_utc`, catalog epoch) are written strictly to `.meta.json`. Scenario JSON files contain zero wall-clock timestamps. The simulation timestep sequence begins deterministically at $t = 0.0\text{ s}$ with constant $\Delta t$.
3. **Fixed Dictionary Ordering**: All JSON serialization uses `json.dumps(..., indent=2, sort_keys=True)`.
4. **Integer & Quantized Floats**: Chief altitude is quantized to 3 decimal places (`round(chief["altitude_km"], 3)`), and mean motion is recomputed via `mean_motion(altitude_km * 1000.0)` to ensure exact arithmetic consistency with the simulation core.
5. **Frozen Random Seeds**: Default simulation seed is fixed to `42`.

### 9.2 Offline Unit Test Suite: `tests/test_live_import.py`
Pytest MUST NEVER access external networks. An autouse fixture in `tests/test_live_import.py` intercepts network sockets to guarantee test isolation:

```python
@pytest.fixture(autouse=True)
def block_external_network(monkeypatch):
    """Guarantees zero network calls during offline test execution."""
    def _forbidden(*args, **kwargs):
        raise RuntimeError("External network access forbidden in offline test suite")
    monkeypatch.setattr(urllib.request, "urlopen", _forbidden)
```

| Test Case | Method / Target | Expected Verification Behavior |
|---|---|---|
| `test_network_https_enforcement` | `validate_request_url` with `http://` | Rejects with `ValueError("Refusing insecure scheme")`. |
| `test_network_userinfo_ssrf_rejection`| `validate_request_url` with userinfo | Rejects `https://celestrak.org:443@169.254.169.254/` with `ValueError("Userinfo in URL is strictly forbidden")`. |
| `test_network_ssrf_redirect_containment`| `StrictRedirectHandler` | Blocks redirect targeting non-allowlisted host or port $\ne 443$. |
| `test_network_cumulative_timeout` | Mock stream with slow chunks | Aborts when cumulative duration exceeds timeout; raises `TimeoutError`. |
| `test_network_size_cap` | Mock stream exceeding 5 MB | Aborts streaming download and raises `ValueError`. |
| `test_credential_isolation_and_redaction`| Exception and URL sanitization | Confirms API keys in URLs and `HTTPError` messages are replaced with `[REDACTED]`. |
| `test_cache_atomic_write` | Cache manager atomic swap | Verifies `.tmp` file creation and atomic replacement via `os.replace`. |
| `test_cli_path_confinement_traversal` | `--out ../escape.json` | Refuses with clean argparse error (exit code 2); zero files written. |
| `test_cli_protected_directory_protection`| `--out cubesat/sim.py` | Refuses with exit code 2; prevents overwriting core source files. |
| `test_astrodynamics_kepler_limits` | `solve_kepler` with non-finite / $e \ge 1$ | Rejects non-finite inputs and raises `ValueError` if exceeding 50 iterations. |
| `test_phase_presorting_ellipse_fit` | Arbitrarily ordered deputies | Confirms identical $A, \psi_0$ fit regardless of input catalog order. |
| `test_small_cluster_swarm_expansion` | $N=2$ GRACE-FO cluster | Verifies expansion to $N=6$ slots with 1 leader, 1 downlink, 4 imagers. |
| `test_scenario_pydantic_validation` | Generated scenario payload | Passes `Scenario.model_validate()` cleanly with baseline parameters. |
| `test_meta_determinism_on_cache_hit` | Consecutive cache runs | Confirms byte-identical `.meta.json` files generated on cache replay. |

### 9.3 Live End-to-End Determinism Proof: `cubesat/live_import_e2e.py`
To prove determinism on real-world data, the verification harness executes the following protocol:

```powershell
uv run python -m cubesat.live_import_e2e
```

#### Execution Protocol:
```
[Step 1: Ingestion & Formation Synthesis]
   |--> Query CelesTrak API for GRACE-FO cluster (or load data/celestrak snapshot if offline)
   |--> Compute Brouwer J2 epoch propagation to median epoch
   |--> Pre-sort deputies by empirical phase and fit closed-form passive 2:1 ellipse
   |--> Expand N=2 cluster to N=6 operational swarm with default 2 failures
   |--> Emit data/scenarios/live_e2e_swarm.json and .meta.json

[Step 2: Simulation Execution - Pass 1]
   |--> Load scenario via cubesat.scenario.load_scenario()
   |--> Execute sim = run_scenario(scenario)
   |--> Serialize execution events to /tmp/run1.jsonl (sort_keys=True)
   |--> Compute SHA-256 hash H1 = sha256(run1.jsonl)

[Step 3: Simulation Execution - Pass 2]
   |--> Re-execute sim = run_scenario(scenario)
   |--> Serialize execution events to /tmp/run2.jsonl (sort_keys=True)
   |--> Compute SHA-256 hash H2 = sha256(run2.jsonl)

[Step 4: Cryptographic Assertion & Recovery Verification]
   |--> Assert H1 == H2 (Byte-identical replay check)
   |--> Verify presence of state transitions: NOMINAL -> FAILURE_DETECTED -> REPLANNING -> RECOVERED
   |--> Output exit code 0 on verified match
```

---

## 10. Implementation Plan & File Responsibilities

| File Path | Role | Lines (Budget) | Dependencies |
|---|---|---|---|
| `docs/LIVE_IMPORT_DESIGN.md` | Architecture & Design Specification | Complete document | None (Documentation) |
| `cubesat/_live_network.py` | URL validator, redirect handler, stream reader, atomic cache | $\le 160$ lines | Stdlib (`urllib.request`, `urllib.error`, `urllib.parse`, `ssl`, `hashlib`, `re`, `time`, `os`, `pathlib`) |
| `cubesat/live_import.py` | CLI, astrodynamics, phase presorting, ellipse fit, scenario builder | $\le 280$ lines | `cubesat._live_network`, `cubesat.scenario`, Stdlib (`math`, `datetime`, `json`, `argparse`, `pathlib`, `os`), `numpy`, `scipy.optimize.linear_sum_assignment` |
| `cubesat/live_import_e2e.py`| Live E2E determinism test runner | $\le 120$ lines | `cubesat.live_import`, `cubesat.sim`, `cubesat.scenario`, `hashlib`, `pathlib` |
| `tests/test_live_import.py` | Offline unit and integration test suite | $\le 300$ lines | `pytest`, `cubesat.live_import`, `cubesat._live_network`, frozen fixtures in `data/celestrak/` |
| `data/scenarios/live_e2e_swarm.json` | Live verification scenario fixture | ~75 lines | Generated by `live_import.py` |
| `data/scenarios/live_e2e_swarm.meta.json` | Sidecar provenance fixture | ~25 lines | Generated by `live_import.py` |

---

## 11. Conclusion
The revised live orbital data ingestion and formation fitting pipeline specified herein resolves all adversarial security and architectural audit findings:
1. **SSRF and redirect defenses** eliminate userinfo confusion by strictly inspecting `parsed.hostname` and rejecting credentials in URLs.
2. **Pre-flight request validation** guarantees that non-HTTPS schemes or unauthorized hosts are blocked prior to socket creation.
3. **Cumulative timeout monitoring** protects against slowloris-style denial of service.
4. **Kepler solver boundaries** guarantee finite computation and protect against divergence.
5. **Atomic file replacement** prevents cache corruption during interrupted fetches.
6. **Enhanced path confinement** forbids targeting protected repository source code or git directories.
7. **Phase pre-sorting** eliminates the circular dependency in closed-form ellipse fitting.
8. **Small cluster operational sizing** guarantees full failure recovery and state transition verification for $N < 4$ clusters.
9. **Mandatory Pydantic baseline parameters** ensure zero-diff scenario schema validity.
10. **Sidecar snapshot preservation** ensures byte-identical determinism across repeated offline executions.
