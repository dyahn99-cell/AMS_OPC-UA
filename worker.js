const http = require("http");
const fs = require("fs");
const path = require("path");

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
  } catch (err) {
    console.log(`[worker] config read failed (${configPath}): ${err.message}`);
    return {};
  }
}

const config = loadConfig();

const PORT = parseInt(process.env.WORKER_PORT || "7100", 10);
const ENDPOINT = process.env.OPCUA_ENDPOINT || config.opcua_endpoint || "opc.tcp://192.168.0.1:4840";
const PASSWORD = process.env.AMS_PASSWORD || config.ams_password || "admin";
const READ_INTERVAL_MS = parseInt(process.env.OPCUA_READ_INTERVAL_MS || "5000", 10);
const READ_TIMEOUT_MS = parseInt(process.env.OPCUA_READ_TIMEOUT_MS || "4000", 10);
const READ_FAILURES_BEFORE_RECONNECT = parseInt(process.env.OPCUA_READ_FAILURES_BEFORE_RECONNECT || "3", 10);
const WRITE_TIMEOUT_MS = parseInt(process.env.OPCUA_WRITE_TIMEOUT_MS || "5000", 10);
const WRITE_CONNECT_WAIT_MS = parseInt(process.env.OPCUA_WRITE_CONNECT_WAIT_MS || "4000", 10);
const AUTO_CONNECT_DELAY_MS = parseInt(process.env.OPCUA_AUTO_CONNECT_DELAY_MS || "5000", 10);

console.log(`[worker] boot endpoint=${ENDPOINT} port=${PORT}`);

process.on("uncaughtException", err => {
  console.log(`[worker] uncaughtException: ${err && err.stack ? err.stack : err}`);
});

process.on("unhandledRejection", err => {
  console.log(`[worker] unhandledRejection: ${err && err.stack ? err.stack : err}`);
});

// ── Node maps (must match bridge.py) ──────────────────────
function loadNodeMaps() {
  const nodesPath = process.env.AMS_NODES_PATH || path.join(__dirname, "nodes.json");
  try {
    const nodeConfig = JSON.parse(fs.readFileSync(nodesPath, "utf8"));
    const remotes = nodeConfig.remotes || {};
    const maps = {};
    for (const [remoteId, remoteConfig] of Object.entries(remotes)) {
      maps[remoteId] = Object.assign({}, remoteConfig.read || {});
    }
    console.log(`[worker] loaded node maps from ${nodesPath}: ${Object.keys(maps).join(", ") || "none"}`);
    return maps;
  } catch (err) {
    console.log(`[worker] nodes read failed (${nodesPath}): ${err.message}`);
    return {};
  }
}

const REMOTE_NODE_MAPS = loadNodeMaps();

// ── Connection state ───────────────────────────────────────
let client = null;
let session = null;
let connected = false;
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
  if (connecting || connected || connectionResetPromise) return;
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
  if (connected || connecting || connectionResetPromise) return;
  console.log(`[worker] connect trigger: ${reason}`);
  connect().catch(err => {
    console.log(`[worker] connect trigger failed (${reason}): ${err && err.stack ? err.stack : err}`);
  });
}

