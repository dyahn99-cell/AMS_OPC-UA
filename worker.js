const http = require("http");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

// Private Python-owned loopback protocol. Never print the token or put it in a URL.
const WORKER_PROTOCOL = "ams-worker-owner-v1";
function requiredOwnerValue(name, length) {
  const value = process.env[name];
  if (typeof value !== "string" || !new RegExp(`^[0-9a-f]{${length}}$`).test(value)) {
    throw new Error("worker ownership credentials missing or invalid");
  }
  return value;
}
const OWNER_TOKEN = requiredOwnerValue("AMS_WORKER_OWNER_TOKEN", 64);
const INSTANCE_ID = requiredOwnerValue("AMS_WORKER_INSTANCE_ID", 32);
const EXPECTED_FINGERPRINT = requiredOwnerValue("AMS_WORKER_FINGERPRINT", 64);

function sameSecret(actual, expected) {
  if (typeof actual !== "string" || actual.length !== expected.length) return false;
  const actualBytes = Buffer.from(actual, "utf8");
  const expectedBytes = Buffer.from(expected, "utf8");
  return actualBytes.length === expectedBytes.length && crypto.timingSafeEqual(actualBytes, expectedBytes);
}

// Match app.worker_owner.worker_fingerprint exactly, including byte lengths.
function workerFingerprint(nodesBytes, endpoint, password) {
  const endpointBytes = Buffer.from(endpoint, "utf8");
  const framed = bytes => {
    const length = Buffer.alloc(8);
    length.writeBigUInt64BE(BigInt(bytes.length));
    return [length, bytes];
  };
  return crypto.createHash("sha256").update(Buffer.concat([
    Buffer.from(`${WORKER_PROTOCOL}\0`, "ascii"),
    ...framed(nodesBytes),
    ...framed(endpointBytes),
    crypto.createHash("sha256").update(password, "utf8").digest(),
  ])).digest("hex");
}

let OPCUAClient = null;
let MessageSecurityMode = null;
let SecurityPolicy = null;
let DataType = null;
let AttributeIds = null;
let Variant = null;
let VariantArrayType = null;

function loadOpcua() {
  if (OPCUAClient) return;
  ({
    OPCUAClient,
    MessageSecurityMode,
    SecurityPolicy,
    DataType,
    AttributeIds,
    Variant,
    VariantArrayType,
  } = require("node-opcua"));
}

function loadConfig() {
  const configPath = process.env.AMS_CONFIG_PATH || path.join(__dirname, "config.json");
  try {
    return JSON.parse(fs.readFileSync(configPath, "utf8"));
  } catch (_) {
    throw new Error("worker config could not be loaded");
  }
}

const config = loadConfig();

const portText = process.env.WORKER_PORT || "7100";
if (!/^[1-9][0-9]{0,4}$/.test(portText) || Number(portText) > 65535) {
  throw new Error("worker port must be an integer 1..65535");
}
const PORT = Number(portText);
const ENDPOINT = process.env.OPCUA_ENDPOINT ?? config.opcua_endpoint ?? "opc.tcp://192.168.0.1:4840";
const PASSWORD = process.env.AMS_PASSWORD ?? config.ams_password ?? "admin";
if (typeof ENDPOINT !== "string" || !ENDPOINT || typeof PASSWORD !== "string") {
  throw new Error("worker endpoint or password invalid");
}
const READ_INTERVAL_MS = parseInt(process.env.OPCUA_READ_INTERVAL_MS || "5000", 10);
const READ_TIMEOUT_MS = parseInt(process.env.OPCUA_READ_TIMEOUT_MS || "4000", 10);
const READ_FAILURES_BEFORE_RECONNECT = parseInt(process.env.OPCUA_READ_FAILURES_BEFORE_RECONNECT || "3", 10);
const WRITE_TIMEOUT_MS = parseInt(process.env.OPCUA_WRITE_TIMEOUT_MS || "5000", 10);
const WRITE_CONNECT_WAIT_MS = parseInt(process.env.OPCUA_WRITE_CONNECT_WAIT_MS || "4000", 10);
const AUTO_CONNECT_DELAY_MS = parseInt(process.env.OPCUA_AUTO_CONNECT_DELAY_MS || "5000", 10);

