function cellValue(row, headers, name) {
  const index = headers.findIndex(header => header.replace(/\s/g, "").includes(name));
  return index >= 0 ? (row.querySelectorAll("td")[index]?.innerText.trim() || "") : "";
}

chrome.runtime.onMessage.addListener((message, _sender, reply) => {
  if (message.type !== "REQM_READ_29CM_CATALOG") return;
  const headers = [...document.querySelectorAll("thead th")].map(cell => cell.innerText.trim());
  const rows = [...document.querySelectorAll("tbody tr")].map(row => {
    const cells = [...row.querySelectorAll("td")].map(cell => cell.innerText.trim()).filter(Boolean);
    const link = [...row.querySelectorAll("a")].map(a => a.href).find(href => /partner-item\.29cm\.co\.kr\/\d+/.test(href)) || "";
    const itemMatch = link.match(/partner-item\.29cm\.co\.kr\/(\d+)/);
    const numeric = cells.filter(value => /^\d{6,}$/.test(value));
    const status = cells.find(value => value === "판매중" || value.startsWith("일시품절") || value === "판매중지") || "";
    const itemName = cells.find(value => value.length > 8 && !/^\d+$/.test(value) && !value.includes("저장")) || "";
    return {
      marketplace_item_no: itemMatch?.[1] || "",
      marketplace_option_no: numeric[0] || "",
      marketplace_item_name: itemName,
      marketplace_option_name: cellValue(row, headers, "옵션명"),
      sale_status: status,
      stock: [...row.querySelectorAll("input")][1]?.value || cellValue(row, headers, "재고")
    };
  }).filter(row => row.marketplace_option_no && row.marketplace_item_name);
  reply({rows});
});
