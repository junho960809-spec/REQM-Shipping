function cellValue(row, headers, name) {
  const index = headers.findIndex(header => header.replace(/\s/g, "").includes(name));
  return index >= 0 ? (row.querySelectorAll("td")[index]?.innerText.trim() || "") : "";
}

chrome.runtime.onMessage.addListener((message, _sender, reply) => {
  if (message.type !== "REQM_READ_29CM_CATALOG") return;
  const headers = [...document.querySelectorAll("thead th")].map(cell => cell.innerText.trim());
  const rows = [...document.querySelectorAll("tbody tr")].map(row => ({
    marketplace_item_no: cellValue(row, headers, "상품번호"),
    marketplace_option_no: cellValue(row, headers, "옵션번호"),
    marketplace_item_name: cellValue(row, headers, "상품명"),
    marketplace_option_name: cellValue(row, headers, "옵션명"),
    sale_status: cellValue(row, headers, "판매상태"),
    stock: [...row.querySelectorAll("input")][1]?.value || cellValue(row, headers, "재고")
  })).filter(row => row.marketplace_item_no && row.marketplace_option_no);
  reply({rows});
});