// ── Node maps (must match bridge.py) ──────────────────────
function loadNodeMaps() {
  const nodesPath = process.env.AMS_NODES_PATH || path.join(__dirname, "nodes.json");
  try {
    const nodesBytes = fs.readFileSync(nodesPath);
    const nodeConfig = JSON.parse(nodesBytes.toString("utf8"));
    if (!nodeConfig || typeof nodeConfig !== "object" || Array.isArray(nodeConfig)) {
      throw new Error("invalid node map");
    }
    const fingerprint = workerFingerprint(nodesBytes, ENDPOINT, PASSWORD);
    if (!sameSecret(fingerprint, EXPECTED_FINGERPRINT)) {
      throw new Error("worker fingerprint mismatch");
    }
    const remotes = nodeConfig.remotes || {};
    const maps = {};
    for (const [remoteId, remoteConfig] of Object.entries(remotes)) {
      maps[remoteId] = Object.assign({}, remoteConfig.read || {});
    }
    console.log(`[worker] loaded node maps from ${nodesPath}: ${Object.keys(maps).join(", ") || "none"}`);
    return { maps, fingerprint };
  } catch (_) {
    // JSON parse errors may include source text; do not leak config/credentials.
    throw new Error("worker node inputs invalid or fingerprint mismatch");
  }
}

const { maps: REMOTE_NODE_MAPS, fingerprint: FINGERPRINT } = loadNodeMaps();
console.log(`[worker] boot endpoint=${ENDPOINT} port=${PORT}`);

process.on("uncaughtException", err => {
  console.log(`[worker] uncaughtException: ${err && err.stack ? err.stack : err}`);
});

process.on("unhandledRejection", err => {
  console.log(`[worker] unhandledRejection: ${err && err.stack ? err.stack : err}`);
});

// ── Connection state ───────────────────────────────────────
let client = null;
let session = null;
let connected = false;
let connectionGeneration = 0;
let sampleSequence = 0;
let connecting = false;
let connectionResetPromise = null;
let lastError = null;
let lastConnectAt = null;
let reconnectTimer = null;
let readLoopTimer = null;
let writeCount = 0;
let writeErrorCount = 0;
let readLoopBusy = false;
let writePending = 0;
let refreshQueued = false;
let serverListening = false;
let shuttingDown = false;
let startupTimer = null;

async function closeCurrentClient() {
  stopReadLoop();
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  const oldSession = session;
  const oldClient = client;
  session = null;
  client = null;
  connected = false;
  for (const cache of Object.values(readCache)) {
    cache.connected = false;
    cache.stale = true;
    cache.last_error = "connection_closed";
  }
  try { if (oldSession) await withTimeout(oldSession.close(), 2000, "session_close_timeout"); } catch (_) {}
  try { if (oldClient) await withTimeout(oldClient.disconnect(), 2000, "client_disconnect_timeout"); } catch (_) {}
}

function resetConnection(reason) {
  if (connectionResetPromise) return connectionResetPromise;
  connectionResetPromise = (async () => {
    console.log(`[worker] resetting connection: ${reason}`);
    await closeCurrentClient();
    scheduleReconnect();
  })().finally(() => {
    connectionResetPromise = null;
  });
  return connectionResetPromise;
}

const STALE_GRACE_MS = 10000; // 연속 실패해도 이 시간 안에는 이전 값 유지

// Per-remote read cache: remoteId → { connected, values, read_at, read_latency_ms, last_error, stale }
const readCache = {};
const readFailCount = {}; // remoteId → 연속 실패 횟수

