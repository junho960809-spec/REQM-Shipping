const BRIDGE = "http://127.0.0.1:8765";

async function bridge(path, options = {}) {
  return fetch(`${BRIDGE}${path}`, {headers: {"Content-Type": "application/json"}, ...options});
}

async function sync29cm() {
  const tabs = await chrome.tabs.query({url: "https://partner-item.29cm.co.kr/*"});
  if (!tabs.length) return;
  const result = await chrome.tabs.sendMessage(tabs[0].id, {type: "REQM_READ_29CM_CATALOG"}).catch(() => null);
  if (result?.rows?.length) await bridge("/api/29cm/catalog", {method: "POST", body: JSON.stringify({rows: result.rows})});
}

chrome.action.onClicked.addListener(sync29cm);
chrome.alarms.create("reqm-catalog-sync", {periodInMinutes: 5});
chrome.alarms.onAlarm.addListener(sync29cm);
chrome.runtime.onMessage.addListener((message, _sender, reply) => {
  if (message.type === "REQM_SYNC_NOW") sync29cm().then(() => reply({ok: true}));
  return true;
});