function scheduleReconnect(delay = 2000) {
  if (reconnectTimer) return;
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
  let goodCount = 0;
  let badCount = 0;
  keys.forEach((key, i) => {
    const dv = dataValues[i];
    const statusCode = dv && dv.statusCode;
    const statusText = statusCode ? statusCode.toString() : "NoStatus";
    const isGood = !!(statusCode && typeof statusCode.isGood === "function" && statusCode.isGood());
    statuses[key] = statusText;
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
    throw err;
  }

  return { values, statuses, good_count: goodCount, bad_count: badCount, read_latency_ms: latency };
}

async function readAllRemotes() {
  if (!connected || !session) return;

  for (const [remoteId, nodeMap] of Object.entries(REMOTE_NODE_MAPS)) {
    try {
      const { values, statuses, good_count, bad_count, read_latency_ms } = await readRemote(remoteId, nodeMap);
      readCache[remoteId] = {
        connected: true,
        values,
        node_status: statuses,
        good_count,
        bad_count,
        read_at: Date.now(),
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
        connected: withinGrace,   // grace 기간 중엔 connected 유지
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

async function writeNode(nodeId, value) {
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
  const byteValue = typeof value === "string" ? parseInt(value.replace(/^0x/i, ""), 16) : Number(value);
  if (!Number.isInteger(byteValue) || byteValue < 0 || byteValue > 255) {
    throw new Error("value must be a byte 0..255");
  }
  return byteValue;
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
    throw new Error("bytes must be an array");
  }
  if (bytes.length < 1 || bytes.length > 16) {
    throw new Error("bytes length must be 1..16");
  }
  return bytes.map((item, index) => {
    const value = typeof item === "string" ? parseInt(item.replace(/^0x/i, ""), 16) : Number(item);
    if (!Number.isInteger(value) || value < 0 || value > 255) {
      throw new Error(`invalid byte at index ${index}`);
    }
    return value;
  });
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
  const [dv] = await session.read([{ nodeId, attributeId: AttributeIds.Value }]);
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
function readBody(req) {
  return new Promise((resolve, reject) => {
    let buf = "";
    req.on("data", chunk => { buf += chunk; });
    req.on("end", () => {
      try { resolve(JSON.parse(buf)); } catch (e) { reject(e); }
    });
    req.on("error", reject);
  });
}

// ── HTTP server ────────────────────────────────────────────
const server = http.createServer(async (req, res) => {
  res.setHeader("Content-Type", "application/json");
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const { pathname } = url;

  try {
    // GET /status
    if (req.method === "GET" && pathname === "/status") {
      triggerConnect("status");
      res.end(JSON.stringify({
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

      if (!nodeId || value === undefined) {
        res.statusCode = 400;
        res.end(JSON.stringify({ ok: false, error: "nodeId and value required" }));
        return;
      }

      const boolValue =
        typeof value === "boolean" ? value
          : String(value).toLowerCase() === "true" || value === 1;

      const result = await writeNode(nodeId, boolValue);
      res.end(JSON.stringify(result));
      return;
    }

    // POST /write-bytes
    if (req.method === "POST" && pathname === "/write-bytes") {
      const body = await readBody(req);
      const { nodeId, bytes } = body;

      if (!nodeId || !Array.isArray(bytes)) {
        res.statusCode = 400;
        res.end(JSON.stringify({ ok: false, error: "nodeId and bytes[] required" }));
        return;
      }

      const result = await writeByteArray(nodeId, bytes);
      res.end(JSON.stringify(result));
      return;
    }

    // POST /read  — single node diagnostic read
    // POST /write-byte
    if (req.method === "POST" && pathname === "/write-byte") {
      const body = await readBody(req);
      const { nodeId, value } = body;

      if (!nodeId || value === undefined) {
        res.statusCode = 400;
        res.end(JSON.stringify({ ok: false, error: "nodeId and value required" }));
        return;
      }

      const result = await writeByte(nodeId, value);
      res.end(JSON.stringify(result));
      return;
    }

    if (req.method === "POST" && pathname === "/read") {
      const body = await readBody(req);
      const { nodeId } = body;
      if (!nodeId) {
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
    res.statusCode = 500;
    res.end(JSON.stringify({ ok: false, error: err.message || String(err) }));
  }
});

console.log("[worker] starting local HTTP server");
server.on("error", err => {
  if (err && err.code === "EADDRINUSE") {
    console.log(`[worker] port ${PORT} already in use; exiting`);
  } else {
    console.log(`[worker] server error: ${err && err.stack ? err.stack : err}`);
  }
  setTimeout(() => process.exit(1), 10);
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`[worker] listening on 127.0.0.1:${PORT}`);
  setTimeout(() => triggerConnect("startup"), AUTO_CONNECT_DELAY_MS);
});

// ── Graceful shutdown ──────────────────────────────────────
async function shutdown() {
  console.log("[worker] shutting down");
  await closeCurrentClient();
  process.exit(0);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