// ── Connection ─────────────────────────────────────────────
async function connect() {
  if (!serverListening || shuttingDown || connecting || connected || connectionResetPromise) return;
  connecting = true;
  lastError = null;
  console.log(`[worker] connect start -> ${ENDPOINT}`);

  try {
    loadOpcua();
    if (client || session) {
      await closeCurrentClient();
    }
    client = OPCUAClient.create({
      endpointMustExist: false,
      securityMode: MessageSecurityMode.None,
      securityPolicy: SecurityPolicy.None,
      connectionStrategy: { initialDelay: 100, maxRetry: 3, maxDelay: 2000 },
      requestedSessionTimeout: 60000,
    });

    const thisClient = client;
    client.on("connection_lost", () => {
      if (client !== thisClient) return;
      console.log("[worker] connection lost — scheduling reconnect");
      resetConnection("connection_lost").catch(err => {
        console.log(`[worker] connection reset failed: ${err && err.stack ? err.stack : err}`);
      });
    });

    await client.connect(ENDPOINT);

    try {
      session = await client.createSession();
    } catch (err) {
      if (String(err.message || err).toLowerCase().includes("anonymous")) {
        session = await client.createSession({ userName: "admin", password: PASSWORD });
      } else {
        throw err;
      }
    }

    connected = true;
    connectionGeneration++;
    lastConnectAt = new Date().toISOString();
    console.log(`[worker] connected to ${ENDPOINT}`);
    startReadLoop();
  } catch (err) {
    connected = false;
    session = null;
    lastError = err.message || String(err);
    console.log(`[worker] connection failed: ${lastError}`);
    scheduleReconnect();
  } finally {
    connecting = false;
  }
}

function triggerConnect(reason) {
  if (!serverListening || shuttingDown || connected || connecting || connectionResetPromise) return;
  console.log(`[worker] connect trigger: ${reason}`);
  connect().catch(err => {
    console.log(`[worker] connect trigger failed (${reason}): ${err && err.stack ? err.stack : err}`);
  });
}

function scheduleReconnect(delay = 2000) {
  if (!serverListening || shuttingDown || reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    triggerConnect("reconnect");
  }, delay);
}

// ── Read loop ──────────────────────────────────────────────
function startReadLoop() {
  stopReadLoop();
  // immediate first read
  runReadCycle().catch(() => {});
  readLoopTimer = setInterval(() => {
    if (connected && session) {
      runReadCycle().catch(err => {
        console.log(`[worker] read loop error: ${err.message}`);
      });
    }
  }, READ_INTERVAL_MS);
}

function stopReadLoop() {
  if (readLoopTimer) {
    clearInterval(readLoopTimer);
    readLoopTimer = null;
  }
}

// After a write succeeds, the physical value just changed but readCache
// still holds the pre-write snapshot until the next periodic read cycle
// (READ_INTERVAL_MS, default 5s) - and that cycle is itself skipped
// entirely whenever writePending > 0. Callers (the Python hub, and the
// dashboard's UI-pending guards) assume a fresh read shows up soon after
// a write resolves, so ask for one right away instead of waiting on the
// timer. Coalesced (refreshQueued) so back-to-back writes only queue one
// extra read, and it waits for the normal readLoopBusy/writePending gate
// to clear on its own rather than forcing a read concurrently with any
// still-in-flight session I/O.
async function requestImmediateRefresh(reason) {
  if (refreshQueued) return;
  refreshQueued = true;
  try {
    const waitStart = Date.now();
    while ((readLoopBusy || writePending > 0) && Date.now() - waitStart < 3000) {
      await sleep(25);
    }
    if (connected && session && !readLoopBusy) {
      await runReadCycle();
    }
  } catch (err) {
    console.log(`[worker] immediate refresh (${reason}) failed: ${err.message}`);
  } finally {
    refreshQueued = false;
  }
}

function withTimeout(promise, timeoutMs, label) {
  let timer = null;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(label || "timeout")), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => {
    if (timer) clearTimeout(timer);
  });
}

