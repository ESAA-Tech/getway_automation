/**
 * Four-Faith Gateway Provisioning Station UI Logic
 */

let currentGatewayIp = "192.168.4.1";
let isRunning = false;

// DOM Elements
const elGatewaySelect = document.getElementById("gateway-select");
const elStatusIndicator = document.getElementById("status-indicator");
const elStatusText = document.getElementById("status-text");

// Inputs
const inpScreenIp = document.getElementById("inp-screen-ip");
const inpCloudId = document.getElementById("inp-cloud-id");
const inpClientPrefix = document.getElementById("inp-client-prefix");
const inpBrokerUrl = document.getElementById("inp-broker-url");
const inpBrokerPort = document.getElementById("inp-broker-port");
const inpMqttUser = document.getElementById("inp-mqtt-user");
const inpMqttPass = document.getElementById("inp-mqtt-pass");
const inpPoleId = document.getElementById("inp-pole-id");
const inpSiteId = document.getElementById("inp-site-id");
const selScriptSource = document.getElementById("sel-script-source");

// Previews
const topicEnv = document.getElementById("topic-env");
const topicCamera = document.getElementById("topic-camera");
const topicScreen = document.getElementById("topic-screen");
const topicLamp = document.getElementById("topic-lamp");
const previewUpNames = document.getElementById("preview-up-names");
const previewDownNames = document.getElementById("preview-down-names");
const badgeScriptCount = document.getElementById("badge-script-count");
const previewClientIdBadge = document.getElementById("preview-clientid-badge");

// Action & Log Elements
const btnWriteSingle = document.getElementById("btn-write-single");
const btnWriteAll = document.getElementById("btn-write-all");
const terminalBody = document.getElementById("terminal-body");
const logStatusBadge = document.getElementById("log-status-badge");
const toastContainer = document.getElementById("toast-container");

// Initialize on Load
document.addEventListener("DOMContentLoaded", async () => {
  log("Provisioning Station initialized.", "info");
  await loadGateways();
  setupEventListeners();
  updateTopicPreviews();
  checkGatewayStatus();
});

const inpCustomGwIp = document.getElementById("inp-custom-gw-ip");
const btnCustomGwConnect = document.getElementById("btn-custom-gw-connect");

// Load Gateway list
async function loadGateways() {
  try {
    const res = await API.getGateways();
    elGatewaySelect.innerHTML = "";
    if (res.gateways && res.gateways.length > 0) {
      res.gateways.forEach(gw => {
        const opt = document.createElement("option");
        opt.value = gw.ip_address;
        opt.textContent = `${gw.gateway_id} (${gw.ip_address})`;
        elGatewaySelect.appendChild(opt);
      });
      currentGatewayIp = elGatewaySelect.value;
    }
    const customOpt = document.createElement("option");
    customOpt.value = "custom";
    customOpt.textContent = "+ Custom Gateway IP...";
    elGatewaySelect.appendChild(customOpt);
  } catch (e) {
    log(`Note on gateways list: ${e.message}`, "info");
    const customOpt = document.createElement("option");
    customOpt.value = "custom";
    customOpt.textContent = "+ Custom Gateway IP...";
    elGatewaySelect.appendChild(customOpt);
  }
}

// Check gateway connection
async function checkGatewayStatus() {
  try {
    const data = await API.getStatus(currentGatewayIp);
    if (data.online) {
      elStatusIndicator.className = "status-indicator online";
      elStatusText.textContent = "ONLINE (Ready)";
    } else {
      elStatusIndicator.className = "status-indicator offline";
      elStatusText.textContent = "OFFLINE (Unreachable)";
    }
  } catch (e) {
    elStatusIndicator.className = "status-indicator offline";
    elStatusText.textContent = "OFFLINE";
  }
}

