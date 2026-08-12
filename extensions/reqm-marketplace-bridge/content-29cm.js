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
    const cells = [...row.querySelectorAll("td")].map(cell => cell.innerText.trim());
    const numericIndex = cells.reduce((last, value, index) => /^\d{6,}$/.test(value) ? index : last, -1);
    // 옵션 재고 화면에는 다단 헤더 외에 저장 버튼도 포함된다. 번호 뒤 첫 값이
    // 실제 옵션명(샌드·스카이블루 등)이므로 버튼 텍스트를 제외하고 읽는다.
    const optionName = numericIndex >= 0 ? cells.slice(numericIndex + 1).find(value =>
      value && !/^(판매중|일시품절|판매중지|저장|저장\s*판매중지)$/.test(value) && !/^\d+$/.test(value)
    ) || "" : "";
    const itemName = cells.find(value => value.length > 10 && !/^\d+$/.test(value) && !/^(판매중|일시품절|판매중지|저장)/.test(value)) || "";
    return {
      marketplace_item_no: cellValue(row, headers, "상품번호") || itemMatch?.[1] || "",
      marketplace_option_no: cells[numericIndex] || cellValue(row, headers, "옵션번호"),
      marketplace_item_name: itemName || cellValue(row, headers, "상품명"),
      marketplace_option_name: optionName || cellValue(row, headers, "옵션명"),
      sale_status: cells.find(value => value === "판매중" || value.startsWith("일시품절") || value === "판매중지") || cellValue(row, headers, "판매상태"),
      stock: [...row.querySelectorAll("input")][1]?.value || cellValue(row, headers, "재고")
    };
  }).filter(row => row.marketplace_item_no && row.marketplace_option_no && row.marketplace_item_name);
  reply({rows});
});