async function readRemote(remoteId, nodeMap) {
  const keys = Object.keys(nodeMap);
  const nodesToRead = keys.map(key => ({
    nodeId: nodeMap[key],
    attributeId: AttributeIds.Value,
  }));

  const t0 = Date.now();
  const dataValues = await withTimeout(session.read(nodesToRead), READ_TIMEOUT_MS, "read_timeout");
  const latency = Date.now() - t0;

  const values = {};
  const statuses = {};
  const source_timestamps = {};
  let goodCount = 0;
  let badCount = 0;
  keys.forEach((key, i) => {
    const dv = dataValues[i];
    const statusCode = dv && dv.statusCode;
    const statusText = statusCode ? statusCode.toString() : "NoStatus";
    const isGood = !!(statusCode && typeof statusCode.isGood === "function" && statusCode.isGood());
    statuses[key] = statusText;
    const sourceTime = dv && dv.sourceTimestamp;
    const sourceMs = sourceTime == null ? NaN : new Date(sourceTime).getTime();
    source_timestamps[key] = Number.isFinite(sourceMs) ? new Date(sourceMs).toISOString() : null;
    if (!isGood) {
      badCount++;
      values[key] = null;
      return;
    }
    goodCount++;
    values[key] = dv && dv.value != null ? dv.value.value : null;
  });

  if (goodCount === 0) {
    const err = new Error(`all_nodes_bad:${Object.values(statuses).slice(0, 3).join(",")}`);
    err.statuses = statuses;
    err.source_timestamps = source_timestamps;
    throw err;
  }

  return { values, statuses, source_timestamps, good_count: goodCount, bad_count: badCount, read_latency_ms: latency };
}

async function readAllRemotesSequential() {
  if (!connected || !session) return;

  for (const [remoteId, nodeMap] of Object.entries(REMOTE_NODE_MAPS)) {
    try {
      const { values, statuses, source_timestamps, good_count, bad_count, read_latency_ms } = await readRemote(remoteId, nodeMap);
      readCache[remoteId] = {
        connected: true,
        values,
        node_status: statuses,
        source_timestamps,
        good_count,
        bad_count,
        read_at: Date.now(),
        sample_id: `${INSTANCE_ID}:${connectionGeneration}:${++sampleSequence}`,
        connection_generation: connectionGeneration,
        read_latency_ms,
        last_error: null,
        stale: false,
      };
      readFailCount[remoteId] = 0;
    } catch (err) {
      const existing = readCache[remoteId];
      readFailCount[remoteId] = (readFailCount[remoteId] || 0) + 1;
      const withinGrace = existing && existing.read_at && (Date.now() - existing.read_at) < STALE_GRACE_MS;
      readCache[remoteId] = {
        ...existing,
        node_status: err.statuses || (existing && existing.node_status) || {},
        source_timestamps: err.source_timestamps || (existing && existing.source_timestamps) || {},
        connected: false,
        values: existing ? existing.values : null,
        read_at: existing ? existing.read_at : null,
        read_latency_ms: null,
        last_error: err.message || String(err),
        stale: true,
      };
      // Transport error → reconnect
      const msg = err.message || String(err);
      if (/transport|connection|timeout|eof|reset|refused/i.test(msg)) {
        const failures = readFailCount[remoteId];
        console.log(`[worker] transport error on ${remoteId}: ${msg} (failure ${failures}/${READ_FAILURES_BEFORE_RECONNECT})`);
        if (failures >= READ_FAILURES_BEFORE_RECONNECT) {
          await resetConnection(`transport error on ${remoteId}: ${msg}`);
          break;
        }
      }
    }
  }
}