// Update topic previews dynamically
function updateTopicPreviews() {
  const source = selScriptSource ? selScriptSource.value : "testserver";
  const site = (inpSiteId ? inpSiteId.value.trim() : "") || "5efa910f-8e17-4443-af76-8b0a674d23f5";
  const pole = inpPoleId.value.trim() || "Pole-CBD-3444";
  const prefix = inpClientPrefix.value.trim() || "scmp-pole";

  if (previewClientIdBadge) previewClientIdBadge.textContent = `Client: ${prefix}-${pole}`;

  if (source === "testserver") {
    if (badgeScriptCount) badgeScriptCount.textContent = "24 UP / 5 DOWN Scripts";
    if (previewUpNames) {
      previewUpNames.textContent = "Publish, Temperature, Noise, S02, NO2, CO, O3, PM10, Humidity, Pressure, Wind speed, Rainfall, Winddirection, Radiation, Illuminance, UV index, CO2, Negative O2 ions, TSP, PM1, ack, camera_status, led_screen_status";
    }
    if (previewDownNames) {
      previewDownNames.textContent = "Subscribe, LampControlTopic, new, testsub, LedScreenControl";
    }
    if (topicEnv) topicEnv.textContent = `scmp/v1/${site}/${pole}/env/29748b52-5203-49de-8221-7f9df657e28e/telemetry`;
    if (topicCamera) topicCamera.textContent = `scmp/v1/${site}/${pole}/camera/camera-01/status`;
    if (topicScreen) topicScreen.textContent = `scmp/v1/${site}/${pole}/screen/screen-01/status`;
    if (topicLamp) topicLamp.textContent = `scmp/v1/.../${pole}/lamp/.../cmd/control`;
  } else if (source === "test") {
    if (badgeScriptCount) badgeScriptCount.textContent = "20 UP / 5 DOWN Scripts";
    if (previewUpNames) {
      previewUpNames.textContent = "Publish, Temperature, CO2, Noise, S02, NO2, CO, O3, PM10, Humidity, Pressure, Wind speed, Rainfall, Winddirection, UV index, Negative O2 ions, TSP, PM1, Fault, ScreenFault";
    }
    if (previewDownNames) {
      previewDownNames.textContent = "Subscribe, Led, Strip, LampControl, screen";
    }
    if (topicEnv) topicEnv.textContent = `scmp/v1/${site}/${pole}/env/29748b52-5203-49de-8221-7f9df657e28e/telemetry`;
    if (topicCamera) topicCamera.textContent = `scmp/v1/${site}/${pole}/camera/camera-01/status`;
    if (topicScreen) topicScreen.textContent = `scmp/v1/${site}/${pole}/screen/screen-01/status`;
    if (topicLamp) topicLamp.textContent = `scmp/v1/${site}/${pole}/lamp/lamp-01/cmd/control`;
  } else {
    if (badgeScriptCount) badgeScriptCount.textContent = "5 UP / 2 DOWN Scripts";
    if (previewUpNames) {
      previewUpNames.textContent = "EnvTelemetry, PoleIoTelemetry, RgbTelemetry, CameraFault, ScreenFault";
    }
    if (previewDownNames) {
      previewDownNames.textContent = "LampControl, RgbControl";
    }
    if (topicEnv) topicEnv.textContent = `scmp/v1/${site}/${pole}/env/env-01/telemetry`;
    if (topicCamera) topicCamera.textContent = `scmp/v1/${site}/${pole}/camera/camera-01/status`;
    if (topicScreen) topicScreen.textContent = `scmp/v1/${site}/${pole}/screen/screen-01/status`;
    if (topicLamp) topicLamp.textContent = `scmp/v1/${site}/${pole}/lamp/lamp-01/cmd/control`;
  }
}

// Event Listeners
function setupEventListeners() {
  elGatewaySelect.addEventListener("change", (e) => {
    if (e.target.value === "custom") {
      if (inpCustomGwIp) {
        inpCustomGwIp.style.display = "inline-block";
        inpCustomGwIp.focus();
      }
      if (btnCustomGwConnect) btnCustomGwConnect.style.display = "inline-block";
    } else {
      if (inpCustomGwIp) inpCustomGwIp.style.display = "none";
      if (btnCustomGwConnect) btnCustomGwConnect.style.display = "none";
      currentGatewayIp = e.target.value;
      log(`Target gateway switched to ${currentGatewayIp}`, "info");
      checkGatewayStatus();
    }
  });

  function applyCustomIp() {
    const customIp = inpCustomGwIp ? inpCustomGwIp.value.trim() : "";
    if (!customIp) {
      showToast("Please enter a valid IP address.", "error");
      return;
    }
    const opt = document.createElement("option");
    opt.value = customIp;
    opt.textContent = `Custom (${customIp})`;
    elGatewaySelect.insertBefore(opt, elGatewaySelect.lastElementChild);
    elGatewaySelect.value = customIp;
    inpCustomGwIp.style.display = "none";
    btnCustomGwConnect.style.display = "none";
    currentGatewayIp = customIp;
    log(`Target gateway switched to custom IP: ${currentGatewayIp}`, "info");
    checkGatewayStatus();
  }

  if (btnCustomGwConnect) btnCustomGwConnect.addEventListener("click", applyCustomIp);
  if (inpCustomGwIp) {
    inpCustomGwIp.addEventListener("keydown", (e) => {
      if (e.key === "Enter") applyCustomIp();
    });
  }

  if (selScriptSource) selScriptSource.addEventListener("change", updateTopicPreviews);
  if (inpSiteId) inpSiteId.addEventListener("input", updateTopicPreviews);
  inpPoleId.addEventListener("input", updateTopicPreviews);
  inpClientPrefix.addEventListener("input", updateTopicPreviews);

  // Single Gateway Provision
  btnWriteSingle.addEventListener("click", () => handleProvision(false));

  // Bulk All Gateways Provision
  btnWriteAll.addEventListener("click", () => handleProvision(true));
}

