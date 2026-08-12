const BRIDGE = "http://127.0.0.1:8765";

async function bridge(path, options = {}) {
  return fetch(`${BRIDGE}${path}`, {headers: {"Content-Type": "application/json"}, ...options});
}

async function sync29cm() {
  const tabs = await chrome.tabs.query({url: "https://partner-item.29cm.co.kr/option-stock*"});
  // SSO 로그인 화면이나 자동 생성 탭에는 주입하지 않는다. REQM_CS의
  // 로그인된 옵션 재고 관리 탭이 열려 있을 때만 목록을 읽는다.
  if (!tabs.length) return;
  // 확장을 다시 로드해도 기존 탭의 content script는 자동 교체되지 않는다.
  // 매 동기화 시 최신 파일을 주입하고 전역 파서를 직접 호출한다.
  await chrome.scripting.executeScript({target: {tabId: tabs[0].id}, files: ["content-29cm.js"]});
  const result = await chrome.scripting.executeScript({
    target: {tabId: tabs[0].id},
    func: () => globalThis.__REQM_READ_29CM_CATALOG?.() || []
  }).catch(() => []);
  const rows = result[0]?.result || [];
  if (rows.length) await bridge("/api/29cm/catalog", {method: "POST", body: JSON.stringify({rows})});
}

chrome.action.onClicked.addListener(sync29cm);
chrome.alarms.create("reqm-catalog-sync", {periodInMinutes: 1});
chrome.alarms.onAlarm.addListener(async () => {
  const request = await bridge("/api/29cm/sync-request").then(r => r.json()).catch(() => null);
  if (request?.requested) await sync29cm();
});
chrome.runtime.onMessage.addListener((message, _sender, reply) => {
  if (message.type === "REQM_SYNC_NOW") sync29cm().then(() => reply({ok: true}));
  return true;
});