// ── Write ──────────────────────────────────────────────────
async function readAllRemotes() {
  if (!connected || !session) return;
  const entries = Object.entries(REMOTE_NODE_MAPS);
  const results = await Promise.all(entries.map(async ([remoteId, nodeMap]) => {
    try {
      return { remoteId, ok: true, data: await readRemote(remoteId, nodeMap) };
    } catch (error) {
      return { remoteId, ok: false, error };
    }
  }));

  let reconnectReason = null;
  for (const result of results) {
    const { remoteId } = result;
    if (result.ok) {
      const { values, statuses, source_timestamps, good_count, bad_count, read_latency_ms } = result.data;
      readCache[remoteId] = {
        connected: true,
        values,
        node_status: statuses,
        source_timestamps,
        good_count,
        bad_count,
        read_at: Date.now(),
        sample_id: `${INSTANCE_ID}:${connectionGeneration}:${++sampleSequence}`,
        connection_generation: connectionGeneration,
        read_latency_ms,
        last_error: null,
        stale: false,
      };
      readFailCount[remoteId] = 0;
      continue;
    }

    const err = result.error;
    const existing = readCache[remoteId];
    readFailCount[remoteId] = (readFailCount[remoteId] || 0) + 1;
    const withinGrace = existing && existing.read_at && (Date.now() - existing.read_at) < STALE_GRACE_MS;
    readCache[remoteId] = {
      ...existing,
      node_status: err.statuses || (existing && existing.node_status) || {},
      source_timestamps: err.source_timestamps || (existing && existing.source_timestamps) || {},
      connected: false,
      values: existing ? existing.values : null,
      read_at: existing ? existing.read_at : null,
      read_latency_ms: null,
      last_error: err.message || String(err),
      stale: true,
    };
    const msg = err.message || String(err);
    if (/transport|connection|timeout|eof|reset|refused/i.test(msg)) {
      const failures = readFailCount[remoteId];
      console.log(`[worker] transport error on ${remoteId}: ${msg} (failure ${failures}/${READ_FAILURES_BEFORE_RECONNECT})`);
      if (!reconnectReason && failures >= READ_FAILURES_BEFORE_RECONNECT) {
        reconnectReason = `transport error on ${remoteId}: ${msg}`;
      }
    }
  }
  if (reconnectReason) await resetConnection(reconnectReason);
}

async function runReadCycle() {
  if (readLoopBusy || writePending > 0) return;
  readLoopBusy = true;
  try {
    await readAllRemotes();
  } finally {
    readLoopBusy = false;
  }
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function ensureConnectedForWrite() {
  if (!serverListening || shuttingDown) throw new Error("worker_not_accepting_requests");
  if (connected && session) return;
  if (!connecting) {
    connect().catch(() => {});
  }
  const t0 = Date.now();
  while (!(connected && session) && Date.now() - t0 < WRITE_CONNECT_WAIT_MS) {
    await sleep(50);
  }
  if (!(connected && session)) {
    throw new Error(connecting ? "connect_timeout" : "not_connected");
  }
}

function invalidInput(message) {
  return Object.assign(new Error(message), { statusCode: 400 });
}

function normalizeBoolean(value) {
  if (typeof value !== "boolean") throw invalidInput("value must be a boolean");
  return value;
}

async function writeNode(nodeId, value) {
  normalizeBoolean(value);
  await ensureConnectedForWrite();
  writePending++;
  const waitStart = Date.now();
  while (readLoopBusy && Date.now() - waitStart < 2500) {
    await sleep(25);
  }
  const queue_wait_ms = Date.now() - waitStart;
  const t0 = Date.now();
  try {
    const statusCode = await withTimeout(session.write({
      nodeId,
      attributeId: AttributeIds.Value,
      value: { value: new Variant({ dataType: DataType.Boolean, value }) },
    }), WRITE_TIMEOUT_MS, "write_timeout");
    const elapsed_ms = Date.now() - t0;
    if (statusCode.isNotGood()) {
      throw new Error(statusCode.toString());
    }
    writeCount++;
    return { ok: true, nodeId, value, statusCode: statusCode.toString(), elapsed_ms, queue_wait_ms };
  } finally {
    writePending--;
  }
}

function normalizeByte(value) {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0 || value > 255) {
    throw invalidInput("value must be a numeric byte 0..255");
  }
  return value;
}

