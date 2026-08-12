const BRIDGE = "http://127.0.0.1:8765";

async function bridge(path, options = {}) {
  return fetch(`${BRIDGE}${path}`, {headers: {"Content-Type": "application/json"}, ...options});
}

function waitForTabLoad(tabId, urlPrefix = "https://partner-item.29cm.co.kr/option-stock", timeout = 20000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      reject(new Error("29CM 옵션 재고 화면을 불러오지 못했습니다."));
    }, timeout);
    function listener(updatedId, changeInfo, tab) {
      if (updatedId !== tabId || changeInfo.status !== "complete") return;
      if (!tab.url?.startsWith(urlPrefix)) return;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(listener);
      resolve(tab);
    }
    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function sync29cm() {
  const optionTabs = await chrome.tabs.query({url: "https://partner-item.29cm.co.kr/option-stock*"});
  const dashboardTabs = await chrome.tabs.query({url: "https://partner-connect.29cm.co.kr/dashboard*"});
  let tab = optionTabs[0];
  let temporaryTab = false;
  if (!tab && dashboardTabs.length) {
    // 사용자가 열어 둔 로그인된 대시보드 세션으로 옵션 재고 탭을 백그라운드 생성한다.
    tab = await chrome.tabs.create({url: "https://partner-item.29cm.co.kr/option-stock", active: false});
    temporaryTab = true;
    try {
      tab = await waitForTabLoad(tab.id);
    } catch (_error) {
      await chrome.tabs.remove(tab.id).catch(() => {});
      return;
    }
  }
  if (!tab) return;
  // 확장을 다시 로드해도 기존 탭의 content script는 자동 교체되지 않는다.
  // 매 동기화 시 최신 파일을 주입하고 전역 파서를 직접 호출한다.
  await chrome.scripting.executeScript({target: {tabId: tab.id}, files: ["content-29cm.js"]});
  const result = await chrome.scripting.executeScript({
    target: {tabId: tab.id},
    func: () => globalThis.__REQM_READ_29CM_CATALOG?.() || []
  }).catch(() => []);
  const rows = result[0]?.result || [];
  if (rows.length) await bridge("/api/29cm/catalog", {method: "POST", body: JSON.stringify({rows})});
  if (temporaryTab) await chrome.tabs.remove(tab.id).catch(() => {});
}

async function execute29cmAction(action) {
  const target = `https://partner-item.29cm.co.kr/${action.marketplace_item_no}?from=option-stock`;
  const tab = await chrome.tabs.create({url: target, active: false});
  try {
    await waitForTabLoad(tab.id, "https://partner-item.29cm.co.kr/");
    const result = await chrome.scripting.executeScript({
      target: {tabId: tab.id},
      args: [action],
      func: async (work) => {
        const row = [...document.querySelectorAll("tr")].find(item => item.innerText.includes(work.marketplace_option_no));
        if (!row) throw new Error("옵션 행을 찾지 못했습니다.");
        const inputs = row.querySelectorAll("input");
        if (inputs.length < 2) throw new Error("재고 입력칸을 찾지 못했습니다.");
        const targetStock = work.action === "SOLD_OUT" ? "0" : String(work.target_stock);
        const previousStock = inputs[1].value;
        inputs[1].focus();
        inputs[1].value = targetStock;
        inputs[1].dispatchEvent(new Event("input", {bubbles: true}));
        inputs[1].dispatchEvent(new Event("change", {bubbles: true}));
        const save = [...document.querySelectorAll("button")].find(button => button.innerText.trim() === "수정 완료");
        if (!save) throw new Error("수정 완료 버튼을 찾지 못했습니다.");
        save.click();
        await new Promise(resolve => setTimeout(resolve, 1600));
        return {previous_stock: previousStock, target_stock: targetStock};
      }
    });
    await bridge("/api/29cm/action-result", {method: "POST", body: JSON.stringify({
      action_id: action.action_id, status: "COMPLETED", details: result[0]?.result || {}
    })});
  } catch (error) {
    await bridge("/api/29cm/action-result", {method: "POST", body: JSON.stringify({
      action_id: action.action_id, status: "FAILED", error_message: String(error?.message || error)
    })}).catch(() => {});
  } finally {
    await chrome.tabs.remove(tab.id).catch(() => {});
  }
}

chrome.action.onClicked.addListener(sync29cm);
chrome.alarms.create("reqm-catalog-sync", {periodInMinutes: 1});
chrome.alarms.onAlarm.addListener(async () => {
  const request = await bridge("/api/29cm/sync-request").then(r => r.json()).catch(() => null);
  if (request?.requested) await sync29cm();
  const action = await bridge("/api/29cm/pending-action").then(r => r.json()).catch(() => null);
  if (action?.action) await execute29cmAction(action.action);
});
chrome.runtime.onMessage.addListener((message, _sender, reply) => {
  if (message.type === "REQM_SYNC_NOW") sync29cm().then(() => reply({ok: true}));
  return true;
});
