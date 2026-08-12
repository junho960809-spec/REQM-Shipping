function cellValue(row, headers, name) {
  const index = headers.findIndex(header => header.replace(/\s/g, "").includes(name));
  return index >= 0 ? (row.querySelectorAll("td")[index]?.innerText.trim() || "") : "";
}

chrome.runtime.onMessage.addListener((message, _sender, reply) => {
  if (message.type !== "REQM_READ_29CM_CATALOG") return;
  const rows = [...document.querySelectorAll("tbody tr")].map(row => {
    // 29CM은 '상품 정보 / 옵션 정보'의 2단 헤더를 사용한다. 마지막 헤더 행만
    // 써야 td 열 위치가 맞아 상품명·옵션명 색상이 뒤바뀌지 않는다.
    const table = row.closest("table");
    const headers = [...(table?.querySelectorAll("thead tr:last-child th") || [])].map(cell => cell.innerText.trim());
    const link = [...row.querySelectorAll("a")].map(a => a.href).find(href => /partner-item\.29cm\.co\.kr\/\d+/.test(href)) || "";
    const itemMatch = link.match(/partner-item\.29cm\.co\.kr\/(\d+)/);
    return {
      marketplace_item_no: cellValue(row, headers, "상품번호") || itemMatch?.[1] || "",
      marketplace_option_no: cellValue(row, headers, "옵션번호"),
      marketplace_item_name: cellValue(row, headers, "상품명"),
      marketplace_option_name: cellValue(row, headers, "옵션명"),
      sale_status: cellValue(row, headers, "판매상태"),
      stock: [...row.querySelectorAll("input")][1]?.value || cellValue(row, headers, "재고")
    };
  }).filter(row => row.marketplace_item_no && row.marketplace_option_no && row.marketplace_item_name);
  reply({rows});
});