async function writeByte(nodeId, value) {
  const byteValue = normalizeByte(value);
  await ensureConnectedForWrite();
  writePending++;
  const waitStart = Date.now();
  while (readLoopBusy && Date.now() - waitStart < 2500) {
    await sleep(25);
  }
  const queue_wait_ms = Date.now() - waitStart;
  const t0 = Date.now();
  try {
    const statusCode = await withTimeout(session.write({
      nodeId,
      attributeId: AttributeIds.Value,
      value: { value: new Variant({ dataType: DataType.Byte, value: byteValue }) },
    }), WRITE_TIMEOUT_MS, "write_timeout");
    const elapsed_ms = Date.now() - t0;
    if (statusCode.isNotGood()) {
      throw new Error(statusCode.toString());
    }
    writeCount++;
    return { ok: true, nodeId, value: byteValue, statusCode: statusCode.toString(), elapsed_ms, queue_wait_ms };
  } finally {
    writePending--;
  }
}

function normalizeBytes(bytes) {
  if (!Array.isArray(bytes)) {
    throw invalidInput("bytes must be an array");
  }
  if (bytes.length < 1 || bytes.length > 16) {
    throw invalidInput("bytes length must be 1..16");
  }
  return bytes.map(normalizeByte);
}

async function writeByteArray(nodeId, bytes) {
  const byteValues = normalizeBytes(bytes);
  await ensureConnectedForWrite();
  writePending++;
  const waitStart = Date.now();
  while (readLoopBusy && Date.now() - waitStart < 2500) {
    await sleep(25);
  }
  const queue_wait_ms = Date.now() - waitStart;
  const t0 = Date.now();
  try {
    const statusCode = await withTimeout(session.write({
      nodeId,
      attributeId: AttributeIds.Value,
      value: {
        value: new Variant({
          dataType: DataType.Byte,
          arrayType: VariantArrayType.Array,
          value: byteValues,
        }),
      },
    }), WRITE_TIMEOUT_MS, "write_timeout");
    const elapsed_ms = Date.now() - t0;
    if (statusCode.isNotGood()) {
      throw new Error(statusCode.toString());
    }
    writeCount++;
    return {
      ok: true,
      nodeId,
      bytes: byteValues,
      statusCode: statusCode.toString(),
      elapsed_ms,
      queue_wait_ms,
    };
  } finally {
    writePending--;
  }
}

// ── Single-node read (for diagnostics) ────────────────────
async function readSingleNode(nodeId) {
  if (!connected || !session) {
    throw new Error("not_connected");
  }
  const t0 = Date.now();
  const [dv] = await withTimeout(
    session.read([{ nodeId, attributeId: AttributeIds.Value }]),
    READ_TIMEOUT_MS,
    "read_timeout",
  );
  const elapsed_ms = Date.now() - t0;
  const statusCode = dv && dv.statusCode;
  const statusText = statusCode ? statusCode.toString() : "NoStatus";
  const isGood = !!(statusCode && typeof statusCode.isGood === "function" && statusCode.isGood());
  if (!isGood) {
    return { ok: false, nodeId, statusCode: statusText, error: statusText, elapsed_ms };
  }
  const value = dv && dv.value != null ? dv.value.value : null;
  return { ok: true, nodeId, value, value_type: typeof value, statusCode: statusText, elapsed_ms };
}

// ── HTTP helpers ───────────────────────────────────────────
function authorizedRequest(req) {
  const headers = req.headers || {};
  if (Object.prototype.hasOwnProperty.call(headers, "origin")) return false;
  if (headers.host !== `127.0.0.1:${PORT}`) return false;
  // Reject duplicate identity/authority headers rather than relying on Node's
  // joining/discarding rules. Browser preflights are never granted CORS access.
  const singletonHeaders = new Set([
    "host", "x-ams-worker-token", "x-ams-worker-instance", "x-ams-worker-fingerprint",
  ]);
  const seen = new Set();
  for (let i = 0; i < (req.rawHeaders || []).length; i += 2) {
    const name = req.rawHeaders[i].toLowerCase();
    if (name === "origin") return false;
    if (!singletonHeaders.has(name)) continue;
    if (seen.has(name)) return false;
    seen.add(name);
  }
  return sameSecret(headers["x-ams-worker-token"], OWNER_TOKEN)
    && sameSecret(headers["x-ams-worker-instance"], INSTANCE_ID)
    && sameSecret(headers["x-ams-worker-fingerprint"], FINGERPRINT);
}