// Core Provisioning Execution
async function handleProvision(writeAll) {
  if (isRunning) return;

  const targetIp = currentGatewayIp;
  const screenIp = inpScreenIp.value.trim();
  const poleId = inpPoleId.value.trim();
  const siteId = (inpSiteId ? inpSiteId.value.trim() : "") || "default-site";
  const scriptSource = selScriptSource ? selScriptSource.value : "testserver";

  const cloudConfig = {
    ct_id: inpCloudId.value.trim(),
    client_id_prefix: inpClientPrefix.value.trim(),
    url: inpBrokerUrl.value.trim(),
    port: parseInt(inpBrokerPort.value, 10) || 1883,
    username: inpMqttUser.value.trim(),
    password: inpMqttPass.value.trim()
  };

  if (!screenIp || !poleId || !cloudConfig.url) {
    showToast("Please fill in Screen IP, Pole Number, and Broker IP.", "error");
    return;
  }

  isRunning = true;
  btnWriteSingle.disabled = true;
  btnWriteAll.disabled = true;
  btnWriteSingle.style.opacity = "0.5";
  btnWriteAll.style.opacity = "0.5";
  logStatusBadge.textContent = "WRITING...";
  logStatusBadge.style.color = "var(--accent-amber)";

  const targetTitle = writeAll ? "ALL Gateways on LAN" : `Gateway ${targetIp}`;
  log(`=== Starting Automated Write to ${targetTitle} (Source: ${scriptSource}) ===`, "info");
  showToast(`Writing configuration to ${targetTitle}...`, "info");

  try {
    const payload = {
      target_ip: targetIp,
      screen_ip: screenIp,
      pole_id: poleId,
      site_id: siteId,
      script_source: scriptSource,
      cloud_config: cloudConfig,
      write_all_gateways: writeAll
    };

    const res = await API.provisionGateway(payload);

    if (writeAll) {
      log(`[+] SUCCESS: Provisioned ${res.count} gateways successfully across LAN.`, "success");
      res.results.forEach(r => {
        log(`   - ${r.gateway_ip} (${r.pole_id}): ${r.variables_count} variables & ${r.scripts_up + r.scripts_down} scripts injected.`, "success");
      });
      showToast(`All ${res.count} gateways successfully written and committed!`, "success");
    } else {
      const r = res.result;
      log(`[+] SUCCESS: Gateway ${r.gateway_ip} successfully provisioned!`, "success");
      if (r.logs) {
        r.logs.forEach(l => log(`   ${l}`, "success"));
      }
      showToast(`Gateway ${r.gateway_ip} written and applied successfully!`, "success");
    }

    logStatusBadge.textContent = "SUCCESS";
    logStatusBadge.style.color = "var(--accent-emerald)";
    checkGatewayStatus();

  } catch (err) {
    log(`[-] PROVISIONING ERROR: ${err.message}`, "error");
    showToast(`Provisioning failed: ${err.message}`, "error");
    logStatusBadge.textContent = "ERROR";
    logStatusBadge.style.color = "var(--accent-rose)";
  } finally {
    isRunning = false;
    btnWriteSingle.disabled = false;
    btnWriteAll.disabled = false;
    btnWriteSingle.style.opacity = "1";
    btnWriteAll.style.opacity = "1";
  }
}

// Log line helper
function log(msg, type = "info") {
  const line = document.createElement("div");
  line.className = `log-entry ${type}`;
  const ts = new Date().toLocaleTimeString();
  line.textContent = `[${ts}] ${msg}`;
  terminalBody.appendChild(line);
  terminalBody.scrollTop = terminalBody.scrollHeight;
}

// Toast helper
function showToast(msg, type = "info") {
  const t = document.createElement("div");
  t.className = `toast ${type}`;
  t.textContent = msg;
  toastContainer.appendChild(t);
  setTimeout(() => {
    t.style.opacity = "0";
    setTimeout(() => t.remove(), 300);
  }, 4000);
}