function rejectRequest(res, status, error) {
  res.statusCode = status;
  res.setHeader("Connection", "close");
  res.end(JSON.stringify({ ok: false, error }));
}

function validNodeId(nodeId) {
  return typeof nodeId === "string" && nodeId.trim().length > 0;
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let buf = "";
    req.on("data", chunk => {
      buf += chunk;
      if (buf.length > 65536) {
        reject(new Error("request_body_too_large"));
        req.destroy();
      }
    });
    req.on("end", () => {
      try {
        const body = JSON.parse(buf);
        if (!body || typeof body !== "object" || Array.isArray(body)) {
          throw invalidInput("request body must be a JSON object");
        }
        resolve(body);
      } catch (_) {
        reject(invalidInput("invalid JSON object body"));
      }
    });
    req.on("error", reject);
  });
}

// ── HTTP server ────────────────────────────────────────────
const server = http.createServer(async (req, res) => {
  res.setHeader("Content-Type", "application/json");
  res.setHeader("Cache-Control", "no-store");
  // No route, body read, connection or shutdown may precede these checks.
  if (!authorizedRequest(req)) {
    rejectRequest(res, 403, "worker_request_forbidden");
    return;
  }
  if (!serverListening || shuttingDown) {
    rejectRequest(res, 503, "worker_not_accepting_requests");
    return;
  }
  // The private client uses origin-form paths only; no query-token alternative.
  if (typeof req.url !== "string" || !/^\/[A-Za-z0-9_/-]*$/.test(req.url)) {
    rejectRequest(res, 400, "invalid_request_target");
    return;
  }
  const pathname = req.url;

  try {
    // GET /status is passive, including the first readiness probe after spawn.
    if (req.method === "GET" && pathname === "/status") {
      res.end(JSON.stringify({
        worker_protocol: WORKER_PROTOCOL,
        worker_instance_id: INSTANCE_ID,
        worker_fingerprint: FINGERPRINT,
        pid: process.pid,
        connected,
        connecting,
        endpoint: ENDPOINT,
        last_connect_at: lastConnectAt,
        last_error: lastError,
        read_interval_ms: READ_INTERVAL_MS,
        read_timeout_ms: READ_TIMEOUT_MS,
        read_failures_before_reconnect: READ_FAILURES_BEFORE_RECONNECT,
        write_timeout_ms: WRITE_TIMEOUT_MS,
        write_connect_wait_ms: WRITE_CONNECT_WAIT_MS,
        auto_connect_delay_ms: AUTO_CONNECT_DELAY_MS,
        node_remotes: Object.keys(REMOTE_NODE_MAPS),
        read_busy: readLoopBusy,
        write_pending: writePending,
        write_count: writeCount,
        write_error_count: writeErrorCount,
        remotes: Object.fromEntries(
          Object.entries(readCache).map(([id, c]) => [id, {
            connected: c.connected,
            read_at: c.read_at,
            read_latency_ms: c.read_latency_ms,
            last_error: c.last_error,
            stale: c.stale,
          }])
        ),
      }));
      return;
    }

    // GET /data  — all remotes, with raw values
    if (req.method === "GET" && pathname === "/data") {
      triggerConnect("data");
      res.end(JSON.stringify({ ok: true, connected, remotes: readCache }));
      return;
    }

    // GET /data/:remoteId
    if (req.method === "GET" && pathname.startsWith("/data/")) {
      const remoteId = pathname.slice(6).toUpperCase();
      const cache = readCache[remoteId];
      if (!cache) {
        res.statusCode = 404;
        res.end(JSON.stringify({ ok: false, error: `remote ${remoteId} not found` }));
        return;
      }
      res.end(JSON.stringify({ ok: true, remote_id: remoteId, ...cache }));
      return;
    }

    // POST /write
    if (req.method === "POST" && pathname === "/write") {
      const body = await readBody(req);
      const { nodeId, value } = body;

      if (!validNodeId(nodeId) || value === undefined) {
        res.statusCode = 400;
        res.end(JSON.stringify({ ok: false, error: "nodeId and value required" }));
        return;
      }

      const result = await writeNode(nodeId, normalizeBoolean(value));
      requestImmediateRefresh("write").catch(() => {});
      res.end(JSON.stringify(result));
      return;
    }

    // POST /write-bytes
    if (req.method === "POST" && pathname === "/write-bytes") {
      const body = await readBody(req);
      const { nodeId, bytes } = body;

      if (!validNodeId(nodeId) || !Array.isArray(bytes)) {
        res.statusCode = 400;
        res.end(JSON.stringify({ ok: false, error: "nodeId and bytes[] required" }));
        return;
      }

      const result = await writeByteArray(nodeId, bytes);
      requestImmediateRefresh("write-bytes").catch(() => {});
      res.end(JSON.stringify(result));
      return;
    }

    // POST /read  — single node diagnostic read
    // POST /write-byte
    if (req.method === "POST" && pathname === "/write-byte") {
      const body = await readBody(req);
      const { nodeId, value } = body;

      if (!validNodeId(nodeId) || value === undefined) {
        res.statusCode = 400;
        res.end(JSON.stringify({ ok: false, error: "nodeId and value required" }));
        return;
      }

      const result = await writeByte(nodeId, value);
      requestImmediateRefresh("write-byte").catch(() => {});
      res.end(JSON.stringify(result));
      return;
    }

    if (req.method === "POST" && pathname === "/read") {
      const body = await readBody(req);
      const { nodeId } = body;
      if (!validNodeId(nodeId)) {
        res.statusCode = 400;
        res.end(JSON.stringify({ ok: false, error: "nodeId required" }));
        return;
      }
      const result = await readSingleNode(nodeId);
      res.end(JSON.stringify(result));
      return;
    }

    // POST /shutdown — graceful worker shutdown before Python exits
    if (req.method === "POST" && pathname === "/shutdown") {
      res.end(JSON.stringify({ ok: true, shutting_down: true }));
      setTimeout(() => shutdown().catch(() => process.exit(0)), 10);
      return;
    }

    res.statusCode = 404;
    res.end(JSON.stringify({ error: "not found" }));
  } catch (err) {
    if (pathname === "/write") writeErrorCount++;
    res.statusCode = err.statusCode === 400 ? 400 : 500;
    res.end(JSON.stringify({ ok: false, error: err.message || String(err) }));
  }
});

console.log("[worker] starting local HTTP server");
server.on("error", err => {
  serverListening = false;
  shuttingDown = true;
  if (startupTimer) clearTimeout(startupTimer);
  if (reconnectTimer) clearTimeout(reconnectTimer);
  stopReadLoop();
  if (err && err.code === "EADDRINUSE") {
    console.log(`[worker] port ${PORT} already in use; exiting`);
  } else {
    console.log(`[worker] server error: ${err && err.stack ? err.stack : err}`);
  }
  setTimeout(() => process.exit(1), 10);
});

server.listen(PORT, "127.0.0.1", () => {
  if (shuttingDown) return;
  serverListening = true;
  console.log(`[worker] listening on 127.0.0.1:${PORT}`);
  startupTimer = setTimeout(() => {
    startupTimer = null;
    triggerConnect("startup");
  }, AUTO_CONNECT_DELAY_MS);
});

// ── Graceful shutdown ──────────────────────────────────────
async function shutdown() {
  shuttingDown = true;
  serverListening = false;
  if (startupTimer) {
    clearTimeout(startupTimer);
    startupTimer = null;
  }
  server.close();
  console.log("[worker] shutting down");
  await closeCurrentClient();
  process.exit(0);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
